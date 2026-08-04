"""Kanonisk produktmatching.

Gjor om en ra butikkoppforing ("Maks 1 per pers. Pokemon Ascended Heroes
Elite Trainer Box") til et kanonisk produkt-ID ("ascended-heroes:etb:en").

Hele poenget: uten dette er 18 000 butikkrader bare stoy. Med det kan vi si
"Pitch Black Booster Box - 4 av 6 butikker har den pa lager", sammenligne
pris pa tvers, og la brukere folge ET PRODUKT i stedet for en butikklenke.

Se katalog.json for datagrunnlaget.
"""
import json
import os
import re
import unicodedata

_HER = os.path.dirname(os.path.abspath(__file__))

# Loskort: "#095 Onix 095/165 Uncommon", "125/193 Common", "Reverse Holo".
# Disse skal aldri inn i den kanoniske katalogen -- de er ikke sealed produkt.
SINGLE_RE = re.compile(
    r"(^\s*#?\d{1,3}\s)"                      # "#095 Onix ..."
    r"|(\b\d{1,3}\s*/\s*\d{1,3}\b)"          # "095/165"
    r"|\b(reverse\s*holo|uncommon)\b"          # sjeldenhetsgrad
    r"|\s-\s*(nm|lp|mp|hp|dmg|ex-mt|played)\s*$"  # tilstandskode: "... - NM"
    r"|\b(1st\s*edition|unlimited\s*edition)\b"
    r"|\bpromos\b"                             # "... - Scarlet & Violet Promos - NM"
    r"|\(jp\)\s*\d+"                          # "Budew (JP) 196 holo"
    r"|\s\d{1,3}\s+holo\b"
    r"|\b(psa|bgs|cgc)\s*\d"                   # graderte kort
    r"|\s\d{1,3}\s*-\s+\w",                   # "Carnivine 16 - Triumphant"
    re.I)

# Butikker som utelukkende selger loskort. Vi henter dem ikke i det hele tatt
# til den kanoniske katalogen -- de sto for 10 598 av 18 228 rader (58 %) og
# ingen onsker restock-varsel pa enkeltkort.
SINGLES_ONLY_STORES = {"LABOGE", "Pokesingles"}

# Merch: plysj, figurer, sleeves osv. Ikke sealed TCG-produkt.
MERCH_RE = re.compile(
    r"\b(plush|plysj|figur|figure|moncolle|re-?ment|sleeve|sleeves|binder|perm|"
    r"playmat|spillematte|sticker|klistremerke|kosedyr|mug|kopp|nokkelring|"
    r"nakkelring|keychain|puslespill|puzzle|backpack|sekk|caps|lue|t-?skjorte|"
    r"genser|handkle|pin|coin|mynt|lanyard|armband|smykke|veske|pennal|funko|"
    r"portfolio|album|toploader|penn|notatbok)\b", re.I)

# Butikkstoy som ma bort for matching ("Maks 1 per pers.", "Bestillingsvare")
NOISE_RE = re.compile(
    r"(maks\s*\d+\s*per\s*pers\.?|bestillingsvare|forh[ao]ndsbestilling|pre-?order|"
    r"kommer\s+snart|utsolgt|nyhet!?|tilbud!?|kampanje)", re.I)


def strip_diacritics(text):
    """'Pokémon' -> 'pokemon', 'ø' -> 'o'. Uten dette matcher ikke norske
    titler mot engelske aliaser."""
    text = text.replace("ø", "o").replace("Ø", "O").replace("æ", "ae").replace("Æ", "AE")
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(title):
    t = strip_diacritics(title or "").lower()
    t = NOISE_RE.sub(" ", t)
    t = re.sub(r"[^\w\s&]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class Katalog:
    def __init__(self, path=None):
        with open(path or os.path.join(_HER, "katalog.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.sets = data["sets"]
        self.types = data["types"]
        self.regions = data["regions"]

        # Sorter aliaser lengst forst, slik at "elite trainer box" vinner over
        # "box", og "mini tin" over "tin".
        self._set_aliases = self._build(self.sets)
        self._type_aliases = self._build(self.types)
        self._region_aliases = self._build(self.regions)

    @staticmethod
    def _build(entries):
        pairs = []
        for e in entries:
            for a in e["aliases"]:
                pairs.append((normalize(a), e["id"]))
        return sorted(pairs, key=lambda p: -len(p[0]))

    @staticmethod
    def _find(text, pairs):
        for alias, eid in pairs:
            if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text):
                return eid
        return None

    def classify(self, title):
        """-> 'single' | 'merch' | 'sealed'"""
        if SINGLE_RE.search(title or ""):
            return "single"
        if MERCH_RE.search(title or ""):
            return "merch"
        return "sealed"

    def match(self, title):
        """-> dict med set_id/type_id/region/product_id, eller None."""
        if self.classify(title) != "sealed":
            return None
        t = normalize(title)
        set_id = self._find(t, self._set_aliases)
        type_id = self._find(t, self._type_aliases)
        if not set_id or not type_id:
            return None

        # Region: eksplisitt i tittelen ("Japansk") vinner, ellers settets
        # egen region. Et japansk sett solgt uten spraakmarkering er japansk.
        region = self._find(t, self._region_aliases)
        if not region:
            region = next(s["region"] for s in self.sets if s["id"] == set_id)

        return {
            "set_id": set_id,
            "type_id": type_id,
            "region": region,
            "product_id": "%s:%s:%s" % (set_id, type_id, region),
        }
