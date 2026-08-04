#!/usr/bin/env python3
"""Integrasjonstest som kjorer mot en ekte Postgres.

Kjores pa serveren, der databasen finnes:

    createdb pokepuls_test
    POKEPULS_DSN=postgresql:///pokepuls_test venv/bin/python tests/selvtest.py
    dropdb pokepuls_test

Testen bruker det EKTE datasettet og folger en historie i fire kjoringer:

  1. Tom database   -> alt settes inn, INGEN hendelser (ellers ville forste
                       oppstart sendt 2 000 varsler).
  2. Samme data     -> ingenting endret seg, INGEN hendelser. Dette er den
                       viktigste asserten i hele repoet: en stille kjoring
                       skal vaere stille.
  3. Endret data    -> noyaktig de endringene vi la inn, og ingen andre.
  4. Tom butikk     -> krympvernet slar inn, butikken beholdes urort.
                       Dette er F1: én feilet skanning ga 773 falske varsler.
"""
import argparse
import copy
import json
import os
import sys
import tempfile

import psycopg

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROT, "ingest"))
from ingest import kjor  # noqa: E402

FEIL = []
OK = 0


def sjekk(pastand, tekst, faktisk=None):
    global OK
    if pastand:
        OK += 1
        print("  ok   %s" % tekst)
    else:
        FEIL.append(tekst)
        print("  FEIL %s%s" % (tekst, "" if faktisk is None else "  (fikk %r)" % (faktisk,)))


def tell(dsn, sql, *a):
    with psycopg.connect(dsn) as c:
        return c.execute(sql, a or None).fetchone()[0]


