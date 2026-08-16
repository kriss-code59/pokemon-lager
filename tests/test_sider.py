"""SEO paa de serverrendrede sidene.

Disse sidene er hele grunnen til at Pokepuls kan bli funnet i det hele
tatt. Forsiden er klientrendret og sier «laster…» til JS-en er kjort --
det er /p/-sidene, /butikker og /kalender som baerer soeketrafikken.

Testene leser kilden direkte. Aa faktisk kalle endepunktene ville krevd en
database med produkter i, og det som gaar galt her er uansett ikke logikk
-- det er felt som stille faller ut.
"""
import json
import re
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent
KILDE = (ROT / "api" / "sider.py").read_text(encoding="utf-8")


def test_cacheversjonen_folger_resten_av_nettstedet():
    """Den sto hardkodet som v24 mens alt annet var paa v26.

    Den slags oppdager ingen: siden ser riktig ut, den er bare gammel. Naa
    er tallet bundet til sw.js, saa de ikke kan gaa fra hverandre igjen.
    """
    m = re.search(r"^CSS_V = (\d+)", KILDE, re.M)
    assert m, "CSS_V finnes ikke"
    sw = (ROT / "web" / "sw.js").read_text(encoding="utf-8")
    assert f"pokepuls-skall-v{m.group(1)}" in sw, \
        "CSS_V i sider.py og cacheversjonen i sw.js har gaatt fra hverandre"
    assert "style.css?v=24" not in KILDE, "hardkodet versjon staar igjen"


def test_nettstedet_presenterer_seg_paa_hver_side():
    # Uten dette maa Google gjette at treffene hoerer til samme avsender.
    assert "NETTSTED_LD" in KILDE
    assert '"@type": "WebSite"' in KILDE
    assert "SearchAction" in KILDE
    i = KILDE.index("def _sidehode(")
    kropp = KILDE[i:i + 1400]
    assert "@graph" in kropp, "dataene samles ikke i én graf"
    assert "NETTSTED_LD" in kropp


def test_produktsiden_har_brodsmuler():
    # Google viser brodsmuler i stedet for den raa adressen i treffet.
    assert '"@type": "BreadcrumbList"' in KILDE
    i = KILDE.index('"@type": "BreadcrumbList"')
    assert "itemListElement" in KILDE[i:i + 600]


def test_produktsidene_lenker_til_hverandre():
    """Produktsidene laa som oyer: sitemap inn, ingen lenker mellom dem.

    En soekemotor maatte tilbake til sitemap for hver eneste side, og ingen
    side gav noen annen side vekt.
    """
    assert "SOSKEN_SQL" in KILDE
    # Bare produkter vi faktisk har en oppforing paa -- en lenke til en tom
    # side er verre enn ingen lenke.
    i = KILDE.index("SOSKEN_SQL")
    sql = KILDE[i:KILDE.index('"""', KILDE.index('"""', i) + 3)]
    assert "JOIN listings" in sql
    assert "last_seen_at" in sql
    assert "p.id <> %s" in sql, "produktet lenker til seg selv"
    assert 'href="/p/' in KILDE


def test_oversiktssidene_er_merket_som_lister():
    # Begge sendte tidligere None som strukturerte data.
    assert KILDE.count('"@type": "ItemList"') >= 2
    assert "BASE + \"/butikker\", None)" not in KILDE
    assert "BASE + \"/kalender\", None)" not in KILDE


def test_forsiden_har_strukturerte_data():
    """Forsiden er klientrendret. Uten dette har den siden folk faktisk
    lenker til ingen strukturerte data i det hele tatt.
    """
    h = (ROT / "web" / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)
    assert m, "ingen JSON-LD paa forsiden"
    data = json.loads(m.group(1))  # maa vaere gyldig JSON
    typer = {n["@type"] for n in data["@graph"]}
    assert "WebSite" in typer
    assert "WebApplication" in typer


def test_404_siden_faktisk_interpolerer_versjonen():
    """_ikke_funnet() var ikke en f-streng. «?v={CSS_V}» ville staatt
    ordrett i HTML-en, og siden ville aldri lastet CSS-en sin.
    """
    i = KILDE.index("def _ikke_funnet")
    kropp = KILDE[i:i + 400]
    assert 'return f"""' in kropp, "ikke en f-streng"
    assert "{CSS_V}" in kropp


def test_forsiden_har_bare_én_websitenode():
    """Forsiden hadde allerede en WebSite-blokk. Da jeg la til grafen, sto
    det plutselig to -- og to motstridende WebSite-noder er ikke dobbelt
    saa mye data, det er data soekemotoren maa velge mellom.
    """
    h = (ROT / "web" / "index.html").read_text(encoding="utf-8")
    assert h.count('type="application/ld+json"') == 1
    assert h.count('"@type":"WebSite"') == 1
