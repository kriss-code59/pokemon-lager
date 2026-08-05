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
from datetime import datetime

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

        # ------------------------------------------------- 6. hele API-et
        # Kjor endepunktene gjennom ekte HTTP i stedet for bare a sjekke
        # SQL-en. Uten dette gar en serialiseringsfeil (datetime i
        # JSONResponse) rett i produksjon -- den gjorde det én gang.
        print("\n6. API-endepunktene svarer")
        os.environ["POKEPULS_DSN"] = a.dsn
        sys.path.insert(0, ROT)
        from fastapi.testclient import TestClient  # noqa: E402
        from api import main as api  # noqa: E402

        with TestClient(api.app) as klient:
            r = klient.get("/api/health")
            sjekk(r.status_code in (200, 503), "/health svarer med gyldig status",
                  r.status_code)
            sjekk("sist_kjort" in r.json(), "/health har sist_kjort", r.text[:120])

            r = klient.get("/api/snapshot")
            sjekk(r.status_code == 200, "/snapshot svarer 200", r.status_code)
            d = r.json()
            sjekk(len(d["produkter"]) > 300,
                  "snapshot gir over 300 kanoniske produkter", len(d["produkter"]))
            storrelse = len(r.content)
            sjekk(storrelse < 1_500_000,
                  "snapshot er %.0f KB ra (data.json er 5 800 KB)" % (storrelse / 1024))
            etag = r.headers.get("etag")
            sjekk(bool(etag), "snapshot har ETag", etag)
            sjekk(klient.get("/api/snapshot",
                             headers={"If-None-Match": etag}).status_code == 304,
                  "uendret snapshot gir 304 og tom kropp")

            pid = d["produkter"][0]["id"]
            r = klient.get("/api/product/" + pid)
            sjekk(r.status_code == 200, "/product/<id> svarer 200", r.status_code)
            sjekk(len(r.json()["tilbud"]) > 0, "produktet har minst ett tilbud")
            sjekk(klient.get("/api/product/finnes-ikke:x:en").status_code == 404,
                  "ukjent produkt gir 404")

            for sti in ["/api/catalog", "/api/unmatched?limit=50",
                        "/api/history?limit=10", "/api/history?kind=restock"]:
                sjekk(klient.get(sti).status_code == 200, sti + " svarer 200")
            sjekk(klient.get("/api/history?kind=tull").status_code == 400,
                  "ugyldig hendelsestype gir 400")

            # --------------------------------------------- 7. konto og folgeliste
            print("\n7. Konto, sesjon og folgeliste")
            e_post = "selvtest-%d@pokepuls.no" % int(datetime.now().timestamp())
            passord = "et-ganske-langt-passord"

            sjekk(klient.get("/api/watchlist").status_code == 401,
                  "folgelisten krever innlogging")
            sjekk(klient.post("/api/auth/register",
                              json={"email": e_post, "password": "kort"}).status_code == 422,
                  "for kort passord avvises")

            r = klient.post("/api/auth/register", json={"email": e_post, "password": passord})
            sjekk(r.status_code == 200, "registrering svarer 200", r.text[:120])
            sjekk("pokepuls_sesjon" in r.cookies or "pokepuls_sesjon" in klient.cookies,
                  "sesjonscookie ble satt")
            sjekk(klient.post("/api/auth/register",
                              json={"email": e_post, "password": passord}).status_code == 409,
                  "samme e-post to ganger gir 409")

            r = klient.get("/api/auth/me")
            sjekk(r.json().get("innlogget") is True, "/auth/me ser sesjonen", r.text[:120])

            r = klient.post("/api/watchlist", json={"product_id": pid})
            sjekk(r.status_code == 200, "kan folge et produkt", r.text[:120])
            abonnement = r.json()["id"]
            liste = klient.get("/api/watchlist").json()["folger"]
            sjekk(len(liste) == 1 and liste[0]["product_id"] == pid,
                  "produktet ligger i folgelisten")
            fl = klient.get("/api/watchlist/snapshot").json()["produkter"]
            sjekk(len(fl) == 1 and fl[0]["id"] == pid,
                  "folgeliste-snapshot gir samme form som /snapshot")

            sjekk(klient.delete("/api/watchlist/%d" % abonnement).status_code == 200,
                  "kan slutte a folge")
            sjekk(len(klient.get("/api/watchlist").json()["folger"]) == 0,
                  "folgelisten er tom igjen")

            klient.post("/api/auth/logout")
            sjekk(klient.get("/api/auth/me").json().get("innlogget") is False,
                  "utlogging avslutter sesjonen")
            sjekk(klient.post("/api/auth/login",
                              json={"email": e_post, "password": "feil passord"}
                              ).status_code == 401, "feil passord gir 401")
            sjekk(klient.post("/api/auth/login",
                              json={"email": e_post, "password": passord}
                              ).status_code == 200, "kan logge inn igjen")

            # Passordet skal aldri kunne leses ut av databasen, og tokenet
            # skal ikke ligge der i klartekst.
            with psycopg.connect(a.dsn) as c:
                hash_ = c.execute("SELECT password_hash FROM users WHERE email = %s",
                                  (e_post,)).fetchone()[0]
                sjekk(hash_.startswith("$argon2id$"), "passordet er argon2id-hashet",
                      hash_[:20])
                sjekk(passord not in hash_, "passordet star ikke i klartekst")
                token_rader = c.execute(
                    "SELECT token_hash FROM sessions").fetchall()
                sjekk(all(len(t[0]) == 64 for t in token_rader),
                      "sesjoner lagres som sha256, ikke som token")

    print("\n%d sjekker ok, %d feil" % (OK, len(FEIL)))
    if FEIL:
        for f in FEIL:
            print("  - " + f)
        sys.exit(1)
    print("Alt gront.")


if __name__ == "__main__":
    main()
