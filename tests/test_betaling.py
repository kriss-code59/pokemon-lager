"""Betalingsløypa.

Ingen av testene her snakker med Stripe. De handler om de faa reglene som
avgjor om noen kan faa premium uten aa betale, eller betale uten aa faa
premium -- og begge feilene er dyre paa hver sin maate.

Kortdata finnes ikke i denne kodebasen i det hele tatt. Det er ikke noe vi
er flinke til; det er hele grunnen til aa bruke Stripe.
"""
from pathlib import Path

import pytest

ROT = Path(__file__).resolve().parents[1]
KILDE = (ROT / "api" / "betaling.py").read_text(encoding="utf-8")
SQL = (ROT / "db" / "008_stripe.sql").read_text(encoding="utf-8")

pytest.importorskip("fastapi")


def test_returadressen_gir_ikke_premium():
    """Den viktigste testen i fila.

    Naar Stripe sender brukeren tilbake til success_url, er det bare
    nettleseren som forteller oss noe. Hvem som helst kan aapne den
    adressen. Settes premium der, er gratis premium ett bokmerke unna.

    Rollen skal settes ETT sted: i webhooken, etter signaturkontroll.
    """
    i = KILDE.index("async def webhook")
    j = KILDE.index("app.include_router(router)")
    webhook_delen = KILDE[i:j]
    assert "role = 'premium'" in webhook_delen

    # Og ingen andre steder.
    resten = KILDE[:i]
    assert "role = 'premium'" not in resten, \
        "premium settes utenfor webhooken -- da kan den forfalskes"


def test_signaturen_kontrolleres_for_innholdet_leses():
    i = KILDE.index("async def webhook")
    kropp = KILDE[i:i + 1600]
    assert "construct_event" in kropp
    sig = kropp.index("construct_event")
    bruk = kropp.index('hendelse["type"]') if 'hendelse["type"]' in kropp else len(kropp)
    assert sig < bruk, "innholdet leses for signaturen er sjekket"


def test_feilmeldingen_roper_ikke_hvorfor():
    # Et endepunkt som forklarer hvorfor en signatur ikke holdt, hjelper
    # den som prover aa gjette seg fram.
    i = KILDE.index("Ugyldig signatur")
    assert "except Exception" in KILDE[max(0, i - 400):i]


def test_gjentatte_webhooks_teller_bare_en_gang():
    """Stripe leverer MINST én gang, ikke NOYAKTIG én.

    Uten sperre kunne en gjentatt checkout.session.completed gitt to
    maaneder for én betaling.
    """
    assert "stripe_hendelser" in SQL
    assert "id        TEXT PRIMARY KEY" in SQL
    assert "ON CONFLICT (id) DO NOTHING" in KILDE
    assert "gjentakelse" in KILDE


def test_vi_senker_aldri_noen_i_webhooken():
    """Sier du opp midt i perioden, beholder du premium ut perioden.

    Det staar i vilkaarene. Stripe sender `subscription.updated` med
    cancel_at_period_end, og hadde vi senket rollen der, ville folk mistet
    noe de har betalt for.
    """
    assert "role = 'free'" not in KILDE
    assert "premium_until = NULL" not in KILDE


def test_admin_mister_ikke_rollen_sin():
    # UPDATE-en setter role='premium'. Uten unntaket ville en admin som
    # kjoper premium blitt degradert til vanlig betalende bruker -- og
    # mistet admin-tilgangen sin i samme slengen.
    i = KILDE.index("role = 'premium'")
    assert "role <> 'admin'" in KILDE[i:i + 300]


def test_modulen_er_av_uten_fullt_oppsett():
    """En halvkonfigurert betalingsloype skal ikke se ut som en fungerende.

    Mangler én av de tre variablene, svarer endepunktene 503 og
    grensesnittet viser ingen kjopsknapp.
    """
    from api import betaling
    assert betaling.paa() is False, "ingen nokler satt i testmiljoet"
    assert "def paa()" in KILDE
    for felt in ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_ID"]:
        assert felt in KILDE


def test_stripe_importeres_forst_ved_bruk():
    # En manglende avhengighet skal ikke ta ned hele API-et -- inkludert
    # alt som er gratis og virker.
    assert "\nimport stripe" not in KILDE, "stripe importeres paa modulnivaa"
    assert "def _stripe()" in KILDE


def _uten_kommentarer(tekst: str) -> str:
    """Bare kode. Kommentarene VAAR omtaler kortdata for aa forklare at vi
    ikke roerer dem, og en test som ikke skiller de to ville slaatt ut paa
    sin egen begrunnelse."""
    ut = []
    i_docstring = False
    for linje in tekst.splitlines():
        strippet = linje.strip()
        if strippet.count('"""') == 1:
            i_docstring = not i_docstring
            continue
        if i_docstring or strippet.startswith(("#", "--")):
            continue
        ut.append(linje.split("#")[0])
    return "\n".join(ut)


def test_ingen_kortdata_noe_sted():
    lav = _uten_kommentarer(KILDE + "\n" + SQL).lower()
    for ord_ in ["card_number", "cvc", "kortnummer", "expiry", "cardnumber"]:
        assert ord_ not in lav, f"«{ord_}» skal ikke finnes i denne kodebasen"


def test_prisen_star_i_stripe_ikke_i_koden():
    """PRIS_KR er til visning, ikke til belastning.

    Bel\u00f8pet som faktisk trekkes ligger paa pris-ID-en i Stripe. Gaar de
    to fra hverandre, er det Stripe som tar pengene -- og da er det Stripe
    som gjelder. Det maa staa i koden, ellers vil noen en dag endre tallet
    her og tro at prisen er endret.
    """
    i = KILDE.index("PRIS_KR = ")
    rundt = KILDE[max(0, i - 400):i]
    assert "visning" in rundt, "PRIS_KR mangler forklaringen om at den bare vises"
    # Den skal aldri sendes til Stripe som beloep.
    assert "amount" not in KILDE, "beloepet skal komme fra pris-ID-en, ikke herfra"
