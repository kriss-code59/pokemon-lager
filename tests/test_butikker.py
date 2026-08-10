"""Butikkonfigurasjonen i scrape.py.

Aa legge til en butikk skal vaere en konfigurasjonsrad, ikke ny kode. Da er
det ogsaa konfigurasjonen som er den sannsynlige feilkilden -- en skrivefeil
i et samlingsnavn, en base_url med skraastrek paa slutten, to butikker med
samme navn. Ingen av dem gir en exception; de gir en butikk som stille
leverer null varer, og en butikk som leverer null ser ut som en butikk uten
noe paa lager.

Testene leses med `ast`, ikke ved aa importere scrape.py. Importen drar med
seg playwright og resten av verktoykassa, og en test som krever en
nettleser for aa sjekke en ordbok er en test som blir slaatt av.
"""
import ast
from pathlib import Path

import pytest

ROT = Path(__file__).resolve().parents[1]

LISTER = ("SHOPIFY_STORES", "WOOCOMMERCE_SITES", "QUICKBUTIK_SITES",
          "MANUAL_CHECK_STORES")


def _les_lister():
    tre = ast.parse((ROT / "scrape.py").read_text(encoding="utf-8"))
    ut = {}
    for node in tre.body:
        if (isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in LISTER):
            ut[node.targets[0].id] = ast.literal_eval(node.value)
    return ut


KONF = _les_lister()
SHOPIFY = KONF["SHOPIFY_STORES"]
MANUELLE = KONF["MANUAL_CHECK_STORES"]

ALLE = [(navn, b) for navn, liste in KONF.items() for b in liste]


def test_alle_listene_ble_funnet():
    # Endrer noen navnet paa en liste, skal denne fila si fra -- ikke stille
    # slutte aa teste den.
    assert set(KONF) == set(LISTER), "en liste har byttet navn eller forsvunnet"


@pytest.mark.parametrize("butikk", SHOPIFY, ids=[b["store"] for b in SHOPIFY])
def test_shopify_har_feltene_skraperen_leser(butikk):
    for felt in ("store", "base_url", "collections", "variant_mode"):
        assert felt in butikk, f"mangler {felt}"
    assert butikk["variant_mode"] in ("first", "each")
    assert isinstance(butikk["collections"], list) and butikk["collections"]


@pytest.mark.parametrize("butikk", SHOPIFY, ids=[b["store"] for b in SHOPIFY])
def test_base_url_er_https_uten_skraastrek_paa_slutten(butikk):
    # scrape_shopify_collection() limer sammen base_url + "/collections/...".
    # En skraastrek for mye gir "//collections", som Shopify svarer 404 paa
    # -- og en 404 per samling ser ut som en butikk uten varer.
    url = butikk["base_url"]
    assert url.startswith("https://"), url
    assert not url.endswith("/"), url


# Arcticloot og Braspill hentet enkeltkort lenge for denne regelen fantes, og
# hos dem er det faa nok til at det ikke merkes. De staar oppfort her i stedet
# for aa bli endret: en test skal ikke stille gjore om paa et valg noen tok
# bevisst. Skal de ut, er det en egen avgjorelse med egen begrunnelse.
SINGLES_FRA_FOR = {"Arcticloot", "Braspill"}
NYE = [b for b in SHOPIFY if b["store"] not in SINGLES_FRA_FOR]


@pytest.mark.parametrize("butikk", NYE, ids=[b["store"] for b in NYE])
def test_ingen_singles_samlinger(butikk):
    """Forseglet vare, ikke enkeltkort.

    Kortix alene har over 4 000 enkeltkort fordelt paa ~90 samlinger. Tar
    man dem med, vokser rundetiden kraftig for aa fylle katalogen med noe
    Pokepuls ikke folger -- og rundetiden er hele produktet: den bestemmer
    hvor gammelt et restock-varsel kan vaere.
    """
    for samling in butikk["collections"]:
        assert "single" not in samling.lower(), samling


def test_ingen_butikk_heter_det_samme_som_en_annen():
    # store-navnet blir store_id i databasen. To like navn betyr at den ene
    # butikkens varer overskriver den andres ved hver kjoring, og at
    # krympvernet ser det som at halve utvalget forsvant.
    navn = [b["store"] for _, b in ALLE]
    dubletter = {n for n in navn if navn.count(n) > 1}
    assert not dubletter, f"samme butikk star flere steder: {dubletter}"


