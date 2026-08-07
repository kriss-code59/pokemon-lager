"""Sider som serveres ferdig utfylt fra serveren, for sokemotorer.

Hvorfor dette maatte til: resten av Pokepuls er en enkeltsides app som
henter alt via /api. Googlebot KAN kjore JavaScript, men gjor det i en egen,
tregere ko, og for et nytt domene uten autoritet betyr det i praksis at
sidene ikke indekseres. En side som "Prismatic Evolutions Booster Bundle
pris" ikke finnes paa, kan ikke rangere paa det soket.

Loesningen er ikke aa skrive om frontenden. Det er aa gi hver vare EN ekte
URL som svarer med ferdig HTML:

    /p/prismatic-evolutions:booster-bundle:en

Innholdet er det samme som arket i appen viser -- pris per butikk, lager,
historikk -- men i markup som finnes for JavaScript kjorer. JSON-LD paa
toppen gjor at Google kan vise pris og lagerstatus rett i sokeresultatet.

Sidene er bevisst enkle og lenker inn i appen. De er en inngangsdor fra
Google, ikke et andre grensesnitt aa vedlikeholde.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(tags=["sider"])

BASE = "https://pokepuls.no"
REGION_ORD = {"en": "engelsk", "jp": "japansk", "cn": "kinesisk", "ko": "koreansk"}

# Bare produkter med ekte tilbud kommer i sidekartet. Aa be Google indeksere
# 460 sider der halvparten er tomme er en rask maate aa laere den at
# domenet ikke er verdt aa krype.
SITEMAP_SQL = """
SELECT p.id, max(l.last_seen_at) AS endret,
       count(*) FILTER (WHERE l.in_stock) AS inne
FROM products p JOIN listings l ON l.product_id = p.id
WHERE l.last_seen_at > now() - interval '14 days'
GROUP BY p.id HAVING count(*) > 0
ORDER BY count(*) FILTER (WHERE l.in_stock) DESC, p.id
"""

PRODUKT_SQL = """
SELECT p.id, p.region, p.msrp_ore, s.label AS set_label, s.release_date,
       t.label AS type_label
FROM products p JOIN sets s ON s.id = p.set_id
JOIN product_types t ON t.id = p.type_id WHERE p.id = %s
"""

TILBUD_SQL = """
SELECT l.store_id, st.name AS store_name, l.title, l.price_ore, l.in_stock,
       l.url, l.image_url, l.last_seen_at, l.bestillingstype
FROM listings l JOIN stores st ON st.id = l.store_id
WHERE l.product_id = %s AND l.last_seen_at > now() - interval '14 days'
ORDER BY (l.in_stock AND l.bestillingstype IS NULL) DESC NULLS LAST,
         l.in_stock DESC NULLS LAST, l.price_ore NULLS LAST
"""

# Hva merkelappen skal si. Speiler katalog/tilgjengelighet.py.
BESTILLING_ORD = {"forhandssalg": "Forhåndssalg", "bestillingsvare": "Bestillingsvare"}


def _kr(ore):
    if ore is None:
        return None
    hele, rest = divmod(int(ore), 100)
    t = f"{hele:,}".replace(",", " ")
    return t + (f",{rest:02d}" if rest else "") + " kr"


def _e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def _sidehode(tittel: str, beskrivelse: str, kanonisk: str, jsonld: dict | None,
              bilde: str | None = None) -> str:
    ld = ('<script type="application/ld+json">%s</script>'
          % json.dumps(jsonld, ensure_ascii=False)) if jsonld else ""
    og_bilde = f'<meta property="og:image" content="{_e(bilde)}">' if bilde else ""
    return f"""<!DOCTYPE html>
<html lang="no"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0d10">
<title>{_e(tittel)}</title>
<meta name="description" content="{_e(beskrivelse)}">
<link rel="canonical" href="{_e(kanonisk)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Pokepuls">
<meta property="og:title" content="{_e(tittel)}">
<meta property="og:description" content="{_e(beskrivelse)}">
<meta property="og:url" content="{_e(kanonisk)}">
{og_bilde}
<meta name="twitter:card" content="summary_large_image">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/ikon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/style.css?v=7">
{ld}
</head><body class="side">"""


SIDEFOT = """
<footer class="side-fot">
  <p><a href="/">Pokepuls</a> foelger lagerstatus og pris paa forseglede
  Pok&eacute;mon-produkter hos norske butikker, og oppdaterer hvert 20. minutt.</p>
