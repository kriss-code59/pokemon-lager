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

def test_testomraadet_holdes_ute_av_google():
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    i = konf.index("location = /ny {")
    assert 'X-Robots-Tag "noindex, nofollow"' in konf[i:i + 1500]
    assert '"Disallow: /ny' in KILDE


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


# ------------------------------------------- fysiske butikker og kartet

def test_kartet_lover_ikke_lager_i_den_enkelte_butikken():
    """Vi undersokte alle 46 butikkene. Bare Outland oppgir lager i fysisk
    butikk, og bare som et ANTALL -- «Tilgjengelig i 4 butikker», ikke
    hvilke fire.

    Et kart faar folk til aa tro paa presisjon. En gronn prikk paa Bergen
    for en vare som finnes i «4 av 15» ville faatt noen til aa kjore dit.
    Forbeholdet maa derfor staa i SVARET, ikke bare i grensesnittet -- den
    som leser API-et direkte skal se det samme.
    """
    main = (ROT / "api" / "main.py").read_text(encoding="utf-8")
    i = main.index('@app.get("/api/steder")')
    kropp = main[i:i + 2200]
    assert '"forbehold"' in kropp
    # Setningen brytes over to linjer i kilden. Test innholdet, ikke
    # linjebruddet -- ellers slaar testen ut neste gang noen rykker inn.
    assert "Viser hvor kjedene har utsalg" in kropp
    assert "Ring butikken før du drar" in kropp


def test_kolonnenavnet_sier_at_det_er_et_antall():
    """Kolonnen heter «antall_fysiske_butikker», ikke «butikker». Ingen
    skal senere tro den kan peke paa et kart.
    """
    sql = (ROT / "db" / "010_fysiske_butikker.sql").read_text(encoding="utf-8")
    assert "antall_fysiske_butikker INT" in sql
    ing = (ROT / "ingest" / "ingest.py").read_text(encoding="utf-8")
    assert "antall_fysiske_butikker = COALESCE(" in ing, \
        "en tom runde tommer kolonnen for alle varene"


def test_koordinater_er_numeric_ikke_float():
    # En breddegrad som flyter er en prikk som flytter seg.
    sql = (ROT / "db" / "010_fysiske_butikker.sql").read_text(encoding="utf-8")
    assert "lat         NUMERIC(8, 5) NOT NULL" in sql
    assert "lon         NUMERIC(8, 5) NOT NULL" in sql


def test_alle_femten_outlandbutikker_er_seedet():
    import re
    sql = (ROT / "db" / "010_fysiske_butikker.sql").read_text(encoding="utf-8")
    rader = re.findall(r"^  \('outland-", sql, re.M)
    assert len(rader) == 15, f"fant {len(rader)} butikker"
    # Tromso har ikke aapnet enna og skal ikke telle som et sted du kan dra.
    assert "'Åpner høsten 2026'" in sql
    assert "18.95530, FALSE" in sql


def test_testomraadet_kan_ikke_mellomlagres():
    """Kristian saa den gamle forhandsvisningen i timevis etter at den var
    slettet: nettleseren serverte /ny fra sin egen disk uten aa spore
    serveren. Jeg lette etter feilen paa serveren, der alt var riktig.

    En adresse som bytter innhold flere ganger om dagen skal ikke kunne
    ligge i en cache. Forsiden kan det -- den har versjonsstreng paa CSS
    og JS -- men /ny er selve stedet der ting endrer seg.
    """
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    i = konf.index("location = /ny {")
    blokk = konf[i:konf.index("}", i)]
    assert 'Cache-Control "no-store' in blokk




# ------------------------------------------------- ekte kart (Leaflet)

def test_leaflet_ligger_lokalt_ikke_paa_et_cdn():
    """CSP-en tillater bare egne skript, og den skal ikke myknes opp for
    et kartbibliotek. Et `script-src` som slipper inn et CDN, slipper inn
    alt det CDN-et noen gang serverer.
    """
    assert (ROT / "web" / "vendor" / "leaflet" / "leaflet.js").exists()
    assert (ROT / "web" / "vendor" / "leaflet" / "leaflet.css").exists()
    # BSD-lisensen skal folge med koden.
    assert (ROT / "web" / "vendor" / "leaflet" / "LICENSE").exists()
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'LEAFLET_JS = "/vendor/leaflet/leaflet.js"' in js
    assert "unpkg.com" not in js and "cdn.jsdelivr" not in js

    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    assert konf.count("script-src 'self';") >= 1
    assert "script-src 'self' https" not in konf, "CSP er myknet opp"


