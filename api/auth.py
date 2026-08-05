"""Kontoer, sesjoner og folgeliste.

Designvalg det er verdt a vite om:

* **Passord hashes med argon2id.** Ikke bcrypt, ikke sha256+salt. Argon2 er
  minneharde, som er det eneste som faktisk gjor GPU-knekking dyrt.
* **Sesjonstokenet lagres aldri.** Databasen har bare sha256 av det. Lekker
  `sessions`-tabellen, kan ingen logge inn med innholdet.
* **Cookie, ikke JWT i localStorage.** HttpOnly gjor at et XSS-hull ikke
  kan lese tokenet, og SameSite=Lax stopper CSRF for alt annet enn GET.
* **E-postverifisering er ikke pa enna.** `users.email_verified_at` finnes
  og fylles den dagen vi har en avsendertjeneste; ingenting annet ma
  skrives om for a sla det pa.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

router = APIRouter(prefix="/api/auth", tags=["auth"])
liste_router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

COOKIE = "pokepuls_sesjon"
SESJON_DAGER = 90

# Standardparametrene til argon2-cffi er fornuftige i 2026 og bevisst ikke
# senket: en innlogging skal koste noe.
_hasher = PasswordHasher()

# Enkel bremsekloss mot passordgjetting. Holder i minnet med vilje -- vi har
# én API-prosessgruppe, og et tapt tellerverk ved omstart er ufarlig.
_forsok: dict[str, list[float]] = {}
MAKS_FORSOK = 8
VINDU_SEKUNDER = 300


def _bank_pa(nokkel: str) -> None:
    na = time.time()
    tider = [t for t in _forsok.get(nokkel, []) if na - t < VINDU_SEKUNDER]
    if len(tider) >= MAKS_FORSOK:
        raise HTTPException(429, "For mange forsok. Vent noen minutter.")
    tider.append(na)
    _forsok[nokkel] = tider


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Registrering(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class Innlogging(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class Folg(BaseModel):
    product_id: str | None = None
    set_id: str | None = None
    kinds: list[str] = ["restock", "ny"]


# Modellene ma ligge pa modulniva. Defineres de inne i monter(), far
# `from __future__ import annotations` pydantic til a se en ForwardRef den
# ikke kan slaa opp, og hele OpenAPI-genereringen faller.
GYLDIGE_HENDELSER = {"ny", "restock", "utsolgt", "prisendring"}


def _sett_cookie(svar: Response, token: str, sikker: bool) -> None:
    svar.set_cookie(
        COOKIE, token,
        max_age=SESJON_DAGER * 86400,
        httponly=True,
        samesite="lax",
        secure=sikker,
        path="/",
    )


def _sikker(request: Request) -> bool:
    """Secure-flagget ma vaere av pa http, ellers sender nettleseren aldri
    cookien og innlogging ser ut til a mislykkes uten feilmelding."""
    if request.headers.get("x-forwarded-proto") == "https":
        return True
    return request.url.scheme == "https"


async def _ny_sesjon(pool, bruker_id, svar: Response, request: Request) -> None:
    token = secrets.token_urlsafe(32)
    utloper = datetime.now(timezone.utc) + timedelta(days=SESJON_DAGER)
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
            (_hash_token(token), bruker_id, utloper))
    _sett_cookie(svar, token, _sikker(request))


async def hent_bruker(pool, token: str | None):
    """-> brukerrad eller None. Brukes bade av /me og av folgelisten."""
    if not token:
        return None
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT u.id, u.email, u.role, u.premium_until, u.created_at "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.expires_at > now()",
            (_hash_token(token),))
        return await cur.fetchone()


def _krev(bruker):
    if not bruker:
        raise HTTPException(401, "Ikke innlogget")
    return bruker


def monter(app, hent_pool):
    """Kobler rutene pa appen. `hent_pool` er en funksjon som gir tilkoblings-
    poolen -- den finnes ikke ved import, bare etter oppstart."""

    @router.post("/register")
    async def registrer(data: Registrering, request: Request, svar: Response):
        _bank_pa("reg:" + (request.client.host if request.client else "?"))
        pool = hent_pool()
        e_post = data.email.strip().lower()
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT 1 FROM users WHERE email = %s", (e_post,))
            if await cur.fetchone():
                raise HTTPException(409, "Det finnes allerede en konto med denne e-posten")
            cur = await conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
                (e_post, _hasher.hash(data.password)))
            bruker_id = (await cur.fetchone())["id"]
        await _ny_sesjon(pool, bruker_id, svar, request)
        return {"email": e_post, "role": "free"}

    @router.post("/login")
    async def logg_inn(data: Innlogging, request: Request, svar: Response):
        e_post = data.email.strip().lower()
        _bank_pa("inn:" + e_post)
        pool = hent_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, email, password_hash, role FROM users WHERE email = %s",
                (e_post,))
            bruker = await cur.fetchone()
        # Samme feilmelding uansett om det er e-posten eller passordet som er
        # feil: alt annet rapporterer hvilke adresser som finnes.
        if not bruker:
            raise HTTPException(401, "Feil e-post eller passord")
        try:
            _hasher.verify(bruker["password_hash"], data.password)
        except (VerifyMismatchError, VerificationError):
            raise HTTPException(401, "Feil e-post eller passord")

        if _hasher.check_needs_rehash(bruker["password_hash"]):
            async with pool.connection() as conn:
                await conn.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                                   (_hasher.hash(data.password), bruker["id"]))
        async with pool.connection() as conn:
            await conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s",
                               (bruker["id"],))
        await _ny_sesjon(pool, bruker["id"], svar, request)
        return {"email": bruker["email"], "role": bruker["role"]}

    @router.post("/logout")
    async def logg_ut(svar: Response, pokepuls_sesjon: str | None = Cookie(None)):
        if pokepuls_sesjon:
            async with hent_pool().connection() as conn:
                await conn.execute("DELETE FROM sessions WHERE token_hash = %s",
                                   (_hash_token(pokepuls_sesjon),))
        svar.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @router.get("/me")
    async def meg(pokepuls_sesjon: str | None = Cookie(None)):
        bruker = await hent_bruker(hent_pool(), pokepuls_sesjon)
        if not bruker:
            return {"innlogget": False}
        return {"innlogget": True, "email": bruker["email"], "role": bruker["role"],
                "premium_until": bruker["premium_until"]}

    # ----------------------------------------------------------- folgeliste

    @liste_router.get("")
    async def liste(pokepuls_sesjon: str | None = Cookie(None)):
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT s.id, s.product_id, s.set_id, s.kinds, s.fast_lane, "
                "       se.label AS set_label, t.label AS type_label, p.region "
                "FROM subscriptions s "
                "LEFT JOIN products p ON p.id = s.product_id "
                "LEFT JOIN sets se ON se.id = COALESCE(p.set_id, s.set_id) "
                "LEFT JOIN product_types t ON t.id = p.type_id "
                "WHERE s.user_id = %s ORDER BY se.label, t.sort_order",
                (bruker["id"],))
            return {"folger": await cur.fetchall()}

    @liste_router.post("")
    async def folg(data: Folg, pokepuls_sesjon: str | None = Cookie(None)):
        if not data.product_id and not data.set_id:
            raise HTTPException(400, "Oppgi product_id eller set_id")
        kinds = [k for k in data.kinds if k in GYLDIGE_HENDELSER] or ["restock", "ny"]
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id FROM subscriptions WHERE user_id = %s "
                "AND product_id IS NOT DISTINCT FROM %s AND set_id IS NOT DISTINCT FROM %s",
                (bruker["id"], data.product_id, data.set_id))
            finnes = await cur.fetchone()
            if finnes:
                await conn.execute("UPDATE subscriptions SET kinds = %s WHERE id = %s",
                                   (kinds, finnes["id"]))
                return {"id": finnes["id"], "oppdatert": True}
            cur = await conn.execute(
                "INSERT INTO subscriptions (user_id, product_id, set_id, kinds) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (bruker["id"], data.product_id, data.set_id, kinds))
            return {"id": (await cur.fetchone())["id"], "oppdatert": False}

    @liste_router.delete("/{abonnement_id}")
    async def slutt_a_folge(abonnement_id: int,
                            pokepuls_sesjon: str | None = Cookie(None)):
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        async with pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM subscriptions WHERE id = %s AND user_id = %s RETURNING id",
                (abonnement_id, bruker["id"]))
            if not await cur.fetchone():
                raise HTTPException(404, "Fant ikke abonnementet")
        return {"ok": True}

    @liste_router.get("/snapshot")
    async def folgeliste_snapshot(pokepuls_sesjon: str | None = Cookie(None)):
        """Produktene brukeren folger, med samme form som /api/snapshot slik at
        frontenden kan gjenbruke tegnekoden uten spesialtilfeller."""
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        from .main import SNAPSHOT_SQL  # noqa: WPS433 - unngar sirkulaer import
        sql = SNAPSHOT_SQL.replace(
            "WHERE l.last_seen_at > now() - interval '7 days'",
            "WHERE l.last_seen_at > now() - interval '7 days' AND (p.id IN ("
            "  SELECT product_id FROM subscriptions WHERE user_id = %s AND product_id IS NOT NULL"
            ") OR p.set_id IN ("
            "  SELECT set_id FROM subscriptions WHERE user_id = %s AND set_id IS NOT NULL))")
        async with pool.connection() as conn:
            cur = await conn.execute(sql, (bruker["id"], bruker["id"]))
            return {"produkter": await cur.fetchall(),
                    "felt": ["butikk", "pris_ore", "pa_lager"]}

    app.include_router(router)
    app.include_router(liste_router)
