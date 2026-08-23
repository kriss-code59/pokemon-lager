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


def test_byttede_nokler_oppdages_med_en_gang():
    """Byttefeilen som kostet oss en runde med journalctl.

    STRIPE_SECRET_KEY og STRIPE_WEBHOOK_SECRET er begge lange, tilfeldige
    strenger man limer inn etter hverandre. Bytter man om, feiler ingenting
    ved oppstart -- det feiler forst naar en ekte kunde trykker kjop, med
    «Invalid API Key» dypt nede i et Stripe-spor.

    Prefiksene er faste. Da er det ingen grunn til aa oppdage det senere
    enn med én gang.
    """
    import importlib
    from api import betaling

    gammel = betaling.FORVENTET
    try:
        betaling.FORVENTET = {
            "STRIPE_SECRET_KEY": ("sk_", "whsec_abc123"),
            "STRIPE_WEBHOOK_SECRET": ("whsec_", "sk_test_abc123"),
            "STRIPE_PRICE_ID": ("price_", "price_ok"),
        }
        feil = betaling.feilkonfigurert()
        assert len(feil) == 2
        assert "byttet om" in feil[0]
        # Verdien skal ALDRI gjentas i meldingen -- den havner i loggen,
        # og loggen er ikke hemmelig.
        assert "abc123" not in " ".join(feil)
    finally:
        betaling.FORVENTET = gammel
        importlib.reload(betaling)


def test_riktige_prefikser_gir_ingen_klage():
    from api import betaling
    gammel = betaling.FORVENTET
    try:
        betaling.FORVENTET = {
            "STRIPE_SECRET_KEY": ("sk_", "sk_test_x"),
            "STRIPE_WEBHOOK_SECRET": ("whsec_", "whsec_y"),
            "STRIPE_PRICE_ID": ("price_", "price_z"),
        }
        assert betaling.feilkonfigurert() == []
    finally:
        betaling.FORVENTET = gammel


# ------------------------------------------- StripeObject er ikke en dict

class _FalskStripeObject:
    """Oppforer seg som stripe._stripe_object.StripeObject.

    Stotter [] men IKKE .get() -- __getattr__ fanger navnet «get» og leter
    etter et felt som heter det. Det er noyaktig oppforselen som ga
    «AttributeError: get» og 500 i webhooken paa forste ekte betaling.
    """

    def __init__(self, **felt):
        self._data = felt

    def __getitem__(self, k):
        return self._data[k]

    def __getattr__(self, k):
        try:
            return self._data[k]
        except KeyError as e:
            raise AttributeError(*e.args) from e


def test_felt_leser_uten_aa_bruke_get():
    from api.betaling import _felt
    o = _FalskStripeObject(customer="cus_1", status="active")
    assert _felt(o, "customer") == "cus_1"
    assert _felt(o, "finnes_ikke") is None
    assert _felt(o, "finnes_ikke", "reserve") == "reserve"
    assert _felt(None, "hva som helst") is None


def test_koden_bruker_aldri_punktum_get_paa_stripe_objekter():
    """Regresjonsvern.

    Fella er lett aa gaa i igjen: objektet oppforer seg som en dict i alt
    annet, og feilen dukker forst opp naar en EKTE hendelse kommer inn --
    altsaa naar noen har betalt.
    """
    import re
    for linje in KILDE.splitlines():
        if linje.strip().startswith("#"):
            continue
        assert not re.search(r"\b(data|abo|hendelse)\.get\(", linje), linje.strip()


