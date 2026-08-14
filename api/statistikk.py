"""Prishistorikk og restock-statistikk. Premium.

HVORFOR DETTE ER VERDT PENGER, OG PRISGRENSEN ALENE IKKE VAR DET

Prisgrensen sier fra naar noe er billig nok. Den svarer ikke paa
spoersmaalet en flipper faktisk stiller: ER dette billig? 3 999 for en
booster box er et godt kjop eller et daarlig ett, og forskjellen ser du
bare mot det den har kostet for.

Begge sidene her bygger paa `events`. Tabellen har ligget der siden dag én
og blitt brukt til nøyaktig én ting: aa sende varsler. Alt dette er data vi
allerede har -- ingen ny innsamling, ingen ny skraping.

TO ADVARSLER SOM STAAR I SVARENE OGSAA

* Historikken starter den dagen vi begynte aa maale, ikke den dagen varen
  kom i salg. «Laveste noensinne» betyr «laveste vi har sett». Sier vi det
  ikke, leser folk det som en fasit det ikke er.

* Restock-statistikken teller naar VI OPPDAGET noe, ikke naar butikken la
  det ut. Vi skanner hvert tiende minutt, saa et klokkeslett her er noyaktig
  paa ti minutter -- godt nok til aa se at Cardcenter fyller paa om
  formiddagen, for daarlig til aa sitte klar 09:03.
"""
from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException

router = APIRouter(prefix="/api/statistikk", tags=["statistikk"])

# Daglig LAVESTE pris, ikke gjennomsnitt.
#
# Gjennomsnitt over butikker er et tall som ikke tilsvarer noe du kunne
# kjopt. Laveste er prisen som faktisk fantes den dagen, og det er den du
# sammenligner dagens tilbud mot.
#
# COALESCE paa prev_price_ore: en prisendring har den NYE prisen i
# price_ore, saa den holder. Men en 'utsolgt' har ingen ny pris -- da er
# den forrige det siste vi visste.
PRISHISTORIKK_SQL = """
SELECT date_trunc('day', e.detected_at)::date AS dag,
       min(COALESCE(e.price_ore, e.prev_price_ore)) AS laveste,
       count(*) AS hendelser
FROM events e
WHERE e.product_id = %s
  AND e.detected_at > now() - make_interval(days => %s)
  AND COALESCE(e.price_ore, e.prev_price_ore) IS NOT NULL
GROUP BY 1 ORDER BY 1
"""

BUNN_SQL = """
SELECT min(COALESCE(e.price_ore, e.prev_price_ore)) AS laveste
FROM events e WHERE e.product_id = %s
  AND COALESCE(e.price_ore, e.prev_price_ore) IS NOT NULL
"""

# Hvem hadde den laveste, og naar. Et tall uten butikk og dato er en paastand
# du ikke kan gjore noe med.
BUNN_DETALJ_SQL = """
SELECT e.store_id, st.name AS store_name, e.detected_at,
       COALESCE(e.price_ore, e.prev_price_ore) AS pris
FROM events e LEFT JOIN stores st ON st.id = e.store_id
WHERE e.product_id = %s AND COALESCE(e.price_ore, e.prev_price_ore) = %s
ORDER BY e.detected_at DESC LIMIT 1
"""

RESTOCK_BUTIKK_SQL = """
SELECT e.store_id, st.name AS store_name, count(*) AS antall,
       max(e.detected_at) AS sist
FROM events e LEFT JOIN stores st ON st.id = e.store_id
     LEFT JOIN listings l ON l.id = e.listing_id
WHERE e.kind = 'restock' AND e.detected_at > now() - make_interval(days => %s)
  AND (l.bestillingstype IS NULL OR l.bestillingstype <> 'bestillingsvare')
GROUP BY e.store_id, st.name ORDER BY antall DESC LIMIT 20
"""

