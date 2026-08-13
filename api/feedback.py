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

import hashlib
import os
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


class AapenMelding(BaseModel):
    tekst: str = Field(min_length=10, max_length=4000)
    # Valgfri. Krever vi e-post, faar vi bare falske adresser -- og den som
    # bare vil si fra om en feil trenger ikke svar.
    epost: str | None = Field(default=None, max_length=200)
    # Honningkrukke. Skjult for mennesker, fristende for roboter.
    nettsted: str | None = Field(default=None, max_length=200)


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

    # ------------------------------------------------------------ aapent
    #
    # Kontaktskjema UTEN innlogging.
    #
    # Feedback-skjemaet over krever konto, og det er riktig for det det er:
    # nesten null soppel, og alltid en adresse aa svare paa. Men en tjeneste
    # som tar betalt maa ha en vei inn for folk som IKKE har konto -- den som
    # vurderer aa lage en, den som ikke kommer inn, den som vil klage.
    #
    # Prisen er soppel. Tre ting mot det, ingen av dem en CAPTCHA:
    #   1. Honningkrukke: et felt mennesker ikke ser og roboter fyller ut.
    #      Er det fylt, later vi som alt gikk bra og kaster meldingen.
    #   2. Bremsekloss per avsender, flyktig og saltet -- samme mekanisme som
    #      i api/bruk.py.
    #   3. E-post er valgfritt. Krever vi det, faar vi bare falske adresser.
    _aapne: dict[str, list[float]] = {}
    _AAPEN_SALT = os.urandom(16)

    @router.post("/apen")
    async def apen(data: AapenMelding, request: Request):
        if data.nettsted:
            # Honningkrukka. Svar 200 -- en robot som faar vite at den ble
            # avslort, prover paa nytt med et annet triks.
            return {"ok": True}

        raa = request.client.host if request.client else "?"
        nokkel = hashlib.blake2b(raa.encode(), key=_AAPEN_SALT, digest_size=8).hexdigest()
        na = time.time()
        tider = [t for t in _aapne.get(nokkel, []) if na - t < 3600]
        if len(tider) >= 3:
            raise HTTPException(429, "Du har sendt noen meldinger nå. Prøv igjen om en time.")
        tider.append(na)
        _aapne[nokkel] = tider

        pool = hent_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO feedback (user_id, epost, tekst, slag, side, user_agent) "
                "VALUES (NULL, %s, %s, 'annet', 'kontakt', %s) RETURNING id",
                (data.epost, data.tekst.strip(),
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
