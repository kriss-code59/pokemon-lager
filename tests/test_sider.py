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


def test_odelagt_skraper_kalles_ikke_et_valg():
    """Emken, Collectible og Ark sto under «Kartlagt, men ikke
    automatisert» -- sammen med butikker vi bevisst ikke leser.

    Men vi HADDE lest dem. Skraperne var i stykker, og siden presenterte
    det som en beslutning. Det er samme feil som gaar igjen overalt her:
    en butikk som leverer null feiler ikke, den tier -- og skjuler vi
    tausheten bak en pen overskrift, blir den aldri oppdaget.
    """
    assert "stille = [r for r in tomme if r[\"sist\"]]" in KILDE
    assert "aldri = [r for r in tomme if not r[\"sist\"]]" in KILDE
    # To ulike overskrifter, ikke én samlesekk.
    assert "Uten ferske tall" in KILDE
    assert "Kartlagt, men ikke automatisert" in KILDE
    # Og et tall man kan gjore noe med.
    assert "_dager_siden" in KILDE


def test_dager_siden_taaler_alt():
    import types
    rom: dict = {}
    i = KILDE.index("def _dager_siden")
    exec(KILDE[i:KILDE.index("\ndef ", i + 10)], rom)
    f = rom["_dager_siden"]
    from datetime import datetime, timedelta, timezone
    na = datetime.now(timezone.utc)
    assert f(None) == "aldri"
    assert f(na) == "i dag"
    assert f(na - timedelta(days=1)) == "i går"
    assert f(na - timedelta(days=9)) == "9 dager siden"


# ------------------------------------------------------ serverrendret forside

def test_forsiden_serverrendres():
    """Forsiden var et JavaScript-skall. Det forste en soekemotor saa var
    ordet «laster…». Produktsidene rangerte, men SELVE forsiden -- den folk
    lenker til -- hadde ingen tekst i det hele tatt.
    """
    assert "FORSIDE_SQL" in KILDE
    assert '@router.get("/")' in KILDE
    i = KILDE.index("async def forside")
    kropp = KILDE[i:KILDE.index("# ---", i)]
    # Innholdet maa faktisk injiseres i skallet.
    assert 'id="liste" class="liste"></div>' in kropp
    assert 'id="teller"></p>' in kropp
    # Og lenke til produktsidene -- det er slik forsiden gir dem vekt.
    assert 'href="/p/' in kropp


def test_forsiden_har_én_kilde_til_skallet():
    """Kopierte vi HTML-en inn i Python, ville vi hatt to forsider aa holde
    i takt -- og den ene ville blitt glemt neste gang noen la til en fane.
    """
    assert "def _skallet" in KILDE
    i = KILDE.index("def _skallet")
    kropp = KILDE[i:KILDE.index("\ndef ", i + 10)]
    assert '"web" / "index.html"' in kropp
    assert "st_mtime" in kropp, "leser filen paa nytt ved hver forespoersel"


def test_forsiden_viser_det_samme_til_alle():
    """Serverer man én ting til Google og en annen til folk, heter det
    cloaking. Det er en av de faa tingene som gir manuell straff.

    Sikringen er at det server-rendrede innholdet kommer fra samme
    database som API-et appen henter fra -- ikke fra en egen liste.
    """
    i = KILDE.index("FORSIDE_SQL")
    sql = KILDE[i:KILDE.index('"""', KILDE.index('"""', i) + 3)]
    assert "FROM products p" in sql
    assert "JOIN listings l" in sql
    # Bare varer vi faktisk har sett nylig.
    assert "last_seen_at >" in sql


def test_nginx_faller_tilbake_naar_api_et_er_nede():
    """Forsiden var det ene som alltid virket, uansett hva som var galt med
    API-et. Den avhengigheten kan vi ikke innfore uten et nett under.
    """
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    assert "location @forside_statisk" in konf
    assert "proxy_intercept_errors on;" in konf
    # Likhetstegnet: uten det beholdes 502-statusen selv naar vi leverer en
    # fungerende side, og soekemotorer tror forsiden er nede.
    assert "error_page 500 502 503 504 = @forside_statisk;" in konf
    # Fallbacken maa ha sine egne headere -- én add_header i en location
    # slaar av ALLE arvede.
    i = konf.index("location @forside_statisk")
    assert "Content-Security-Policy" in konf[i:i + 1200]


def test_bare_én_adresse_for_nettstedet():
    """Malt mot produksjon: bade pokepuls.no og www.pokepuls.no svarte 200
    med hele nettstedet. Google saa to komplette kopier og maatte gjette --
    lenker, autoritet og kravlebudsjett delt paa to.

    Canonical-taggen peker riktig, men den er et HINT. En 301 er en regel.
    """
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    assert "if ($host = www.pokepuls.no)" in konf
    assert "return 301 https://pokepuls.no$request_uri;" in konf


def test_friskhetsfilteret_gjelder_alle_tallene():
    """Emken sto med «17 varer» og «41 inne» -- flere paa lager enn
    butikken hadde varer.

    `varer` filtrerte paa siste sju dogn, `inne` og `billigst` gjorde det
    ikke. Da talte «inne» oppforinger vi ikke hadde sett paa uker, og
    «billigst» kunne vise prisen paa en vare som ikke fantes lenger.
    """
    i = KILDE.index("BUTIKKER_SQL")
    sql = KILDE[i:KILDE.index('"""', KILDE.index('"""', i) + 3)]
    # Tre tall, tre friskhetsfiltre.
    assert sql.count("last_seen_at > now() - interval '7 days'") == 3


