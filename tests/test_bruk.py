"""Sidevisninger.

Det som testes her er ikke at et tall gaar opp. Det er de tre egenskapene
som gjor at endepunktet kan staa aapent paa internett uten tilsyn:

1. Radantallet er bundet -- `side` hvitlistes, saa ingen kan fylle disken
   med tilfeldige strenger.
2. Det lekker ingenting -- svaret er alltid 204, uansett hva som skjedde.
3. Det velter aldri siden -- en database som er nede skal gi en tapt
   telling, ikke en feil i konsollen hos brukeren.

Pluss den ene som er lett aa miste i en refaktorering, og som ville gjort
hele funksjonen til et loftebrudd: at INSERT-en ikke har noe sted aa gjore
av en IP eller en bruker-id.
"""
import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402

from api import bruk  # noqa: E402

ROT = Path(__file__).resolve().parents[1]


class _Cursor:
    def __init__(self, rader):
        self._rader = rader

    async def fetchall(self):
        return self._rader

    async def fetchone(self):
        return self._rader[0] if self._rader else None


class _Conn:
    def __init__(self, kaster=False):
        self.kaster = kaster
        self.kall = []

    async def execute(self, sql, params=None):
        if self.kaster:
            raise RuntimeError("databasen er nede")
        self.kall.append((sql, params))
        return _Cursor([{"alle": 0, "installert": 0}])


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Ctx()


class _Klient:
    """Nok av en Request til at ruta kan kjores direkte."""

    def __init__(self, host="203.0.113.7"):
        self.client = type("K", (), {"host": host})()


def _meld(side="hjem", standalone=False, conn=None, host="203.0.113.7"):
    conn = conn or _Conn()
    app = FastAPI()
    bruk.monter(app, lambda: _Pool(conn), None)
    rute = [r for r in bruk.router.routes if getattr(r, "path", "") == "/api/bruk"][-1]
    svar = asyncio.run(rute.endpoint(
        bruk.Bruk(side=side, standalone=standalone), _Klient(host)))
    return svar, conn


@pytest.fixture(autouse=True)
def _nullstill():
    # Bremseklossen lever i modulen. Uten dette lekker tellinger mellom
    # tester, og den siste feiler av grunner som ikke er dens egne.
    bruk._sett.clear()
    yield
    bruk._sett.clear()


# ------------------------------------------------------------- hvitlisten

def test_kjent_side_lagres_som_seg_selv():
    _, conn = _meld(side="produkt")
    assert conn.kall[0][1][0] == "produkt"


def test_ukjent_side_blir_annet_i_stedet_for_aa_bli_avvist():
    # Avvisning ville betydd at en eldre klient mister tellingen sin i
    # stillhet. «annet» beholder den, og holder radantallet bundet.
    _, conn = _meld(side="../../etc/passwd")
    assert conn.kall[0][1][0] == "annet"


def test_alle_sider_i_hvitlisten_slipper_gjennom():
    for side in bruk.SIDER:
        _, conn = _meld(side=side)
        bruk._sett.clear()
        assert conn.kall[0][1][0] == side


# ---------------------------------------------------------------- lekkasje

def test_svarer_204_uten_kropp():
    svar, _ = _meld()
    assert svar.status_code == 204
    assert not svar.body


def test_bremset_avsender_faar_samme_svar_som_alle_andre():
    # Et endepunkt som sier «du er bremset» forteller den som prover at det
    # finnes en grense og omtrent hvor den gaar. Det skal se likt ut uansett.
    for _ in range(bruk.MAKS_PER_TIME):
        _meld()
    svar, conn = _meld()
    assert svar.status_code == 204
    assert conn.kall == [], "skal ikke ha skrevet noe"


def test_databasen_nede_gir_ikke_feil_til_brukeren():
    svar, _ = _meld(conn=_Conn(kaster=True))
    assert svar.status_code == 204


# ----------------------------------------------------------- bremseklossen

def test_grensen_gjelder_per_avsender_ikke_globalt():
    # Ellers kunne én person stoppet tellingen for alle andre.
    for _ in range(bruk.MAKS_PER_TIME):
        _meld(host="203.0.113.7")
    _, conn = _meld(host="198.51.100.3")
    assert conn.kall, "en annen avsender skal fortsatt telles"


def test_noekkelen_er_verken_ip_en_eller_en_naken_hash_av_den():
    # En usaltet hash av en IP er en pseudonymisert IP -- fortsatt en
    # personopplysning, og trivielt aa slaa opp med fire milliarder forsok.
    # Saltet lages ved import og doer med prosessen.
    import hashlib
    n = bruk._noekkel(_Klient("203.0.113.7"))
    assert "203.0.113.7" not in n
    assert n != hashlib.blake2b(b"203.0.113.7", digest_size=8).hexdigest()


# ------------------------------------------------------------ loftet i SQL

def test_insert_lagrer_bare_dag_side_standalone_og_antall():
    """Den viktigste testen i fila.

    Personvernerklaeringen lover «ingen sporing». Bryter noen det, skjer
    det ikke ved at noen lager en ny tabell -- det skjer ved at en kolonne
    sniker seg inn i denne ene INSERT-en.
    """
    _, conn = _meld()
    sql = " ".join(conn.kall[0][0].split())
    kolonner = re.search(r"sidevisninger \(([^)]*)\)", sql).group(1)
    assert [k.strip() for k in kolonner.split(",")] == \
        ["dag", "side", "standalone", "antall"]
    for forbudt in ["ip", "user_id", "bruker", "user_agent", "referrer", "session"]:
        assert forbudt not in sql.lower(), f"{forbudt} har ingenting her aa gjore"


def test_migrasjonen_har_ingen_kolonne_aa_spore_med():
    sql = (ROT / "db" / "006_bruk.sql").read_text(encoding="utf-8").lower()
    kropp = sql.split("create table")[1].split(";")[0]
    for forbudt in ["inet", "user_id", "uuid", "user_agent", "referrer",
                    "timestamp", "timestamptz"]:
        assert forbudt not in kropp, \
            f"{forbudt} i sidevisninger ville gjort dette til sporing"


def test_migrasjonen_kjores_av_oppsettet():
    """Regresjon mot en felle som bare smeller i produksjon.

    Fram til 005 sto hver migrasjon oppfort for hand i oppsett-api.sh. Blir
    en glemt, deployer koden fint og endepunktet gir 500 fordi tabellen
    ikke finnes -- og testene her sier ingenting, for de kjorer aldri mot
    en ekte database.
    """
    skript = (ROT / "deploy" / "oppsett-api.sh").read_text(encoding="utf-8")
    assert "db/*.sql" in skript, \
        "oppsettet maa kjore alle migrasjoner, ikke en handskrevet liste"
