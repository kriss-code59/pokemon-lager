"""Pokepuls API.

Erstatter docs/data.json (5,8 MB, cache-bustet ved hvert sidebesok) med noen
fa endepunkter som kan caches.

Designvalg som er verdt a vite om:

* /snapshot leverer KANONISKE PRODUKTER med tilbud under seg, ikke en flat
  liste av butikkrader. Det er hele poenget med katalogen: brukeren folger
  "Pitch Black Booster Box", ikke 6 ulike butikklenker.
* Tilbud sendes som lister, ikke objekter. Med ~2 200 tilbud sparer det
  omtrent halvparten av rapayloaden, og frontend er var egen.
* Alt som kan caches har ETag. Klienten sender If-None-Match og far 304 med
  tom kropp nar ingenting har endret seg -- som skjer 19 av 20 minutter.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

DSN = os.environ.get("POKEPULS_DSN", "postgresql:///pokepuls")

# Snapshot regenereres uansett bare hvert 20. minutt av scraperen.
CACHE_SNAPSHOT = "public, max-age=60, stale-while-revalidate=600"
CACHE_KATALOG = "public, max-age=3600, stale-while-revalidate=86400"
CACHE_HENDELSER = "public, max-age=30, stale-while-revalidate=300"

pool: AsyncConnectionPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = AsyncConnectionPool(DSN, min_size=1, max_size=8, open=False,
                               kwargs={"row_factory": dict_row})
    await pool.open(wait=True, timeout=15)
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="Pokepuls API", version="1.1", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://pokepuls.no", "https://www.pokepuls.no",
                   "https://kriss-code59.github.io", "http://localhost:8000",
                   "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Kontoer, sesjoner og folgeliste ligger i api/auth.py. De monteres her fordi
# de trenger den samme tilkoblingspoolen, som ikke finnes for oppstart.
from . import admin, auth, betaling, bruk, feedback, push, sider  # noqa: E402

auth.monter(app, lambda: pool)
# push og admin gjenbruker auth.hent_bruker sa det bare finnes EN vei fra
# cookie til bruker. To implementasjoner av "hvem er dette" er to steder en
# autentiseringsfeil kan gjemme seg.
push.monter(app, lambda: pool, auth.hent_bruker)
_krev_admin = admin.monter(app, lambda: pool, auth.hent_bruker)
feedback.monter(app, lambda: pool, auth.hent_bruker)
# Sidevisninger. Aapent endepunkt inn, adminbeskyttet endepunkt ut -- derfor
# faar den vakten fra admin i stedet for aa lage sin egen.
bruk.monter(app, lambda: pool, _krev_admin)
# Betaling. er_premium sendes inn i stedet for aa importeres, saa det
# fortsatt bare finnes ÉN definisjon av «har denne betalt?».
betaling.monter(app, lambda: pool, auth.hent_bruker, auth.er_premium)
# Serverrendrede produktsider og sidekart. Ligger utenfor /api med vilje:
# de er sider, ikke data, og de skal ha ekte URL-er som kan deles.
sider.monter(app, lambda: pool)


def _svar(request: Request, data: dict, cache: str) -> Response:
    """JSON med ETag. Returnerer 304 hvis klienten allerede har versjonen."""
    kropp = json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                       default=str).encode("utf-8")
    etag = '"%s"' % hashlib.blake2b(kropp, digest_size=16).hexdigest()
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache})
    return Response(content=kropp, media_type="application/json; charset=utf-8",
                    headers={"ETag": etag, "Cache-Control": cache})


async def _hent(sql: str, *args) -> list[dict]:
    async with pool.connection() as conn:
        cur = await conn.execute(sql, args if args else None)
        return await cur.fetchall()


# ------------------------------------------------------------------ helse

@app.get("/api/health")
async def health():
    """Bevisst ucachet. Dodmannsknappen og uptime-sjekker leser denne."""
    try:
        rader = await _hent(
            "SELECT started_at, finished_at, product_count, store_count, "
            "       failed_stores, carried_stores, ok "
            "FROM scrape_runs ORDER BY started_at DESC LIMIT 1")
    except Exception as e:  # databasen nede
        return JSONResponse({"ok": False, "feil": str(e)[:200]}, status_code=503)

    if not rader:
        return JSONResponse({"ok": False, "feil": "ingen kjoringer registrert"},
                            status_code=503)

    kjoring = rader[0]
    alder = datetime.now(timezone.utc) - kjoring["started_at"]
    fersk = alder < timedelta(minutes=60)
    # JSONResponse serialiserer ikke datetime. Det ma skje her, ikke i et
    # unntak nede i starlette -- dette endepunktet er det siste som skal
    # kunne feile, siden dodmannsknappen leser det.
    return JSONResponse(
        {"ok": bool(kjoring["ok"]) and fersk,
         "sist_kjort": kjoring["started_at"].isoformat(),
         "alder_minutter": round(alder.total_seconds() / 60, 1),
         "oppforinger": kjoring["product_count"],
         "butikker": kjoring["store_count"],
         "feilede_butikker": kjoring["failed_stores"] or [],
         "fremforte_butikker": kjoring["carried_stores"] or []},
        status_code=200 if fersk else 503,
        headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- katalog

@app.get("/api/catalog")
async def catalog(request: Request):
    """Sett, typer og butikker. Endres sjelden -- caches en time."""
    sets = await _hent(
        "SELECT s.id, s.label, s.region, s.release_date, "
        "  count(DISTINCT p.id) FILTER (WHERE l.id IS NOT NULL) AS produkter "
        "FROM sets s "
        "LEFT JOIN products p ON p.set_id = s.id "
        "LEFT JOIN listings l ON l.product_id = p.id "
        "GROUP BY s.id ORDER BY s.label")
    typer = await _hent("SELECT id, label, sort_order FROM product_types ORDER BY sort_order")
    butikker = await _hent(
        "SELECT s.id, s.name, count(l.id) AS oppforinger, "
        "  count(l.id) FILTER (WHERE l.in_stock) AS pa_lager "
        "FROM stores s LEFT JOIN listings l ON l.store_id = s.id "
        "GROUP BY s.id ORDER BY s.name")
    return _svar(request, {"sets": sets, "types": typer, "stores": butikker},
                 CACHE_KATALOG)


# --------------------------------------------------------------- snapshot

SNAPSHOT_SQL = """
SELECT p.id, p.set_id, p.type_id, p.region, s.label AS set_label,
       t.label AS type_label, t.sort_order,
       json_agg(json_build_array(
           l.store_id, l.price_ore,
           CASE WHEN l.in_stock IS TRUE THEN 1
                WHEN l.in_stock IS FALSE THEN 0 ELSE null END,
           l.bestillingstype)
         -- Ekte lager forst, deretter forhaandssalg, sa pris. Frontenden
         -- leser tilbud[0] som «billigst kjopbar», og da ma en ekte vare
         -- alltid sla et forhaandssalg.
         ORDER BY (l.in_stock AND l.bestillingstype IS NULL) DESC NULLS LAST,
                  l.in_stock DESC NULLS LAST, l.price_ore NULLS LAST) AS tilbud,
       -- «Paa lager» betyr na: butikken sier ja, OG det er ikke et
       -- forhaandssalg eller en bestillingsvare. Se
       -- katalog/tilgjengelighet.py -- butikkene setter available=true paa
       -- begge, saa uten dette skillet sto varer du ikke kunne faa som
       -- «Paa lager», og utloste restock-varsel.
       min(l.price_ore) FILTER (
         WHERE l.in_stock AND l.bestillingstype IS NULL) AS min_pris,
       count(*) FILTER (
         WHERE l.in_stock AND l.bestillingstype IS NULL) AS antall_pa_lager,
       -- Egne tall, sa frontenden kan si «kan forhandsbestilles hos 3»
       -- uten a blande det med ekte lager.
       count(*) FILTER (
         WHERE l.in_stock AND l.bestillingstype = 'forhandssalg') AS antall_forhandssalg,
       count(*) FILTER (
         WHERE l.in_stock AND l.bestillingstype = 'bestillingsvare') AS antall_bestilling,
       min(l.price_ore) FILTER (
         WHERE l.in_stock AND l.bestillingstype IS NOT NULL) AS min_pris_bestilling,
       -- Ett representativt bilde: helst fra en butikk som har varen inne,
       -- ellers hvilken som helst. Frontenden faller tilbake pa egen grafikk
       -- nar dette er null.
       (array_remove(array_agg(l.image_url ORDER BY l.in_stock DESC NULLS LAST,
                                                   l.price_ore NULLS LAST), NULL))[1] AS bilde,
       max(l.last_seen_at) AS sist_sett,
       -- Siste RELEVANTE hendelse, ikke siste hendelse. "Utsolgt" skal ikke
       -- loefte en vare til toppen av "nylig aktivitet" -- det er nyheten om
       -- at det ikke er noe aa hente. Uten dette skillet fylles toppen av
       -- listen med varer du nettopp gikk glipp av.
       (SELECT max(e.detected_at) FROM events e
         WHERE e.product_id = p.id
           AND e.kind IN ('ny','restock','prisendring')
           AND e.detected_at > now() - interval '14 days') AS sist_hendelse