def test_periode_slutt_leses_baade_gammelt_og_nytt_sted():
    """`current_period_end` flyttet.

    Fram til API-versjon 2025-03 laa den paa selve abonnementet. I nyere
    versjoner -- deriblant 2026-07-29.dahlia som webhooken bruker -- ligger
    den paa LINJENE, fordi et abonnement kan ha flere med ulik periode.
    """
    from api.betaling import _periode_slutt

    gammelt = _FalskStripeObject(current_period_end=1800000000)
    assert _periode_slutt(gammelt) == 1800000000

    nytt = _FalskStripeObject(items=_FalskStripeObject(
        data=[_FalskStripeObject(current_period_end=1900000000)]))
    assert _periode_slutt(nytt) == 1900000000

    # Ingen av delene: skal gi None, ikke kaste. En manglende dato er
    # ubehagelig; en exception i webhooken er en tapt betaling.
    assert _periode_slutt(_FalskStripeObject(status="active")) is None


# ------------------------------------------- ett endepunkt per nettleser

"""Duplikatvarslene.

Malt i drift 14. august: én bruker hadde TRE push-endepunkter, opprettet
7., 9. og 13. august. Alle med feil_pa_rad = 0 og last_ok_at samme time --
altsaa alle levende. Hvert varsel gikk ut i tre kopier til samme person.

Aarsaken er at nettleseren kan bytte push-abonnement naar service workeren
oppdateres, og den oppdateres ved hver cache-bump. Tolv deployer paa én dag
ga tre nye abonnementer.

Den vanlige oppryddingen hjelper ikke: den sletter DODE endepunkter. Disse
er ikke dode.
"""

PUSH = (ROT / "api" / "push.py").read_text(encoding="utf-8")
APP_JS = (ROT / "web" / "app.js").read_text(encoding="utf-8")


def test_abonner_rydder_bort_forrige_fra_samme_nettleser():
    """En bruker skal ha ÉN registrering per nettleser, ikke én per
    service worker-generasjon.

    Testen sto tidligere og krevde at oppryddingen matchet paa user_agent.
    Den laaste fast nettopp regelen som viste seg aa vaere feil: strengen
    endrer seg naar telefonen oppdaterer iOS, og da overlevde duplikatene.
    Testen var altsaa gronn mens feilen sto i drift.

    Den maaler naa resultatet -- at rader uten installasjons-id ryddes bort
    naar det finnes en med -- ikke hvordan jeg lose det forste gang.
    """
    kilde = (ROT / "api" / "push.py").read_text(encoding="utf-8")
    i = kilde.index('@router.post("/abonner")')
    kropp = kilde[i:kilde.index('@router.post("/avmeld")', i)]
    assert "DELETE FROM push_endpoints" in kropp
    assert "installasjon = %s OR installasjon IS NULL" in kropp
    # Den nye raden maa vaere unntatt, ellers sletter vi det vi nettopp
    # lagde og brukeren staar uten varsler.
    assert "id <> %s" in kropp

def test_oppryddingen_rorer_ikke_andre_enheter():
    # En som faktisk bruker to telefoner skal beholde begge. Sletting skjer
    # bare paa samme installasjon eller samme user agent.
    i = PUSH.index("DELETE FROM push_endpoints WHERE user_id")
    setning = PUSH[i:i + 400]
    assert "id <> %s" in setning, "den nye raden maa overleve"
    assert "user_id = %s" in setning, "aldri paa tvers av brukere"


def test_installasjons_id_overlever_at_fanen_lukkes():
    # sessionStorage ville gitt en ny id per fane, og da hadde vi loest
    # ingenting. Den MAA vaere localStorage.
    i = APP_JS.index("function installasjonsId")
    kropp = APP_JS[i:i + 700]
    assert "localStorage" in kropp
    assert "sessionStorage" not in kropp


def test_klienten_uten_id_faar_fortsatt_abonnere():
    # Privat modus kaster paa localStorage. Da mister vi oppryddingen, men
    # varslene skal fortsatt virke -- en bekvemmelighet skal aldri vaere
    # grunnen til at hovedfunksjonen ryker.
    assert "installasjon: str | None" in PUSH
    i = APP_JS.index("function installasjonsId")
    assert "return null" in APP_JS[i:i + 800]


# ------------------------------------------------- gratis premium fra admin

ADMIN = (ROT / "api" / "admin.py").read_text(encoding="utf-8")


