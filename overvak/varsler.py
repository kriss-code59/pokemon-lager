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
       l.title, l.url, l.image_url,
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

# Hvem foelger dette? Enten produktet direkte, eller hele settet.
ABONNENTER_SQL = """
SELECT DISTINCT u.id, u.email, u.varsel_stille_natt, u.varsel_maks_pris_ore
FROM subscriptions sub
JOIN users u ON u.id = sub.user_id
WHERE %s = ANY(sub.kinds)
  AND (   (sub.product_id IS NOT NULL AND sub.product_id = %s)
       OR (sub.set_id     IS NOT NULL AND sub.set_id     = %s))
"""

ENHETER_SQL = """
SELECT id, endpoint, p256dh, auth FROM push_endpoints WHERE user_id = %s
"""


def er_natt(na: datetime | None = None) -> bool:
    time = (na or datetime.now(timezone.utc)).astimezone(OSLO).hour
    return time >= NATT_FRA or time < NATT_TIL


def sett_vannmerke(cur, event_id: int) -> None:
    cur.execute(
        "UPDATE varsel_tilstand SET siste_event_id = %s, sist_kjort_at = now() "
        "WHERE id = 1 AND siste_event_id < %s", (event_id, event_id))


def kjor(dsn: str = DSN, torrkjor: bool = False, verbose: bool = True) -> dict:
    stat = {"vurdert": 0, "kandidater": 0, "sendt": 0, "feilet": 0,
            "hoppet_natt": 0, "hoppet_pris": 0, "doede_enheter": 0, "storm": False}

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
                    else:
                        stat["feilet"] += 1
                        cur.execute("UPDATE notifications_sent SET ok = FALSE, feil = %s "
                                    "WHERE user_id = %s AND event_id = %s",
                                    (siste_feil, bruker["id"], h["id"]))

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
