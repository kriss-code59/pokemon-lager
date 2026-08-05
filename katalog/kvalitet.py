#!/usr/bin/env python3
"""Mal hvor god katalogmatchingen er.

`dekning.py` svarer pa hvor MANGE varer vi treffer. Denne svarer pa om
treffene er RIKTIGE -- som er et helt annet sporsmal, og det som avgjor om
tallene pa siden er til a stole pa.

Hovedmalet er prisspredning. Nar to varer havner under samme kanoniske
produkt, ser du det pa prisen: en Booster Bundle til 599 kr og en kartong
med 25 av dem til 39 999 kr er ikke samme vare. Et produkt der dyreste
tilbud er mer enn ti ganger det billigste er nesten alltid en feilmatch.

    python3 katalog/kvalitet.py                 # sammendrag
    python3 katalog/kvalitet.py --detaljer 15   # vis de verste gruppene
    python3 katalog/kvalitet.py --json          # for maskinell sammenligning

Kjor den for og etter en katalogendring. Tallet som skal ned er
"produkter med >10x spredning".
"""
import argparse
import collections
import json
import os
import sys

_HER = os.path.dirname(os.path.abspath(__file__))
_ROT = os.path.dirname(_HER)
sys.path.insert(0, _HER)
sys.path.insert(0, os.path.join(_ROT, "ingest"))

from ingest import grupper_per_butikk  # noqa: E402
from matcher import Katalog  # noqa: E402

# Over denne faktoren mellom dyreste og billigste tilbud er det nesten
# alltid to ulike varer som har havnet i samme gruppe.
MISTENKELIG_FAKTOR = 10


def samle(data_sti, katalog_sti=None):
    katalog = Katalog(katalog_sti)
    with open(data_sti, encoding="utf-8") as f:
        data = json.load(f)
    per_butikk, forkastet = grupper_per_butikk(data.get("products") or [], katalog)

    per_produkt = collections.defaultdict(list)
    umatchet = []
    for butikk, oppforinger in per_butikk.items():
        for o in oppforinger.values():
            if o["product_id"]:
                per_produkt[o["product_id"]].append((butikk, o["title"], o["price_ore"]))
            else:
                umatchet.append((butikk, o["title"]))
    return data, per_butikk, forkastet, per_produkt, umatchet


def spredning(per_produkt):
    ut = []
    for pid, rader in per_produkt.items():
        priser = [p for _, _, p in rader if p]
        if len(priser) >= 2:
            ut.append((max(priser) / min(priser), pid, len(rader),
                       min(priser), max(priser)))
    return sorted(ut, reverse=True)


def main():
    p = argparse.ArgumentParser(description="Mal kvaliteten pa katalogmatchingen.")
    p.add_argument("--data", default=os.path.join(_ROT, "docs", "data.json"))
    p.add_argument("--katalog", default=None)
    p.add_argument("--detaljer", type=int, default=0,
                   help="vis de N verste gruppene med alle tilbud")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    data, per_butikk, forkastet, per_produkt, umatchet = samle(a.data, a.katalog)
    sp = spredning(per_produkt)
    mistenkelige = [x for x in sp if x[0] > MISTENKELIG_FAKTOR]
    beholdt = sum(len(v) for v in per_butikk.values())
    matchet = sum(len(v) for v in per_produkt.values())

    sammendrag = {
        "skannet": data.get("last_updated"),
        "rader_inn": len(data.get("products") or []),
        "forkastet": forkastet,
        "forseglede_varer": beholdt,
        "matchet": matchet,
        "umatchet": len(umatchet),
        "dekning_prosent": round(100 * matchet / max(1, beholdt), 1),
        "kanoniske_produkter": len(per_produkt),
        "produkter_med_pris": len(sp),
        "mistenkelig_spredning": len(mistenkelige),
    }

    if a.json:
        print(json.dumps(sammendrag, ensure_ascii=False, indent=2))
        return

    print("Skannet:            %s" % sammendrag["skannet"])
    print("Rader inn:          %d" % sammendrag["rader_inn"])
    print("Forkastet:          %s" % ", ".join(
        "%s %d" % (k, v) for k, v in sorted(forkastet.items())))
    print("Forseglede varer:   %d" % beholdt)
    print("Matchet:            %d  (%.1f %% dekning)"
          % (matchet, sammendrag["dekning_prosent"]))
    print("Umatchet:           %d" % len(umatchet))
    print("Kanoniske produkter:%d" % len(per_produkt))
    print()
    print("Produkter med >%dx prisspredning: %d av %d med minst to priser"
          % (MISTENKELIG_FAKTOR, len(mistenkelige), len(sp)))
    for faktor, pid, n, lo, hi in sp[:10]:
        merke = "  <-- se pa denne" if faktor > MISTENKELIG_FAKTOR else ""
        print("   %6.1fx  %-38s %2d tilbud  %6.0f - %7.0f kr%s"
              % (faktor, pid, n, lo / 100, hi / 100, merke))

    for faktor, pid, n, lo, hi in sp[:a.detaljer]:
        print("\n=== %s (%.0fx) ===" % (pid, faktor))
        for butikk, tittel, pris in sorted(per_produkt[pid], key=lambda r: r[2] or 0):
            print("   %8s  %-16s %s"
                  % (pris / 100 if pris else "-", butikk[:16], tittel[:70]))

    if umatchet:
        print("\nVanligste umatchede titler (kandidater til nye aliaser):")
        for tittel, n in collections.Counter(t for _, t in umatchet).most_common(12):
            print("   %2d  %s" % (n, tittel[:76]))


if __name__ == "__main__":
    main()
