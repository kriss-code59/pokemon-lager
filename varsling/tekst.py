"""Varseltekst.

Rene funksjoner uten database. Alt som skal til for a bygge et varsel tas
inn som argumenter, slik at teksten kan testes uten Postgres -- og fordi
det er her feilene faktisk oppstar. En pris som vises som "1049 kr" i
stedet for "1 049 kr" er ikke en kosmetisk feil nar varselet skal leses pa
en lasseskjerm pa to sekunder.

Formatet:

    Naa inne hos Mythic
    Prismatic Evolutions - Booster Bundle
    1 399 kr - ingen har den billigere

Tittelen sier hva som SKJEDDE, ikke hva noe ER. Det er forskjellen paa
"Mythic: Paa lager" og "Naa inne hos Mythic": den forste er en tilstand du
maa tolke, den andre er en beskjed. Paa en laaseskjerm rekker du bare den
ene linjen, og da skal den vaere en beskjed.

Andre linje svarer paa det eneste spoersmaalet som avgjoer om du klikker:
ER DETTE EN GOD PRIS? Uten den maa du aapne siden for aa vite om varselet
var verdt aa faa, og da har varselet ikke spart deg for noe.

Ordlyden er bevisst norsk og muntlig ("naa inne hos", "ingen har den
billigere") framfor etikettpreget ("paa lager", "billigst"). Det er den
samme informasjonen; det er ikke den samme stemmen.
"""
from __future__ import annotations

REGION_MERKE = {"en": "", "jp": "JP", "cn": "CN", "ko": "KR"}

EMOJI = {"restock": "🛒", "ny": "🛒", "prisendring": "💸", "utsolgt": "⚫"}

BESTILLING_EMOJI = {"forhandssalg": "📅", "bestillingsvare": "📦"}

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


def _antall_ord(n: int) -> str:
    """'fire andre' leses raskere enn '4 andre' i en setning."""
    return {2: "to", 3: "tre", 4: "fire", 5: "fem", 6: "seks",
            7: "sju", 8: "åtte", 9: "ni"}.get(n, str(n))


def produktnavn(set_label: str | None, type_label: str | None,
                region: str | None = None, tittel: str | None = None) -> str:
    """'Prismatic Evolutions - Booster Bundle' -- samme rekkefolge som i
    hodet ditt: hvilket sett, sa hvilken eske."""
    if set_label and type_label:
        navn = f"{set_label} · {type_label}"
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
        if billigst_butikk:
            return f"men {billigst_butikk} har den til {kroner(billigst_na_ore)}"
        return f"finnes til {kroner(billigst_na_ore)} et annet sted"

    # Vi er billigst av dem som har den inne -- men bare verdt aa si hvis
    # det finnes noen aa vaere billigst enn.
    if antall_pa_lager > 1:
        return "ingen har den billigere"

    # Eneste butikk med varen inne. Da er historikken den eneste maalestokken.
    if billigst_7d_ore is not None and billigst_7d_ore >= MIN_EKTE_PRIS_ORE:
        if pris_ore <= billigst_7d_ore:
            return "laveste på en uke"
        return f"billigere for noen dager siden: {kroner(billigst_7d_ore)}"

    return "eneste butikk med varen inne"


def bygg(hendelse: dict, kontekst: dict) -> dict:
    """-> {'title', 'body', 'url', 'tag', 'kind', 'hastig', ...}

    `hendelse` er en rad fra events med butikk- og produktnavn slaatt opp.
    `kontekst` er prisbildet: billigst_na_ore, billigst_butikk,
    billigst_7d_ore, antall_pa_lager.
    """
    kind = hendelse.get("kind", "ny")
    butikk = hendelse.get("store_name") or hendelse.get("store_id") or "Ukjent butikk"
    pris = hendelse.get("price_ore")
    bestilling = hendelse.get("bestillingstype")
    andre = kontekst.get("antall_pa_lager") or 0

    navn = produktnavn(hendelse.get("set_label"), hendelse.get("type_label"),
                       hendelse.get("region"), hendelse.get("title"))

    # ---------------------------------------------------------- forhaandssalg
    # Forhaandssalg og bestillingsvarer far sin egen tittel, men bare naar
    # varselet handler om at noe ble tilgjengelig. En prisendring paa et
    # forhaandssalg er fortsatt en prisendring.
    if bestilling and kind in ("restock", "ny"):
        if bestilling == "forhandssalg":
            tittel = "📅 Åpnet for forhåndsbestilling"
            linje = f"{kroner(pris)} hos {butikk} — kommer ved slipp"
        else:
            tittel = f"📦 Kan bestilles hos {butikk}"
            linje = f"{kroner(pris)} — butikken skaffer den"
        # Ingen «ingen har den billigere» her: den sammenligner mot varer du
        # faktisk kan faa naa, og det er ikke det dette er.
        if andre:
            linje += (f" · {_antall_ord(andre)} har den inne fra "
                      f"{kroner(kontekst.get('billigst_na_ore'))}")

    # ---------------------------------------------------------------- utsolgt
    elif kind == "utsolgt":
        tittel = f"⚫ Tomt hos {butikk}"
        linje = (f"{_antall_ord(andre).capitalize()} andre har den fortsatt inne"
                 if andre else "Ingen andre har den inne heller")

    # ------------------------------------------------------------ prisendring
    elif kind == "prisendring":
        for_ = hendelse.get("prev_price_ore")
        if for_ and pris:
            diff = abs(for_ - pris)
            retning = "Ned" if pris < for_ else "Opp"
            tittel = f"💸 {retning} {kroner(diff)} hos {butikk}"
        else:
            tittel = f"💸 Ny pris hos {butikk}"
        pil = "→"
        linje = f"{kroner(for_)} {pil} {kroner(pris)} — " + vurdering(
            pris, kontekst.get("billigst_na_ore"), kontekst.get("billigst_butikk"),
            kontekst.get("billigst_7d_ore"), andre)

    # ------------------------------------------------------- restock og nytt
    else:
        tittel = f"🛒 Nå inne hos {butikk}"
        linje = f"{kroner(pris)} — " + vurdering(
            pris, kontekst.get("billigst_na_ore"), kontekst.get("billigst_butikk"),
            kontekst.get("billigst_7d_ore"), andre)

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
        # vibrere telefonen. En bestillingsvare haster ikke -- den kan
        # bestilles i morgen ogsaa. Et forhaandssalg haster derimot: det er
        # der du sikrer deg til veiledende pris for alle andre.
        "hastig": kind in ("restock", "ny") and bestilling != "bestillingsvare",
        "bestillingstype": bestilling,
    }
