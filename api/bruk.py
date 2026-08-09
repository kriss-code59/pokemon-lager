"""Sidevisninger og hvor mange som har installert.

Det eneste spoersmaalet dette finnes for: VIRKER DET AA BE FOLK INSTALLERE?
Installasjonsveiledningen i app.js koster plass og oppmerksomhet. Uten et
tall er det umulig aa vite om den gjor nytte eller bare staar i veien.

HVA VI IKKE GJOR

Ingen IP, ingen bruker-id, ingen informasjonskapsel, ingen enhets-id, ingen
referrer, ingen user agent, ingen klokkeslett finere enn dagen. Se
db/006_bruk.sql -- det finnes ikke en kolonne aa legge slikt i. Det er
bevisst: personvernerklaeringen lover «ingen sporing», og et loefte som
bare holdes av at koden over er velmenende, holder ikke saerlig lenge.

DERFOR ER DETTE VANSKELIGERE ENN DET SER UT

Endepunktet er aapent -- det maa det vaere, siden det skal telle folk som
ikke har konto. Et aapent endepunkt som oeker et tall er en invitasjon.
To ting stopper det verste:

1. `side` HVITLISTES. Ukjente verdier blir «annet» i stedet for aa bli
   avvist. Da kan ingen fylle disken med tilfeldige strenger, og en eldre
   klient som sender noe vi ikke kjenner igjen, mister ikke tellingen sin.
2. En FLYKTIG bremsekloss per avsender. Den lever i minnet, noekkelen er
   saltet med et tilfeldig tall som lages paa nytt ved hver oppstart, og
   ingenting av det naar disken. Den kan altsaa ikke kobles til noe som
   helst, og doer med prosessen. Det er ikke sporing; det er den samme
   mekanismen som allerede bremser passordgjetting i api/auth.py.

Og vaer aerlig om hva tallet er verdt: det kan fortsatt blaases opp av noen
som vil. Les det som en trend, ikke som en fasit.
"""
from __future__ import annotations

import hashlib
import secrets
import time

from fastapi import APIRouter, Cookie, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(tags=["bruk"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

# Sidene vi kjenner. Alt annet blir «annet» -- se modulteksten over.
SIDER = {"hjem", "produkt", "personvern", "nytt-passord", "admin"}

# Maks 20 meldinger per avsender per time. Frontenden sender ÉN per
# fane-oekt, saa 20 er rikelig for et menneske med mange faner og trangt for
# et skript. Med to uvicorn-arbeidere er den effektive grensen 40; det er
# godt nok til formaalet, og aa dele tellerverket mellom prosesser ville
# krevd lagring vi nettopp har lovet aa ikke ha.
MAKS_PER_TIME = 20
VINDU = 3600

# Saltet lages ved import og forlater aldri prosessen. Uten det ville
# noekkelen vaert en hash av IP-en -- altsaa en pseudonymisert IP, som
# fortsatt er en personopplysning. Med saltet er den et tall uten mening
# utenfor denne prosessens levetid.
_SALT = secrets.token_bytes(16)
_sett: dict[str, list[float]] = {}


class Bruk(BaseModel):
    side: str = Field(default="hjem", max_length=40)
    standalone: bool = False


def _noekkel(request: Request) -> str:
    raa = request.client.host if request.client else "?"
    return hashlib.blake2b(raa.encode(), key=_SALT, digest_size=8).hexdigest()


def _for_ofte(request: Request) -> bool:
    na = time.time()
    n = _noekkel(request)
    tider = [t for t in _sett.get(n, []) if na - t < VINDU]
    if len(tider) >= MAKS_PER_TIME:
        return True
    tider.append(na)
    _sett[n] = tider
    # Rydd bort avsendere som ikke har vaert her paa en time. Uten dette
    # vokser ordboka i det uendelige i en prosess som lever i ukevis.
    if len(_sett) > 5000:
        for k in [k for k, v in _sett.items() if not v or na - v[-1] > VINDU]:
            _sett.pop(k, None)
    return False


def monter(app, hent_pool, krev_admin):

    @router.post("/api/bruk")
    async def meld(data: Bruk, request: Request):
        """Svarer alltid 204, ogsaa naar vi ikke teller.

        En teller skal ikke kunne fortelle den som spoer noe som helst --
        verken at han er bremset, eller at databasen er nede. Og den skal
        ALDRI vaere grunnen til at noen ser en feil i konsollen paa en side
        som ellers virker.
        """
        if _for_ofte(request):
            return Response(status_code=204)
        side = data.side if data.side in SIDER else "annet"
        try:
            async with hent_pool().connection() as conn:
                await conn.execute(
                    "INSERT INTO sidevisninger (dag, side, standalone, antall) "
                    "VALUES (current_date, %s, %s, 1) "
                    "ON CONFLICT (dag, side, standalone) "
                    "DO UPDATE SET antall = sidevisninger.antall + 1",
                    (side, data.standalone))
        except Exception:
            pass      # en tapt telling er ikke verdt en feil hos brukeren
        return Response(status_code=204)

    @admin_router.get("/bruk")
    async def oversikt(pokepuls_sesjon: str | None = Cookie(None)):
        await krev_admin(pokepuls_sesjon)
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "SELECT dag, side, standalone, antall FROM sidevisninger "
                "WHERE dag > current_date - 30 ORDER BY dag DESC, side")
            rader = await cur.fetchall()
            # Andelen installert regnes over 30 dager samlet, ikke dag for
            # dag. Med liten trafikk er en dagsandel stoy: to iPhone-brukere
            # fra eller til flytter den ti prosentpoeng.
            cur = await conn.execute(
                "SELECT coalesce(sum(antall), 0) AS alle, "
                "       coalesce(sum(antall) FILTER (WHERE standalone), 0) AS installert "
                "FROM sidevisninger WHERE dag > current_date - 30")
            sum30 = await cur.fetchone()
        return {"rader": rader, "sum30": sum30}

    app.include_router(router)
    app.include_router(admin_router)
