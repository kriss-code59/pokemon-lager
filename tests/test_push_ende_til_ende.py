"""Ende-til-ende for Web Push, uten aa sende noe ut paa nettet.

Denne testen finnes fordi Web Push har et feilmodus som ingen andre tester
fanger: alt ser ut til aa virke -- serveren svarer 201, loggen sier «sendt»,
tabellen sier ok=true -- og telefonen viser ingenting. Aarsaken er da alltid
det samme: krypteringen eller VAPID-signaturen var feil, og pushtjenesten
kastet meldingen uten aa si ifra.

Saa her spiller vi begge roller. Vi lager et abonnement slik en nettleser
gjor det (en fersk P-256-nokkel og en tilfeldig auth-hemmelighet), sender et
ekte varsel gjennom var egen kode, og DEKRYPTERER det tilbake med
klientnokkelen. Kommer den samme teksten ut igjen, virker hele kjeden:

    varsling.vapid.generer()  ->  pywebpush (aes128gcm)  ->  klienten

Krever `pywebpush` og `http_ece`, som begge folger med api/requirements.txt.
"""
import base64
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("pywebpush")
pytest.importorskip("http_ece")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

from varsling import send as sender  # noqa: E402
from varsling import vapid  # noqa: E402
from varsling.tekst import bygg  # noqa: E402


def _b64(raa: bytes) -> str:
    return base64.urlsafe_b64encode(raa).decode().rstrip("=")


class _Falsk(BaseHTTPRequestHandler):
    """Later som den er Apples/Googles pushtjeneste."""
    mottatt: dict = {}

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _Falsk.mottatt = {"kropp": self.rfile.read(n),
                          "headers": {k.lower(): v for k, v in self.headers.items()}}
        self.send_response(201)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def pushtjeneste():
    srv = HTTPServer(("127.0.0.1", 0), _Falsk)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/push/testabonnement"
    srv.shutdown()


@pytest.fixture
def abonnement():
    """Et abonnement slik nettleseren ville laget det."""
    klient = ec.generate_private_key(ec.SECP256R1())
    p256dh = _b64(klient.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    return klient, p256dh, _b64(os.urandom(16))


@pytest.fixture
def nokler(monkeypatch):
    privat, offentlig = vapid.generer()
    monkeypatch.setenv("POKEPULS_VAPID_PRIVATE", privat)
    monkeypatch.setenv("POKEPULS_VAPID_PUBLIC", offentlig)
    return privat, offentlig


VARSEL = bygg(
    dict(kind="restock", store_name="Mythic", store_id="mythic",
         set_label="Prismatic Evolutions", type_label="Booster Bundle",
         region="en", price_ore=139900, url="https://mythic.no/x",
         product_id="prismatic-evolutions:bundle:en"),
    dict(billigst_na_ore=139900, billigst_butikk="Mythic",
         billigst_7d_ore=139900, antall_pa_lager=3))


def test_varselet_kan_dekrypteres_av_mottakeren(pushtjeneste, abonnement, nokler):
    klient, p256dh, auth = abonnement
    ok, feil, status = sender.send(
        {"endpoint": pushtjeneste, "p256dh": p256dh, "auth": auth}, VARSEL)
    assert ok, feil
    assert status == 201

    import http_ece
    klartekst = http_ece.decrypt(
        _Falsk.mottatt["kropp"],
        private_key=klient,
        auth_secret=base64.urlsafe_b64decode(auth + "=="),
    )
    d = json.loads(klartekst)
    assert d["title"] == "🛒 Nå inne hos Mythic"
    assert "Prismatic Evolutions · Booster Bundle" in d["body"]
    # Lenken ma gaa til butikken. Gaar den til oss, har brukeren tapt de
    # sekundene varselet skulle spare dem for.
    assert d["url"] == "https://mythic.no/x"
    assert d["hastig"] is True


def test_riktige_headere(pushtjeneste, abonnement, nokler):
    _, p256dh, auth = abonnement
    sender.send({"endpoint": pushtjeneste, "p256dh": p256dh, "auth": auth}, VARSEL)
    h = _Falsk.mottatt["headers"]
    assert h["content-encoding"] == "aes128gcm"
    # TTL 1800: en restock-beskjed som leveres fire timer senere er verre
    # enn ingen -- du gaar til butikken og varen er borte igjen.
    assert h["ttl"] == "1800"
    assert h["urgency"] == "high"
    assert h["authorization"].startswith("vapid t=")


def test_prisendring_er_ikke_hastig(pushtjeneste, abonnement, nokler):
    varsel = bygg(
        dict(kind="prisendring", store_name="Outland", store_id="outland",
             set_label="Pitch Black", type_label="Booster Box", region="en",
             price_ore=239900, prev_price_ore=289900, url="https://outland.no/x",
             product_id="pitch-black:booster-box:en"),
        dict(billigst_na_ore=239900, billigst_butikk="Outland",
             billigst_7d_ore=239900, antall_pa_lager=2))
    sender.send({"endpoint": pushtjeneste, "p256dh": abonnement[1],
                 "auth": abonnement[2]}, varsel)
    assert _Falsk.mottatt["headers"]["urgency"] == "normal"


def test_uten_nokler_kaster_tydelig(monkeypatch, pushtjeneste, abonnement):
    monkeypatch.delenv("POKEPULS_VAPID_PRIVATE", raising=False)
    monkeypatch.delenv("POKEPULS_VAPID_PUBLIC", raising=False)
    with pytest.raises(sender.IkkeKonfigurert):
        sender.send({"endpoint": pushtjeneste, "p256dh": abonnement[1],
                     "auth": abonnement[2]}, VARSEL)


def test_404_regnes_som_dod_enhet():
    # 404/410 = abonnementet finnes ikke lenger, og enheten skal slettes.
    # 500 = pushtjenesten har hikke, eller telefonen er av. Da skal den IKKE
    # slettes -- ellers mister brukeren varslene sine av en forbigaaende feil.
    assert sender.er_dod(404) and sender.er_dod(410)
    assert not sender.er_dod(500) and not sender.er_dod(None)