FROM listings l
JOIN products p      ON p.id = l.product_id
JOIN sets s          ON s.id = p.set_id
JOIN product_types t ON t.id = p.type_id
WHERE l.last_seen_at > now() - interval '7 days'
GROUP BY p.id, s.label, t.label, t.sort_order
ORDER BY s.label, p.region, t.sort_order
"""


@app.get("/api/snapshot")
async def snapshot(request: Request):
    """Kanoniske produkter med tilbud.

    tilbud = [butikk_id, pris_ore, pa_lager (1/0/null)]

    Bevisst uten tittel og url: de to feltene alene tredoblet payloaden
    (123 KB -> 457 KB ra) og trengs bare nar noen apner ETT produkt.
    Da henter frontenden /api/product/<id>, som har alt.
    """
    produkter = await _hent(SNAPSHOT_SQL)
    kjoring = await _hent(
        "SELECT started_at, ok FROM scrape_runs ORDER BY started_at DESC LIMIT 1")
    # Ingen "generert"-tidsstempel her. Det virker uskyldig, men det gjor
    # kroppen ulik ved hver forespørsel, og da endres ETag-en hver gang --
    # og hele poenget med caching forsvinner. Klienten trenger uansett
    # sist_skannet, ikke naar serveren tilfeldigvis svarte.
    return _svar(request, {
        "sist_skannet": kjoring[0]["started_at"] if kjoring else None,
        "skanning_ok": bool(kjoring[0]["ok"]) if kjoring else None,
        "felt": ["butikk", "pris_ore", "pa_lager", "bestillingstype"],
        "produkter": produkter,
    }, CACHE_SNAPSHOT)


@app.get("/api/unmatched")
async def unmatched(request: Request,
                    limit: int = Query(3000, ge=1, le=10000)):
    """Forseglede varer vi ikke har klart a mappe til et kanonisk produkt.

    Katalogdekningen er rundt 50 %. Uten dette endepunktet ville halvparten
    av det ekte varelageret vart usynlig, og det er verre enn en litt rotete
    liste. Alt her er en kandidat til et nytt alias i katalog.json.
    """
    rader = await _hent(
        "SELECT l.store_id, l.title, l.price_ore, l.in_stock, l.url, l.image_url "
        "FROM listings l WHERE l.product_id IS NULL "
        "  AND l.last_seen_at > now() - interval '7 days' "
        "ORDER BY l.in_stock DESC NULLS LAST, l.title LIMIT %s", limit)
    return _svar(request, {"antall": len(rader), "varer": rader}, CACHE_SNAPSHOT)


# ---------------------------------------------------------------- produkt

@app.get("/api/product/{produkt_id}")
async def product(request: Request, produkt_id: str):
    rader = await _hent(
        "SELECT p.id, p.set_id, p.type_id, p.region, p.msrp_ore, "
        "       s.label AS set_label, t.label AS type_label "
        "FROM products p JOIN sets s ON s.id = p.set_id "
        "JOIN product_types t ON t.id = p.type_id WHERE p.id = %s", produkt_id)
    if not rader:
        raise HTTPException(404, "ukjent produkt")

    tilbud = await _hent(
        "SELECT l.store_id, st.name AS store_name, l.title, l.price_ore, "
        "       l.in_stock, l.url, l.image_url, l.last_seen_at, l.bestillingstype "
        "FROM listings l JOIN stores st ON st.id = l.store_id "
        "WHERE l.product_id = %s "
        "ORDER BY (l.in_stock AND l.bestillingstype IS NULL) DESC NULLS LAST, "
        "         l.in_stock DESC NULLS LAST, l.price_ore",
        produkt_id)
    hendelser = await _hent(
        "SELECT kind, store_id, price_ore, prev_price_ore, detected_at "
        "FROM events WHERE product_id = %s ORDER BY detected_at DESC LIMIT 100",
        produkt_id)
    return _svar(request, {"produkt": rader[0], "tilbud": tilbud,
                           "hendelser": hendelser}, CACHE_SNAPSHOT)


# --------------------------------------------------------------- hendelser

@app.get("/api/history")
async def history(request: Request,
                  limit: int = Query(200, ge=1, le=1000),
                  kind: str | None = Query(None),
                  timer: int = Query(168, ge=1, le=720)):
    vilkar = ["e.detected_at > now() - make_interval(hours => %s)"]
    args: list = [timer]
    if kind:
        gyldige = {"ny", "restock", "utsolgt", "prisendring"}
        valgt = [k for k in kind.split(",") if k in gyldige]
        if not valgt:
            raise HTTPException(400, "ugyldig kind")
        vilkar.append("e.kind = ANY(%s)")
        args.append(valgt)
    args.append(limit)
    rader = await _hent(
        "SELECT e.kind, e.detected_at, e.price_ore, e.prev_price_ore, "
        "       e.store_id, st.name AS store_name, e.product_id, "
        "       l.title, l.url, s.label AS set_label, t.label AS type_label "
        "FROM events e "
        "LEFT JOIN listings l ON l.id = e.listing_id "
        "LEFT JOIN stores st ON st.id = e.store_id "
        "LEFT JOIN products p ON p.id = e.product_id "
        "LEFT JOIN sets s ON s.id = p.set_id "
        "LEFT JOIN product_types t ON t.id = p.type_id "
        "WHERE " + " AND ".join(vilkar) +
        " ORDER BY e.detected_at DESC LIMIT %s", *args)
    return _svar(request, {"antall": len(rader), "hendelser": rader}, CACHE_HENDELSER)
