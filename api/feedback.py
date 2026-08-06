"""Tilbakemeldinger fra brukere.

Kun innloggede kan skrive. Det koster oss de mest spontane tilbake-
meldingene, og gir til gjengjeld to ting som betyr mer naar man er alene om
a drifte noe: nesten null soppel, og en adresse a svare paa.

Merk at teksten aldri tolkes som noe annet enn tekst. Den vises i admin-
siden med esc() rundt seg, og den havner aldri i en SQL-streng. En bruker
som skriver `<script>` i feedbacken skal se `<script>` i admin, ikke kjore
det i nettleseren din -- du er tross alt den ene personen paa siden som er
verdt a angripe.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Cookie, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

SLAG = {"feil", "onske", "butikk", "annet"}

# Maks 5 tilbakemeldinger per bruker per time. Ikke for aa stoppe misbruk --
# innlogging gjor det -- men for aa stoppe en knapp som sender ti ganger
# fordi noen dobbelttrykket paa daarlig nett.
MAKS_PER_TIME = 5
_sendt: dict[str, list[float]] = {}


class Melding(BaseModel):
    tekst: str = Field(min_length=3, max_length=4000)
    slag: str = Field(default="annet")
    side: str | None = Field(default=None, max_length=200)


def monter(app, hent_pool, hent_bruker):

    @router.post("")
    async def send(data: Melding, request: Request,
                   pokepuls_sesjon: str | None = Cookie(None)):
        pool = hent_pool()
        bruker = await hent_bruker(pool, pokepuls_sesjon)
        if not bruker:
            raise HTTPException(401, "Logg inn for å sende tilbakemelding.")

        na = time.time()
        nokkel = str(bruker["id"])
        tider = [t for t in _sendt.get(nokkel, []) if na - t < 3600]
        if len(tider) >= MAKS_PER_TIME:
            raise HTTPException(429, "Du har sendt en del nå. Prøv igjen om en time.")
        tider.append(na)
        _sendt[nokkel] = tider

        slag = data.slag if data.slag in SLAG else "annet"
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO feedback (user_id, epost, tekst, slag, side, user_agent) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (bruker["id"], bruker["email"], data.tekst.strip(), slag, data.side,
                 (request.headers.get("user-agent") or "")[:300]))
            return {"ok": True, "id": (await cur.fetchone())["id"]}

    @router.get("/mine")
    async def mine(pokepuls_sesjon: str | None = Cookie(None)):
        """Brukerens egne meldinger, med status. Aa se at noe er merket
        «gjort» er den eneste grunnen til at noen sender nummer to."""
        pool = hent_pool()
        bruker = await hent_bruker(pool, pokepuls_sesjon)
        if not bruker:
            raise HTTPException(401, "Ikke innlogget")
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, tekst, slag, status, created_at FROM feedback "
                "WHERE user_id = %s ORDER BY created_at DESC LIMIT 20",
                (bruker["id"],))
            return {"meldinger": await cur.fetchall()}

    app.include_router(router)