def test_gratis_premium_nullstiller_utlopsdatoen():
    """Rollen alene er ikke nok.

    er_premium() krever role='premium' OG at premium_until er NULL eller i
    framtiden. Gir du premium til noen som har hatt et abonnement som gikk
    ut, staar den gamle datoen igjen og har passert -- og gaven virker
    ikke. Det ville vaert en feil ingen oppdaget for kunden klaget.
    """
    i = ADMIN.index("async def sett_premium")
    kropp = ADMIN[i:ADMIN.index("@router.get", i)]
    assert "role = 'premium', premium_until = NULL" in kropp
    assert "role = 'free', premium_until = NULL" in kropp


def test_admin_rorer_aldri_abonnementet():
    """En som betaler skal ikke miste abonnementet med et uhell herfra.

    Vi skriver aldri til stripe_kunder. Tar du premium fra noen som
    betaler, fortsetter Stripe aa trekke dem -- og neste webhook setter
    rollen tilbake. Derfor sier svaret fra i stedet for aa late som.
    """
    i = ADMIN.index("async def sett_premium")
    kropp = ADMIN[i:ADMIN.index("@router.get", i)]
    assert "UPDATE stripe_kunder" not in kropp
    assert "DELETE FROM stripe_kunder" not in kropp
    assert "advarsel" in kropp


def test_admin_kan_ikke_degradere_seg_selv_via_premium():
    # Rolleknappen har allerede en sperre mot aa fjerne egen admin-rolle.
    # Premium-knappen ville ellers vaert en vei rundt den.
    i = ADMIN.index("async def sett_premium")
    kropp = ADMIN[i:ADMIN.index("@router.get", i)]
    assert 'role"] == "admin"' in kropp


def test_tellingen_skiller_betalende_fra_gitt():
    # Kampanjen er «de 50 forste faar gratis». Da maa du vite hvor mange av
    # premium-brukerne som faktisk betaler, ellers teller du feil.
    i = ADMIN.index("async def premium_telling")
    kropp = ADMIN[i:i + 1200]
    assert "betalende" in kropp and "gratis" in kropp
    assert "premium_until IS NULL" in kropp, "en gave har ingen utlopsdato"


# MERK: _uten_kommentarer() finnes allerede lenger oppe i fila, og den
# stripper docstrings ogsaa. Da jeg definerte den paa nytt her, skygget den
# for originalen -- og test_ingen_kortdata_noe_sted slo ut paa ordet «cvc»
# i betaling.py sin egen forklaring paa hvorfor vi ALDRI ser kortdata.
# Testen hadde rett; den nye hjelperen var feil.


def test_kundeid_fra_feil_modus_stopper_ikke_kjopet():
    """En kunde-ID hoerer til ÉN modus. `cus_...` laget i testmodus finnes
    ikke i live, og Stripe svarer «No such customer».

    Vi testet betalingen i testmodus for vi skrudde paa live, og raden i
    stripe_kunder ble staaende og peke paa en testkunde. Neste trykk paa
    kjopsknappen ville feilet med en rod boks og ingen forklaring.

    Det skal ikke vaere noe man rydder opp i manuelt i databasen -- det
    skal vaere noe koden taaler.
    """
    kilde = _uten_kommentarer(
        (ROT / "api" / "betaling.py").read_text(encoding="utf-8"))
    assert "def _finnes(" in kilde
    i = kilde.index("async def start(")
    kropp = kilde[i:kilde.index("async def portal(", i)]
    assert "_finnes(stripe, kunde)" in kropp
    assert "kunde = None" in kropp


def test_portalen_sier_ifra_i_stedet_for_aa_kraesje():
    kilde = _uten_kommentarer(
        (ROT / "api" / "betaling.py").read_text(encoding="utf-8"))
    i = kilde.index("async def portal(")
    kropp = kilde[i:i + 1400]
    assert "_finnes(stripe, rad[" in kropp
    assert "404" in kropp
