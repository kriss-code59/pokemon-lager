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
    # "Carnivine 16 - Triumphant" er et kort. "Gem Pack Vol 1 - Chinese
    # Booster Box" er det ikke, sa volumnummer ma unntas.
    r"|(?<!vol)(?<!vol\.)(?<!volume)(?<!nr)(?<!no)\s\d{1,3}\s*-\s+\w",
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
    r"portfolio|album|toploader|penn|notatbok|display\s*stand|"
    r"binder\s*set|badge\s*box|deck\s*case|mystery\s*bag)\b", re.I)

# Multipakker: en kartong med 25 bundles er ikke samme vare som én bundle.
# Uten dette havnet "Ascended Heroes Booster Bundle" (599 kr) og
# "Ascended Heroes Booster Bundle Case (6 sealed displays)" (119 940 kr)
# under samme kanoniske produkt, og "billigste pris" ble meningslos.
MULTIPAKKE_RE = re.compile(
    # "(Case tilgjengelig)" er en OPPLYSNING om at butikken ogsa selger case.
    # Varen som selges er én boks. Uten unntaket her forsvant ti ekte
    # oppforinger fra BoosterKongen.
    r"\bcase\b(?!\s*tilgjengelig)"               # "Bundle Case", "Booster Case"
    r"|\(\s*\d+\s*(stk|pcs|pack|sealed)"        # "(25 stk)", "(6 sealed displays)"
    r"|\bart\s*set\b"                            # "Booster Packs ART SET"
    r"|\b\d{2,}\s*booster\s*pack"               # "100 Booster Packs to Destiny"
    r"|\bspeed\s*run\b"
    r"|\d+\s*\.?\s*pack\s*run\b"                # "15. Pack Run"
    # "Mini Tin Sealed Display", "Booster Bundle - Sealed Display",
    # "Mini Tin (Display)": en display FULL av mindre enheter.
    # NB: "Booster Display" alene betyr booster box og skal IKKE hit -- derfor
    # kreves en mindre enhet foran.
    r"|\b(mini\s*tin|tin|bundle|blister|etb|elite\s*trainer\s*box|collection)\b"
    r"[\s\w()-]{0,24}?\bdisplay\b"
    r"|\(\s*display\s*\)"
    r"|\bdisplay\s*\(\s*sealed",
    re.I)

# Vintage: WotC-era forseglet produkt. Prisene ligger en storrelsesorden over
# moderne varer (6 999 kr for én booster pack fra 2000), og de kjopes av en
# helt annen grunn. De skal ikke inn i prissammenligningen for et moderne sett.
#
# To fallgruver som begge kostet ekte oppforinger da de var med:
#   * Arstall i parentes betyr bare vintage hvis arstallet ER gammelt.
#     "Trick or Trade Booster Pakke (2024)" er en helt vanlig moderne vare.
#   * "(Charizard art)" brukes ogsa om moderne kinesiske bokser med
#     omslagsvariant. Kunstnavn alene sier ingenting om alder.
VINTAGE_RE = re.compile(
    r"\((?:[^)]*\s)?(19\d{2}|20[01]\d)\)"        # "(2000)", "(Black & White 2013)"
    r"|\b1\.?\s*edition\b"
    r"|\bunlimited\b"
    r"|tamper\s*sealed"
    r"|[åa]pnet\s+live"
    r"|\bwotc\b",
    re.I)

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


# En parentes som teller opp innholdet beskriver ikke varetypen:
# "Mini Tin (2 Booster Packs)" er en mini tin, ikke en boosterpakke.
# Uten dette vant "booster pack" over "mini tin" fordi aliaset er lengre.
_INNMAT_RE = re.compile(r"\(\s*\d+\s*[^)]*\)")


