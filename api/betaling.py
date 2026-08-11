"""Pokepuls Premium -- betaling gjennom Stripe.

DEN ENE REGELEN SOM BETYR NOE

**Webhooken er fasit. Retur-URL-en beviser ingenting.**

Naar Stripe sender brukeren tilbake til success_url, er det bare nettleseren
som forteller oss noe. Hvem som helst kan aapne den adressen. Hadde vi satt
premium der, ville gratis premium vaert ett bokmerke unna.

Derfor: retur-siden sier bare «takk, det kan ta et oyeblikk». Rollen settes
naar Stripe selv ringer oss, med en signatur vi kontrollerer.

HVA VI ALDRI SER

Kortnummer, utlopsdato, CVC. Alt det skjer paa Stripes egne sider. Vi
lagrer to ID-er og en dato -- se db/008_stripe.sql.

WEBHOOKS KOMMER MINST ÉN GANG, IKKE NOYAKTIG ÉN

Den samme hendelsen kan komme to ganger ved nettverksfeil, eller naar vi
svarer for sent. Uten sperre kunne en gjentatt `checkout.session.completed`
gitt to maaneder for én betaling. Sperren er primaernokkelen i
stripe_hendelser: gikk INSERT-en ikke inn, har vi sett den for.

NAAR PREMIUM FALLER BORT

Aldri brått. Sier du opp, beholder du premium ut perioden du har betalt for
-- det staar i vilkaarene, og `er_premium()` i api/auth.py leser
`premium_until` og gjor resten av seg selv. Vi trenger ingen jobb som
senker folk ned; en dato som har passert er nok.

OPPSETT PAA SERVEREN (/etc/pokepuls.env)

    STRIPE_SECRET_KEY=sk_test_...     hemmelig -- deles aldri
    STRIPE_WEBHOOK_SECRET=whsec_...   hemmelig -- deles aldri
    STRIPE_PRICE_ID=price_...         ikke hemmelig

Mangler noen av dem, er hele modulen AV: endepunktene svarer 503 og
grensesnittet viser ingen kjopsknapp. Det er med vilje -- en halvkonfigurert
betalingsloype skal ikke se ut som en fungerende en.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/betaling", tags=["betaling"])

HEMMELIG = os.environ.get("STRIPE_SECRET_KEY", "").strip()
WEBHOOK_HEMMELIG = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
PRIS_ID = os.environ.get("STRIPE_PRICE_ID", "").strip()
BASE = os.environ.get("POKEPULS_BASE_URL", "https://pokepuls.no").rstrip("/")

# Beloepet staar ETT sted som sannhet: i Stripe. Dette tallet er bare til
# visning, og hvis de to gaar fra hverandre er det Stripe som gjelder.
PRIS_KR = 49


def _stripe():
    """Importeres ved bruk, ikke ved oppstart.

    API-et skal starte selv om stripe-pakken ikke er installert enna. Ellers
    ville en manglende avhengighet tatt ned hele siden -- inkludert alt som
    er gratis og virker.
    """
    import stripe
    stripe.api_key = HEMMELIG
    return stripe


def paa() -> bool:
    return bool(HEMMELIG and WEBHOOK_HEMMELIG and PRIS_ID)


class Start(BaseModel):
    pass


def monter(app, hent_pool, hent_bruker, er_premium):

    async def _bruker(token):
        bruker = await hent_bruker(hent_pool(), token)
        if not bruker:
            raise HTTPException(401, "Ikke innlogget")
        return bruker

    # ------------------------------------------------------------ status

    @router.get("/status")
    async def status(pokepuls_sesjon: str | None = Cookie(None)):
        """Hva grensesnittet trenger for aa tegne riktig knapp."""
        bruker = await hent_bruker(hent_pool(), pokepuls_sesjon)
        rad = None
        if bruker:
            async with hent_pool().connection() as conn:
                cur = await conn.execute(
                    "SELECT status, gjelder_til FROM stripe_kunder WHERE user_id = %s",
                    (bruker["id"],))
                rad = await cur.fetchone()
        return {
            "paa": paa(),
            "pris_kr": PRIS_KR,
            "premium": er_premium(bruker) if bruker else False,
            "status": rad["status"] if rad else None,
            "gjelder_til": rad["gjelder_til"] if rad else None,
        }

    # ------------------------------------------------------------- kjope

    @router.post("/start")
    async def start(request: Request, pokepuls_sesjon: str | None = Cookie(None)):
        if not paa():
            raise HTTPException(503, "Betaling er ikke satt opp ennå.")
        bruker = await _bruker(pokepuls_sesjon)
        if er_premium(bruker):
            raise HTTPException(400, "Du har allerede Premium.")

        stripe = _stripe()
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "SELECT stripe_customer_id FROM stripe_kunder WHERE user_id = %s",
                (bruker["id"],))
            rad = await cur.fetchone()

            kunde = rad["stripe_customer_id"] if rad else None
            if not kunde:
                # Gjenbruk kunden ved neste kjop. Uten dette faar samme
                # person en ny kunde per forsok, og betalingshistorikken
                # deres blir umulig aa foelge naar de spor om noe.
                k = stripe.Customer.create(
                    email=bruker["email"],
                    metadata={"pokepuls_user_id": str(bruker["id"])},
                )
                kunde = k["id"]
                await conn.execute(
                    "INSERT INTO stripe_kunder (user_id, stripe_customer_id) "
                    "VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET "
                    "  stripe_customer_id = EXCLUDED.stripe_customer_id",
                    (bruker["id"], kunde))

        okt = stripe.checkout.Session.create(
            mode="subscription",
            customer=kunde,
            line_items=[{"price": PRIS_ID, "quantity": 1}],
            success_url=BASE + "/?betaling=ok",
            cancel_url=BASE + "/?betaling=avbrutt",
            locale="nb",
            # client_reference_id foelger med tilbake i webhooken. Den er
            # reserven hvis kundekoblingen skulle mangle.
            client_reference_id=str(bruker["id"]),
            subscription_data={"metadata": {"pokepuls_user_id": str(bruker["id"])}},
        )
        return {"url": okt["url"]}

    # ------------------------------------------------------- si opp/endre

    @router.post("/portal")
    async def portal(pokepuls_sesjon: str | None = Cookie(None)):
        """Stripes egen kundeportal.

        Der sier man opp, bytter kort og henter kvitteringer. Aa bygge det
        selv ville betydd tre skjermbilder til aa vedlikeholde, og ett av
        dem haandterer kortdata.
        """
        if not paa():
            raise HTTPException(503, "Betaling er ikke satt opp ennå.")
        bruker = await _bruker(pokepuls_sesjon)
        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "SELECT stripe_customer_id FROM stripe_kunder WHERE user_id = %s",
                (bruker["id"],))
            rad = await cur.fetchone()
        if not rad:
            raise HTTPException(404, "Du har ingen betaling å administrere.")
        okt = _stripe().billing_portal.Session.create(
            customer=rad["stripe_customer_id"], return_url=BASE + "/")
        return {"url": okt["url"]}

    # ----------------------------------------------------------- webhook

    @router.post("/webhook")
    async def webhook(request: Request):
        """Her, og bare her, settes premium.

        Signaturen kontrolleres for vi ser paa innholdet. Uten det er dette
        et endepunkt hvem som helst kan sende «denne har betalt» til.
        """
        if not paa():
            raise HTTPException(503, "Betaling er ikke satt opp ennå.")
        kropp = await request.body()
        signatur = request.headers.get("stripe-signature", "")
        stripe = _stripe()
        try:
            hendelse = stripe.Webhook.construct_event(
                kropp, signatur, WEBHOOK_HEMMELIG)
        except Exception:
            # Ikke si HVA som var galt. Et endepunkt som forklarer hvorfor
            # en signatur ikke holdt, hjelper den som prover aa gjette.
            raise HTTPException(400, "Ugyldig signatur")

        async with hent_pool().connection() as conn:
            cur = await conn.execute(
                "INSERT INTO stripe_hendelser (id, type) VALUES (%s, %s) "
                "ON CONFLICT (id) DO NOTHING RETURNING id",
                (hendelse["id"], hendelse["type"]))
            if not await cur.fetchone():
                # Sett for. Stripe leverer minst én gang, ikke noyaktig én.
                return {"ok": True, "gjentakelse": True}

            await _behandle(conn, stripe, hendelse)
        return {"ok": True}

    async def _behandle(conn, stripe, hendelse):
        type_ = hendelse["type"]
        data = hendelse["data"]["object"]

        if type_ == "checkout.session.completed":
            kunde = data.get("customer")
            abo_id = data.get("subscription")
            if not (kunde and abo_id):
                return
            abo = stripe.Subscription.retrieve(abo_id)
            await _oppdater(conn, kunde, abo)

        elif type_ in ("customer.subscription.created",
                       "customer.subscription.updated",
                       "customer.subscription.deleted"):
            await _oppdater(conn, data.get("customer"), data)

    async def _oppdater(conn, kunde_id, abo):
        """Skriv status og dato, og loft eller la rollen staa.

        Vi SENKER aldri noen her. Sier du opp midt i perioden, sender Stripe
        `subscription.updated` med cancel_at_period_end -- og du skal
        beholde premium ut perioden. `er_premium()` leser datoen og gjor
        resten av seg selv naar den passerer.
        """
        if not kunde_id:
            return
        status = abo.get("status")
        slutt = abo.get("current_period_end")
        gjelder_til = (datetime.fromtimestamp(slutt, tz=timezone.utc)
                       if slutt else None)

        cur = await conn.execute(
            "UPDATE stripe_kunder SET abonnement_id = %s, status = %s, "
            "  gjelder_til = %s, endret = now() "
            "WHERE stripe_customer_id = %s RETURNING user_id",
            (abo.get("id"), status, gjelder_til, kunde_id))
        rad = await cur.fetchone()
        if not rad:
            return

        # «active» og «trialing» er de to som gir tilgang. `past_due` gjor
        # det ikke -- men vi tar heller ikke fra noen der og da: datoen de
        # allerede har betalt for staar, og Stripe prover kortet igjen.
        if status in ("active", "trialing"):
            await conn.execute(
                "UPDATE users SET role = 'premium', premium_until = %s "
                "WHERE id = %s AND role <> 'admin'",
                (gjelder_til, rad["user_id"]))

    app.include_router(router)
