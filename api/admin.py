"""Admin-endepunkter. Alt bak role='admin'.

Tre sporsmaal siden skal svare paa, og ingenting mer:

1. **Hvem er brukerne mine, og hva folger de?** Uten dette er den eneste
   maaten aa vite noe om brukerne aa kjore SQL over ssh.
2. **Virker driften?** Kjoringer, feilede butikker, varsler sendt. Dette er
   det dodmannsknappen aldri kunne vise: den sier "noe er galt", ikke "hva".
3. **Hva mangler i katalogen, og kan jeg fikse det herfra?** 1 800 umatchede
   varer er den storste enkeltmangelen i produktet. Aa koble dem har krevd
   at man redigerer katalog.json og deployer.

Ingen sletting av brukere her. Det er en irreversibel handling paa en annens
data, og den skal gjores bevisst med SQL, ikke med et uhell paa mobil.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/admin", tags=["admin"])

# To laser, ikke én.
#
# role='admin' i databasen er den vanlige. POKEPULS_ADMIN_EPOST er den andre:
# en liste over adresser som FAKTISK slipper inn, satt i /etc/pokepuls.env og
# utenfor databasens rekkevidde.
#
# Poenget er ikke at databasen er utrygg. Poenget er at en SQL-injeksjon, en
# feil i rolleknappen eller en tastefeil i en UPDATE ellers ville vaere nok
# til aa gi noen full innsikt i alle brukerne. Med to laser maa begge feile.
#
# Er variabelen tom, gjelder bare rollen -- da oppforer alt seg som for.
_ADMIN_EPOST = {e.strip().lower() for e in
                os.environ.get("POKEPULS_ADMIN_EPOST", "").split(",") if e.strip()}


class Kobling(BaseModel):
    title: str = Field(min_length=3, max_length=400)
    product_id: str = Field(min_length=3, max_length=200)


class Rolle(BaseModel):
    user_id: str
    role: str = Field(pattern="^(free|premium|admin)$")


class FeedbackStatus(BaseModel):
    status: str | None = Field(default=None, pattern="^(ny|lest|gjort|avvist)$")
    notat: str | None = Field(default=None, max_length=2000)


def monter(app, hent_pool, hent_bruker):
    async def _krev_admin(token):
        bruker = await hent_bruker(hent_pool(), token)
        if not bruker:
            raise HTTPException(401, "Ikke innlogget")
        # 404, ikke 403: en side som svarer "forbudt" bekrefter at den
        # finnes. Den skal ikke finnes for andre enn admin.
        if bruker["role"] != "admin":
            raise HTTPException(404, "Ikke funnet")
        if _ADMIN_EPOST and bruker["email"].lower() not in _ADMIN_EPOST:
            print(f"[admin] AVVIST: {bruker['email']} har role=admin i databasen, "
                  f"men staar ikke i POKEPULS_ADMIN_EPOST")
            raise HTTPException(404, "Ikke funnet")
        return bruker

    # ------------------------------------------------------------ brukere

    @router.get("/users")
    async def brukere(pokepuls_sesjon: str | None = Cookie(None)):
        await _krev_admin(pokepuls_sesjon)
        async with hent_pool().connection() as conn:
            cur = await conn.execute("""
                SELECT u.id, u.email, u.role, u.created_at, u.last_login_at,
                       u.email_verified_at, u.varsel_stille_natt,
                       (SELECT count(*) FROM subscriptions s WHERE s.user_id = u.id)
                         AS folger,
                       (SELECT count(*) FROM push_endpoints p WHERE p.user_id = u.id)
                         AS enheter,
                       (SELECT count(*) FROM notifications_sent n
                         WHERE n.user_id = u.id AND n.sendt_at > now() - interval '30 days')
                         AS varsler_30d
                FROM users u ORDER BY u.created_at DESC""")
            return {"brukere": await cur.fetchall()}

    @router.get("/users/{bruker_id}")
    async def bruker_detalj(bruker_id: str, pokepuls_sesjon: str | None = Cookie(None)):
        await _krev_admin(pokepuls_sesjon)
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "SELECT id, email, role, created_at, last_login_at, premium_until "
                "FROM users WHERE id = %s", (bruker_id,))
            u = await cur.fetchone()
            if not u:
                raise HTTPException(404, "Ukjent bruker")
            cur = await conn.execute("""
                SELECT s.id, s.product_id, s.set_id, s.kinds, s.created_at,
                       COALESCE(se.label, se2.label) AS set_label,
                       t.label AS type_label, p.region
                FROM subscriptions s
                LEFT JOIN products p       ON p.id  = s.product_id
                LEFT JOIN sets se          ON se.id = p.set_id
                LEFT JOIN sets se2         ON se2.id = s.set_id
                LEFT JOIN product_types t  ON t.id  = p.type_id
                WHERE s.user_id = %s ORDER BY s.created_at DESC""", (bruker_id,))
            folger = await cur.fetchall()
            cur = await conn.execute(
                "SELECT id, user_agent, created_at, last_ok_at, feil_pa_rad, sist_feil "
                "FROM push_endpoints WHERE user_id = %s", (bruker_id,))
            enheter = await cur.fetchall()
            cur = await conn.execute("""
                SELECT n.sendt_at, n.ok, n.feil, e.kind, e.store_id, e.price_ore,
                       e.product_id
                FROM notifications_sent n JOIN events e ON e.id = n.event_id
                WHERE n.user_id = %s ORDER BY n.sendt_at DESC LIMIT 50""", (bruker_id,))
            varsler = await cur.fetchall()
        return {"bruker": u, "folger": folger, "enheter": enheter, "varsler": varsler}

    @router.post("/role")
    async def sett_rolle(data: Rolle, pokepuls_sesjon: str | None = Cookie(None)):
        meg = await _krev_admin(pokepuls_sesjon)
        if str(meg["id"]) == data.user_id and data.role != "admin":
            # Aa fjerne sin egen admin-rolle laaser deg ute av siden du
            # nettopp brukte for aa gjore det.
            raise HTTPException(400, "Du kan ikke fjerne din egen admin-rolle herfra.")
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "UPDATE users SET role = %s WHERE id = %s RETURNING email, role",
                (data.role, data.user_id))
            rad = await cur.fetchone()
            if not rad:
                raise HTTPException(404, "Ukjent bruker")
        return rad

    # -------------------------------------------------------------- drift

    @router.get("/drift")
    async def drift(pokepuls_sesjon: str | None = Cookie(None)):
        await _krev_admin(pokepuls_sesjon)
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "SELECT id, started_at, finished_at, product_count, store_count, "
                "       failed_stores, carried_stores, ok, "
                "       EXTRACT(EPOCH FROM (finished_at - started_at))::int AS sekunder "
                "FROM scrape_runs ORDER BY started_at DESC LIMIT 40")
            kjoringer = await cur.fetchall()
            cur = await conn.execute("""
                SELECT s.id, s.name, s.active, s.manual_only,
                       count(l.id) AS oppforinger,
                       count(l.id) FILTER (WHERE l.in_stock) AS pa_lager,
                       count(l.id) FILTER (WHERE l.product_id IS NULL) AS umatchet,
                       max(l.last_ok_at) AS sist_ok
                FROM stores s LEFT JOIN listings l ON l.store_id = s.id
                GROUP BY s.id ORDER BY s.name""")
            butikker = await cur.fetchall()
            cur = await conn.execute("""
                SELECT kind, count(*) AS n FROM events
                WHERE detected_at > now() - interval '24 hours' GROUP BY kind""")
            hendelser = {r["kind"]: r["n"] for r in await cur.fetchall()}
            cur = await conn.execute("""
                SELECT count(*) AS sendt,
                       count(*) FILTER (WHERE NOT ok) AS feilet
                FROM notifications_sent WHERE sendt_at > now() - interval '24 hours'""")
            varsler = await cur.fetchone()
            cur = await conn.execute("""
                SELECT (SELECT count(*) FROM users) AS brukere,
                       (SELECT count(*) FROM subscriptions) AS abonnementer,
                       (SELECT count(*) FROM push_endpoints) AS enheter,
                       (SELECT count(*) FROM listings WHERE product_id IS NULL
                          AND last_seen_at > now() - interval '7 days') AS umatchet,
                       (SELECT count(*) FROM listings
                          WHERE last_seen_at > now() - interval '7 days') AS oppforinger,
                       (SELECT count(*) FROM listings WHERE image_url IS NOT NULL)
                         AS med_bilde,
                       (SELECT siste_event_id FROM varsel_tilstand WHERE id = 1)
                         AS varsel_vannmerke""")
            tall = await cur.fetchone()
        return {"kjoringer": kjoringer, "butikker": butikker,
                "hendelser_24t": hendelser, "varsler_24t": varsler, "tall": tall}

    # --------------------------------------------------------- feedback

    @router.get("/feedback")
    async def feedback(pokepuls_sesjon: str | None = Cookie(None),
                       status: str | None = Query(None)):
        await _krev_admin(pokepuls_sesjon)
        vilkar, args = [], []
        if status in {"ny", "lest", "gjort", "avvist"}:
            vilkar.append("f.status = %s")
            args.append(status)
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "SELECT f.id, f.tekst, f.slag, f.side, f.status, f.notat, "
                "       f.created_at, f.user_agent, "
                "       COALESCE(u.email, f.epost) AS epost, "
                "       (u.id IS NULL) AS slettet_konto, u.role "
                "FROM feedback f LEFT JOIN users u ON u.id = f.user_id " +
                ("WHERE " + " AND ".join(vilkar) + " " if vilkar else "") +
                "ORDER BY (f.status = 'ny') DESC, f.created_at DESC LIMIT 300", args)
            meldinger = await cur.fetchall()
            cur = await conn.execute(
                "SELECT status, count(*) AS n FROM feedback GROUP BY status")
            antall = {r["status"]: r["n"] for r in await cur.fetchall()}
        return {"meldinger": meldinger, "antall": antall}

    @router.post("/feedback/{melding_id}")
    async def sett_feedback_status(melding_id: int, data: FeedbackStatus,
                                   pokepuls_sesjon: str | None = Cookie(None)):
        await _krev_admin(pokepuls_sesjon)
        felt, verdier = [], []
        if data.status:
            felt.append("status = %s")
            verdier.append(data.status)
        if data.notat is not None:
            felt.append("notat = %s")
            verdier.append(data.notat or None)
        if not felt:
            return {"ok": True}
        verdier.append(melding_id)
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "UPDATE feedback SET " + ", ".join(felt) + " WHERE id = %s RETURNING id",
                tuple(verdier))
            if not await cur.fetchone():
                raise HTTPException(404, "Ukjent melding")
        return {"ok": True}

    # ---------------------------------------------------------- katalog

    @router.get("/umatchet")
    async def umatchet(pokepuls_sesjon: str | None = Cookie(None),
                       limit: int = Query(200, ge=1, le=2000),
                       q: str | None = Query(None, max_length=100)):
        """Umatchede titler, gruppert paa tittel.

        Gruppering er poenget: den samme varen ligger hos seks butikker med
        seks titler, men de aller fleste hullene er ETT sett som mangler
        alias. Sortert paa antall butikker, sa den mest lonnsomme koblingen
        ligger overst.
        """
        await _krev_admin(pokepuls_sesjon)
        vilkar = ["l.product_id IS NULL",
                  "l.last_seen_at > now() - interval '7 days'"]
        args: list = []
        if q:
            vilkar.append("l.title ILIKE %s")
            args.append(f"%{q}%")
        args.append(limit)
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "SELECT l.title, count(*) AS butikker, "
                "       array_agg(DISTINCT l.store_id) AS butikk_ider, "
                "       min(l.price_ore) AS min_pris, "
                "       bool_or(l.in_stock) AS noen_inne, "
                "       (array_agg(l.url))[1] AS url, "
                "       (array_remove(array_agg(l.image_url), NULL))[1] AS bilde "
                "FROM listings l WHERE " + " AND ".join(vilkar) +
                " GROUP BY l.title ORDER BY count(*) DESC, l.title LIMIT %s", args)
            return {"varer": await cur.fetchall()}

    @router.get("/produkter")
    async def produkter(pokepuls_sesjon: str | None = Cookie(None)):
        """Alle kanoniske produkter -- valglisten naar man kobler."""
        await _krev_admin(pokepuls_sesjon)
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "SELECT p.id, s.label AS set_label, t.label AS type_label, p.region "
                "FROM products p JOIN sets s ON s.id = p.set_id "
                "JOIN product_types t ON t.id = p.type_id "
                "ORDER BY s.label, p.region, t.sort_order")
            return {"produkter": await cur.fetchall()}

    @router.post("/koble")
    async def koble(data: Kobling, pokepuls_sesjon: str | None = Cookie(None)):
        """Kobler alle oppforinger med denne tittelen til produktet.

        Skriver bade listings.product_id (virker med en gang) og
        manual_matches (overlever neste ingest, som ellers ville satt
        product_id tilbake til NULL fra matcher.py).
        """
        bruker = await _krev_admin(pokepuls_sesjon)
        async with hent_pool().connection() as conn:
            cur = await conn.execute("SELECT 1 FROM products WHERE id = %s",
                                     (data.product_id,))
            if not await cur.fetchone():
                raise HTTPException(400, "Ukjent produkt-id")
            await conn.execute(
                "INSERT INTO manual_matches (title, product_id, laget_av) "
                "VALUES (%s, %s, %s) ON CONFLICT (title) DO UPDATE SET "
                "  product_id = EXCLUDED.product_id, laget_av = EXCLUDED.laget_av",
                (data.title, data.product_id, bruker["id"]))
            cur = await conn.execute(
                "UPDATE listings SET product_id = %s WHERE title = %s RETURNING id",
                (data.product_id, data.title))
            rader = await cur.fetchall()
        return {"ok": True, "koblet": len(rader)}

    @router.delete("/koble")
    async def fjern_kobling(title: str = Query(min_length=3),
                            pokepuls_sesjon: str | None = Cookie(None)):
        await _krev_admin(pokepuls_sesjon)
        async with hent_pool().connection() as conn:
            await conn.execute("DELETE FROM manual_matches WHERE title = %s", (title,))
            await conn.execute(
                "UPDATE listings SET product_id = NULL WHERE title = %s", (title,))
        return {"ok": True}

    @router.get("/koblinger")
    async def koblinger(pokepuls_sesjon: str | None = Cookie(None)):
        await _krev_admin(pokepuls_sesjon)
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "SELECT m.title, m.product_id, m.created_at, u.email AS av, "
                "       s.label AS set_label, t.label AS type_label "
                "FROM manual_matches m "
                "LEFT JOIN users u ON u.id = m.laget_av "
                "LEFT JOIN products p ON p.id = m.product_id "
                "LEFT JOIN sets s ON s.id = p.set_id "
                "LEFT JOIN product_types t ON t.id = p.type_id "
                "ORDER BY m.created_at DESC")
            return {"koblinger": await cur.fetchall()}

    app.include_router(router)
