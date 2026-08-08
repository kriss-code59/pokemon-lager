"""«Foelg alt» med demping.

Testene her er paa de rene funksjonene -- samletekst() og kort_navn() --
fordi det er de som lager det brukeren faktisk leser. Kvotelogikken selv
er SQL og testes mot databasen i test_varsler_db.py der den finnes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overvak.varsler import kort_navn, samletekst


def test_kort_navn_tar_produktlinjen():
    # Kroppen er "produkt\npris - vurdering". I en samleliste er det bare
    # produktnavnet som gir mening; pris og butikk varierer per rad.
    v = {"body": "Prismatic Evolutions · Booster Bundle\n1 399 kr — billigst"}
    assert kort_navn(v) == "Prismatic Evolutions · Booster Bundle"


def test_kort_navn_taaler_tom_kropp():
    assert kort_navn({}) == ""
    assert kort_navn({"body": ""}) == ""


def test_kort_navn_kortes_av():
    v = {"body": "A" * 200 + "\nnoe"}
    assert len(kort_navn(v)) == 60


def test_samletekst_har_antallet_i_tittelen():
    # Tallet er det som avgjor om du apner Pokepuls na eller etter middag.
    d = samletekst(14, ["Vare A", "Vare B", "Vare C", "Vare D"])
    assert d["title"] == "🛒 14 flere varer kom inn"


def test_samletekst_viser_tre_navn_og_teller_resten():
    d = samletekst(14, ["Vare A", "Vare B", "Vare C", "Vare D", "Vare E"])
    assert "Vare A" in d["body"] and "Vare C" in d["body"]
    assert "Vare D" not in d["body"]
    assert "og 11 til" in d["body"]


def test_samletekst_uten_hale_naar_alt_vises():
    d = samletekst(2, ["Vare A", "Vare B"])
    assert "og" not in d["body"].split("·")[-1]


def test_samletekst_taaler_at_navnene_mangler():
    d = samletekst(9, [])
    assert d["body"] == "Se alle på pokepuls.no"
    assert "9" in d["title"]


def test_samlevarsel_haster_ikke():
    # Et sammendrag skal ikke vibrere telefonen. Hadde det hastet, ville
    # det vaert sendt enkeltvis i stedet for dempet.
    assert samletekst(20, ["x"])["hastig"] is False


def test_samlevarsel_erstatter_seg_selv():
    # Fast tag: neste times sammendrag skal bytte ut det forrige, ikke
    # stable seg opp i varslingssenteret.
    assert samletekst(3, ["a"])["tag"] == samletekst(9, ["b"])["tag"]


def test_samlevarsel_peker_til_pokepuls_ikke_butikken():
    # Enkeltvarsler gaar rett til butikken fordi sekunder teller. Et
    # sammendrag har ingen enkelt butikk aa peke paa.
    assert samletekst(5, ["a"])["url"] == "https://pokepuls.no/"
