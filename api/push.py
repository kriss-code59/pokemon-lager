"""Web Push: abonnement, avmelding og testvarsel.

Nettleseren lager abonnementet selv -- vi faar bare et endepunkt og to
nokler tilbake, og lagrer dem. Selve utsendingen skjer i overvak/varsler.py.

Det eneste som er verdt aa merke seg her: `endpoint` er UNIQUE i skjemaet,
og en bruker kan bytte enhet eller logge inn paa nytt uten at nettleseren
lager et nytt abonnement. Derfor er innsettingen en UPSERT som ogsaa
flytter eierskapet -- ellers ville "logg inn med en annen konto paa samme
telefon" gi en 500 fra en unik-indeks, og varslene ville fortsatt gaa til
den forrige kontoen.
"""
from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Request
from pydantic import BaseModel, Field

from varsling import kontekst as kontekst_modul
from varsling import send as sender
from varsling import tekst as tekst_modul
from varsling import vapid

router = APIRouter(prefix="/api/push", tags=["push"])


class Nokler(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class Abonnement(BaseModel):
    endpoint: str = Field(min_length=20, max_length=800)
    keys: Nokler


class Endepunkt(BaseModel):
    endpoint: str = Field(min_length=20, max_length=800)


class Innstillinger(BaseModel):
    stille_natt: bool | None = None
    maks_pris_kr: int | None = Field(default=None, ge=0, le=1_000_000)


def monter(app, hent_pool, hent_bruker):
    def _krev(bruker):
        if not bruker:
            raise HTTPException(401, "Ikke innlogget")
        return bruker

    @router.get("/nokkel")
    async def nokkel():
        """Offentlig VAPID-nokkel. Uten den kan nettleseren ikke abonnere.

        Svarer 200 med paa=false naar noklene ikke er satt, ikke 500:
        frontenden skal kunne vise "varsler er ikke satt opp enna" i stedet
        for en feilmelding.
        """
        n = vapid.offentlig_nokkel()
        return {"paa": bool(n), "public_key": n}

    @router.get("/status")
    async def status(pokepuls_sesjon: str | None = Cookie(None)):
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, user_agent, created_at, last_ok_at "
                "FROM push_endpoints WHERE user_id = %s ORDER BY created_at",
                (bruker["id"],))
            enheter = await cur.fetchall()
            cur = await conn.execute(
                "SELECT varsel_stille_natt, varsel_maks_pris_ore FROM users WHERE id = %s",
                (bruker["id"],))
            innst = await cur.fetchone()
            cur = await conn.execute(
                "SELECT count(*) AS n FROM notifications_sent "
                "WHERE user_id = %s AND sendt_at > now() - interval '7 days'",
                (bruker["id"],))
            sendt = (await cur.fetchone())["n"]
        return {"enheter": enheter, "antall": len(enheter),
                "stille_natt": innst["varsel_stille_natt"],
                "maks_pris_ore": innst["varsel_maks_pris_ore"],
                "sendt_7d": sendt, "vapid_paa": bool(vapid.offentlig_nokkel())}

    @router.post("/abonner")
    async def abonner(data: Abonnement, request: Request,
                      pokepuls_sesjon: str | None = Cookie(None)):
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        ua = (request.headers.get("user-agent") or "")[:300]
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO push_endpoints (user_id, endpoint, p256dh, auth, user_agent) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (endpoint) DO UPDATE SET "
                "  user_id = EXCLUDED.user_id, p256dh = EXCLUDED.p256dh, "
                "  auth = EXCLUDED.auth, user_agent = EXCLUDED.user_agent, "
                "  feil_pa_rad = 0, sist_feil = NULL "
                "RETURNING id", (bruker["id"], data.endpoint,
                                 data.keys.p256dh, data.keys.auth, ua))
            return {"id": (await cur.fetchone())["id"], "ok": True}

    @router.post("/avmeld")
    async def avmeld(data: Endepunkt, pokepuls_sesjon: str | None = Cookie(None)):
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        async with pool.connection() as conn:
            await conn.execute(
                "DELETE FROM push_endpoints WHERE endpoint = %s AND user_id = %s",
                (data.endpoint, bruker["id"]))
        return {"ok": True}

    @router.post("/innstillinger")
    async def innstillinger(data: Innstillinger,
                            pokepuls_sesjon: str | None = Cookie(None)):
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        felt, verdier = [], []
        if data.stille_natt is not None:
            felt.append("varsel_stille_natt = %s")
            verdier.append(data.stille_natt)
        if data.maks_pris_kr is not None:
            felt.append("varsel_maks_pris_ore = %s")
            verdier.append(data.maks_pris_kr * 100 or None)
        if not felt:
            return {"ok": True}
        verdier.append(bruker["id"])
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE users SET " + ", ".join(felt) + " WHERE id = %s", tuple(verdier))
        return {"ok": True}

    @router.post("/test")
    async def test(pokepuls_sesjon: str | None = Cookie(None)):
        """Sender et ekte varsel til brukerens egne enheter.

        Bruker den samme tekstbyggeren som cron-senderen, med et ekte
        produkt fra databasen. Et testvarsel som ser annerledes ut enn de
        ekte tester ingenting.
        """
        pool = hent_pool()
        bruker = _krev(await hent_bruker(pool, pokepuls_sesjon))
        if not vapid.har_nokler():
            raise HTTPException(503, "Varsler er ikke satt opp paa serveren enna.")

        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, endpoint, p256dh, auth FROM push_endpoints WHERE user_id = %s",
                (bruker["id"],))
            enheter = await cur.fetchall()
            if not enheter:
                raise HTTPException(400, "Ingen enheter registrert. Sla paa varsler forst.")

            # Et ekte produkt brukeren folger, ellers et tilfeldig et som er inne.
            cur = await conn.execute(
                "SELECT l.id AS listing_id, l.title, l.url, l.image_url, l.price_ore, "
                "       l.product_id, l.store_id, st.name AS store_name, "
                "       s.label AS set_label, t.label AS type_label, p.region "
                "FROM listings l "
                "JOIN stores st ON st.id = l.store_id "
                "JOIN products p ON p.id = l.product_id "
                "JOIN sets s ON s.id = p.set_id "
                "JOIN product_types t ON t.id = p.type_id "
                "WHERE l.in_stock IS TRUE AND l.price_ore >= 500 "
                "  AND (p.id IN (SELECT product_id FROM subscriptions "
                "                WHERE user_id = %s AND product_id IS NOT NULL) "
                "       OR TRUE) "
                "ORDER BY (p.id IN (SELECT product_id FROM subscriptions "
                "                   WHERE user_id = %s AND product_id IS NOT NULL)) DESC, "
                "         random() LIMIT 1", (bruker["id"], bruker["id"]))
            rad = await cur.fetchone()

        if rad:
            hendelse = dict(rad, kind="restock", prev_price_ore=None)
            async with pool.connection() as conn:
                c = await conn.execute(kontekst_modul.BILLIGST_NA_SQL, (rad["product_id"],))
                inne = await c.fetchall()
                c = await conn.execute(kontekst_modul.BILLIGST_7D_SQL, (rad["product_id"],))
                sju = await c.fetchone()
            ktx = {"billigst_na_ore": inne[0]["price_ore"] if inne else None,
                   "billigst_butikk": inne[0]["store_name"] if inne else None,
                   "billigst_7d_ore": (sju or {}).get("pris"),
                   "antall_pa_lager": len(inne)}
        else:
            hendelse = {"kind": "restock", "store_name": "Testbutikk",
                        "set_label": "Prismatic Evolutions", "type_label": "Booster Bundle",
                        "region": "en", "price_ore": 139900, "url": "https://pokepuls.no/"}
            ktx = {"billigst_na_ore": 139900, "billigst_butikk": "Testbutikk",
                   "billigst_7d_ore": 139900, "antall_pa_lager": 2}

        varsel = tekst_modul.bygg(hendelse, ktx)
        varsel["title"] = "🔔 Testvarsel · " + varsel["title"].split(" ", 1)[-1]

        ok_antall, feil = 0, None
        for enhet in enheter:
            ok, f, status = sender.send(enhet, varsel)
            if ok:
                ok_antall += 1
            else:
                feil = f
                if sender.er_dod(status):
                    async with pool.connection() as conn:
                        await conn.execute("DELETE FROM push_endpoints WHERE id = %s",
                                           (enhet["id"],))
        if not ok_antall:
            raise HTTPException(502, f"Klarte ikke sende: {feil}")
        return {"ok": True, "sendt_til": ok_antall, "varsel": varsel}

    app.include_router(router)