def skriv(data, mappe, navn):
    sti = os.path.join(mappe, navn)
    with open(sti, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return sti


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dsn", default=os.environ.get("POKEPULS_DSN"))
    p.add_argument("--data", default=os.path.join(ROT, "docs", "data.json"))
    a = p.parse_args()
    if not a.dsn:
        p.error("mangler --dsn")
    if "pokepuls_test" not in a.dsn:
        p.error("nekter a kjore mot noe annet enn pokepuls_test - "
                "denne testen tommer tabeller")

    print("Laster skjema ...")
    with psycopg.connect(a.dsn, autocommit=True) as c:
        with open(os.path.join(ROT, "db", "001_skjema.sql"), encoding="utf-8") as f:
            c.execute(f.read())
        for t in ["events", "listings", "scrape_runs", "products",
                  "sets", "product_types", "stores"]:
            c.execute("TRUNCATE %s CASCADE" % t)

    with open(a.data, encoding="utf-8") as f:
        original = json.load(f)

    with tempfile.TemporaryDirectory() as tmp:
        # ---------------------------------------------------- 1. bootstrap
        print("\n1. Forste kjoring (tom database)")
        s1 = kjor(a.dsn, a.data, verbose=False)
        oppforinger = tell(a.dsn, "SELECT count(*) FROM listings")
        sjekk(oppforinger > 1500, "over 1 500 forseglede oppforinger lagret", oppforinger)
        sjekk(oppforinger < 5000, "loskort ble ikke med inn", oppforinger)
        h = tell(a.dsn, "SELECT count(*) FROM events")
        sjekk(h == 0, "ingen hendelser ved forste oppstart", h)
        mappet = tell(a.dsn, "SELECT count(*) FROM listings WHERE product_id IS NOT NULL")
        sjekk(mappet > 1500, "over 1 500 oppforinger mappet til kanonisk produkt", mappet)
        kanoniske = tell(a.dsn,
                         "SELECT count(DISTINCT product_id) FROM listings "
                         "WHERE product_id IS NOT NULL")
        sjekk(kanoniske > 300, "over 300 kanoniske produkter i bruk", kanoniske)
        sjekk(tell(a.dsn, "SELECT count(*) FROM listings WHERE price_ore < 0") == 0,
              "ingen negative priser")

        # -------------------------------------------- 2. identisk kjoring
        print("\n2. Identisk kjoring (ingenting har endret seg)")
        kjor(a.dsn, a.data, verbose=False)
        h = tell(a.dsn, "SELECT count(*) FROM events")
        sjekk(h == 0, "en stille kjoring lager ingen hendelser", h)
        sjekk(tell(a.dsn, "SELECT count(*) FROM listings") == oppforinger,
              "antall oppforinger er uendret")

        # ------------------------------------------------ 3. ekte endring
        print("\n3. Kjoring med tre bevisste endringer")
        endret = copy.deepcopy(original)
        rader = [r for r in endret["products"]
                 if r.get("store") == "Cardcenter" and r.get("url")]
        utsolgt = next(r for r in rader if r.get("in_stock") is False)
        pa_lager = next(r for r in rader if r.get("in_stock") is True)
        med_pris = next(r for r in rader
                        if r is not utsolgt and r is not pa_lager and r.get("price"))
        utsolgt["in_stock"] = True                       # -> restock
        pa_lager["in_stock"] = False                     # -> utsolgt
        med_pris["price"] = "12345.00 kr"                # -> prisendring
        kjor(a.dsn, skriv(endret, tmp, "endret.json"), verbose=False)

        for kind, forventet in [("restock", 1), ("utsolgt", 1), ("prisendring", 1)]:
            n = tell(a.dsn, "SELECT count(*) FROM events WHERE kind = %s", kind)
            sjekk(n == forventet, "noyaktig %d %s-hendelse" % (forventet, kind), n)
        sjekk(tell(a.dsn, "SELECT count(*) FROM events WHERE kind = 'ny'") == 0,
              "ingen falske 'ny'-hendelser")
        ny_pris = tell(a.dsn, "SELECT price_ore FROM listings WHERE url = %s",
                       med_pris["url"])
        sjekk(ny_pris == 1234500, "pris lagret som heltall i ore", ny_pris)

        # --------------------------------------------- 4. feilet skanning
        print("\n4. Kjoring der Cardcenter leverer null produkter (F1)")
        for_ = tell(a.dsn, "SELECT count(*) FROM listings WHERE store_id = 'cardcenter'")
        hendelser_for = tell(a.dsn, "SELECT count(*) FROM events")
        tomt = copy.deepcopy(endret)
        tomt["products"] = [r for r in tomt["products"] if r.get("store") != "Cardcenter"]
        stat = kjor(a.dsn, skriv(tomt, tmp, "tomt.json"), verbose=False)
        etter = tell(a.dsn, "SELECT count(*) FROM listings WHERE store_id = 'cardcenter'")
        sjekk(etter == for_, "Cardcenters oppforinger ble beholdt", (for_, etter))
        sjekk(tell(a.dsn, "SELECT count(*) FROM events") == hendelser_for,
              "ingen nye hendelser fra en butikk som forsvant")
        sjekk(any("Cardcenter (ikke i kjoringen)" == s for s in stat["hoppet_over"]),
              "butikken ble rapportert som fravaerende, ikke stille utelatt",
              stat["hoppet_over"])

        # ------------------------------------------ 4b. halvferdig skanning
        print("\n4b. Kjoring der Cardcenter bare leverer halve katalogen")
        halv = copy.deepcopy(endret)
        cc = [r for r in halv["products"] if r.get("store") == "Cardcenter"]
        behold = {r["url"] for r in cc[:len(cc) // 2]}
        halv["products"] = [r for r in halv["products"]
                            if r.get("store") != "Cardcenter" or r["url"] in behold]
        stat = kjor(a.dsn, skriv(halv, tmp, "halv.json"), verbose=False)
        sjekk(any("krympvern" in s for s in stat["hoppet_over"]),
              "krympvernet slo inn pa en halvferdig skanning", stat["hoppet_over"])
        sjekk(tell(a.dsn, "SELECT count(*) FROM listings WHERE store_id = 'cardcenter'") == for_,
              "ingen oppforinger ble slettet av den halve skanningen")
        sjekk(tell(a.dsn, "SELECT count(*) FROM events") == hendelser_for,
              "og ingen hendelser ble laget")

        # --------------------------------------- 5. eksplisitt feilmelding
        print("\n5. Kjoring der helse-feltet melder at butikken feilet")
        feilet = copy.deepcopy(endret)
        feilet["health"] = {"failed_stores": ["Cardcenter"], "carried_forward_stores": []}
        feilet["products"] = [r for r in feilet["products"] if r.get("store") != "Cardcenter"]
        stat = kjor(a.dsn, skriv(feilet, tmp, "feilet.json"), verbose=False)
        sjekk(any("Cardcenter (feilet)" == s for s in stat["hoppet_over"]),
              "butikken ble hoppet over pa grunn av helsestatus", stat["hoppet_over"])
        sjekk(tell(a.dsn, "SELECT count(*) FROM listings WHERE store_id = 'cardcenter'") == for_,
              "oppforingene star fortsatt urort")

        # ------------------------------------------------- 6. sporringene
        print("\n6. API-sporringene kjorer mot ekte data")
        sys.path.insert(0, os.path.join(ROT, "api"))
        import main as api  # noqa: E402
        with psycopg.connect(a.dsn) as c:
            rader = c.execute(api.SNAPSHOT_SQL).fetchall()
        sjekk(len(rader) > 300, "snapshot gir over 300 kanoniske produkter", len(rader))
        rapayload = len(json.dumps(rader, default=str))
        sjekk(rapayload < 1_500_000,
              "snapshot er under 1,5 MB ra (data.json er 5,8 MB): %.0f KB" % (rapayload / 1024))

    print("\n%d sjekker ok, %d feil" % (OK, len(FEIL)))
    if FEIL:
        for f in FEIL:
            print("  - " + f)
        sys.exit(1)
    print("Alt gront.")


if __name__ == "__main__":
    main()
