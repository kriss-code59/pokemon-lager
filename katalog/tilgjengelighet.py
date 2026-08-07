"""Skiller «kan kjopes og sendes naa» fra «kan bestilles».

Bakgrunnen er en produktside som sa dette:

    Paa lager nao
      BoosterKongen   (Forhaandsbestilling) Pokemon TCG: ...   2 699 kr
      Mystic Trades   [BESTILLING] - Pokemon S&S: ...          3 499 kr

Ingen av dem hadde varen. Butikkene setter `available: true` i Shopify paa
forhaandssalg og bestillingsvarer -- teknisk riktig, for du KAN legge dem i
handlekurven -- men for en kjoper som venter paa en restock er det feil svar
paa spoersmaalet de stilte.

Et varsel som sier «paa lager» om noe du ikke kan faa, er verre enn ingen
varsel: det er det som faar folk til aa skru dem av.

Vi skjuler dem ikke. Forhaandssalg er ofte det mest verdifulle signalet som
finnes -- det er der du sikrer deg til veiledende pris for alle andre. Vi
sier bare hva det ER.

To typer, med helt ulik betydning for en kjoper:

  forhandssalg   Varen er ikke sluppet enda. Du sikrer et eksemplar til
                 avtalt pris, og den kommer paa slippdatoen. Dette er en
                 mulighet, og den forsvinner fort.

  bestillingsvare  Butikken har den ikke, men bestiller den hjem hvis du
                 kjoper. Ingen slippdato, ingen garanti for naar. For en
                 som venter paa restock er dette i praksis «utsolgt».

Reglene under kommer fra ekte titler i databasen, ikke fra fantasi. Hver
enkelt er sett i drift.
"""
from __future__ import annotations

import re
import unicodedata

FORHANDSSALG = "forhandssalg"
BESTILLINGSVARE = "bestillingsvare"


def _flat(tekst: str) -> str:
    """Ned i sma bokstaver, uten diakritikk. «FORHÅNDSBESTILLING» og
    «Forhandsbestilling» skal treffe samme regel."""
    uten = unicodedata.normalize("NFKD", tekst or "")
    return "".join(c for c in uten if not unicodedata.combining(c)).lower()


# Rekkefolgen betyr noe: bestillingsvare sjekkes forst, fordi
# «[BESTILLINGSVARE]» ogsaa inneholder ordet «bestilling».
_BESTILLINGSVARE = re.compile(
    r"bestillingsvare"
    r"|\bbestillings\s*vare"
    r"|\bskaffevare"
    r"|\brestordre"
    r"|\bbackorder",
    re.IGNORECASE)

_FORHANDSSALG = re.compile(
    r"forhandsbestilling"
    r"|forhandssalg"
    r"|forhandsreservasjon"
    r"|\bpre[\s\-_]?order"
    # «[BESTILLING]» alene brukes av Mystic Trades om forhaandssalg.
    # Krever klammer/parentes rundt, ellers treffer den «ved bestilling
    # av to esker» og lignende i vanlige produktbeskrivelser.
    r"|[\[\(]\s*bestilling\s*[\]\)]",
    re.IGNORECASE)

# «Prerelease» er et EKTE produkt (Prerelease Kit), ikke et forhaandssalg.
# Uten dette unntaket ble «Pokemon - Burning Shadows - Prerelease kit»
# merket som forhaandssalg for alltid, siden den aldri slippes paa nytt.
_IKKE = re.compile(r"pre[\s\-]?release", re.IGNORECASE)


def bestillingstype(tittel: str | None) -> str | None:
    """-> 'forhandssalg', 'bestillingsvare' eller None.

    None betyr «vanlig vare» -- altsaa at butikkens eget lagersignal kan
    tas paa ordet.
    """
    if not tittel:
        return None
    t = _flat(tittel)

    if _BESTILLINGSVARE.search(t):
        return BESTILLINGSVARE

    if _IKKE.search(t):
        # Fjern treffet og se om det staar noe ANNET der ogsaa: en
        # «[FORHÅNDSBESTILLING] Prerelease Kit» er tross alt et forhaandssalg.
        uten = _IKKE.sub(" ", t)
        return FORHANDSSALG if _FORHANDSSALG.search(uten) else None

    if _FORHANDSSALG.search(t):
        return FORHANDSSALG
    return None


# Hva som vises til brukeren. Kort, fordi det skal faa plass som merkelapp
# ved siden av en pris paa en telefon.
ETIKETT = {
    FORHANDSSALG: "Forhåndssalg",
    BESTILLINGSVARE: "Bestillingsvare",
}

# Hva varselet skal si i stedet for «På lager».
VARSEL_STATUS = {
    FORHANDSSALG: "Forhåndssalg åpnet",
    BESTILLINGSVARE: "Kan bestilles",
}


def kan_hentes_naa(bestillingstype_: str | None, in_stock) -> bool:
    """Er dette en vare du faktisk kan faa i hus naa?

    Brukes til «billigst paa lager»-sammenligningen. Et forhaandssalg til
    2 699 kr skal ikke gjore at en ekte vare paa 2 999 kr faar merkelappen
    «finnes billigere» -- det er ikke det samme produktet i tid.
    """
    return in_stock is True and bestillingstype_ is None