def test_en_butikk_er_enten_automatisk_eller_manuell_ikke_begge():
    auto = {b["store"] for navn, b in ALLE if navn != "MANUAL_CHECK_STORES"}
    manuelle = {b["store"] for b in MANUELLE}
    assert not (auto & manuelle), \
        "en butikk som skrapes skal ikke ogsa staa som «sjekk manuelt»"


@pytest.mark.parametrize("butikk", MANUELLE, ids=[b["store"] for b in MANUELLE])
def test_manuell_butikk_har_lenke_og_en_ekte_begrunnelse(butikk):
    """«Sjekk manuelt» er et loefte til brukeren om at vi ikke later som.

    Da maa det staa HVORFOR. En tom eller intetsigende begrunnelse gjor at
    ingen -- heller ikke du om et halvt aar -- vet om butikken kan
    automatiseres naa, eller om noen allerede har provd og gitt opp.
    """
    assert butikk["url"].startswith("https://")
    assert len(butikk.get("reason", "")) > 40, "begrunnelsen ma si noe konkret"


def test_vi_omgaar_ikke_bot_sperrer():
    """Linjen koden allerede har trukket, holdt fast.

    Butikker som stenger doera far staa som «sjekk manuelt» med
    direktelenke. Ingen fingerprint-triksing, ingen Cloudflare-losing, ingen
    CAPTCHA. Det er aerlig, og det ryker ikke neste gang de bytter tema.
    """
    kilde = (ROT / "scrape.py").read_text(encoding="utf-8").lower()
    for teknikk in ["undetected_chromedriver", "cloudscraper", "2captcha",
                    "anticaptcha", "puppeteer-extra-plugin-stealth",
                    "capsolver"]:
        assert teknikk not in kilde, f"{teknikk} horer ikke hjemme her"


# --------------------------------------------------------------- slippdato

def test_30th_har_slippdato_i_katalogen():
    """Nedtellingen leser datoen herfra, ikke fra en dato i frontendkoden.

    Poenget er ikke aa vaere pen. Poenget er at neste sett som skal telles
    ned til krever ÉN rad i katalog.json og ingen kodeendring -- og at
    datoen staar ett sted, saa den ikke kan bli feil to steder.
    """
    import json
    k = json.loads((ROT / "katalog" / "katalog.json").read_text(encoding="utf-8"))
    sett = {s["id"]: s for s in k["sets"]}
    assert sett["30th-celebration"].get("slipp") == "2026-09-16"


def test_slippdatoer_er_iso_og_ingenting_annet():
    # "16.09.2026" ville blitt Invalid Date i nettleseren, og en nedtelling
    # som viser NaN er verre enn ingen nedtelling.
    import json
    import re
    k = json.loads((ROT / "katalog" / "katalog.json").read_text(encoding="utf-8"))
    for s in k["sets"]:
        if "slipp" in s:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["slipp"]), \
                f'{s["id"]}: {s["slipp"]}'


def test_katalogen_synker_slippdatoen_til_databasen():
    # Uten dette staar release_date fortsatt NULL, /api/catalog svarer null,
    # og nedtellingen dukker aldri opp -- uten at noe feiler.
    kilde = (ROT / "ingest" / "ingest.py").read_text(encoding="utf-8")
    assert "release_date" in kilde
    assert 's.get("slipp")' in kilde


# ------------------------------------------------------- lansering

"""Ting som maa vaere paa plass for aa staa offentlig.

Alle sammen er feil som IKKE gir en exception. De gir en side som ser helt
riktig ut mens den mangler noe -- og det er nettopp derfor de trenger en
test og ikke bare et blikk.
"""

WEB = ROT / "web"


def test_sikkerhetsheadere_ligger_i_snippeten_som_faktisk_deployes():
    """Regresjon mot en felle som allerede har kostet oss én gang.

    Headerne sto i deploy/nginx-pokepuls.conf i lang tid og virket aldri:
    certbot eier /etc/nginx/sites-available/pokepuls, saa oppsett-api.sh
    nekter aa kopiere repoets versjon over den. Malt mot produksjon svarte
    pokepuls.no uten en eneste header.

    Snippeten er den ENESTE nginx-filen som installeres ved hver deploy.
    Staar de ikke der, finnes de ikke.
    """
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    for header in ["Strict-Transport-Security", "X-Content-Type-Options",
                   "X-Frame-Options", "Referrer-Policy",
                   "Content-Security-Policy"]:
        assert header in konf, f"{header} mangler i snippeten"


