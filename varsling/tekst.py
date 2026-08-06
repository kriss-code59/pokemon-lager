"""Varseltekst.

Rene funksjoner uten database. Alt som skal til for a bygge et varsel tas
inn som argumenter, slik at teksten kan testes uten Postgres -- og fordi
det er her feilene faktisk oppstar. En pris som vises som "1049 kr" i
stedet for "1 049 kr" er ikke en kosmetisk feil nar varselet skal leses pa
en lasseskjerm pa to sekunder.

Formatet:

    Mythic: Paa lager
    Prismatic Evolutions / Booster Bundle
    1 399 kr - billigst paa lager

Tittelen svarer paa HVOR og HVA SKJEDDE. Forste linje svarer paa HVA.
Andre linje svarer paa det eneste spoersmaalet som avgjoer om du klikker:
ER DETTE EN GOD PRIS? Uten den siste linjen maa du aapne siden for aa vite
om varselet var verdt aa faa, og da har varselet ikke spart deg for noe.
"""
from __future__ import annotations

REGION_MERKE = {"en": "", "jp": "JP", "cn": "CN", "ko": "KR"}

# Tittelens hoyre side. "Paa lager" dekker bade forste gang vi ser varen og
# at den kom tilbake -- for en kjoper er det samme beskjed.
STATUS = {
    "restock": "På lager",
    "ny": "På lager",
    "prisendring": "Ny pris",
    "utsolgt": "Utsolgt",
}

EMOJI = {"restock": "🛒", "ny": "✨", "prisendring": "💸", "utsolgt": "⚫"}

# Under denne grensen regner vi prisen som "ingen pris". Butikkene bruker
# 1 kr og 0 kr som plassholder for varer som ikke kan kjopes enna.
MIN_EKTE_PRIS_ORE = 500


def kroner(ore: int | None) -> str:
    """1399_00 -> '1 399 kr'. Hardt mellomrom, sa tallet ikke brekkes."""
    if ore is None:
        return "ukjent pris"
    hele, rest = divmod(int(ore), 100)
    tall = f"{hele:,}".replace(",", " ")
    if rest:
        tall += f",{rest:02d}"
    return tall + " kr"


def produktnavn(set_label: str | None, type_label: str | None,
                region: str | None = None, tittel: str | None = None) -> str:
    """'Prismatic Evolutions / Booster Bundle' -- samme rekkefolge som i
    hodet ditt: hvilket sett, sa hvilken eske."""
    if set_label and type_label:
        navn = f"{set_label} / {type_label}"
        merke = REGION_MERKE.get(region or "en", "")
        return f"{navn} ({merke})" if merke else navn
    # Umatchet vare: butikkens egen tittel er alt vi har. Kort den ned, ellers
    # spiser den hele varselet.
    t = (tittel or "Ukjent produkt").strip()
    return t if len(t) <= 70 else t[:67].rstrip() + "…"


def vurdering(pris_ore: int | None, billigst_na_ore: int | None,
              billigst_butikk: str | None, billigst_7d_ore: int | None,
              antall_pa_lager: int = 0) -> str:
    """Den siste linjen: er dette en god pris?

    Prioriteringen er ikke tilfeldig. Den viktigste opplysningen er om noen
    andre selger den samme varen billigere AKKURAT NAA -- det er den eneste
    som kan faa deg til aa la vaere aa kjope. Historikk kommer etter, fordi
    en billigere pris for fem dager siden ikke kan handles.
    """
    if pris_ore is None or pris_ore < MIN_EKTE_PRIS_ORE:
        return "pris ikke oppgitt"

    # Noen andre har den inne, og billigere.
    if (billigst_na_ore is not None
            and billigst_na_ore >= MIN_EKTE_PRIS_ORE
            and billigst_na_ore < pris_ore):
        hos = f" hos {billigst_butikk}" if billigst_butikk else ""
        return f"⚠️ finnes billigere: {kroner(billigst_na_ore)}{hos}"

    # Vi er billigst av dem som har den inne -- men bare verdt aa si hvis
    # det finnes noen aa vaere billigst enn.
    if antall_pa_lager > 1:
        return "✅ billigst på lager"

    # Eneste butikk med varen inne. Da er historikken det eneste maalestokken.
    if billigst_7d_ore is not None and billigst_7d_ore >= MIN_EKTE_PRIS_ORE:
        if pris_ore <= billigst_7d_ore:
            return "🔥 laveste pris siste 7 døgn"
        return f"billigst kjøpbar siste 7 døgn: {kroner(billigst_7d_ore)}"

    return "✅ eneste butikk med varen inne"


def bygg(hendelse: dict, kontekst: dict) -> dict:
    """-> {'title', 'body', 'url', 'tag', 'kind', 'krever_handling'}

    `hendelse` er en rad fra events med butikk- og produktnavn slaatt opp.
    `kontekst` er prisbildet: billigst_na_ore, billigst_butikk,
    billigst_7d_ore, antall_pa_lager.
    """
    kind = hendelse.get("kind", "ny")
    butikk = hendelse.get("store_name") or hendelse.get("store_id") or "Ukjent butikk"
    pris = hendelse.get("price_ore")

    tittel = f"{EMOJI.get(kind, '•')} {butikk}: {STATUS.get(kind, kind)}"
    navn = produktnavn(hendelse.get("set_label"), hendelse.get("type_label"),
                       hendelse.get("region"), hendelse.get("title"))

    if kind == "utsolgt":
        linje = "utsolgt hos denne butikken"
        if kontekst.get("antall_pa_lager"):
            linje += f" · fortsatt inne hos {kontekst['antall_pa_lager']} andre"
    elif kind == "prisendring":
        for_ = hendelse.get("prev_price_ore")
        pil = "↓" if (for_ and pris and pris < for_) else "↑"
        linje = f"{kroner(for_)} {pil} {kroner(pris)} · " + vurdering(
            pris, kontekst.get("billigst_na_ore"), kontekst.get("billigst_butikk"),
            kontekst.get("billigst_7d_ore"), kontekst.get("antall_pa_lager", 0))
    else:
        linje = f"{kroner(pris)} · " + vurdering(
            pris, kontekst.get("billigst_na_ore"), kontekst.get("billigst_butikk"),
            kontekst.get("billigst_7d_ore"), kontekst.get("antall_pa_lager", 0))

    return {
        "title": tittel,
        "body": f"{navn}\n{linje}",
        # Lenken gaar til BUTIKKEN, ikke til Pokepuls. Ved en restock er det
        # sekunder som teller, og et ekstra mellomledd er sekunder.
        "url": hendelse.get("url") or "https://pokepuls.no/",
        "produkt_url": ("https://pokepuls.no/p/" + hendelse["product_id"]
                        if hendelse.get("product_id") else "https://pokepuls.no/"),
        "bilde": hendelse.get("image_url"),
        "kind": kind,
        # tag: nyere varsel om SAMME produkt hos SAMME butikk erstatter det
        # gamle i varslingssenteret i stedet for aa stable seg opp.
        "tag": f"{hendelse.get('product_id') or hendelse.get('listing_id')}"
               f":{hendelse.get('store_id')}",
        # Restock er det eneste som faktisk haster. Alt annet skal ikke
        # vibrere telefonen.
        "hastig": kind in ("restock", "ny"),
    }
