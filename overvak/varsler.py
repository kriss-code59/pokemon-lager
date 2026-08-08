#!/usr/bin/env python3
"""Sender Web Push-varsler for nye hendelser til dem som folger produktet.

Kjores av cron rett etter ingest. Egen prosess, ikke en del av ingest:
en feil i varslingen skal aldri kunne rulle tilbake en vellykket ingest.

Slik unngaar den de fire maatene et varslingssystem gjor seg selv ubrukelig:

1. **Duplikater.** notifications_sent har UNIQUE(user_id, event_id). Kjor
   dette skriptet ti ganger paa rad og du faar fortsatt ett varsel.
2. **Storm.** Kommer det flere enn STORM_GRENSE hendelser i én runde, er det
   nesten alltid en datafeil (en butikk som ble tom og kom tilbake), ikke at
   400 varer faktisk kom paa lager. Da flyttes vannmerket uten aa sende.
   Samme resonnement som stormvernet i scrape.py -- og det har reddet oss for.
3. **Gamle nyheter.** Hendelser eldre enn MAKS_ALDER varsles aldri. Etter
   28 timer nede skal du ikke faa 28 timer med restock-beskjeder.
4. **Doede enheter.** 404/410 fra pushtjenesten sletter abonnementet. Uten
   det ville en avinstallert PWA gi feil i loggen i all evighet.

    python overvak/varsler.py            # send
    python overvak/varsler.py --torrkjor # vis hva som ville blitt sendt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from psycopg.rows import dict_row

from varsling import kontekst as kontekst_modul
from varsling import send as sender
from varsling import tekst as tekst_modul

DSN = os.environ.get("POKEPULS_DSN", "postgresql:///pokepuls")
STORM_GRENSE = int(os.environ.get("POKEPULS_VARSEL_STORM", "250"))
MAKS_ALDER_TIMER = 3
OSLO = ZoneInfo("Europe/Oslo")

# Stille natt: 23-07 norsk tid. Varselet gaar ikke tapt -- vi sender det
# aldri, fordi et restock-varsel kl. 03 er verdilost naar du vaakner kl. 07
# og varen har vaert borte i fire timer. Aa lagre det til morgenen ville
# bare gitt deg en koe med daarlige nyheter.
NATT_FRA, NATT_TIL = 23, 7

HENDELSER_SQL = """
SELECT e.id, e.kind, e.price_ore, e.prev_price_ore, e.detected_at,
       e.product_id, e.store_id, e.listing_id,
       st.name AS store_name,
       l.title, l.url, l.image_url, l.bestillingstype,
       s.label AS set_label, t.label AS type_label, p.region, p.set_id
FROM events e
JOIN stores st        ON st.id = e.store_id
LEFT JOIN listings l  ON l.id  = e.listing_id
LEFT JOIN products p  ON p.id  = e.product_id
LEFT JOIN sets s      ON s.id  = p.set_id
LEFT JOIN product_types t ON t.id = p.type_id
WHERE e.id > %s
  AND e.detected_at > now() - make_interval(hours => %s)
ORDER BY e.id
"""

# Hvem foelger dette? Produktet, hele settet, eller ALT (begge NULL).
#
# `spesifikk` avgjor om timeskvoten gjelder. Har du bedt om akkurat DENNE
# varen, skal du faa den uansett hvor mye annet som skjer -- kvoten er der
# for aa temme «foelg alt», ikke for aa holde tilbake noe du har valgt selv.
# Traff en bruker baade spesifikt og via «alt», vinner det spesifikke.
ABONNENTER_SQL = """
SELECT u.id, u.email, u.varsel_stille_natt, u.varsel_maks_pris_ore,
       u.varsel_maks_per_time,
       bool_or(sub.product_id IS NOT NULL OR sub.set_id IS NOT NULL) AS spesifikk
