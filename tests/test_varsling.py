"""Tester for varseltekst og VAPID.

Teksten er testet i detalj fordi det er den eneste delen av systemet
brukeren faktisk leser, og fordi den leses paa to sekunder paa en
laaseskjerm. En pris som staar som "1049 kr" i stedet for "1 049 kr", eller
en "billigst"-paastand som er feil, er ikke kosmetikk -- det er forskjellen
paa et varsel du stoler paa og et du slaar av.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from varsling import vapid  # noqa: E402
from varsling.tekst import bygg, kroner, produktnavn, vurdering  # noqa: E402

# Tallene bruker hardt mellomrom (U+00A0) med vilje, sa "1 399 kr" aldri
# brekkes over to linjer paa en laaseskjerm. Testene under leser lettere
# med vanlige mellomrom, saa vi normaliserer -- og sjekker det harde
# mellomrommet eksplisitt i en egen test.
NBSP = "\u00a0"


def n(tekst):
    return tekst.replace(NBSP, " ")


# ------------------------------------------------------------------ kroner

@pytest.mark.parametrize("ore, ventet", [
    (139900, "1 399 kr"),
    (99900, "999 kr"),
    (104950, "1 049,50 kr"),
    (1000000, "10 000 kr"),
    (0, "0 kr"),
    (None, "ukjent pris"),
])
def test_kroner(ore, ventet):
    assert n(kroner(ore)) == ventet


def test_kroner_bruker_hardt_mellomrom_ikke_komma_som_tusenskille():
    # "1,399 kr" leses som 1,4 kroner av en nordmann. Og et vanlig
    # mellomrom lar "1 399\nkr" brekke midt i beloepet.
    assert kroner(139900) == "1" + NBSP + "399" + NBSP + "kr"


def test_desimaler_bruker_komma():
    assert n(kroner(104950)) == "1 049,50 kr"


# ------------------------------------------------------------- produktnavn

def test_produktnavn_uten_regionmerke_for_engelsk():
    assert produktnavn("Prismatic Evolutions", "Booster Bundle", "en") == \
        "Prismatic Evolutions · Booster Bundle"


def test_produktnavn_merker_japansk():
    assert produktnavn("Mega Dream", "Booster Box", "jp").endswith("(JP)")


def test_umatchet_vare_bruker_butikkens_tittel():
    assert produktnavn(None, None, "en", "Pokemon Rammeverk Blister") == \
        "Pokemon Rammeverk Blister"


def test_lang_tittel_kortes_ned():
    lang = "A" * 200
    ut = produktnavn(None, None, "en", lang)
    assert len(ut) <= 70 and ut.endswith("…")


# --------------------------------------------------------------- vurdering

def test_billigst_naar_flere_har_den_inne():
    assert vurdering(139900, 139900, "Mythic", 139900, antall_pa_lager=3) == \
        "ingen har den billigere"


def test_sier_ifra_naar_noen_er_billigere():
    ut = n(vurdering(104900, 89900, "Kanoncon", 89900, antall_pa_lager=4))
    assert "har den til" in ut and "899 kr" in ut and "Kanoncon" in ut


def test_eneste_butikk_sammenlignes_med_historikk():
    ut = n(vurdering(129900, 129900, "Pokestore", 99900, antall_pa_lager=1))
    assert "noen dager siden" in ut and "999 kr" in ut


def test_laveste_pris_paa_en_uke_markeres():
    assert "laveste" in vurdering(149900, 149900, "Emken", 159900,
                                       antall_pa_lager=1)


def test_plassholderpris_gir_ingen_falsk_paastand():
    # Butikkene bruker 1 kr og 0 kr for varer som ikke kan kjopes enna. Da
    # skal vi ikke rope "billigst på lager".
    assert vurdering(100, 139900, "Mythic", 139900, 3) == "pris ikke oppgitt"
    assert vurdering(None, None, None, None, 0) == "pris ikke oppgitt"


def test_billigere_alternativ_med_plassholderpris_ignoreres():
    # En annen butikk med 1 kr er ikke "billigere" -- den er ikke i salg.
    ut = vurdering(139900, 100, "Rar Butikk", None, antall_pa_lager=2)
    assert "har den til" not in ut


def test_en_butikk_alene_paastaar_ikke_billigst():
    # "billigst på lager" er meningslost naar det ikke finnes noen a vaere
    # billigst enn -- og det hoeres ut som en anbefaling.
    ut = vurdering(139900, 139900, "Mythic", None, antall_pa_lager=1)
    assert ut == "eneste butikk med varen inne"


# -------------------------------------------------------------------- bygg

def _h(**kw):
    grunn = dict(kind="restock", store_name="Mythic", store_id="mythic",
                 set_label="Prismatic Evolutions", type_label="Booster Bundle",
                 region="en", price_ore=139900, url="https://mythic.no/x",
                 product_id="prismatic-evolutions:bundle:en")
    grunn.update(kw)
    return grunn


def _k(**kw):
    grunn = dict(billigst_na_ore=139900, billigst_butikk="Mythic",
                 billigst_7d_ore=139900, antall_pa_lager=3)
    grunn.update(kw)
    return grunn


def test_tittel_har_butikk_og_status():
    v = bygg(_h(), _k())
    assert v["title"] == "🛒 Nå inne hos Mythic"


def test_kroppen_har_produkt_paa_forste_linje_og_pris_paa_andre():
    v = bygg(_h(), _k())
    forste, andre = n(v["body"]).split("\n")
    assert forste == "Prismatic Evolutions · Booster Bundle"
    assert andre.startswith("1 399 kr — ")


def test_lenken_gaar_til_butikken_ikke_til_oss():
    # Ved en restock er det sekunder som teller. Et mellomledd er sekunder.
    assert bygg(_h(), _k())["url"] == "https://mythic.no/x"


def test_produktlenken_finnes_som_alternativ():
    assert bygg(_h(), _k())["produkt_url"].startswith("https://pokepuls.no/p/")


def test_prisendring_viser_gammel_og_ny_pris():
    v = bygg(_h(kind="prisendring", price_ore=239900, prev_price_ore=289900),
             _k(billigst_na_ore=239900))
    # Retningen staar i TITTELEN ("Ned 500 kr"), ikke som en pil i kroppen.
    # Da slipper kroppen aa gjenta noe du allerede har lest.
    assert "2 899 kr → 2 399 kr" in n(v["body"])
    assert "Ned" in v["title"] and "500 kr" in n(v["title"])


def test_prisokning_far_pil_opp():
    v = bygg(_h(kind="prisendring", price_ore=289900, prev_price_ore=239900),
             _k(billigst_na_ore=289900))
    assert "Opp" in v["title"] and "500 kr" in n(v["title"])


def test_utsolgt_sier_hvor_mange_andre_som_har_den():
    v = bygg(_h(kind="utsolgt"), _k(antall_pa_lager=2))
    assert "To andre har den fortsatt inne" in v["body"]


def test_bare_restock_og_ny_er_hastig():
    # Alt annet skal kunne komme uten a vibrere telefonen.
    assert bygg(_h(kind="restock"), _k())["hastig"] is True
    assert bygg(_h(kind="ny"), _k())["hastig"] is True
    assert bygg(_h(kind="prisendring"), _k())["hastig"] is False
    assert bygg(_h(kind="utsolgt"), _k())["hastig"] is False


def test_tag_samler_samme_vare_hos_samme_butikk():
    # Samme tag = et nytt varsel erstatter det gamle i varslingssenteret i
    # stedet for a stable seg opp i en koe du aldri leser.
    a = bygg(_h(), _k())["tag"]
    b = bygg(_h(price_ore=129900), _k())["tag"]
    assert a == b
    c = bygg(_h(store_id="annen"), _k())["tag"]
    assert a != c


# ------------------------------------------------------------------- vapid

def test_genererte_nokler_har_riktig_lengde():
    import base64
    privat, offentlig = vapid.generer()

    def raa(s):
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    assert len(raa(privat)) == 32, "privat nokkel skal vaere 32 byte"
    # 65 byte = ukomprimert P-256-punkt (0x04 + x + y). Nettleseren godtar
    # ikke komprimert form i applicationServerKey.
    assert len(raa(offentlig)) == 65
    assert raa(offentlig)[0] == 0x04


def test_nokler_er_base64url_uten_padding():
    privat, offentlig = vapid.generer()
    for nokkel in (privat, offentlig):
        assert "=" not in nokkel and "+" not in nokkel and "/" not in nokkel


def test_to_kall_gir_ulike_nokler():
    assert vapid.generer()[0] != vapid.generer()[0]