def strip_innmat(text):
    return re.sub(r"\s+", " ", _INNMAT_RE.sub(" ", text or "")).strip()


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

        # Serienavn ("Mega Evolution", "Sword & Shield") star i katalogen som
        # `serie_aliaser`. De brukes BARE hvis ingen ekte sett traff.
        #
        # Uten dette skillet vinner det lengste aliaset, og siden
        # "mega evolution" er lengre enn "pitch black", havnet
        # "Mega Evolution Pitch Black Booster Pack" under serien i stedet for
        # settet. Det gjaldt 30+ oppforinger og gjorde prissammenligningen
        # meningslos: ME01 Base Set og ME05 Pitch Black er ikke samme vare.
        self._serie_aliases = self._build(self.sets, "serie_aliaser")

        # Hvor stor enhet typen er. Brukes nar flere typer treffer samme
        # tittel; se _velg_type. Uten verdi teller typen som minst.
        self._storrelse = {t["id"]: t.get("storrelse", 0) for t in self.types}

    @staticmethod
    def _build(entries, felt="aliases"):
        pairs = []
        for e in entries:
            for a in e.get(felt) or []:
                pairs.append((normalize(a), e["id"]))
        return sorted(pairs, key=lambda p: -len(p[0]))

    @staticmethod
    def _finn(text, pairs):
        """-> (id, start, slutt) for det lengste aliaset som treffer."""
        for alias, eid in pairs:
            m = re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text)
            if m:
                return eid, m.start(), m.end()
        return None, -1, -1

    @classmethod
    def _find(cls, text, pairs):
        return cls._finn(text, pairs)[0]

    def _velg_type(self, t):
        """Nar flere typer treffer, vinner den STORSTE enheten.

        "Crimson Haze - Booster Pack (Japansk) - Booster Box" er en boks.
        Butikken har skrevet begge deler i tittelen, og med rent lengste-
        alias-treff vant "booster pack" -- som gjorde at en boks til 1 449 kr
        havnet sammen med losspakker til 49 kr.

        En boks inneholder pakker; nevner tittelen begge, er varen boksen.
        """
        treff = []
        for alias, tid in self._type_aliases:
            m = re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", t)
            if m:
                treff.append((m.start(), m.end(), self._storrelse.get(tid, 0),
                              len(alias), tid))
        if not treff:
            return None

        # Et alias som ligger INNI et annet er den mindre presise lesningen:
        # "tin" inne i "mini tin" beskriver ikke en tin. Storrelsesregelen
        # gjelder bare mellom typer som star hver for seg i tittelen.
        egne = [a for a in treff
                if not any(b is not a and b[0] <= a[0] and a[1] <= b[1]
                           and (b[1] - b[0]) > (a[1] - a[0]) for b in treff)]
        return max(egne or treff, key=lambda x: (x[2], x[3]))[4]

    def _velg_sett(self, t):
        """Sett vinner over serie -- med ett unntak.

        Et serienavn brukes bare som fallback, ellers havner
        "Mega Evolution Pitch Black" under serien i stedet for settet.

        Unntaket er nar serietreffet OVERLAPPER settreffet: i
        "Mega Evolutions Elite Trainer Box" ligger settaliaset "evolutions"
        inni serienavnet "mega evolutions". Da er settreffet et tilfeldig
        utsnitt av serienavnet, ikke et eget sett, og serien vinner.
        """
        sett, s0, s1 = self._finn(t, self._set_aliases)
        serie, r0, r1 = self._finn(t, self._serie_aliases)
        if serie and (not sett or (r0 < s1 and s0 < r1 and (r1 - r0) > (s1 - s0))):
            return serie
        return sett

    def classify(self, title):
        """-> 'single' | 'merch' | 'multipakke' | 'vintage' | 'sealed'"""
        if SINGLE_RE.search(title or ""):
            return "single"
        if MERCH_RE.search(title or ""):
            return "merch"
        if MULTIPAKKE_RE.search(title or ""):
            return "multipakke"
        if VINTAGE_RE.search(title or ""):
            return "vintage"
        return "sealed"

    def match(self, title):
        """-> dict med set_id/type_id/region/product_id, eller None."""
        if self.classify(title) != "sealed":
            return None
        t = normalize(title)
        set_id = self._velg_sett(t)
        # Typen leses uten innholdsparenteser -- de ma fjernes FOR normalize,
        # som selv stryker parentesene.
        type_id = self._velg_type(normalize(strip_innmat(title)))
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