# Norsk tid, ikke UTC. En bruker som leser «13» skal kjenne seg igjen i sin
# egen klokke, og halve aaret er de to en time fra hverandre.
RESTOCK_TIME_SQL = """
SELECT EXTRACT(HOUR FROM e.detected_at AT TIME ZONE 'Europe/Oslo')::int AS time,
       count(*) AS antall
FROM events e
WHERE e.kind = 'restock' AND e.detected_at > now() - make_interval(days => %s)
GROUP BY 1 ORDER BY 1
"""

RESTOCK_UKEDAG_SQL = """
SELECT EXTRACT(ISODOW FROM e.detected_at AT TIME ZONE 'Europe/Oslo')::int AS dag,
       count(*) AS antall
FROM events e
WHERE e.kind = 'restock' AND e.detected_at > now() - make_interval(days => %s)
GROUP BY 1 ORDER BY 1
"""

TOPP_VARER_SQL = """
SELECT e.product_id, s.label AS set_label, t.label AS type_label, p.region,
       count(*) AS antall, max(e.detected_at) AS sist
FROM events e
JOIN products p ON p.id = e.product_id
LEFT JOIN sets s ON s.id = p.set_id
LEFT JOIN product_types t ON t.id = p.type_id
WHERE e.kind = 'restock' AND e.detected_at > now() - make_interval(days => %s)
GROUP BY e.product_id, s.label, t.label, p.region
ORDER BY antall DESC LIMIT 15
"""


def monter(app, hent_pool, hent_bruker, er_premium):

    async def _premium(token):
        bruker = await hent_bruker(hent_pool(), token)
        if not bruker:
            raise HTTPException(401, "Ikke innlogget")
        if not er_premium(bruker):
            # 402, ikke 403. Dette er ikke forbudt -- det er ikke betalt for.
            raise HTTPException(402, "Statistikk er en premium-funksjon.")
        return bruker

    async def _hent(sql, *args):
        async with hent_pool().connection() as conn:
            cur = await conn.execute(sql, args)
            return await cur.fetchall()

    @router.get("/pris/{produkt_id}")
    async def prishistorikk(produkt_id: str, dager: int = 180,
                            pokepuls_sesjon: str | None = Cookie(None)):
        await _premium(pokepuls_sesjon)
        dager = max(7, min(dager, 730))
        punkter = await _hent(PRISHISTORIKK_SQL, produkt_id, dager)
        bunn = await _hent(BUNN_SQL, produkt_id)
        laveste = bunn[0]["laveste"] if bunn else None
        detalj = (await _hent(BUNN_DETALJ_SQL, produkt_id, laveste))[0] if laveste else None
        return {
            "punkter": punkter,
            "laveste_ore": laveste,
            "laveste_hos": detalj["store_name"] if detalj else None,
            "laveste_nar": detalj["detected_at"] if detalj else None,
            # Staar i svaret, ikke bare i grensesnittet: den som leser
            # API-et direkte skal se samme forbehold.
            "forbehold": "Laveste vi har registrert, ikke laveste noensinne. "
                         "Historikken starter da vi begynte å måle produktet.",
        }

    @router.get("/restock")
    async def restock(dager: int = 30, pokepuls_sesjon: str | None = Cookie(None)):
        await _premium(pokepuls_sesjon)
        dager = max(7, min(dager, 365))
        butikker = await _hent(RESTOCK_BUTIKK_SQL, dager)
        timer = {r["time"]: r["antall"] for r in await _hent(RESTOCK_TIME_SQL, dager)}
        ukedager = {r["dag"]: r["antall"] for r in await _hent(RESTOCK_UKEDAG_SQL, dager)}
        varer = await _hent(TOPP_VARER_SQL, dager)
        return {
            "dager": dager,
            "butikker": butikker,
            # Fyll hullene: en time uten restock er null, ikke fravaerende.
            # Ellers tegner frontenden en graf med huller den maa gjette i.
            "per_time": [{"time": t, "antall": timer.get(t, 0)} for t in range(24)],
            "per_ukedag": [{"dag": d, "antall": ukedager.get(d, 0)} for d in range(1, 8)],
            "varer": varer,
            "forbehold": "Tidspunktene viser når vi oppdaget påfyllet, ikke når "
                         "butikken la det ut. Vi skanner hvert tiende minutt.",
        }

    app.include_router(router)
