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


# ------------------------------------------------- bestillingsvarer tier

"""En bestillingsvare skal aldri bli en hendelse.

Maalt i drift 10. august 2026: 210 av 350 hendelser i hele systemet paa seks
timer var bestillingsvarer. Mystic Trades alene sto for 228 «restock» -- ikke
fordi noe kom paa lager, men fordi `in_stock` paa en bestillingsvare blafrer
mellom sant og usant fra kjoring til kjoring.

katalog/tilgjengelighet.py sier det selv: for en som venter paa restock er en
bestillingsvare i praksis utsolgt. Vi hadde dempet dem i TEKSTEN -- de
vibrerer ikke -- men hendelsen ble laget likevel, og et varsel som ikke
vibrerer er fortsatt et varsel.

Forhaandssalg er noe helt annet og maa fortsatt slippe gjennom.
"""


def test_bestillingsvare_er_stille():
    from ingest import _stille
    assert _stille("bestillingsvare") is True


def test_forhandssalg_er_ikke_stille():
    # Det er der du sikrer deg til veiledende pris for alle andre. Demper vi
    # den, har vi fjernet det mest verdifulle signalet i hele produktet.
    from ingest import _stille
    assert _stille("forhandssalg") is False


def test_vanlig_vare_er_ikke_stille():
    from ingest import _stille
    assert _stille(None) is False


def test_regelen_gjelder_alle_stedene_en_hendelse_lages():
    """Leser kilden, fordi hendelsene lages inni en lang databaseloop.

    En regel som bare daekker tre av fire steder er verre enn ingen regel:
    stoyen gaar ned nok til at man tror det er fikset, og fortsetter aa komme
    fra det fjerde. Derfor sjekkes HVERT sted en hendelse legges paa listen,
    ikke bare at ordet «_stille» finnes i filen.
    """
    from pathlib import Path
    kilde = (Path(__file__).resolve().parents[1] / "ingest" / "ingest.py").read_text(
        encoding="utf-8")
    linjer = kilde.splitlines()

    steder = [(i, l) for i, l in enumerate(linjer)
              if any(f'"{k}", ' in l for k in ("ny", "restock", "utsolgt"))
              and "price_ore" in l]
    assert len(steder) >= 4, f"fant bare {len(steder)} hendelsessteder"

    # `not ny["bestillingstype"]` teller ogsaa som en gyldig sjekk. Det er
    # regelen for «forhaandssalg eller bestillingsvare ble en vanlig vare»,
    # og den er en EKTE restock: varen gikk fra noe butikken maatte skaffe,
    # til noe de har staaende. Den skal du ha beskjed om.
    for i, linje in steder:
        rundt = "\n".join(linjer[max(0, i - 8):i + 1])
        assert ("_stille(" in rundt or "not stille" in rundt
                or 'not ny["bestillingstype"]' in rundt), \
            f"linje {i + 1} lager en hendelse uten bestillingsvare-sjekk: {linje.strip()}"


def test_sett_abonnement_teller_som_bredt_ikke_spesifikt():
    """Timeskvoten skal gjelde for sett.

    Ett sett er ni produkttyper ganger 41 butikker. Aa foelge et sett ligner
    mye mer paa «foelg alt» enn paa «foelg denne varen». Uten dempingen kan
    ett sett i bevegelse gi femti varsler i slengen -- og da skrur folk av
    varsler, som er den ene feilen dette systemet ikke har raad til.
    """
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "overvak" / "varsler.py").read_text(
        encoding="utf-8")
    assert "bool_or(sub.product_id IS NOT NULL) AS spesifikk" in sql
    assert "bool_or(sub.product_id IS NOT NULL OR sub.set_id IS NOT NULL)" not in sql


def test_bare_forhandssalg_gir_restock_naar_merkingen_forsvinner():
    """Malt i drift 14. august: 105 falske restock paa tre timer.

    Regelen «bestillingstype forsvant -> varen ble ekte -> restock» sto
    opprinnelig for BEGGE typer. Mekanismen som gjorde den farlig er
    subtil: merkingen leses fra TITTELEN. Leser scraperen den én gang uten
    «[BESTILLINGSVARE]» -- fordi butikkens side rendret annerledes det
    sekundet -- ser ingest at merkingen forsvant og tolker det som at varen
    ble ekte. Neste kjoring er merket tilbake, og runden gjentar seg.

    For FORHAANDSSALG er overgangen ekte og skjer én gang: paa
    slippdagen. Den beholder vi.
    """
    from pathlib import Path
    kilde = (Path(__file__).resolve().parents[1] / "ingest" / "ingest.py").read_text(
        encoding="utf-8")
    i = kilde.index('and not ny["bestillingstype"]')
    rundt = kilde[max(0, i - 120):i + 60]
    assert "== FORHANDSSALG" in rundt, \
        "regelen maa gjelde BARE forhaandssalg, ikke enhver bestillingstype"


def test_statistikken_teller_ikke_bestillingsvarer_som_paafyll():
    # En bestillingsvare er ikke paafyll. Uten filteret ble «butikken som
    # fyller paa oftest» en maaling av hvilken butikk som blafret mest.
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "api" / "statistikk.py").read_text(
        encoding="utf-8")
    i = sql.index("RESTOCK_BUTIKK_SQL")
    assert "bestillingsvare" in sql[i:i + 700]
