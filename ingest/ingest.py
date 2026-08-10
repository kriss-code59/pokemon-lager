#!/usr/bin/env python3
"""Les scraperens data.json og skriv den inn i Postgres.

Dette er broen mellom den gamle verdenen (en 5,8 MB JSON-fil committet til
git hvert 20. minutt) og den nye (Postgres + API). Scraperen trenger ikke
vite at databasen finnes -- den skriver data.json som for, og denne kjorer
etterpa.

Tre ting skjer her, i rekkefolge:

  1. Katalogen (sets/types/products) synkes fra katalog/katalog.json.
  2. Hver ra butikkoppforing klassifiseres. Loskort og merch kastes.
     Sealed-varer mappes mot et kanonisk produkt der det er mulig.
  3. Tilstanden sammenlignes mot forrige kjoring, og BARE ekte endringer
     blir hendelser i events.

Vernene mot falske varsler (F1/F4 i auditen) er bevisst duplisert her og
i scrape.py. Databasen er siste skanse: selv om en fremtidig endring i
scraperen slipper gjennom en tom butikk, skal det ikke bli 773 varsler.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

_HER = os.path.dirname(os.path.abspath(__file__))
_ROT = os.path.dirname(_HER)
sys.path.insert(0, os.path.join(_ROT, "katalog"))

from matcher import Katalog, SINGLES_ONLY_STORES  # noqa: E402

# En butikk som mister mer enn dette av katalogen sin siden forrige kjoring
# har nesten sikkert feilet, ikke tomt lageret. Da rorer vi den ikke.
KRYMP_GRENSE = 0.25

# Under dette antallet oppforinger er krympvernet meningslost stoy.
KRYMP_MINIMUM = 20

# Én kjoring som produserer flere hendelser enn dette er en feil, ikke en
# nyhet. Hendelsene lagres, men markeres slik at varsling kan hoppe over dem.
STORM_GRENSE = 200

# Prisendringer under 1 krone er avrunding, ikke en prisendring.
PRIS_STOY_ORE = 100

# Butikker setter 1,00 kr pa varer som ikke er prissatt ennaa (forhandsbestilling
# uten pris). Det er ikke en pris, det er et tomt felt med et tall i. Uten denne
# grensen ble "billigste pris" pa et helt sett til 1 krone.
MIN_EKTE_PRIS_ORE = 500


def slug(tekst: str) -> str:
    t = (tekst or "").replace("ø", "o").replace("æ", "ae").replace("å", "a")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "ukjent"


_PRIS_RE = re.compile(r"(\d[\d\s.,]*)")


def pris_til_ore(verdi) -> int | None:
    """'1799.00 kr' -> 179900. Losningen pa F5: pris er et heltall, aldri tekst.

    Norsk og engelsk tallformat blandes fritt i butikkene: '1 799,00', '1799.00',
    '1.799,-'. Regelen som holder for alle: siste separator er desimalskille
    hvis den etterfolges av ETT eller TO siffer. Tre siffer er tusenskille
    ('1.799'), og det er nettopp den forvekslingen som gjor at pris aldri
    kan lagres som tekst (F5).
    """
    if verdi is None:
        return None
    if isinstance(verdi, (int, float)):
        return int(round(float(verdi) * 100))
    m = _PRIS_RE.search(str(verdi))
    if not m:
        return None
    tall = m.group(1).strip().replace(" ", "").replace("\xa0", "")
    d = re.search(r"[.,](\d{1,2})$", tall)
    if d:
        heltall = tall[:d.start()]
        desimal = d.group(1).ljust(2, "0")
    else:
        heltall, desimal = tall, "00"
    heltall = re.sub(r"[.,]", "", heltall)
    if not heltall.isdigit():
        return None
    try:
        ore = int(heltall) * 100 + int(desimal)
    except ValueError:
        return None
    return ore if ore >= MIN_EKTE_PRIS_ORE else None


def normaliser_lager(verdi):
    """Tri-state bevares. None betyr 'vet ikke', ikke 'utsolgt' (F4)."""
    if verdi is True or verdi is False:
        return verdi
    return None


# --------------------------------------------------------------- katalogen

def synk_katalog(cur, katalog: Katalog) -> int:
    regioner = {r["id"]: r["label"] for r in katalog.regions}
    # `slipp` er valgfri og finnes bare paa sett som ikke er ute enna.
    # Kolonnen release_date har staatt tom siden dag én; den fylles her, og
    # frontenden teller ned fra den i stedet for aa ha datoen hardkodet.
    cur.executemany(
        "INSERT INTO sets (id, label, region, release_date) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label, "
        "  region = EXCLUDED.region, release_date = EXCLUDED.release_date",
        [(s["id"], s["label"], s["region"], s.get("slipp")) for s in katalog.sets],
    )
    cur.executemany(
        "INSERT INTO product_types (id, label, sort_order) VALUES (%s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label, sort_order = EXCLUDED.sort_order",
        [(t["id"], t["label"], i * 10) for i, t in enumerate(katalog.types)],
    )
    rader = []
    for s in katalog.sets:
        for t in katalog.types:
            rader.append(("%s:%s:%s" % (s["id"], t["id"], s["region"]),
                          s["id"], t["id"], s["region"]))
    cur.executemany(
        "INSERT INTO products (id, set_id, type_id, region) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        rader,
    )
    return len(regioner)


def sikre_produkter(cur, produkt_ider):
    """Opprett kanoniske produkter som katalogen ikke forutsa.

    matcher.match() lar en eksplisitt spraakmarkering i tittelen overstyre
    settets egen region: "White Flare Japansk Booster Box" blir
    `white-flare:booster-box:jp`, selv om White Flare star som `en` i
    katalogen. Slike kombinasjoner finnes ikke i krysstabellen over, og
    uten denne funksjonen faller oppforingen pa en fremmednokkelfeil.
    """
    manglende = sorted(produkt_ider)
    if not manglende:
        return 0
    rader = []
    for pid in manglende:
        set_id, type_id, region = pid.split(":")
        rader.append((pid, set_id, type_id, region))
    cur.executemany(
        "INSERT INTO products (id, set_id, type_id, region) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        rader,
    )
    return len(rader)


# ------------------------------------------------------------------- kjor

def les_data(sti: str) -> dict:
    with open(sti, encoding="utf-8") as f:
        return json.load(f)


def _bestillingstype(tittel):
    """Forhaandssalg og bestillingsvarer skal ikke telle som «paa lager».

    Importeres sent og feiler mykt: en ingest som stopper fordi en ny modul
    mangler, er verre enn en ingest uten denne merkingen.
    """
    try:
        from katalog.tilgjengelighet import bestillingstype
        return bestillingstype(tittel)
    except Exception:
        return None


def les_manuelle_koblinger(cur) -> dict:
    """tittel -> product_id, satt av et menneske paa /admin.

    Disse overstyrer matcher.py. Grunnen er praktisk: naar du ser en umatchet
    vare i admin og vet hva den er, skal koblingen gjelde ved neste ingest --
    ikke forsvinne fordi regelmotoren fortsatt ikke kjenner igjen tittelen.
    """
    try:
        cur.execute("SELECT title, product_id FROM manual_matches")
        return {r["title"]: r["product_id"] for r in cur.fetchall()}
    except Exception:
        # 002_varsler.sql har ikke kjort enna. Ingest skal ikke stoppe av det.
        return {}


def grupper_per_butikk(rader, katalog: Katalog, manuelle: dict | None = None):
    """Ra rader -> {butikknavn: {url: oppforing}}, kun sealed."""
    manuelle = manuelle or {}
    per_butikk: dict[str, dict] = {}
    forkastet = collections.Counter()
    for r in rader:
        butikk = r.get("store")
        url = r.get("url")
        navn = r.get("name")
        if not butikk or not url or not navn:
            continue
        if butikk in SINGLES_ONLY_STORES:
            forkastet["singles-butikk"] += 1
            continue
        klasse = katalog.classify(navn)
        if klasse != "sealed":
            forkastet[klasse] += 1
            continue
        treff = katalog.match(navn)
        manuell = manuelle.get(navn)
        bod = per_butikk.setdefault(butikk, {})
        if url in bod:
            forkastet["duplikat"] += 1
            continue
        bod[url] = {
            "url": url,
            "title": navn[:500],
            "price_ore": pris_til_ore(r.get("price")),
            "in_stock": normaliser_lager(r.get("in_stock")),
            # Manuell kobling vinner over regelmotoren. Et menneske som har
            # sett varen vet mer enn et regexuttrykk.
            "product_id": manuell or (treff["product_id"] if treff else None),
            # Forhaandssalg og bestillingsvarer skal ikke telle som "paa
            # lager". MAA settes her, sammen med resten av oppforingen --
            # koden under leser ny["bestillingstype"] direkte, og en
            # manglende noekkel stopper HELE ingesten med KeyError.
            # Det skjedde 2026-08-07: skanningen gikk fint hver 10. minutt,
            # men ingenting kom inn i databasen paa halvannen time.
            "bestillingstype": _bestillingstype(navn),
            # Butikkens produktbilde. Skjemaet har hatt listings.image_url
            # siden starten og API-et har alltid lest den -- men ingen skrev
            # den. Resultatet var 0 av 3 900 oppforinger med bilde, og en
            # liste med bare reservesilhuetter, mens data.json hadde 19 000
            # bilde-URL-er liggende. Et felt som leses av alle og skrives av
            # ingen feiler stille: ingenting kaster, det ser bare tomt ut.
            "image_url": (r.get("image") or None),
        }
    return per_butikk, dict(forkastet)


def kjor(dsn: str, data_sti: str, katalog_sti: str | None = None,
         verbose: bool = True) -> dict:
    katalog = Katalog(katalog_sti)
    data = les_data(data_sti)
    helse = data.get("health") or {}
    feilede = set(helse.get("failed_stores") or [])
    fremfort = set(helse.get("carried_forward_stores") or [])
    sist_oppdatert = data.get("last_updated")
    # Skanningens ekte starttid hvis scraperen oppgir den; ellers faller vi
    # tilbake pa naar filen ble skrevet, som er naar skanningen var FERDIG.
    startet = helse.get("started_at") or sist_oppdatert

    # Egen kort tilkobling: de manuelle koblingene maa leses FOR grupperingen,
    # og grupperingen skjer for hovedtransaksjonen apnes.
    with psycopg.connect(dsn, row_factory=dict_row) as _c:
        with _c.cursor() as _cur:
            manuelle = les_manuelle_koblinger(_cur)

    per_butikk, forkastet = grupper_per_butikk(data.get("products") or [], katalog,
                                               manuelle)

    hendelser: list[tuple] = []
    stat = {"nye": 0, "restock": 0, "utsolgt": 0, "prisendring": 0,
            "hoppet_over": [], "oppforinger": 0, "butikker": len(per_butikk),
            "forkastet": forkastet, "bootstrap": []}

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute("SET search_path TO public")
        with conn.cursor() as cur:
            synk_katalog(cur, katalog)
            sikre_produkter(cur, {o["product_id"] for b in per_butikk.values()
                                  for o in b.values() if o["product_id"]})

            cur.execute(
                "INSERT INTO scrape_runs (started_at, store_count, failed_stores, carried_stores) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (startet or datetime.now(timezone.utc), len(per_butikk),
                 sorted(feilede), sorted(fremfort)),
            )
            kjoring_id = cur.fetchone()["id"]

            # Butikker som er meldt feilet finnes ofte IKKE i per_butikk i det
            # hele tatt -- en butikk som returnerte null produkter har ingen
            # rader a gruppere. De ma likevel innom lokken, ellers blir en
            # feilet skanning helt usynlig i rapporten.
            for butikk in sorted(set(per_butikk) | feilede):
                oppforinger = per_butikk.get(butikk, {})
                butikk_id = slug(butikk)
                cur.execute(
                    "INSERT INTO stores (id, name) VALUES (%s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
                    (butikk_id, butikk),
                )

                if butikk in feilede:
                    stat["hoppet_over"].append("%s (feilet)" % butikk)
                    continue

                cur.execute(
                    "SELECT id, url, title, price_ore, in_stock, product_id, "
                    "       bestillingstype "
                    "FROM listings WHERE store_id = %s", (butikk_id,))
                for_ = {r["url"]: r for r in cur.fetchall()}

                # Krympvernet. Uten dette blir en halvferdig skanning til en
                # katalog som "forsvant", og neste kjoring til en varselstorm.
                if (len(for_) >= KRYMP_MINIMUM
                        and len(oppforinger) < len(for_) * (1 - KRYMP_GRENSE)):
                    stat["hoppet_over"].append(
                        "%s (%d -> %d, krympvern)" % (butikk, len(for_), len(oppforinger)))
                    continue

                bootstrap = not for_
                if bootstrap:
                    stat["bootstrap"].append(butikk)

                na = datetime.now(timezone.utc)
                oppdater, sett_inn = [], []
                for url, ny in oppforinger.items():
                    gammel = for_.get(url)
                    if gammel is None:
                        sett_inn.append((butikk_id, ny["product_id"], url, ny["title"],
                                         ny["price_ore"], ny["in_stock"], na, na,
                                         ny["image_url"], ny["bestillingstype"]))
                        if ny["in_stock"] is True and not bootstrap:
                            hendelser.append((None, url, ny["product_id"], butikk_id,
                                              "ny", ny["price_ore"], None))
                        continue

                    oppdater.append((ny["product_id"], ny["title"], ny["price_ore"],
                                     ny["in_stock"], na, na, ny["image_url"],
                                     ny["bestillingstype"], gammel["id"]))
                    if bootstrap:
                        continue

                    var, er = gammel["in_stock"], ny["in_stock"]
                    # None pa noen av sidene betyr "vet ikke" og skal aldri
                    # bli en hendelse. Det var nettopp den antagelsen som
                    # sendte falske restock-varsler for.
                    if var is False and er is True:
                        hendelser.append((gammel["id"], url, ny["product_id"], butikk_id,
                                          "restock", ny["price_ore"], None))
                    elif var is True and er is False:
                        hendelser.append((gammel["id"], url, ny["product_id"], butikk_id,
                                          "utsolgt", ny["price_ore"], None))

                    # Forhaandssalg -> vanlig vare. Butikken lar in_stock staa
                    # paa true gjennom hele skiftet, saa restock-regelen over
                    # ser ingenting. Men det er nettopp NAA varen ble ekte.
                    if (gammel.get("bestillingstype") and not ny["bestillingstype"]
                            and er is True):
                        hendelser.append((gammel["id"], url, ny["product_id"], butikk_id,
                                          "restock", ny["price_ore"], None))

                    gp, np_ = gammel["price_ore"], ny["price_ore"]
                    if (gp and np_ and abs(np_ - gp) >= PRIS_STOY_ORE):
                        hendelser.append((gammel["id"], url, ny["product_id"], butikk_id,
                                          "prisendring", np_, gp))

                if sett_inn:
                    cur.executemany(
                        "INSERT INTO listings (store_id, product_id, url, title, price_ore, "
                        "in_stock, last_seen_at, last_ok_at, image_url, bestillingstype) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (url) DO UPDATE SET "
                        "  product_id = EXCLUDED.product_id, title = EXCLUDED.title, "
                        "  price_ore = EXCLUDED.price_ore, in_stock = EXCLUDED.in_stock, "
                        "  last_seen_at = EXCLUDED.last_seen_at, last_ok_at = EXCLUDED.last_ok_at, "
                        # COALESCE, ikke EXCLUDED alene: en kjoring der en
                        # butikk endrer temaet sitt og slutter a levere bilder
                        # skal ikke tomme kolonnen for alle varene deres.
                        "  image_url = COALESCE(EXCLUDED.image_url, listings.image_url), "
                        # Denne SKAL settes til NULL naar merkingen forsvinner:
                        # et forhaandssalg blir en vanlig vare paa slippdatoen,
                        # og da skal merkelappen bort av seg selv.
                        "  bestillingstype = EXCLUDED.bestillingstype",
                        sett_inn)
                if oppdater:
                    cur.executemany(
                        "UPDATE listings SET product_id = %s, title = %s, price_ore = %s, "
                        "in_stock = %s, last_seen_at = %s, last_ok_at = %s, "
                        "image_url = COALESCE(%s, image_url), bestillingstype = %s "
                        "WHERE id = %s",
                        oppdater)

                # Oppforinger som ikke lenger finnes i butikkens katalog.
                # Vi kom hit bare fordi krympvernet sa at skanningen var hel,
                # sa dette er ekte avpubliseringer. De regnes som utsolgt.
                borte = [r for u, r in for_.items() if u not in oppforinger]
                if borte and not bootstrap:
                    for r in borte:
                        if r["in_stock"] is True:
                            hendelser.append((r["id"], r["url"], r["product_id"], butikk_id,
                                              "utsolgt", r["price_ore"], None))
                    cur.execute(
                        "UPDATE listings SET in_stock = FALSE WHERE id = ANY(%s) AND in_stock",
                        ([r["id"] for r in borte],))

                stat["oppforinger"] += len(oppforinger)

            # En butikk som forsvant helt fra kjoringen uten a bli meldt som
            # feilet er nettopp F1-scenarioet: skanningen ga null produkter,
            # og forrige tilstand ma sta urort. Vi rorer den ikke -- men den
            # skal vaere synlig i rapporten, ikke bare stille utelatt.
            cur.execute(
                "SELECT s.id, s.name FROM stores s "
                "WHERE EXISTS (SELECT 1 FROM listings l WHERE l.store_id = s.id)")
            for rad in cur.fetchall():
                if rad["name"] not in per_butikk and rad["name"] not in feilede:
                    stat["hoppet_over"].append("%s (ikke i kjoringen)" % rad["name"])

            # Hendelser med listing_id = None kom fra rader som nettopp ble
            # satt inn; sla opp id-ene deres i én sporring.
            manglende = [h[1] for h in hendelser if h[0] is None]
            oppslag = {}
            if manglende:
                cur.execute("SELECT id, url FROM listings WHERE url = ANY(%s)", (manglende,))
                oppslag = {r["url"]: r["id"] for r in cur.fetchall()}

            storm = len(hendelser) > STORM_GRENSE
            if hendelser:
                cur.executemany(
                    "INSERT INTO events (listing_id, product_id, store_id, kind, "
                    "price_ore, prev_price_ore) VALUES (%s, %s, %s, %s, %s, %s)",
                    [(h[0] if h[0] is not None else oppslag.get(h[1]), h[2], h[3],
                      h[4], h[5], h[6]) for h in hendelser])

            for h in hendelser:
                stat[{"ny": "nye", "restock": "restock", "utsolgt": "utsolgt",
                      "prisendring": "prisendring"}[h[4]]] += 1

            cur.execute(
                "UPDATE scrape_runs SET finished_at = now(), product_count = %s, ok = %s "
                "WHERE id = %s",
                (stat["oppforinger"], not feilede and not storm, kjoring_id))
        conn.commit()

    stat["storm"] = storm
    if verbose:
        print(json.dumps(stat, ensure_ascii=False, indent=2))
        if storm:
            print("ADVARSEL: %d hendelser i én kjoring (grense %d). "
                  "Varsling bor hoppe over denne." % (len(hendelser), STORM_GRENSE))
    return stat


def main():
    p = argparse.ArgumentParser(description="Skriv data.json inn i Postgres.")
    p.add_argument("--data", default=os.path.join(_ROT, "docs", "data.json"))
    p.add_argument("--katalog", default=None)
    p.add_argument("--dsn", default=os.environ.get("POKEPULS_DSN"))
    a = p.parse_args()
    if not a.dsn:
        p.error("mangler --dsn eller POKEPULS_DSN")
    kjor(a.dsn, a.data, a.katalog)


if __name__ == "__main__":
    main()
