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