def test_admin_gjentar_headerne():
    # nginx sin arveregel: én add_header i en location slaar av ALLE arvede.
    # /admin har sin egen X-Robots-Tag, saa uten gjentakelse ville admin --
    # den ene siden det er verdt aa angripe -- vaert uten CSP.
    konf = (ROT / "deploy" / "nginx-sider.conf").read_text(encoding="utf-8")
    admin = konf[konf.index("location ~ ^/admin"):]
    for header in ["Content-Security-Policy", "X-Frame-Options",
                   "Strict-Transport-Security"]:
        assert header in admin, f"{header} mangler i admin-blokka"


def test_ingen_innebygde_skript_i_html():
    """CSP-en setter script-src 'self' uten unsafe-inline.

    Et innebygd <script> ville sluttet aa kjore i det CSP-en slaar inn --
    stille, uten feil paa serveren. Det innebygde skriptet i
    nytt-passord.html ble flyttet ut nettopp derfor, og den siden er den
    ENE som maa virke naar alt annet har gaatt galt: den er veien tilbake
    inn i en konto du er laast ute av.
    """
    import re
    for fil in WEB.glob("*.html"):
        html = fil.read_text(encoding="utf-8")
        for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>", html):
            tag = m.group(0)
            # JSON-LD er et datablokk-element, ikke kjorbar kode.
            assert "application/ld+json" in tag, f"{fil.name}: {tag}"


def test_forsiden_har_delebilde():
    # Uten dette ser en lenke delt i en Facebook-gruppe eller paa Discord ut
    # som en naken URL. Det er nettopp der veksten kommer fra.
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'property="og:image"' in html
    assert (WEB / "og-bilde.png").exists(), "bildet det pekes paa maa finnes"


def test_vilkaar_finnes_og_er_lenket():
    vilkar = WEB / "vilkar.html"
    assert vilkar.exists()
    tekst = vilkar.read_text(encoding="utf-8")
    # De tre tingene som MAA staa i et forbrukerkjop av et abonnement.
    for maa in ["49", "Angrerett", "fornyes automatisk"]:
        assert maa in tekst, f"vilkaarene mangler «{maa}»"
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert "/vilkar.html" in app, "vilkaarene maa vaere naabare fra kontosiden"


def test_ukjent_produkt_gir_en_side_og_ikke_rå_json():
    kilde = (ROT / "api" / "sider.py").read_text(encoding="utf-8")
    assert "_ikke_funnet" in kilde
    assert "status_code=404" in kilde, "den skal fortsatt VAERE 404 for Google"


def test_cron_har_usr_sbin_i_path():
    """Rotaarsaken til at sikkerhetsheaderne aldri kom ut.

    /etc/cron.d/pokepuls skrives av oppsett-api.sh og satte
    PATH=/usr/local/bin:/usr/bin:/bin. nginx ligger i /usr/sbin. Dermed ga
    `nginx -t` «command not found» i deployen, skriptet gikk videre, og
    konfigurasjonen ble skrevet til disk uten noen gang aa bli lest inn.

    Feilen er usynlig utenfra: filen ER oppdatert, tidsstemplet ER ferskt,
    og `nginx -t` kjort for haand sier at alt er i orden.
    """
    skript = (ROT / "deploy" / "oppsett-api.sh").read_text(encoding="utf-8")
    path_linjer = [l for l in skript.splitlines() if l.startswith("PATH=")]
    assert path_linjer, "fant ingen PATH-linje i cron-oppsettet"
    for l in path_linjer:
        assert "/usr/sbin" in l, f"cron mangler /usr/sbin: {l}"


def test_deployen_bruker_absolutt_sti_til_nginx():
    # Belte og seler: selv om PATH skulle bli feil igjen, skal deployen
    # finne nginx -- eller si tydelig fra at den ikke gjor det.
    skript = (ROT / "deploy" / "oppsett-api.sh").read_text(encoding="utf-8")
    assert "/usr/sbin/nginx" in skript
    assert '"$NGINX" -t' in skript