def test_google_verifiseringsfilen_ligger_der():
    """Search Console-tilgangen henger paa denne ene filen.

    Forsvinner den -- ved en opprydding, en flytting av web/, en .gitignore
    som blir litt for ivrig -- mister vi tilgangen til de eneste ekte
    tallene vi har paa hvordan Pokepuls gjor det i soek. Og vi merker det
    ikke, for nettstedet virker fint uten den.
    """
    fil = ROT / "web" / "google8e11db2d0c64d7f6.html"
    assert fil.exists(), "Google-verifiseringen er borte"
    # Google sammenligner innholdet, ikke bare filnavnet.
    assert fil.read_text(encoding="utf-8").strip() == \
        "google-site-verification: google8e11db2d0c64d7f6.html"


def test_robots_stenger_ikke_verifiseringen_ute():
    # Disallow paa noe som dekker filen ville gjort verifiseringen umulig
    # aa gjennomfore, uten at noe annet sluttet aa virke.
    i = KILDE.index("async def robots")
    kropp = KILDE[i:i + 900]
    for sti in ('"Disallow: /admin', '"Disallow: /api/', '"Disallow: /ny'):
        assert sti in kropp
    assert kropp.count("Disallow:") == 3, "nye Disallow-regler -- sjekk filen"


# ---------------------------------------------------- testomraadet /ny

def test_ny_er_samme_fil_som_forsiden():
    """/ny serverer NOYAKTIG samme index.html. Forskjellen er et flagg i
    app.js.

    Alternativet var en kopi av appen. app.js er over 2000 linjer -- en
    fork ville blitt to forsider aa holde i takt, og den ene ville blitt
    glemt neste gang noen rettet en feil.
    """
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    i = konf.index("location = /ny {")
    blokk = konf[i:i + 1500]
    assert "try_files /index.html =404;" in blokk
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'const NY = location.pathname === "/ny";' in js


def test_forsiden_ser_ikke_testfunksjonene():
    """Hele poenget: Kristian skal kunne prove noe uten at kundene merker
    det. Alt nytt maa ligge bak flagget eller bak `body.ny` i CSS-en.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    # De tre nye funksjonene maa alle sjekke flagget for de gjor noe.
    for fn in ("tegnRestockStripe", "tegnFilterlinje", "tegnTomListe"):
        i = js.index("function " + fn)
        kropp = js[i:i + 420]
        assert "NY" in kropp, fn + " sjekker ikke flagget"

    css = (ROT / "web" / "style.css").read_text(encoding="utf-8")
    i = css.index("TESTOMRAADE (/ny)")
    # Filterpanelet er det ene unntaket: det MAA vaere display:contents paa
    # forsiden, ellers endrer beholderen layouten der ogsaa.
    assert ".filterpanel { display: contents; }" in css[i:]


def test_testomraadet_holdes_ute_av_google():
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    i = konf.index("location = /ny {")
    assert 'X-Robots-Tag "noindex, nofollow"' in konf[i:i + 1500]
    assert '"Disallow: /ny' in KILDE


def test_posisjon_er_kun_tillatt_paa_ny():
    """«Finn naermeste butikk» skal spore om posisjon. Da maa
    Permissions-Policy tillate det -- men BARE der funksjonen finnes.

    Resten av nettstedet skal fortsatt ha geolocation slaatt helt av.
    """
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    assert konf.count("geolocation=(self)") == 1, "posisjon aapnet flere steder"
    i = konf.index("location = /ny {")
    assert "geolocation=(self)" in konf[i:i + 1500]


def test_restockstripen_ser_bare_siste_time():
    """En restock fra i gaar haster ikke, den er historikk -- og hoerer
    hjemme i Nytt-fanen. Stripen mister all mening hvis den fylles med
    gammelt.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    assert "const STRIPE_VINDU_MS = 60 * 60 * 1000;" in js
    i = js.index("function restockNylig")
    kropp = js[i:i + 500]
    assert "STRIPE_VINDU_MS" in kropp
    assert "antall_pa_lager" in kropp, "tar med forhandssalg som restock"


def test_tom_liste_regner_ut_hvilket_filter_som_koster_mest():
    """«Ingen treff» er en blindvei: du maa selv gjette hvilket av tre
    filtre som var for strengt. Naa fjerner vi ett om gangen, teller, og
    tilbyr det som gir flest.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    i = js.index("function tegnTomListe")
    kropp = js[i:js.index("/* RESTOCK-STRIPEN", i)]
    assert "for (const [navn, tekst] of aktive)" in kropp
    assert "filtrert().length" in kropp
    # Og state MAA legges tilbake -- ellers har utregningen endret
    # filtrene brukeren faktisk har paa.
    assert kropp.count("Object.assign(state, sikkerhetskopi)") == 2


def test_filterknappen_gjenbruker_de_gamle_filtrene():
    """Vi bygget ikke et nytt filtersystem. Chip-radene ligger fortsatt i
    panelet bak knappen, og leser og skriver samme state.

    Hadde vi laget et parallelt sett, ville de to kommet ut av takt --
    og feilen ville vaert usynlig til noen brukte begge.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    i = js.index("function nullstillFilter")
    kropp = js[i:i + 900]
    for felt in ("state.kunLager", "state.forhandssalg", "state.region", "state.type"):
        assert felt in kropp, felt
    assert '$("chips").children' in kropp, "chip-radene oppdateres ikke"