FROM subscriptions sub
JOIN users u ON u.id = sub.user_id
WHERE %s = ANY(sub.kinds)
  AND (   (sub.product_id IS NOT NULL AND sub.product_id = %s)
       OR (sub.set_id     IS NOT NULL AND sub.set_id     = %s)
       OR (sub.product_id IS NULL     AND sub.set_id IS NULL))
GROUP BY u.id, u.email, u.varsel_stille_natt, u.varsel_maks_pris_ore,
         u.varsel_maks_per_time
"""

# Henter kvoten og nullstiller den hvis klokketimen har rullet over.
# Nullstillingen skjer i SAMME setning som lesingen, slik at to samtidige
# kjoringer ikke kan se hver sin halvgamle telling.
KVOTE_SQL = """
INSERT INTO varsel_kvote (user_id) VALUES (%s)
ON CONFLICT (user_id) DO UPDATE SET
  time_start = GREATEST(varsel_kvote.time_start, date_trunc('hour', now())),
  sendt  = CASE WHEN varsel_kvote.time_start < date_trunc('hour', now())
                THEN 0 ELSE varsel_kvote.sendt END,
  dempet = CASE WHEN varsel_kvote.time_start < date_trunc('hour', now())
                THEN 0 ELSE varsel_kvote.dempet END,
  dempet_tekst = CASE WHEN varsel_kvote.time_start < date_trunc('hour', now())
                      THEN '{}'::TEXT[] ELSE varsel_kvote.dempet_tekst END
