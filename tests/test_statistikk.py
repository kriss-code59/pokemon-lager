"""Prishistorikk og restock-statistikk.

Begge bygger paa `events`, en tabell som har ligget der siden dag én og
blitt brukt til noyaktig én ting: aa sende varsler. Ingen ny innsamling.

Testene handler om to ting: at premium faktisk sperrer, og at de to
forbeholdene staar i SVARET og ikke bare i grensesnittet. Det siste er
viktigere enn det ser ut -- et tall uten forbehold blir lest som en fasit.
"""
from pathlib import Path

ROT = Path(__file__).resolve().parents[1]
KILDE = (ROT / "api" / "statistikk.py").read_text(encoding="utf-8")
JS = (ROT / "web" / "statistikk.js").read_text(encoding="utf-8")


def test_begge_endepunktene_krever_premium():
    for rute in ['@router.get("/pris/{produkt_id}")', '@router.get("/restock")']:
        i = KILDE.index(rute)
        assert "_premium(pokepuls_sesjon)" in KILDE[i:i + 700], f"{rute} er ikke sperret"


def _kode_uten_kommentarer(tekst: str) -> str:
    """Bare kjorbar kode. Kommentaren over sperren NEVNER 403 for aa
    forklare hvorfor vi ikke bruker den, og en test som ikke skiller de to
    ville slaatt ut paa sin egen begrunnelse."""
    return "\n".join(l.split("#")[0] for l in tekst.splitlines()
                     if not l.strip().startswith("#"))


def test_402_ikke_403():
    # Dette er ikke forbudt -- det er ikke betalt for. Statuskoden er den
    # eneste maaten en klient kan skille de to paa uten aa lese teksten.
    i = KILDE.index("async def _premium")
    assert "402" in KILDE[i:i + 500]
    assert "403" not in _kode_uten_kommentarer(KILDE)


def test_laveste_pris_kaller_seg_ikke_laveste_noensinne():
    """Historikken starter da vi begynte aa maale, ikke da varen kom i salg.

    Kaller vi det «laveste noensinne», leser folk det som en fasit det ikke
    er -- og tar en kjopsbeslutning paa den.
    """
    assert "ikke laveste noensinne" in KILDE
    i = KILDE.index('"forbehold"')
    assert i > 0, "forbeholdet maa staa i API-svaret, ikke bare i frontenden"


def test_restock_forbeholder_seg_om_klokkeslettet():
    # Vi skanner hvert tiende minutt. Et klokkeslett her er noyaktig paa ti
    # minutter -- godt nok til aa se et monster, for daarlig til aa sitte
    # klar 09:03.
    # Teksten er delt over to strengliteraler i kilden, saa vi ser etter
    # den sammenhengende biten.
    assert "oppdaget påfyllet" in KILDE
    assert "hvert tiende minutt" in KILDE


def test_daglig_laveste_ikke_gjennomsnitt():
    """Gjennomsnitt over butikker tilsvarer ingen pris du kunne kjopt.

    Laveste er prisen som faktisk fantes den dagen, og det er den du
    sammenligner dagens tilbud mot.
    """
    i = KILDE.index("PRISHISTORIKK_SQL")
    sql = KILDE[i:i + 600]
    assert "min(" in sql
    assert "avg(" not in sql


def test_tidssonen_er_norsk():
    # En bruker som leser «13» skal kjenne seg igjen i sin egen klokke, og
    # halve aaret er UTC og Oslo en time fra hverandre.
    assert "Europe/Oslo" in KILDE
    assert KILDE.count("Europe/Oslo") >= 2, "baade time- og ukedagsstatistikken"


def test_hull_fylles_med_null():
    # En time uten paafyll er null, ikke fravaerende. Ellers tegner
    # frontenden en graf med huller den maa gjette i.
    assert "for t in range(24)" in KILDE
    assert "for d in range(1, 8)" in KILDE


def test_frontenden_viser_hva_man_gar_glipp_av_ikke_en_feil():
    # 402 er ikke en feil for brukeren, det er et tilbud. En raa
    # feilmelding der ville vaert bortkastet.
    i = JS.index("r.status === 402")
    assert "premium-funksjon" in JS[i:i + 600]
