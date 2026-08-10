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


class Grense(BaseModel):
    # None betyr «fjern grensen». 0 ville betydd «varsle aldri», og det er
    # ikke noe noen mener -- da slutter man aa folge i stedet.
    maks_pris_kr: int | None = Field(default=None, ge=1, le=1_000_000)


class Folg(BaseModel):
    product_id: str | None = None
    set_id: str | None = None
    kinds: list[str] = ["restock", "ny"]


class GlemtPassord(BaseModel):
    email: EmailStr


class NyttPassord(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class Token(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class SlettMeg(BaseModel):
    # Passordet kreves selv om brukeren er innlogget. En apen laptop skal
    # ikke vaere nok til aa slette kontoen til noen andre.
    password: str = Field(min_length=1, max_length=200)
    grunn: str | None = Field(default=None, max_length=500)


# Hvor lenge en engangslenke varer. Passord: kort, fordi den gir full
# tilgang til kontoen. E-postbekreftelse: lang, fordi den ikke gir noe
# annet enn et flagg, og folk leser e-post pa mandag.
PASSORD_TIMER = 1
EPOST_DOGN = 3


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
            "SELECT u.id, u.email, u.role, u.premium_until, u.created_at, "
            "       u.email_verified_at "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.expires_at > now()",
            (_hash_token(token),))
        return await cur.fetchone()


def er_premium(bruker) -> bool:
    """Én definisjon av premium, brukt overalt.

    `premium_until IS NULL` betyr ubegrenset -- det er slik en rolle satt
    for haand i admin ser ut. Stripe fyller feltet med sluttdatoen for
    perioden som er betalt.
    """
    if not bruker or bruker["role"] not in ("premium", "admin"):
        return False
    til = bruker.get("premium_until")
    return til is None or til > datetime.now(timezone.utc)


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
                "premium_until": bruker["premium_until"],
                "epost_bekreftet": bruker["email_verified_at"] is not None}

    # ----------------------------------------------------------- folgeliste

    @liste_router.get("")
    async def liste(pokepuls_sesjon: str | None = Cookie(None)):
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT s.id, s.product_id, s.set_id, s.kinds, s.fast_lane, "
                "       s.maks_pris_ore, "
                "       se.label AS set_label, t.label AS type_label, p.region "
                "FROM subscriptions s "
                "LEFT JOIN products p ON p.id = s.product_id "
                "LEFT JOIN sets se ON se.id = COALESCE(p.set_id, s.set_id) "
                "LEFT JOIN product_types t ON t.id = p.type_id "
                "WHERE s.user_id = %s ORDER BY se.label, t.sort_order",
                (bruker["id"],))
            rader = await cur.fetchall()
            cur = await conn.execute(
                "SELECT varsel_maks_per_time FROM users WHERE id = %s", (bruker["id"],))
            kvote = await cur.fetchone()
        # «alt» er raden uten baade product_id og set_id. Den kunne frontenden
        # regnet ut selv, men da ville regelen for hva «alt» er ligget to
        # steder, og det er nettopp den typen duplisering som glir fra
        # hverandre. Kvoten sendes med fordi knappen lover et konkret tall --
        # staar det 5 i teksten mens brukeren har 12, er teksten en logn.
        return {"folger": rader,
                "alt": any(r["product_id"] is None and r["set_id"] is None for r in rader),
                "maks_per_time": kvote["varsel_maks_per_time"] if kvote else 5,
                "premium": er_premium(bruker)}

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

    # MAA staa FOR /{abonnement_id}. FastAPI matcher i den rekkefolgen
    # rutene er deklarert, og "alt" ville ellers blitt forsokt tolket som
    # et tall og gitt 422.
    @liste_router.post("/alt")
    async def folg_alt(pokepuls_sesjon: str | None = Cookie(None)):
        """Foelg hele katalogen.

        Lagres som EN rad med baade product_id og set_id NULL, ikke som
        3 900 rader. Ellers ville en enkelt bruker fylt tabellen, og
        avfoelging blitt en sletting av tusenvis av rader.

        Dempingen skjer i varslingsloypa, ikke her: se
        overvak/varsler.py. Uten den ville dette gitt 300-500 varsler i
        doegnet, og du hadde skrudd av varsler samme kveld.
        """
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO subscriptions (user_id, product_id, set_id, kinds) "
                "VALUES (%s, NULL, NULL, %s) "
                "ON CONFLICT (user_id) WHERE product_id IS NULL AND set_id IS NULL "
                "DO UPDATE SET kinds = EXCLUDED.kinds RETURNING id",
                (bruker["id"], ["restock", "ny"]))
            return {"id": (await cur.fetchone())["id"], "paa": True}

    @liste_router.delete("/alt")
    async def slutt_folg_alt(pokepuls_sesjon: str | None = Cookie(None)):
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        async with pool.connection() as conn:
            await conn.execute(
                "DELETE FROM subscriptions WHERE user_id = %s "
                "AND product_id IS NULL AND set_id IS NULL", (bruker["id"],))
        # Ikke 404 hvis den ikke fantes: aa skru av noe som allerede er av
        # er ikke en feil, og knappen skal ikke kunne komme ut av synk.
        return {"ok": True, "paa": False}

    @liste_router.post("/{abonnement_id}/grense")
    async def sett_grense(abonnement_id: int, data: Grense,
                          pokepuls_sesjon: str | None = Cookie(None)):
        """«Varsle bare naar den er under X kr» -- per vare.

        Premium. Den globale grensen i /api/push/innstillinger er fortsatt
        gratis; den gjelder hele kontoen og er nesten ubrukelig naar du
        foelger baade boosterpakker til 119 og bokser til 6 000.

        Serveren avviser, ikke bare grensesnittet. En knapp som er skjult er
        ikke en sperre -- endepunktet er aapent for hvem som helst med en
        terminal.
        """
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        if not er_premium(bruker):
            raise HTTPException(
                402, "Prisgrense per vare er en premium-funksjon.")
        ore = data.maks_pris_kr * 100 if data.maks_pris_kr else None
        async with pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE subscriptions SET maks_pris_ore = %s "
                "WHERE id = %s AND user_id = %s RETURNING id",
                (ore, abonnement_id, bruker["id"]))
            if not await cur.fetchone():
                raise HTTPException(404, "Fant ikke abonnementet")
        return {"ok": True, "maks_pris_ore": ore}

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

    # ------------------------------------------------- glemt passord m.m.

    async def _lag_token(pool, bruker_id, kind: str, levetid) -> str:
        token = secrets.token_urlsafe(32)
        async with pool.connection() as conn:
            # Bare én gyldig lenke av hver type om gangen. Ber noen om nytt
            # passord tre ganger, skal ikke alle tre lenkene virke.
            await conn.execute(
                "DELETE FROM engangstokener WHERE user_id = %s AND kind = %s",
                (bruker_id, kind))
            await conn.execute(
                "INSERT INTO engangstokener (token_hash, user_id, kind, expires_at) "
                "VALUES (%s, %s, %s, %s)",
                (_hash_token(token), bruker_id, kind,
                 datetime.now(timezone.utc) + levetid))
        return token

    async def _bruk_token(pool, token: str, kind: str):
        """-> user_id, og merker tokenet som brukt. None hvis ugyldig."""
        async with pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE engangstokener SET brukt_at = now() "
                "WHERE token_hash = %s AND kind = %s AND brukt_at IS NULL "
                "  AND expires_at > now() RETURNING user_id",
                (_hash_token(token), kind))
            rad = await cur.fetchone()
        return rad["user_id"] if rad else None

    @router.post("/glemt")
    async def glemt(data: GlemtPassord, request: Request):
        """Sender en lenke for nytt passord.

        Svarer ALLTID det samme, uansett om adressen finnes. Alt annet gjor
        endepunktet til en liste over hvem som har konto her -- og for et
        Pokemon-nettsted er den listen ikke uinteressant for noen som vil
        gjette passord.
        """
        from varsling import epost as epost_modul

        _bank_pa("glemt:" + (request.client.host if request.client else "?"))
        e_post = data.email.strip().lower()
        pool = hent_pool()
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT id FROM users WHERE email = %s", (e_post,))
            bruker = await cur.fetchone()

        if bruker:
            if not epost_modul.er_satt_opp():
                raise HTTPException(
                    503, "E-post er ikke satt opp på serveren ennå. "
                         "Ta kontakt på norgekriss@gmail.com.")
            token = await _lag_token(pool, bruker["id"], "passord",
                                     timedelta(hours=PASSORD_TIMER))
            ok, feil = epost_modul.send_passordlenke(
                e_post, f"https://pokepuls.no/nytt-passord.html?t={token}")
            if not ok:
                # Loggen skal si hva som gikk galt; brukeren skal ikke faa
                # vite om adressen finnes.
                print(f"[glemt] klarte ikke sende til {e_post}: {feil}")

        return {"ok": True, "melding":
                "Finnes det en konto med denne adressen, er lenken sendt."}

    @router.post("/nytt-passord")
    async def nytt_passord(data: NyttPassord, request: Request, svar: Response):
        _bank_pa("nytt:" + (request.client.host if request.client else "?"))
        pool = hent_pool()
        bruker_id = await _bruk_token(pool, data.token, "passord")
        if not bruker_id:
            raise HTTPException(400, "Lenken er brukt opp eller utløpt. Be om en ny.")
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE users SET password_hash = %s, email_verified_at = "
                "COALESCE(email_verified_at, now()) WHERE id = %s",
                (_hasher.hash(data.password), bruker_id))
            # Alle andre sesjoner ryker. Var kontoen kapret, kastes tyven ut
            # i det du setter nytt passord -- ellers sitter de igjen med en
            # gyldig cookie i 90 dager.
            await conn.execute("DELETE FROM sessions WHERE user_id = %s", (bruker_id,))
            cur = await conn.execute("SELECT email, role FROM users WHERE id = %s",
                                     (bruker_id,))
            bruker = await cur.fetchone()
        await _ny_sesjon(pool, bruker_id, svar, request)
        return {"email": bruker["email"], "role": bruker["role"]}

    @router.post("/send-verifisering")
    async def send_verifisering(pokepuls_sesjon: str | None = Cookie(None)):
        from varsling import epost as epost_modul

        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        if not epost_modul.er_satt_opp():
            raise HTTPException(503, "E-post er ikke satt opp på serveren ennå.")
        token = await _lag_token(pool, bruker["id"], "epost", timedelta(days=EPOST_DOGN))
        ok, feil = epost_modul.send_verifisering(
            bruker["email"], f"https://pokepuls.no/?verifiser={token}")
        if not ok:
            raise HTTPException(502, f"Klarte ikke sende: {feil}")
        return {"ok": True}

    @router.post("/verifiser")
    async def verifiser(data: Token):
        pool = hent_pool()
        bruker_id = await _bruk_token(pool, data.token, "epost")
        if not bruker_id:
            raise HTTPException(400, "Lenken er brukt opp eller utløpt.")
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE users SET email_verified_at = now() WHERE id = %s", (bruker_id,))
        return {"ok": True}

    @router.post("/slett-meg")
    async def slett_meg(data: SlettMeg, svar: Response,
                        pokepuls_sesjon: str | None = Cookie(None)):
        """Brukeren sletter seg selv. Ekte sletting, ikke et flagg.

        Alt henger pa users.id med ON DELETE CASCADE: sesjoner, folgeliste,
        push-enheter, sendte varsler og engangstokener forsvinner i samme
        setning. Feedback beholdes, men uten kobling til personen (SET NULL).
        """
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT password_hash FROM users WHERE id = %s",
                                     (bruker["id"],))
            rad = await cur.fetchone()
        try:
            _hasher.verify(rad["password_hash"], data.password)
        except (VerifyMismatchError, VerificationError):
            raise HTTPException(401, "Feil passord.")

        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT (SELECT count(*) FROM subscriptions WHERE user_id = %s) AS folgt, "
                "       EXTRACT(DAY FROM now() - created_at)::int AS dager "
                "FROM users WHERE id = %s", (bruker["id"], bruker["id"]))
            tall = await cur.fetchone()
            # Anonym statistikk, sa du kan se OM folk slutter uten a vite hvem.
            await conn.execute(
                "INSERT INTO slettede_kontoer (grunn, dager_aktiv, antall_fulgt) "
                "VALUES (%s, %s, %s)", (data.grunn, tall["dager"], tall["folgt"]))
            await conn.execute("UPDATE feedback SET user_id = NULL WHERE user_id = %s",
                               (bruker["id"],))
            await conn.execute("DELETE FROM users WHERE id = %s", (bruker["id"],))
        svar.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    app.include_router(router)
    app.include_router(liste_router)
