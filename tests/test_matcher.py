"""Tester for katalogmatchingen.

Hver test her stammer fra en ekte oppforing som ble matchet feil, og som
gjorde et tall pa siden misvisende. Titlene er derfor beholdt ordrett fra
butikkene -- de er poenget, ikke pynt.

Kjor: python3 -m pytest tests/test_matcher.py -q
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROT, "katalog"))

from matcher import Katalog  # noqa: E402

KAT = Katalog(os.path.join(ROT, "katalog", "katalog.json"))


def pid(tittel):
    m = KAT.match(tittel)
    return m["product_id"] if m else None


# ------------------------------------------------------- serie kontra sett

@pytest.mark.parametrize("tittel,forventet", [
    # Serienavnet er lengre enn settnavnet, men settet er det brukeren folger.
    ("Mega Evolution Pitch Black Booster Pack", "pitch-black:booster-pack:en"),
    ("Pokemon TCG Mega Evolution Chaos Rising Booster Pack",
     "chaos-rising:booster-pack:en"),
    ("Pokemon ME03: Mega Evolution: Perfect Order - Booster Pakke",
     "perfect-order:booster-pack:en"),
    # Uten et settnavn er serien det beste vi har, og da skal den brukes.
    ("Pokemon Mega Evolution Booster Pack", "mega-evolution:booster-pack:en"),
    ("Pokemon - Darkness Ablaze - Booster Box", "darkness-ablaze:booster-box:en"),
])
def test_sett_vinner_over_serie(tittel, forventet):
    assert pid(tittel) == forventet


def test_serie_vinner_nar_settet_ligger_inni_serienavnet():
    """"Mega Evolutions" inneholder "evolutions". Settreffet er da et
    tilfeldig utsnitt av serienavnet, ikke et eget sett."""
    assert pid("Pokemon - ME01 - Mega Evolutions - Elite Trainer Box - Gardevoir") \
        == "mega-evolution:etb:en"
    # Det ekte XY Evolutions-settet skal fortsatt treffe.
    assert pid("Pokemon - Evolutions - Elite Trainer Box (ETB)") == "evolutions:etb:en"


# ------------------------------------------------------------ multipakker

@pytest.mark.parametrize("tittel", [
    "Pokemon Ascended Heroes Booster Bundle Case (25 stk)",
    "Pokemon Ascended Heroes Booster Bundle Case (6 sealed displays)",
    "Pokemon - Prismatic Evolutions - 100 Booster Packs to Destiny",
    "Pokemon - Fusion Strike - 100 Booster Packs - SPEED RUN",
    "Pokemon - Team Rocket 1. Edition - Booster Packs ART SET",
    "15. Pack Run Pokemon Mega Evolution Sleeved boosterpakker",
    "Pokemon Paldean Fates Mini Tin Sealed Display",
    "Shrouded Fable Booster Bundle - Sealed Display",
    "Ascended Heroes Mini Tin (Display)",
    "Shrouded Fable Mini Tin Display 10 stk",
])
def test_multipakke_gjenkjennes(tittel):
    assert KAT.classify(tittel) == "multipakke"
    assert pid(tittel) is None


@pytest.mark.parametrize("tittel,forventet", [
    # "Booster Display" og "Display Box" betyr booster box, ikke multipakke.
    ("Stellar Crown Booster Display Box", "stellar-crown:booster-box:en"),
    ("Mega Evolution Booster Display", "mega-evolution:booster-box:en"),
    # "(Case tilgjengelig)" er en opplysning, ikke varen som selges.
    ("Pokemon Paldean Fates Mini Tin Sealed Display (Case Tilgjengelig)", None),
    ("Pokemon Charizard Ex Super Premium Collection Boks (Case Tilgjengelig)",
     "mega-evolution:premium-collection:en"),
])
def test_display_er_ikke_alltid_multipakke(tittel, forventet):
    if forventet is None:
        assert KAT.classify(tittel) == "multipakke"
    else:
        assert KAT.classify(tittel) == "sealed"


# ---------------------------------------------------------------- vintage

@pytest.mark.parametrize("tittel", [
    "Pokemon - Team Rocket 1. Edition (2000) - Booster Pack (Giovanni art)",
    "Pokemon - Team Rocket Unlimited - Tamper Sealed Booster Pack",
    "Pokemon - Ex Team Rocket Returns (2004) - Booster Pack (Scyther art)",
    "Pokemon - Deoxys Ex Tin (Black & White 2013)",
    "Pokemon - Team Rocket 1. Edition (2000) - Booster Pack - APNET LIVE",
])
def test_vintage_gjenkjennes(tittel):
    assert KAT.classify(tittel) == "vintage"


@pytest.mark.parametrize("tittel", [
    # Nytt arstall i parentes er utgivelsesar, ikke alder.
    "Pokemon Trick or Trade Booster Pakke (2024)",
    "Pokemon Poke Ball Tin (2025)",
    # Moderne pakker selges ogsa med tilfeldig omslag.
    "Pokemon - Mega Evolution - Chaos Rising Booster Pakke (Tilfeldig Pack Art)",
    "Pokemon - Dark Crystal Blaze (Charizard art) - Chinese Booster Box",
])
def test_moderne_varer_er_ikke_vintage(tittel):
    assert KAT.classify(tittel) == "sealed"


# ------------------------------------------------------- type kontra type

def test_storste_enhet_vinner_nar_begge_star_i_tittelen():
    """En boks inneholder pakker. Nevner butikken begge, er varen boksen."""
    assert pid("Pokemon - Crimson Haze - Booster Pack (Japansk) - Booster Box") \
        == "crimson-haze:booster-box:jp"


def test_display_foran_pakke_er_fortsatt_en_pakke():
    """"Japansk Display Booster Pack" er en pakke FRA displayet."""
    assert pid("Mega Brave Japansk Display Booster Pack") \
        == "mega-brave:booster-pack:jp"
    assert pid("Pokemon Mega Brave Japansk Display Booster Box") \
        == "mega-brave:booster-box:jp"


def test_innholdsparentes_beskriver_ikke_typen():
    assert pid("Pokemon - Prismatic Evolutions - Mini Tin (2 Booster Packs)") \
        == "prismatic-evolutions:mini-tin:en"
    assert pid("Pokemon - Ascended Heroes - Booster Bundle (6 Booster Packs)") \
        == "ascended-heroes:bundle:en"


# ------------------------------------------------------ kinesiske serier

@pytest.mark.parametrize("tittel,forventet", [
    ("Pokemon Gem Packs Volume 5 Kinesisk Booster Box", "gem-pack-5:booster-box:cn"),
    ("Pokemon Gem Pack Vol. 2 Kinesisk Booster Pakke", "gem-pack-2:booster-pack:cn"),
    ("Pokemon - Horizons Gem Pack Vol 1 - Chinese Booster Box",
     "gem-pack-1:booster-box:cn"),
    ("Pokemon Collect 151 Journey Kinesisk Booster Box",
     "collect-151-journey:booster-box:cn"),
    ("Pokemon Collect 151 Surprise Volume 3 Kinesisk Jumbo Booster Box",
     "collect-151-surprise:jumbo-booster-box:cn"),
    ("Pokemon Collect 151 Gathering Volume 4 Kinesisk Boosterpakke",
     "collect-151-gathering:booster-pack:cn"),
])
def test_kinesiske_delserier_er_egne_produkter(tittel, forventet):
    assert pid(tittel) == forventet


def test_gem_pack_volumene_blir_ikke_ett_produkt():
    ider = {pid("Pokemon Gem Packs Volume %d Kinesisk Booster Box" % n)
            for n in range(1, 7)}
    assert len(ider) == 6, ider


# ------------------------------------------------------------------ merch

@pytest.mark.parametrize("tittel", [
    "Pokemon Kinesisk Collect 151 Starter Display Stand - Bulbasaur",
    "Pokemon Kinesisk Gem Pack Vol. 3 Binder - Gengar",
    "Pokemon - Crystal Gathering Badge Box",
    "Pokemon Center - Glory of Team Rocket Deck Case",
])
def test_tilbehor_er_merch(tittel):
    assert KAT.classify(tittel) == "merch"