RETURNING sendt, dempet
"""

ENHETER_SQL = """
SELECT id, endpoint, p256dh, auth FROM push_endpoints WHERE user_id = %s
"""


def er_natt(na: datetime | None = None) -> bool:
    time = (na or datetime.now(timezone.utc)).astimezone(OSLO).hour
    return time >= NATT_FRA or time < NATT_TIL


def kort_navn(varsel: dict) -> str:
    """Forste linje av kroppen -- produktnavnet. Det er det eneste som
    gir mening i en samleliste; butikk og pris varierer per rad."""
    return (varsel.get("body") or "").split("\n")[0][:60]


def samletekst(antall: int, navn: list[str]) -> dict:
    """Ett varsel som staar for mange.

    Tallet forst, fordi det er det som forteller deg om du bor apne
    Pokepuls naa eller etter middag. Navnene under, saa du kan se om noe
    du faktisk venter paa er blant dem.
    """
    vist = [n for n in navn if n][:3]
    kropp = " · ".join(vist) if vist else "Se alle på pokepuls.no"
    if antall > len(vist) and vist:
        kropp += f" · og {antall - len(vist)} til"
    return {
        "title": f"🛒 {antall} flere varer kom inn",
        "body": kropp,
        "url": "https://pokepuls.no/",
        "produkt_url": "https://pokepuls.no/",
        "bilde": None,
        "kind": "samle",
        # Fast tag: et nyere samlevarsel erstatter det forrige i stedet
        # for aa stable seg opp time etter time.
        "tag": "pokepuls:samle",
        # Et sammendrag haster per definisjon ikke. Hadde det hastet,
        # ville det vaert sendt enkeltvis.
        "hastig": False,
        "bestillingstype": None,
    }


def send_samlevarsel(cur, sender, natt: bool) -> int:
    """-> antall brukere som fikk et sammendrag."""
    cur.execute("SELECT k.user_id, k.dempet, k.dempet_tekst, u.varsel_stille_natt "
                "FROM varsel_kvote k JOIN users u ON u.id = k.user_id "
                "WHERE k.dempet > 0")
    sendt = 0
    for rad in cur.fetchall():
        # Nullstill uansett. Et sammendrag som ikke ble sendt fordi det er
        # natt, skal ikke dukke opp klokka sju som gammelt nytt.
        cur.execute("UPDATE varsel_kvote SET dempet = 0, dempet_tekst = '{}' "
                    "WHERE user_id = %s", (rad["user_id"],))
        if natt and rad["varsel_stille_natt"]:
            continue
        varsel = samletekst(rad["dempet"], list(rad["dempet_tekst"] or []))
        cur.execute(ENHETER_SQL, (rad["user_id"],))
        for enhet in cur.fetchall():
            ok, _feil, _status = sender.send(enhet, varsel)
            if ok:
                sendt += 1
                break
    return sendt


def sett_vannmerke(cur, event_id: int) -> None:
    cur.execute(
        "UPDATE varsel_tilstand SET siste_event_id = %s, sist_kjort_at = now() "
        "WHERE id = 1 AND siste_event_id < %s", (event_id, event_id))


def kjor(dsn: str = DSN, torrkjor: bool = False, verbose: bool = True) -> dict:
    stat = {"vurdert": 0, "kandidater": 0, "sendt": 0, "feilet": 0,
            "hoppet_natt": 0, "hoppet_pris": 0, "doede_enheter": 0,
            "dempet": 0, "samlevarsler": 0, "storm": False}

    with psycopg.connect(dsn, row_factory=dict_row, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT siste_event_id FROM varsel_tilstand WHERE id = 1")
            rad = cur.fetchone()
            if not rad:
                # 002_varsler.sql har ikke kjort. Ikke send noe -- uten
                # vannmerke ville vi varslet hele historikken.
                raise SystemExit("varsel_tilstand mangler. Kjor db/002_varsler.sql.")
            vannmerke = rad["siste_event_id"]

            cur.execute(HENDELSER_SQL, (vannmerke, MAKS_ALDER_TIMER))
            hendelser = cur.fetchall()
            stat["vurdert"] = len(hendelser)
            if not hendelser:
                if not torrkjor:
                    cur.execute("UPDATE varsel_tilstand SET sist_kjort_at = now() WHERE id = 1")
                    conn.commit()
                if verbose:
                    print(json.dumps(stat, ensure_ascii=False))
                return stat

            hoyeste = hendelser[-1]["id"]

            if len(hendelser) > STORM_GRENSE:
                stat["storm"] = True
                if verbose:
                    print(f"STORMVERN: {len(hendelser)} hendelser (grense "
                          f"{STORM_GRENSE}). Sender ingen varsler. Vannmerket "
                          f"flyttes til {hoyeste} sa vi ikke henger fast her.")
                if not torrkjor:
                    sett_vannmerke(cur, hoyeste)
                    conn.commit()
                return stat

            natt = er_natt()
            # Cache per produkt: en runde har typisk 5-40 hendelser fordelt
            # paa langt faerre produkter, og prisbildet endrer seg ikke
            # mellom to hendelser i samme runde.
            kontekst_cache: dict[str, dict] = {}

            for h in hendelser:
                cur.execute(ABONNENTER_SQL, (h["kind"], h["product_id"], h["set_id"]))
                abonnenter = cur.fetchall()
                if not abonnenter:
                    continue

                pid = h["product_id"] or ""
                if pid not in kontekst_cache:
                    kontekst_cache[pid] = kontekst_modul.hent(cur, h["product_id"])
                ktx = kontekst_cache[pid]
                varsel = tekst_modul.bygg(h, ktx)
                stat["kandidater"] += 1

                for bruker in abonnenter:
                    if natt and bruker["varsel_stille_natt"]:
                        stat["hoppet_natt"] += 1
                        continue
                    tak = bruker["varsel_maks_pris_ore"]
                    if tak and h["price_ore"] and h["price_ore"] > tak:
                        stat["hoppet_pris"] += 1
                        continue

                    # Timeskvoten. Gjelder bare den som har bedt om ALT --
                    # se ABONNENTER_SQL. Er taket naadd, teller vi hendelsen
                    # som dempet og sender ett samlevarsel til slutt i
                    # stedet. Vannmerket flyttes uansett, saa den kommer
                    # aldri tilbake som et nytt varsel senere.
                    if not bruker["spesifikk"]:
                        cur.execute(KVOTE_SQL, (bruker["id"],))
                        kvote = cur.fetchone()
                        maks = bruker["varsel_maks_per_time"] or 5
                        if kvote["sendt"] >= maks:
                            cur.execute(
                                "UPDATE varsel_kvote SET dempet = dempet + 1, "
                                "dempet_tekst = (dempet_tekst || ARRAY[%s])[1:5] "
                                "WHERE user_id = %s",
                                (kort_navn(varsel), bruker["id"]))
                            stat["dempet"] += 1
                            continue

                    # Reserver plassen FOR vi sender. Feiler utsendingen,
                    # staar raden igjen med ok=false -- da vet vi at det
                    # skjedde, og vi sender likevel ikke det samme paa nytt.
                    cur.execute(
                        "INSERT INTO notifications_sent (user_id, event_id) "
                        "VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING id",
                        (bruker["id"], h["id"]))
                    if not cur.fetchone():
                        continue  # allerede sendt

                    if torrkjor:
                        print(f"[{bruker['email']}] {varsel['title']}\n"
                              f"    {varsel['body']}".replace("\n", "\n    "))
                        stat["sendt"] += 1
                        continue

                    cur.execute(ENHETER_SQL, (bruker["id"],))
                    enheter = cur.fetchall()
                    if not enheter:
                        cur.execute("UPDATE notifications_sent SET ok = FALSE, "
                                    "feil = 'ingen push-enheter' "
                                    "WHERE user_id = %s AND event_id = %s",
                                    (bruker["id"], h["id"]))
                        continue

                    noen_ok = False
                    siste_feil = None
                    for enhet in enheter:
                        ok, feil, status = sender.send(enhet, varsel)
                        if ok:
                            noen_ok = True
                            cur.execute("UPDATE push_endpoints SET last_ok_at = now(), "
                                        "feil_pa_rad = 0, sist_feil = NULL WHERE id = %s",
                                        (enhet["id"],))
                        else:
                            siste_feil = feil
                            if sender.er_dod(status):
                                cur.execute("DELETE FROM push_endpoints WHERE id = %s",
                                            (enhet["id"],))
                                stat["doede_enheter"] += 1
                            else:
                                cur.execute("UPDATE push_endpoints SET feil_pa_rad = "
                                            "feil_pa_rad + 1, sist_feil = %s WHERE id = %s",
                                            (feil, enhet["id"]))
                    if noen_ok:
                        stat["sendt"] += 1
                        if not bruker["spesifikk"]:
                            cur.execute("UPDATE varsel_kvote SET sendt = sendt + 1 "
                                        "WHERE user_id = %s", (bruker["id"],))
                    else:
                        stat["feilet"] += 1
                        cur.execute("UPDATE notifications_sent SET ok = FALSE, feil = %s "
                                    "WHERE user_id = %s AND event_id = %s",
                                    (siste_feil, bruker["id"], h["id"]))

            # Ett samlevarsel per bruker som ble dempet. Det sendes til
            # slutt, naar vi vet hvor mange det ble -- ikke underveis, der
            # vi bare ville visst om det forste.
            if not torrkjor:
                stat["samlevarsler"] = send_samlevarsel(cur, sender, natt)

            if not torrkjor:
                sett_vannmerke(cur, hoyeste)
                conn.commit()
            else:
                conn.rollback()

    if verbose:
        print(json.dumps(stat, ensure_ascii=False))
    return stat


def main():
    p = argparse.ArgumentParser(description="Send push-varsler for nye hendelser.")
    p.add_argument("--dsn", default=DSN)
    p.add_argument("--torrkjor", action="store_true",
                   help="Vis hva som ville blitt sendt. Skriver ingenting.")
    p.add_argument("--stille", action="store_true")
    a = p.parse_args()
    kjor(a.dsn, torrkjor=a.torrkjor, verbose=not a.stille)


if __name__ == "__main__":
    main()