</footer>
</body></html>"""


def monter(app, hent_pool):

    async def _hent(sql, *args):
        async with hent_pool().connection() as conn:
            cur = await conn.execute(sql, args if args else None)
            return await cur.fetchall()

    # ------------------------------------------------------------ sitemap

    @router.get("/sitemap.xml")
    async def sitemap():
        rader = await _hent(SITEMAP_SQL)
        na = datetime.now(timezone.utc).date().isoformat()
        deler = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
                 f"<url><loc>{BASE}/</loc><lastmod>{na}</lastmod>"
                 f"<changefreq>hourly</changefreq><priority>1.0</priority></url>"]
        for r in rader:
            endret = (r["endret"].date().isoformat() if r["endret"] else na)
            # Produkter som faktisk er paa lager er de folk soker etter og
            # klikker paa. De skal krypes oftere.
            hyppighet = "hourly" if r["inne"] else "daily"
            prio = "0.8" if r["inne"] else "0.5"
            deler.append(f"<url><loc>{BASE}/p/{_e(r['id'])}</loc>"
                         f"<lastmod>{endret}</lastmod>"
                         f"<changefreq>{hyppighet}</changefreq>"
                         f"<priority>{prio}</priority></url>")
        deler.append("</urlset>")
        return Response("\n".join(deler), media_type="application/xml",
                        headers={"Cache-Control": "public, max-age=3600"})

    @router.get("/robots.txt")
    async def robots():
        return Response(
            "User-agent: *\n"
            "Allow: /\n"
            # Admin og API skal ikke i indeksen. /api/docs spesielt: en
            # OpenAPI-side som rangerer paa merkenavnet ditt er pinlig.
            "Disallow: /admin\n"
            "Disallow: /api/\n"
            "\n"
            f"Sitemap: {BASE}/sitemap.xml\n",
            media_type="text/plain",
            headers={"Cache-Control": "public, max-age=86400"})

    # ------------------------------------------------------- produktside

    @router.get("/p/{produkt_id}")
    async def produktside(request: Request, produkt_id: str):
        rader = await _hent(PRODUKT_SQL, produkt_id)
        if not rader:
            raise HTTPException(404, "Ukjent produkt")
        p = rader[0]
        tilbud = await _hent(TILBUD_SQL, produkt_id)
        # «Paa lager» maa bety at du kan faa den i posten. Et forhaandssalg
        # som staar oeverst under den overskriften er feil svar paa
        # spoersmaalet folk kom hit for aa faa -- og Google leser den samme
        # overskriften.
        inne = [t for t in tilbud
                if t["in_stock"] is True and t["price_ore"] and not t["bestillingstype"]]
        bestill = [t for t in tilbud
                   if t["in_stock"] is True and t["price_ore"] and t["bestillingstype"]]
        ute = [t for t in tilbud if t not in inne and t not in bestill]
        billigst = min((t["price_ore"] for t in inne), default=None)
        bilde = next((t["image_url"] for t in tilbud if t["image_url"]), None)

        navn = f"{p['set_label']} {p['type_label']}"
        regionord = REGION_ORD.get(p["region"], "")
        # Tittelen er det eneste Google viser i sin helhet. Den maa inneholde
        # ordene folk faktisk soker paa: produktnavn + "pris" + "Norge".
        tittel = (f"{navn} – pris og lagerstatus i Norge | Pokepuls"
                  if p["region"] == "en"
                  else f"{navn} ({regionord}) – pris og lager i Norge | Pokepuls")
        if inne:
            besk = (f"{navn} er på lager hos {len(inne)} norske butikker nå. "
                    f"Billigst: {_kr(billigst)}. Priser fra "
                    f"{', '.join(sorted({t['store_name'] for t in inne})[:5])} "
                    f"– oppdatert hvert 20. minutt.")
        elif bestill:
            besk = (f"{navn} er ikke på lager hos noen av de {len(tilbud)} norske "
                    f"butikkene vi følger, men kan forhåndsbestilles hos "
                    f"{len(bestill)}. Få varsel når den kommer på lager.")
        else:
            besk = (f"{navn} er utsolgt hos alle {len(tilbud)} norske butikker vi "
                    f"følger. Få varsel på telefonen når den kommer på lager igjen.")

        # JSON-LD: dette er det som gir pris og «på lager» rett i Google-treffet.
        jsonld = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": navn,
            "description": besk,
            "category": "Pokémon TCG",
            "url": f"{BASE}/p/{produkt_id}",
        }
        if bilde:
            jsonld["image"] = bilde
        if tilbud:
            jsonld["offers"] = {
                "@type": "AggregateOffer",
                "priceCurrency": "NOK",
                "offerCount": len(tilbud),
                # PreOrder er en egen verdi i schema.org, og Google bruker
                # den. Aa melde InStock paa et forhaandssalg er feilmerking
                # av strukturerte data -- det straffes.
                "availability": ("https://schema.org/InStock" if inne
                                 else "https://schema.org/PreOrder" if bestill
                                 else "https://schema.org/OutOfStock"),
                **({"lowPrice": round(billigst / 100, 2),
                    "highPrice": round(max(t["price_ore"] for t in inne) / 100, 2)}
                   if inne else {}),
                "offers": [{
                    "@type": "Offer",
                    "url": t["url"],
                    "priceCurrency": "NOK",
                    "price": round(t["price_ore"] / 100, 2) if t["price_ore"] else None,
                    "availability": (
                        "https://schema.org/PreOrder" if t["bestillingstype"]
                        else "https://schema.org/InStock" if t["in_stock"]
                        else "https://schema.org/OutOfStock"),
                    "seller": {"@type": "Organization", "name": t["store_name"]},
                } for t in tilbud[:20] if t["price_ore"]],
            }

        def rad(t):
            return (f'<li class="side-tilbud">'
                    f'<a href="{_e(t["url"])}" rel="nofollow noopener" target="_blank">'
                    f'<span class="side-butikk">{_e(t["store_name"])}</span>'
                    f'<span class="side-tittel">{_e(t["title"])}</span></a>'
                    f'<span class="side-pris">{_e(_kr(t["price_ore"]) or "–")}</span>'
                    f'<span class="side-lager '
                    f'{"bestilling" if t["bestillingstype"] else "inne" if t["in_stock"] else "ute"}">'
                    f'{BESTILLING_ORD.get(t["bestillingstype"]) if t["bestillingstype"] else "På lager" if t["in_stock"] else "Utsolgt"}'
                    f'</span></li>')

        kropp = [
            _sidehode(tittel, besk, f"{BASE}/p/{produkt_id}", jsonld, bilde),
            '<header class="side-topp"><a class="side-hjem" href="/">'
            '<span class="merke-poke">poke</span><span class="merke-puls">puls</span>'
            "</a></header>",
            '<main class="side-innhold">',
            f"<h1>{_e(navn)}</h1>",
            f'<p class="side-under">{_e(p["set_label"])} · {_e(p["type_label"])}'
            + (f" · {_e(regionord)}" if p["region"] != "en" else "") + "</p>",
        ]
        if inne:
            kropp.append(f'<p class="side-status inne">På lager hos {len(inne)} '
                         f'butikk{"er" if len(inne) > 1 else ""} · billigst '
                         f'<strong>{_e(_kr(billigst))}</strong></p>')
        elif bestill:
            kropp.append(f'<p class="side-status bestilling">Ikke på lager, men '
                         f'kan forhåndsbestilles hos {len(bestill)} '
                         f'butikk{"er" if len(bestill) > 1 else ""}.</p>')
        else:
            kropp.append('<p class="side-status ute">Utsolgt hos alle butikker '
                         'vi følger akkurat nå.</p>')

        kropp.append(f'<p><a class="side-cta" href="/?produkt={_e(produkt_id)}">'
                     "Følg denne varen og få varsel når den kommer inn →</a></p>")

        if inne:
            kropp.append("<h2>På lager nå</h2><ul class=\"side-liste\">"
                         + "".join(rad(t) for t in inne) + "</ul>")
        if bestill:
            kropp.append("<h2>Forhåndssalg og bestillingsvarer</h2>"
                         '<p class="side-under">Kan bestilles, men sendes ikke nå.</p>'
                         '<ul class="side-liste">'
                         + "".join(rad(t) for t in bestill) + "</ul>")
        if ute:
            kropp.append("<h2>Utsolgt</h2><ul class=\"side-liste\">"
                         + "".join(rad(t) for t in ute) + "</ul>")

        kropp.append("</main>" + SIDEFOT)
        return Response("".join(kropp), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=300, "
                                                  "stale-while-revalidate=3600"})

    app.include_router(router)
