"""Dekningsanalyse: hvor mye av de ra dataene treffer katalogen, og hvilke
sett mangler? Kjor denne etter hver storre skanning for a se om nye sett har
dukket opp i butikkene uten a vaere lagt inn i katalog.json."""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from matcher import Katalog, SINGLES_ONLY_STORES  # noqa: E402

STOPP = set("""pokemon booster box display elite trainer etb pack packs pakke pakker bundle tin
collection premium blister sleeved deck chest case boks japansk japanske engelsk engelske kinesisk
kinesiske korean set sets vol stk med og the of and new nye ny card cards kort tcg ex gx vmax vstar
special first partner ultra super mega gift eske samleboks gaveboks bestillingsvare tilfeldig art
pro edition series center build battle league""".split())


def main(path="docs/data.json"):
    k = Katalog()
    produkter = [p for p in json.load(open(path, encoding="utf-8"))["products"]
                 if p["store"] not in SINGLES_ONLY_STORES]

    b = collections.Counter()
    treff = 0
    bom = []
    kanoniske = collections.Counter()
    for p in produkter:
        n = p["name"] or ""
        c = k.classify(n)
        b[c] += 1
        if c != "sealed":
            continue
        m = k.match(n)
        if m:
            treff += 1
            kanoniske[m["product_id"]] += 1
        else:
            bom.append(n)

    print("rader:   %d" % len(produkter))
    print("sealed:  %d   single: %d   merch: %d" % (b["sealed"], b["single"], b["merch"]))
    print("treff:   %d av %d (%.1f%%)" % (treff, b["sealed"], 100 * treff / max(b["sealed"], 1)))
    print("kanoniske produkter: %d" % len(kanoniske))
    print()
    print("=== MULIGE MANGLENDE SETT (hyppige ordpar blant bommene) ===")
    g = collections.Counter()
    for n in bom:
        w = [x for x in re.sub(r"[^\w\s]", " ", n.lower()).split()
             if x not in STOPP and not x.isdigit() and len(x) > 2]
        for i in range(len(w) - 1):
            g[" ".join(w[i:i + 2])] += 1
    for gg, c in g.most_common(30):
        if c >= 5:
            print("  %4d  %s" % (c, gg))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/data.json")