def test_kartet_lastes_forst_naar_noen_aapner_det():
    """148 kB. Forsiden skal ikke betale for en funksjon de fleste aldri
    trykker paa.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    assert "function lastLeaflet" in js
    # Ikke i HTML-en -- da lastes den for alle.
    html = (ROT / "web" / "index.html").read_text(encoding="utf-8")
    assert "leaflet" not in html.lower()


def test_osm_faar_navngiving():
    # Flisene er gratis fordi noen har tegnet dem. Navngiving er kravet.
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    i = js.index("L.tileLayer(")
    assert "OpenStreetMap-bidragsytere" in js[i:i + 400]


def test_markorene_slipper_unna_morkfilteret():
    """Flisene inverteres for aa bli morke. Ligger markorene i samme lag,
    blir gronn til rosa -- og statusfargen er hele poenget med dem.
    """
    css = (ROT / "web" / "style.css").read_text(encoding="utf-8")
    i = css.index(".leaflet-tile-pane")
    assert "invert(1)" in css[i:i + 200]
    # Filteret maa gjelde flis-panelet, ikke hele kartet.
    assert ".leaflet-container {" in css
    j = css.index(".leaflet-container {")
    assert "invert" not in css[j:j + 120]


def test_kartbiblioteket_ligger_ikke_i_skallcachen():
    # 148 kB som aldri endrer seg. Legger vi det i skall-cachen, lastes
    # det ned paa nytt hver gang vi bumper versjonen.
    sw = (ROT / "web" / "sw.js").read_text(encoding="utf-8")
    assert 'url.pathname.startsWith("/vendor/")' in sw
    assert "vendor" not in sw.split("const SKALL")[1].split("]")[0]


def test_byer_klynges_men_kan_zoomes_fra_hverandre():
    # Outland har tre butikker i Oslo. Tre markorer oppa hverandre er en
    # klatt -- men i et ekte kart skiller de seg naar du zoomer inn.
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    assert "function byklynger" in js
    i = js.index("function byklynger")
    assert "byer.set(s.poststed" in js[i:i + 500]


def test_gammelt_kart_ryddes_for_nytt_tegnes():
    """Uten dette klager Leaflet paa at beholderen allerede er i bruk, og
    kartet blir staaende tomt -- noe som forst skjer naar brukeren trykker
    «finn naermeste» og kartet skal tegnes paa nytt.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    i = js.index("function tegnKart")
    kropp = js[i:i + 700]
    assert "kartet.remove()" in kropp
    assert "invalidateSize" in js[i:i + 3000], "hoyden maales aldri paa nytt"


def test_postnummer_i_stedet_for_posisjonstilgang():
    """Forste versjon spurte nettleseren om posisjon. Det koster en
    tillatelsesboks for brukeren har sett noe som helst, virker daarlig
    paa desktop, og er en personopplysning vi ikke trenger.

    Et postnummer holder: vi skal svare paa «hvilken butikk er naermest»,
    ikke navigere deg dit.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    assert "navigator.geolocation" not in js, "spor fortsatt om posisjon"
    assert "const POSTSTEDER = [" in js
    assert "function stedFraPostnummer" in js


def test_geolocation_er_stengt_overalt():
    # Da funksjonen forsvant, skal tillatelsen ogsaa gjore det. En aapen
    # Permissions-Policy uten en funksjon bak er bare en aapen dor.
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    assert "geolocation=(self)" not in konf
    assert konf.count("geolocation=()") >= 5


def test_postnummertabellen_har_ingen_hull():
    """Et postnummer som faller mellom to serier gir ingen treff, og
    brukeren faar «fant ikke postnummeret» paa et helt gyldig nummer.
    """
    import re
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    blokk = js[js.index("const POSTSTEDER = ["):js.index("function stedFraPostnummer")]
    rader = [(int(a), int(b)) for a, b, *_ in
             re.findall(r"\[(\d+), (\d+), \"([^\"]+)\", ([\d.]+), ([\d.]+)\]", blokk)]
    assert len(rader) > 50, f"bare {len(rader)} serier"
    assert rader[0][0] == 1 and rader[-1][1] == 9999, "dekker ikke 0001-9999"
    forrige = 0
    for fra, til in rader:
        assert fra == forrige + 1, f"hull eller overlapp ved {fra} (forrige slutt {forrige})"
        forrige = til


def test_rutenettet_viser_bildet_stort():
    """Vi har bilde paa 487 av 496 produkter -- 98 %. De ble vist som 46
    piksler brede miniatyrer, og da spiller det ingen rolle at vi har dem.

    Konkurrenten viser pakkeskuddet stort, og DET er grunnen til at deres
    side ser bedre ut -- ikke farger, ikke typografi.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    assert "function rutenettKortHtml" in js
    assert 'bildeHtml(p, "rutefoto")' in js
    css = (ROT / "web" / "style.css").read_text(encoding="utf-8")
    i = css.index(".rutefoto {")
    kropp = css[i:i + 300]
    # contain, ikke cover: en booster box skal ikke beskjaeres slik at
    # settnavnet paa esken forsvinner.
    assert "object-fit: contain" in kropp
    # Kvadratisk ramme, ellers hopper radene i hoyde etter hvilke
    # pakkeskudd butikkene tilfeldigvis har.
    assert "aspect-ratio: 1 / 1" in css[css.index(".rutebilde {"):][:300]


