"""Forhaandssalg og bestillingsvarer skal ikke telle som «paa lager».

Hver eneste tittel i denne filen er hentet ut av den ekte databasen. Det er
med vilje: en regel som bare er testet mot titler jeg fant paa selv, er en
regel jeg har testet mot min egen fantasi.

Bakgrunnen er produktsiden for Ascended Heroes Elite Trainer Box, som viste
tre butikker under «Paa lager» der ingen av dem hadde varen.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from katalog.tilgjengelighet import (  # noqa: E402
    BESTILLINGSVARE, ETIKETT, FORHANDSSALG, bestillingstype, kan_hentes_naa)


# ---------------------------------------------------- ekte forhaandssalg

@pytest.mark.parametrize("tittel", [
    "(Forhåndsbestilling) Pokemon TCG: Ascended Heroes Elite Trainer Boks",
    "[FORHÅNDSBESTILLING] – Pokémon Scarlet & Violet: Paldea Evolved",
    "[BESTILLING] - Pokémon S&S: Ascended Heroes Elite Trainer Box (ETB)",
    "[PRE-ORDER] – Pokémon S&V: CSV10C Chasing Glory Together",
    "Pokemon Preorder Booster Box",
    "(FORHANDSSALG) Prismatic Evolutions",
])
def test_forhandssalg(tittel):
    assert bestillingstype(tittel) == FORHANDSSALG


# --------------------------------------------------- ekte bestillingsvarer

@pytest.mark.parametrize("tittel", [
    "[BESTILLINGSVARE] – Pokémon Sun & Moon: Guardians Rising Elite Trainer Box",
    "​[BESTILLINGSVARE] – Pokémon S&S: Base Set Elite Trainer Box",
    "Pokémon Restordre Booster Box",
    "Pokemon Booster Box (backorder)",
])
def test_bestillingsvare(tittel):
    assert bestillingstype(tittel) == BESTILLINGSVARE


def test_bestillingsvare_vinner_over_bestilling():
    # «BESTILLINGSVARE» inneholder ordet «BESTILLING». Rekkefolgen paa
    # reglene er derfor ikke likegyldig -- den mest spesifikke maa forst.
    assert bestillingstype("[BESTILLINGSVARE] – Pokémon") == BESTILLINGSVARE


# ------------------------------------------------------------ vanlige varer

@pytest.mark.parametrize("tittel", [
    "Pokemon Ascended Heroes Elite Trainer Box",
    "Maks 1 per pers. Pokemon Ascended Heroes Elite Trainer Box",
    "Pokemon Prismatic Evolutions Booster Bundle",
    "[KOMMER SNART] – Pokémon Booster Pakke: 30th Celebration",
    "Rabatt ved bestilling av to esker",
    "",
    None,
])
def test_vanlig_vare(tittel):
    assert bestillingstype(tittel) is None


def test_prerelease_er_et_produkt_ikke_et_forhandssalg():
    # Regresjon: «Prerelease» inneholder «pre» + «release» og ble lest som
    # pre-order. Et Prerelease Kit er et ekte, ferdig utgitt produkt -- det
    # ville staatt som «kommer snart» i all evighet.
    assert bestillingstype("Pokemon - Burning Shadows - Prerelease kit") is None
    assert bestillingstype("Pokemon - XY Fates Collide - Prerelease") is None


def test_forhandssalg_av_et_prerelease_kit_er_fortsatt_forhandssalg():
    assert bestillingstype(
        "[FORHÅNDSBESTILLING] Pokemon Prerelease Kit") == FORHANDSSALG


def test_bestilling_i_lopende_tekst_teller_ikke():
    # «[BESTILLING]» i klammer er en merkelapp. Det samme ordet midt i en
    # setning er bare norsk.
    assert bestillingstype("Fri frakt ved bestilling over 500 kr") is None


def test_store_og_sma_bokstaver_og_diakritikk_er_likegyldig():
    for t in ["FORHÅNDSBESTILLING", "forhandsbestilling", "ForhåndsBestilling"]:
        assert bestillingstype("Pokemon " + t + " Box") == FORHANDSSALG


# ------------------------------------------------------------ kan_hentes_naa

def test_bare_ekte_lager_kan_hentes_naa():
    assert kan_hentes_naa(None, True) is True
    assert kan_hentes_naa(FORHANDSSALG, True) is False
    assert kan_hentes_naa(BESTILLINGSVARE, True) is False
    assert kan_hentes_naa(None, False) is False
    assert kan_hentes_naa(None, None) is False


def test_etikettene_finnes_for_begge_typer():
    # Uten etikett faller UI-et tilbake paa den interne slugen, og brukeren
    # far se ordet «forhandssalg» uten aa-lyd midt i en norsk setning.
    assert ETIKETT[FORHANDSSALG] and ETIKETT[BESTILLINGSVARE]


# ------------------------------------------------------- varselteksten

def test_varsel_om_forhandssalg_sier_ikke_paa_lager():
    from varsling.tekst import bygg
    v = bygg(dict(kind="restock", store_name="BoosterKongen", store_id="bk",
                  set_label="Ascended Heroes", type_label="Elite Trainer Box",
                  region="en", price_ore=269900, url="x",
                  product_id="ah:etb:en", bestillingstype=FORHANDSSALG),
             dict(billigst_na_ore=None, billigst_butikk=None,
                  billigst_7d_ore=None, antall_pa_lager=0))
    assert "På lager" not in v["title"]
    assert "forhåndsbestilling" in v["title"]
    assert "kommer ved slipp" in v["body"]
    # Ingen «billigst paa lager»-paastand: den sammenligner mot varer du
    # faktisk kan faa naa.
    assert "ingen har den billigere" not in v["body"]


def test_forhandssalg_naevner_hvem_som_har_den_ekte():
    from varsling.tekst import bygg
    v = bygg(dict(kind="restock", store_name="BoosterKongen", store_id="bk",
                  set_label="Ascended Heroes", type_label="Elite Trainer Box",
                  region="en", price_ore=269900, url="x",
                  product_id="ah:etb:en", bestillingstype=FORHANDSSALG),
             dict(billigst_na_ore=249900, billigst_butikk="Cardcenter",
                  billigst_7d_ore=249900, antall_pa_lager=2))
    assert "to har den inne" in v["body"].replace(" ", " ")


def test_bestillingsvare_haster_ikke():
    # En bestillingsvare kan bestilles i morgen ogsaa. Den skal ikke
    # vibrere telefonen din.
    from varsling.tekst import bygg
    grunn = dict(kind="restock", store_name="X", store_id="x", set_label="S",
                 type_label="T", region="en", price_ore=100000, url="u",
                 product_id="p")
    tom = dict(billigst_na_ore=None, billigst_butikk=None,
               billigst_7d_ore=None, antall_pa_lager=0)
    assert bygg(dict(grunn, bestillingstype=BESTILLINGSVARE), tom)["hastig"] is False
    # Et forhaandssalg haster derimot: det er der du sikrer deg til
    # veiledende pris for alle andre.
    assert bygg(dict(grunn, bestillingstype=FORHANDSSALG), tom)["hastig"] is True
    assert bygg(dict(grunn, bestillingstype=None), tom)["hastig"] is True


def test_prisendring_paa_forhandssalg_er_fortsatt_en_prisendring():
    from varsling.tekst import bygg
    v = bygg(dict(kind="prisendring", store_name="X", store_id="x", set_label="S",
                  type_label="T", region="en", price_ore=90000,
                  prev_price_ore=100000, url="u", product_id="p",
                  bestillingstype=FORHANDSSALG),
             dict(billigst_na_ore=90000, billigst_butikk="X",
                  billigst_7d_ore=90000, antall_pa_lager=1))
    assert "Ned" in v["title"]
    assert "→" in v["body"]
