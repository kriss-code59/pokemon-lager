"""Enhetstester for ingest-laget.

Kjor: python3 -m pytest tests/ -q

Disse trenger ingen database. De dekker det som faktisk har gatt galt for:
prisparsing (F5), tri-state lagerstatus (F4) og klassifisering av loskort.
Databaseoppforselen testes av tests/selvtest.py, som kjorer pa serveren.
"""
import json
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROT, "ingest"))
sys.path.insert(0, os.path.join(ROT, "katalog"))

from ingest import (KRYMP_GRENSE, grupper_per_butikk, normaliser_lager,  # noqa: E402
                    pris_til_ore, slug)
from matcher import Katalog  # noqa: E402


@pytest.mark.parametrize("inn,ut", [
    ("1799.00 kr", 179900),
    ("1799,00 kr", 179900),
    ("1 799,00 kr", 179900),
    ("1.799,00 kr", 179900),
    ("kr 1799", 179900),
    ("1799", 179900),
    ("249,90 kr", 24990),
    ("249.9 kr", 2499_0),          # ett desimal: 2499,0 -> hele kroner 2499
    (1799.5, 179950),
    (1799, 179900),
    (None, None),
    ("", None),
    ("Ta kontakt", None),
])
def test_pris_til_ore(inn, ut):
    assert pris_til_ore(inn) == ut


def test_pris_er_alltid_heltall():
    """F5: '1799.0 kr' og '1799.00 kr' er samme pris og ma ikke bli en
    prisendring."""
    assert pris_til_ore("1799.0 kr") == pris_til_ore("1799.00 kr") == 179900


@pytest.mark.parametrize("inn,ut", [
    (True, True), (False, False), (None, None),
    ("ja", None), (1, None), ("", None),
])
def test_normaliser_lager(inn, ut):
    """F4: alt som ikke er et ekte boolsk svar er 'vet ikke', ikke 'utsolgt'."""
    assert normaliser_lager(inn) is ut


@pytest.mark.parametrize("inn,ut", [
    ("Neo Tokyo", "neo-tokyo"),
    ("Packs of Norway", "packs-of-norway"),
    ("Pokébua", "pokebua"),
    ("Kanoncon!", "kanoncon"),
    ("", "ukjent"),
])
def test_slug(inn, ut):
    assert slug(inn) == ut


# ------------------------------------------------------------ gruppering

KAT = Katalog(os.path.join(ROT, "katalog", "katalog.json"))


def rad(**kw):
    grunn = {"store": "Cardcenter", "name": "Pokemon Pitch Black Booster Box",
             "price": "1799.00 kr", "in_stock": True,
             "url": "https://x.no/1"}
    grunn.update(kw)
    return grunn


def test_grupper_kaster_loskort_og_merch():
    rader = [
        rad(name="Pokemon Pitch Black Booster Box", url="https://x.no/1"),
        rad(name="#095 Onix 095/165 Uncommon", url="https://x.no/2"),
        rad(name="Pikachu Plush 30cm", url="https://x.no/3"),
        rad(store="LABOGE", name="Charizard ex", url="https://x.no/4"),
    ]
    per_butikk, forkastet = grupper_per_butikk(rader, KAT)
    assert len(per_butikk["Cardcenter"]) == 1
    assert forkastet["single"] == 1
    assert forkastet["merch"] == 1
    assert forkastet["singles-butikk"] == 1


def test_grupper_dedupliserer_url():
    rader = [rad(url="https://x.no/1"), rad(url="https://x.no/1")]
    per_butikk, forkastet = grupper_per_butikk(rader, KAT)
    assert len(per_butikk["Cardcenter"]) == 1
    assert forkastet["duplikat"] == 1


def test_grupper_setter_kanonisk_produkt():
    per_butikk, _ = grupper_per_butikk([rad()], KAT)
    assert per_butikk["Cardcenter"]["https://x.no/1"]["product_id"] == \
        "pitch-black:booster-box:en"


def test_grupper_takler_manglende_felt():
    rader = [{"store": "X"}, {"url": "u"}, {}, rad()]
    per_butikk, _ = grupper_per_butikk(rader, KAT)
    assert list(per_butikk) == ["Cardcenter"]


def test_umatchet_sealed_beholdes_med_null_produkt():
    """Ukjente forseglede varer skal IKKE kastes -- de skal bare mangle
    kanonisk kobling, sa de fortsatt vises under 'Andre varer'."""
    per_butikk, _ = grupper_per_butikk(
        [rad(name="Pokemon Center Hiroshima Special Box")], KAT)
    assert per_butikk["Cardcenter"]["https://x.no/1"]["product_id"] is None


# ------------------------------------------------------ mot ekte datasett

DATA = os.path.join(ROT, "docs", "data.json")


@pytest.mark.skipif(not os.path.exists(DATA), reason="data.json mangler")
def test_ekte_datasett_krymper_som_forventet():
    """Sikkerhetsnett mot at en katalogendring plutselig slipper gjennom
    loskort igjen. 19 578 rader inn, under 5 000 forseglede varer ut."""
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    per_butikk, forkastet = grupper_per_butikk(data["products"], KAT)
    beholdt = sum(len(v) for v in per_butikk.values())
    assert beholdt < 5000, "for mange rader slapp gjennom: %d" % beholdt
    assert forkastet["singles-butikk"] > 10000
    matchet = sum(1 for b in per_butikk.values() for o in b.values()
                  if o["product_id"])
    assert matchet > 1800, "katalogdekningen falt: bare %d matchet" % matchet


@pytest.mark.skipif(not os.path.exists(DATA), reason="data.json mangler")
def test_alle_priser_lar_seg_parse_eller_er_tomme():
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    per_butikk, _ = grupper_per_butikk(data["products"], KAT)
    uten = [o for b in per_butikk.values() for o in b.values()
            if o["price_ore"] is None]
    andel = len(uten) / max(1, sum(len(v) for v in per_butikk.values()))
    assert andel < 0.05, "%.1f %% av prisene lot seg ikke parse" % (andel * 100)


def test_krympgrensen_er_fornuftig():
    assert 0 < KRYMP_GRENSE < 0.5


@pytest.mark.skipif(not os.path.exists(DATA), reason="data.json mangler")
def test_produkt_id_kan_ha_annen_region_enn_settet():
    """En japansk utgave av et vestlig sett gir `sett:type:jp`, som ikke
    finnes i krysstabellen sets x types. Uten sikre_produkter() faller
    ingest pa en fremmednokkelfeil -- det skjedde i produksjon."""
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    per_butikk, _ = grupper_per_butikk(data["products"], KAT)
    region_for_sett = {s["id"]: s["region"] for s in KAT.sets}
    ider = {o["product_id"] for b in per_butikk.values() for o in b.values()
            if o["product_id"]}
    avvik = [i for i in ider if i.split(":")[2] != region_for_sett[i.split(":")[0]]]
    assert avvik, "forventet minst ett produkt med avvikende region"
    for pid in ider:
        assert len(pid.split(":")) == 3, pid