def test_bildene_sender_ikke_henviser():
    """Bildene laa der -- 97 % dekning -- URL-ene svarte 200 fra serveren,
    og likevel var rutene tomme i nettleseren.

    Forskjellen er Referer: curl sender ingen, nettleseren sender
    «https://pokepuls.no». Flere Shopify-butikker avviser fremmede
    henvisere paa bilde-CDN-en sin.

    Det var maalt, ikke gjettet: samme URL, 200 fra serveren, blank i
    nettleseren. Uten henviser ser CDN-en et helt vanlig bildekall.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    # Alle tre stedene vi viser butikkbilder.
    assert js.count('referrerpolicy="no-referrer"') >= 3


def test_reservebildet_er_synlig_mot_ramma():
    """Fyllet var #1b2027 -- noyaktig samme farge som .rutebilde bak.
    Et bilde som feilet saa da ut som en tom boks, og det var umulig aa se
    forskjell paa «mangler bilde» og «her er det ingenting».
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    i = js.index("function reservebilde")
    # Strip kommentarene forst. Forklaringen paa hvorfor #1b2027 var feil
    # inneholder naturligvis «#1b2027», og uten dette slaar testen ut paa
    # sin egen begrunnelse -- for femte gang i dette prosjektet.
    kropp = "\n".join(l for l in js[i:i + 1100].splitlines()
                      if not l.lstrip().startswith("//"))
    assert "#1b2027" not in kropp, "reservebildet er usynlig igjen"
    css = (ROT / "web" / "style.css").read_text(encoding="utf-8")
    j = css.index(".rutebilde {")
    assert "var(--flate-2)" in css[j:j + 300]


# ------------------------- fire funksjoner ut av proving, én staar igjen

def test_flagget_gjelder_bare_kartet_naa():
    """Flagget gjaldt fem funksjoner. Fire er godkjent og staar paa
    forsiden for alle -- restock-stripen, filterknappen, veien ut av en
    tom liste og rutenettet.

    Aa skipe dem betydde aa fjerne én if-setning. Det var hele poenget med
    aa bygge dem bak et flagg i stedet for i en kopi av appen.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'const KART_PAA_PROVE = location.pathname === "/ny";' in js
    # Ingen andre funksjoner skal henge paa det.
    assert js.count("KART_PAA_PROVE") == 2, "flagget brukes flere steder enn kartet"
    # Og det gamle navnet skal vaere borte, saa ingen tror det finnes to.
    assert "const NY = " not in js


def test_de_fire_gjelder_for_alle():
    """Ingen av dem skal sjekke hvilken adresse man er paa lenger."""
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    for fn in ("tegnRestockStripe", "tegnFilterlinje", "tegnTomListe"):
        i = js.index("function " + fn)
        kropp = js[i:i + 420]
        assert "KART_PAA_PROVE" not in kropp, fn + " henger fortsatt paa flagget"

    import re
    css = (ROT / "web" / "style.css").read_text(encoding="utf-8")
    # Kommentaren kan nevne det gamle prefikset -- den forklarer nettopp
    # hvorfor det er borte. Reglene kan ikke bruke det. Strip blokkene
    # ordentlig; aa se paa hva en linje BEGYNNER med treffer ikke midten
    # av en flerlinjes kommentar.
    regler = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert "body.ny" not in regler


def test_kartknappen_finnes_bare_paa_ny():
    """Kartet hviler paa lagerdata vi ikke har ordentlig enna -- bare
    Outland oppgir noe, og bare et antall. Da skal knappen ikke staa paa
    forsiden og love noe.
    """
    js = (ROT / "web" / "app.js").read_text(encoding="utf-8")
    i = js.index("const kartKnapp")
    kropp = js[i:i + 320]
    assert "KART_PAA_PROVE" in kropp
    # Fjernes, ikke bare skjules: en skjult knapp i DOM-en er noe folk
    # finner, og da aapner de et kart vi ikke staar inne for.
    assert "kartKnapp.remove()" in kropp
    html = (ROT / "web" / "index.html").read_text(encoding="utf-8")
    i = html.index('id="knapp-kart"')
    assert "hidden" in html[i:i + 120], "knappen vises for JS rekker aa fjerne den"
