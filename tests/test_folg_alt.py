"""«Foelg alt» med demping.

Testene her er paa de rene funksjonene -- samletekst() og kort_navn() --
fordi det er de som lager det brukeren faktisk leser. Kvotelogikken selv
er SQL og testes mot databasen i test_varsler_db.py der den finnes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from overvak.varsler import kort_navn, samletekst


def test_kort_navn_tar_produktlinjen():
    # Kroppen er "produkt\npris - vurdering". I en samleliste er det bare
    # produktnavnet som gir mening; pris og butikk varierer per rad.
    v = {"body": "Prismatic Evolutions · Booster Bundle\n1 399 kr — billigst"}
    assert kort_navn(v) == "Prismatic Evolutions · Booster Bundle"


def test_kort_navn_taaler_tom_kropp():
    assert kort_navn({}) == ""
    assert kort_navn({"body": ""}) == ""


def test_kort_navn_kortes_av():
    v = {"body": "A" * 200 + "\nnoe"}
    assert len(kort_navn(v)) == 60


def test_samletekst_har_antallet_i_tittelen():
    # Tallet er det som avgjor om du apner Pokepuls na eller etter middag.
    d = samletekst(14, ["Vare A", "Vare B", "Vare C", "Vare D"])
    assert d["title"] == "🛒 14 flere varer kom inn"


def test_samletekst_viser_tre_navn_og_teller_resten():
    d = samletekst(14, ["Vare A", "Vare B", "Vare C", "Vare D", "Vare E"])
    assert "Vare A" in d["body"] and "Vare C" in d["body"]
    assert "Vare D" not in d["body"]
    assert "og 11 til" in d["body"]


def test_samletekst_uten_hale_naar_alt_vises():
    d = samletekst(2, ["Vare A", "Vare B"])
    assert "og" not in d["body"].split("·")[-1]


def test_samletekst_taaler_at_navnene_mangler():
    d = samletekst(9, [])
    assert d["body"] == "Se alle på pokepuls.no"
    assert "9" in d["title"]


def test_samlevarsel_haster_ikke():
    # Et sammendrag skal ikke vibrere telefonen. Hadde det hastet, ville
    # det vaert sendt enkeltvis i stedet for dempet.
    assert samletekst(20, ["x"])["hastig"] is False


def test_samlevarsel_erstatter_seg_selv():
    # Fast tag: neste times sammendrag skal bytte ut det forrige, ikke
    # stable seg opp i varslingssenteret.
    assert samletekst(3, ["a"])["tag"] == samletekst(9, ["b"])["tag"]


def test_samlevarsel_peker_til_pokepuls_ikke_butikken():
    # Enkeltvarsler gaar rett til butikken fordi sekunder teller. Et
    # sammendrag har ingen enkelt butikk aa peke paa.
    assert samletekst(5, ["a"])["url"] == "https://pokepuls.no/"


# --------------------------------------------------------------- API-svaret
#
# Knappen i grensesnittet lover et konkret tall («maks 5 varsler i timen»)
# og en konkret tilstand (paa/av). Begge kommer fra GET /api/watchlist. Er
# de feil, staar det en knapp der og lyver -- og en knapp som lyver om
# varsler er verre enn ingen knapp. Derfor testes svarformen her, mot en
# falsk pool: poenget er kontrakten mot frontenden, ikke SQL-en.

import asyncio

import pytest

fastapi = pytest.importorskip("fastapi")


class _Cursor:
    def __init__(self, rader):
        self._rader = rader

    async def fetchall(self):
        return self._rader

    async def fetchone(self):
        return self._rader[0] if self._rader else None


class _Conn:
    """Svarer ut fra hva som staar i sporringen. Grovt, men nok: de tre
    sporringene ruta gjor er lette a skille pa."""

    def __init__(self, bruker, abonnementer, maks):
        self.bruker, self.abonnementer, self.maks = bruker, abonnementer, maks

    async def execute(self, sql, params=None):
        if "FROM sessions s" in sql:
            return _Cursor([self.bruker] if self.bruker else [])
        if "varsel_maks_per_time" in sql:
            return _Cursor([{"varsel_maks_per_time": self.maks}])
        if "FROM subscriptions s" in sql:
            return _Cursor(self.abonnementer)
        return _Cursor([])


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


def _liste(abonnementer, maks=5):
    from fastapi import FastAPI

    from api import auth

    app = FastAPI()
    auth.monter(app, lambda: _Pool(_Conn(
        {"id": "u1", "email": "k@example.no", "role": "free",
         "premium_until": None, "created_at": None, "email_verified_at": None},
        abonnementer, maks)))
    # Rutene hentes fra routeren, ikke fra app.routes: FastAPI pakker
    # inkluderte routere i _IncludedRouter, og der finnes ingen .path.
    # Siste treff, fordi monter() dekorerer den samme modulglobale routeren
    # paa nytt for hvert kall -- det er den ferskeste lukkingen vi vil ha.
    rute = [r for r in auth.liste_router.routes
            if getattr(r, "path", "") == "/api/watchlist" and "GET" in r.methods][-1]
    return asyncio.run(rute.endpoint(pokepuls_sesjon="sesjon"))


ENKELT = {"id": 7, "product_id": "pitch-black:booster-box:en", "set_id": None}
ALT = {"id": 9, "product_id": None, "set_id": None}


def test_alt_er_false_naar_du_bare_folger_enkeltvarer():
    assert _liste([ENKELT])["alt"] is False


def test_alt_er_true_naar_raden_uten_baade_produkt_og_sett_finnes():
    assert _liste([ENKELT, ALT])["alt"] is True


def test_et_sett_alene_er_ikke_alt():
    # Regresjon som ville vaert lett a lage: «ingen product_id» er ikke det
    # samme som «alt». Foelger du ett sett, skal knappen staa av.
    assert _liste([{"id": 4, "product_id": None, "set_id": "pitch-black"}])["alt"] is False


def test_kvoten_kommer_fra_brukeren_ikke_fra_en_konstant():
    assert _liste([], maks=12)["maks_per_time"] == 12


def test_folgelisten_er_uendret():
    # Nye felt skal ikke ha flyttet paa det som allerede virket.
    assert _liste([ENKELT])["folger"] == [ENKELT]
