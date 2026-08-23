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
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(tags=["sider"])

BASE = "https://pokepuls.no"
_ROT = Path(__file__).resolve().parent.parent
REGION_ORD = {"en": "engelsk", "jp": "japansk", "cn": "kinesisk", "ko": "koreansk"}

# Bare produkter med ekte tilbud kommer i sidekartet. Aa be Google indeksere
# 460 sider der halvparten er tomme er en rask maate aa laere den at
# domenet ikke er verdt aa krype.
# Forsiden, serverrendret.
#
# HVORFOR
#
# Forsiden var et JavaScript-skall. Det forste en soekemotor saa var ordet
# «laster…». Produktsidene og oversiktene rangerte, men SELVE forsiden --
# den folk lenker til, og den som skal treffe «pokemon kort pa lager norge»
# -- hadde ingen tekst i det hele tatt.
#
# Google kjorer riktignok JavaScript, men det skjer i en egen ko, dager
# senere, og det rangerer daarligere. Konkurrentene serverer ferdig HTML.
#
# To dagers vindu: en vare som ikke er sett paa to dogn hoerer ikke hjemme
# paa forsiden uansett hvor fin den ser ut i databasen.
FORSIDE_SQL = """
SELECT p.id, s.label AS set_label, p.region, t.label AS type_label,
       s.release_date,
       min(l.price_ore) FILTER (
         WHERE l.in_stock AND l.bestillingstype IS NULL) AS pris,
       count(*) FILTER (
         WHERE l.in_stock AND l.bestillingstype IS NULL) AS butikker
FROM products p
JOIN sets s ON s.id = p.set_id
JOIN product_types t ON t.id = p.type_id
JOIN listings l ON l.product_id = p.id
WHERE l.last_seen_at > now() - interval '2 days'
GROUP BY p.id, s.label, p.region, t.label, s.release_date, t.sort_order
HAVING count(*) FILTER (WHERE l.in_stock AND l.bestillingstype IS NULL) > 0
ORDER BY s.release_date DESC NULLS LAST, s.label, t.sort_order
LIMIT 150
"""

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

# Andre produkter i samme sett.
#
# HVORFOR DETTE ER SEO OG IKKE PYNT
#
# Produktsidene laa som oyer: sitemap inn, ingen lenker mellom dem. En
# soekemotor maatte tilbake til sitemap for hver eneste side, og ingen side
# gav noen annen side vekt. Interne lenker er det billigste som finnes for
# aa faa dype sider indeksert -- og for et menneske som ser paa en ETB er
# «hva annet finnes i dette settet» uansett neste spoersmaal.
#
# Bare produkter vi faktisk har en oppforing paa. En lenke til en tom side
# er verre enn ingen lenke.
SOSKEN_SQL = """
SELECT p.id, s.label AS set_label, t.label AS type_label, p.region,
       count(*) FILTER (WHERE l.in_stock) AS inne
FROM products p
JOIN sets s ON s.id = p.set_id
JOIN product_types t ON t.id = p.type_id
JOIN listings l ON l.product_id = p.id
WHERE p.set_id = (SELECT set_id FROM products WHERE id = %s)
  AND p.id <> %s
  AND l.last_seen_at > now() - interval '14 days'
GROUP BY p.id, s.label, t.label, p.region
ORDER BY count(*) FILTER (WHERE l.in_stock) DESC, t.label
LIMIT 12
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


# Cacheversjonen paa CSS-en. Den sto hardkodet her og hadde drevet fra
# resten av nettstedet -- serverrendrede sider ba om v24 mens alt annet var
# paa v26. Den slags oppdager ingen: siden ser riktig ut, den er bare gammel.
#
# Testen tests/test_sider.py binder dette tallet til sw.js, saa de to ikke
# kan gaa fra hverandre igjen uten at noe blir rodt.
CSS_V = 31


# Hvem nettstedet er. Google bruker den til aa knytte sammen treff fra samme
# avsender, og til aa vise sokefeltet «sok paa pokepuls.no» rett i resultatet.
NETTSTED_LD = {
    "@type": "WebSite",
    "@id": "https://pokepuls.no/#nettsted",
    "name": "Pokepuls",
    "url": "https://pokepuls.no/",
    "inLanguage": "nb-NO",
    "potentialAction": {
        "@type": "SearchAction",
        "target": {"@type": "EntryPoint",
                   "urlTemplate": "https://pokepuls.no/?sok={search_term_string}"},
        "query-input": "required name=search_term_string",
    },
}


_SKALL: dict = {"mtid": None, "html": ""}


def _skallet() -> str:
    """web/index.html, lest fra disk og hurtiglagret paa endringstidspunkt.

    ÉN kilde til forsidens skall. Kopierte vi HTML-en inn i Python, ville vi
    hatt to forsider aa holde i takt -- og den ene ville blitt glemt neste
    gang noen la til en fane.
    """
    fil = _ROT / "web" / "index.html"
    try:
        mtid = fil.stat().st_mtime
    except OSError:
        return ""
    if _SKALL["mtid"] != mtid:
        _SKALL["html"] = fil.read_text(encoding="utf-8")
        _SKALL["mtid"] = mtid
    return _SKALL["html"]


def _dager_siden(tid) -> str:
    """«3 dager siden». Et tall er en paastand man kan gjore noe med;
    «ikke automatisert» er det ikke."""
    if not tid:
        return "aldri"
    from datetime import datetime, timezone
    d = (datetime.now(timezone.utc) - tid).days
    return "i dag" if d < 1 else "i g\u00e5r" if d == 1 else f"{d} dager siden"


def _sidehode(tittel: str, beskrivelse: str, kanonisk: str, jsonld=None,
              bilde: str | None = None) -> str:
    # Alt legges i én @graph. To losrevne script-blokker er lovlig, men da
    # maa Google gjette at de handler om samme side -- i en graf staar det.
    graf = [NETTSTED_LD]
    if jsonld:
        graf += jsonld if isinstance(jsonld, list) else [jsonld]
    ld = ('<script type="application/ld+json">%s</script>'
          % json.dumps({"@context": "https://schema.org", "@graph": graf},
                       ensure_ascii=False))
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
<link rel="stylesheet" href="/style.css?v={CSS_V}">
{ld}
</head><body class="side">"""


SIDEFOT = """
<footer class="bunn">
  <nav class="bunn-lenker" aria-label="Sidekart">
    <a href="/">Forsiden</a>
    <a href="/om.html">Om Pokepuls</a>
    <a href="/butikker">Butikker</a>
    <a href="/kalender">Slippkalender</a>
    <a href="/statistikk.html">Statistikk</a>
    <a href="/vilkar.html">Vilk&aring;r</a>
    <a href="/personvern.html">Personvern</a>
    <a href="/om.html#kontakt">Kontakt</a>
  </nav>
  <p class="bunn-tekst">Pokepuls er en uavhengig tjeneste, og er ikke tilknyttet
  Pok&eacute;mon, Nintendo, Creatures Inc. eller GAME FREAK inc. Vi er ikke en
  butikk &mdash; kj&oslash;p, betaling og levering skjer hos butikkene vi lenker til.</p>
  <p class="bunn-tekst">Priser og lagerstatus hentes automatisk og kan v&aelig;re
  opptil 20 minutter gamle. <strong>Bekreft alltid hos butikken f&oslash;r du
  kj&oslash;per.</strong></p>
  <p class="bunn-merke">&copy; 2026 Pokepuls</p>
</footer>
</body></html>"""


def _svar_html(request, html: str) -> Response:
    """Ferdig side med sidefot og fornuftig cache.

    Fem minutter: butikkoversikten endrer seg med hver skanning, og en
    kalender som er en time gammel er ikke feil -- men en butikkliste som
    sier «12 inne» naar det er null, er det.
    """
    return Response(html + SIDEFOT, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=300, "
                                              "stale-while-revalidate=3600"})


def _ikke_funnet() -> str:
    # f-streng: den eneste klammen i teksten er {CSS_V}. Uten f-en sto
    # «?v={CSS_V}» ordrett i HTML-en -- og den ville aldri lastet CSS.
    return f"""<!DOCTYPE html>
<html lang="no"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0d10">
<meta name="robots" content="noindex">
<title>Fant ikke varen – Pokepuls</title>
<link rel="stylesheet" href="/style.css?v={CSS_V}">
</head><body class="side">
<main class="side-innhold">
  <h1>Vi fant ikke den varen</h1>
  <p class="hjelp">Enten finnes den ikke lenger hos noen av butikkene vi
  følger, eller så er lenken skrevet feil. Begge deler skjer — en vare kan
  bli avpublisert lenge etter at noen delte lenken.</p>
  <p><a class="hovedknapp smal" href="/">Søk i alle produktene</a></p>
  <p class="hjelp liten"><a href="/">Pokepuls</a> følger priser og lagerstatus
  på forseglede Pokémon-produkter hos norske butikker.</p>
</main>
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
        for sti, hyppig, prio in [("/butikker", "daily", "0.7"),
                                  ("/kalender", "daily", "0.7"),
                                  ("/om.html", "monthly", "0.5"),
                                  ("/vilkar.html", "yearly", "0.3"),
                                  ("/personvern.html", "yearly", "0.3")]:
            deler.append(f"<url><loc>{BASE}{sti}</loc><lastmod>{na}</lastmod>"
                         f"<changefreq>{hyppig}</changefreq>"
                         f"<priority>{prio}</priority></url>")
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
            # Forhandsvisningen viser de samme varene som forsiden. To
            # sider med samme innhold konkurrerer med hverandre, og den
            # ene av dem er en kladd.
            "Disallow: /ny\n"
            "\n"
            f"Sitemap: {BASE}/sitemap.xml\n",
            media_type="text/plain",
            headers={"Cache-Control": "public, max-age=86400"})

    # ------------------------------------------------------- produktside

    # ------------------------------------------------------ butikkoversikt

    BUTIKKER_SQL = """
    -- FRISKHETSFILTERET MAA GJELDE ALLE TRE TALLENE.
    --
    -- `varer` filtrerte paa siste sju dogn. `inne` og `billigst` gjorde det
    -- ikke. Derfor sto Emken med «17 varer» og «41 inne» -- flere paa lager
    -- enn butikken hadde varer.
    --
    -- Verre enn at det ser rart ut: «inne» talte oppforinger vi ikke har
    -- sett paa uker, og «billigst» kunne vise en pris fra en vare som ikke
    -- har eksistert siden juni. Det er den slags tall folk stoler paa naar
    -- de velger butikk.
    SELECT s.id, s.name,
           count(l.id) FILTER (WHERE l.last_seen_at > now() - interval '7 days')
             AS varer,
           count(l.id) FILTER (WHERE l.in_stock AND l.bestillingstype IS NULL
                               AND l.last_seen_at > now() - interval '7 days')
             AS inne,
           min(l.price_ore) FILTER (WHERE l.in_stock AND l.bestillingstype IS NULL
                                    AND l.last_seen_at > now() - interval '7 days')
             AS billigst,
           max(l.last_ok_at) AS sist
    FROM stores s LEFT JOIN listings l ON l.store_id = s.id
    GROUP BY s.id, s.name
    ORDER BY inne DESC, varer DESC, s.name
    """

    @router.get("/butikker")
    async def butikker(request: Request):
        """Alle butikkene vi foelger, med hvor mye de har inne akkurat na.

        Dette er en side ingen konkurrent kan kopiere uten aa gjore det
        samme arbeidet: den ER dekningen. Og den svarer paa et sok folk
        faktisk gjor -- «norske pokemon-butikker».
        """
        rader = await _hent(BUTIKKER_SQL)
        aktive = [r for r in rader if r["varer"]]

        # SKILL MELLOM «VI LESER DEN IKKE» OG «VI LESER DEN, MEN FIKK NULL».
        #
        # Begge sto tidligere under «Kartlagt, men ikke automatisert» -- og
        # da leste siden en OEDELAGT skraper som et valg vi hadde tatt.
        # Emken, Collectible og Ark sto slik i minst sju dager.
        #
        # Det er den samme feilen som gaar igjen overalt her: en butikk som
        # leverer null feiler ikke, den tier. Skjuler vi tausheten bak en
        # pen overskrift, blir den aldri oppdaget.
        #
        # `sist` = siste vellykkede skanning. Har vi ALDRI hatt tall, er
        # butikken kartlagt men ikke automatisert. Har vi hatt tall for og
        # ikke naa, er noe i stykker.
        tomme = [r for r in rader if not r["varer"]]
        stille = [r for r in tomme if r["sist"]]
        aldri = [r for r in tomme if not r["sist"]]
        totalt_inne = sum(r["inne"] or 0 for r in aktive)

        def _rad(r):
            pris = (f"<td class=\"tall\">fra {_kr(r['billigst'])}</td>"
                    if r["billigst"] else '<td class="tall">&ndash;</td>')
            return ("<tr><td><strong>" + _e(r["name"]) + "</strong></td>"
                    f"<td class=\"tall\">{r['varer']}</td>"
                    f"<td class=\"tall\">{r['inne']}</td>" + pris + "</tr>")

        html = _sidehode(
            "Norske Pok\u00e9mon-butikker vi f\u00f8lger \u2013 pris og lager | Pokepuls",
            f"Pokepuls f\u00f8lger {len(aktive)} norske nettbutikker som selger "
            f"forseglede Pok\u00e9mon-produkter. Se hvem som har mest inne n\u00e5, "
            "og hvor det er billigst.",
            BASE + "/butikker",
            {
                "@type": "ItemList",
                "name": "Norske nettbutikker med Pok\u00e9mon-produkter",
                "numberOfItems": len(aktive),
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1,
                     "item": {"@type": "Organization", "name": r["name"]}}
                    for i, r in enumerate(aktive[:50])
                ],
            })
        html += "<main class=\"side-innhold\"><h1>Butikkene vi f\u00f8lger</h1>"
        html += (f'<p class="side-under">{len(aktive)} norske nettbutikker '
                 f"\u00b7 {totalt_inne} varer p\u00e5 lager akkurat n\u00e5</p>")
        html += ("<p>Listen oppdateres automatisk hver kj\u00f8ring. «Inne» teller "
                 "bare varer du kan f\u00e5 i posten \u2014 forh\u00e5ndssalg og "
                 "bestillingsvarer er holdt utenfor, fordi de ikke er det samme.</p>")
        html += ('<div class="tabell-side"><table><thead><tr><th>Butikk</th>'
                 '<th class="tall">Varer</th><th class="tall">Inne</th>'
                 '<th class="tall">Billigst</th></tr></thead><tbody>')
        html += "".join(_rad(r) for r in aktive)
        html += "</tbody></table></div>"
        if tomme:
            if aldri:
                html += ("<h2>Kartlagt, men ikke automatisert</h2>"
                         "<p>Disse stenger ute automatiske bes\u00f8k, eller "
                         "kj\u00f8rer en plattform vi ikke leser enn\u00e5. Vi later "
                         "ikke som om vi har ferske tall fra dem.</p>"
                         "<p class=\"hjelp\">"
                         + ", ".join(_e(r["name"]) for r in aldri) + "</p>")
            if stille:
                html += ("<h2>Uten ferske tall</h2>"
                         "<p>Disse har vi lest f\u00f8r, men f\u00e5r ikke noe fra n\u00e5. "
                         "Som regel har butikken lagt om nettsiden sin. Vi viser "
                         "det heller enn \u00e5 la raden st\u00e5 tom.</p>"
                         "<ul class=\"side-liste-tekst\">"
                         + "".join(f"<li>{_e(r['name'])} \u2014 sist "
                                   f"{_dager_siden(r['sist'])}</li>"
                                   for r in stille) + "</ul>")
        html += ('<p><a class="hovedknapp smal" href="/">Se alle produktene</a></p>'
                 "</main>")
        return _svar_html(request, html)

    # ------------------------------------------------------------- forsiden

    @router.get("/")
    async def forside(request: Request):
        """Forsiden med ekte innhold i HTML-en.

        Appen tar over saa snart app.js har kjort -- den skriver over bade
        #teller og #liste med ferske tall fra API-et. Det som staar her er
        altsaa forstevisningen og det soekemotoren leser, og de to viser det
        SAMME: samme varer, samme priser, samme butikkantall.

        Det er ikke en detalj. Serverer man én ting til Google og en annen
        til folk, heter det cloaking, og det er en av de faa tingene som gir
        manuell straff.
        """
        skall = _skallet()
        if not skall:
            # Uten skallet har vi ingenting aa injisere i. Da er det bedre
            # at nginx serverer filen selv enn at vi finner paa noe.
            raise HTTPException(503, "Forsiden er ikke tilgjengelig.")

        rader = await _hent(FORSIDE_SQL)

        # Grupper paa sett OG region -- ellers havner den engelske, japanske
        # og kinesiske utgaven av samme sett i samme bolk, og listen ser ut
        # til aa vise «Booster Box» tre ganger uten forklaring.
        bolker: dict[tuple, list] = {}
        for r in rader:
            bolker.setdefault((r["set_label"], r["region"]), []).append(r)

        biter = []
        for (sett, region), varer in bolker.items():
            merke = ("" if region == "en"
                     else f' <span class="merkelapp {_e(region)}">'
                          f'{_e(REGION_ORD.get(region, region))}</span>')
            biter.append(f'<div class="sett-tittel">{_e(sett)}{merke}</div>')
            for v in varer:
                pris = _kr(v["pris"]) or "\u2013"
                butikker = v["butikker"]
                biter.append(
                    f'<a class="kort" href="/p/{_e(v["id"])}">'
                    f'<span class="kort-venstre">'
                    f'<span class="kort-navn">{_e(v["type_label"])}</span>'
                    f'<span class="kort-under">{butikker} '
                    f'butikk{"er" if butikker != 1 else ""} p\u00e5 lager</span>'
                    f'</span>'
                    f'<span class="kort-pris">{_e(pris)}</span></a>')

        antall = len(rader)
        teller = (f"{antall} forseglede Pok\u00e9mon-produkter er p\u00e5 lager hos "
                  f"norske nettbutikker akkurat n\u00e5. Prisene hentes automatisk "
                  f"og oppdateres gjennom hele d\u00f8gnet.")

        html = skall.replace(
            '<p class="teller" id="teller"></p>',
            f'<p class="teller" id="teller">{teller}</p>', 1)
        html = html.replace(
            '<div id="liste" class="liste"></div>',
            '<div id="liste" class="liste">' + "".join(biter) + "</div>", 1)

        return Response(html, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=60, "
                                                  "stale-while-revalidate=600"})

    # --------------------------------------------------------- slippkalender

    KALENDER_SQL = """
    SELECT s.id, s.label, s.region, s.release_date,
           count(DISTINCT p.id) FILTER (WHERE l.id IS NOT NULL) AS produkter,
           count(l.id) FILTER (WHERE l.in_stock AND l.bestillingstype = 'forhandssalg')
             AS forhandssalg
    FROM sets s
    LEFT JOIN products p ON p.set_id = s.id
    LEFT JOIN listings l ON l.product_id = p.id
    WHERE s.release_date IS NOT NULL
    GROUP BY s.id, s.label, s.region, s.release_date
    ORDER BY s.release_date
    """

    MND = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
           "august", "september", "oktober", "november", "desember"]

    @router.get("/kalender")
    async def kalender(request: Request):
        rader = await _hent(KALENDER_SQL)
        i_dag = datetime.now(timezone.utc).date()
        kommende = [r for r in rader if r["release_date"] >= i_dag]
        tidligere = [r for r in rader if r["release_date"] < i_dag]

        def _post(r):
            d = r["release_date"]
            dager = (d - i_dag).days
            naar = (f"om {dager} dager" if dager > 1 else
                    "i morgen" if dager == 1 else
                    "i dag" if dager == 0 else "sluppet")
            linje = f"{d.day}. {MND[d.month - 1]} {d.year}"
            ut = ('<div class="kal-post"><div class="kal-dato">' + _e(linje) +
                  f'<span class="kal-naar">{_e(naar)}</span></div>'
                  "<h3>" + _e(r["label"]) + "</h3>")
            if r["forhandssalg"]:
                ut += (f'<p class="hjelp">{r["forhandssalg"]} butikkoppf\u00f8ringer '
                       "til forh\u00e5ndsbestilling n\u00e5.</p>")
            elif r["produkter"]:
                ut += (f'<p class="hjelp">{r["produkter"]} produkter er lagt ut hos '
                       "butikkene, men ingen tar bestilling akkurat n\u00e5.</p>")
            else:
                ut += '<p class="hjelp">Ingen norske butikker har lagt ut settet enn\u00e5.</p>'
            return ut + "</div>"

        html = _sidehode(
            "Slippkalender for Pok\u00e9mon-kort \u2013 kommende sett | Pokepuls",
            "N\u00e5r slippes de neste Pok\u00e9mon-settene, og hvilke norske butikker "
            "har \u00e5pnet for forh\u00e5ndsbestilling? Oppdateres automatisk.",
            BASE + "/kalender",
            {
                "@type": "ItemList",
                "name": "Kommende Pok\u00e9mon-sett",
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1,
                     "item": {"@type": "Product", "name": r["label"],
                              "releaseDate": str(r["release_date"])}}
                    for i, r in enumerate(kommende[:25])
                ],
            })
        html += "<main class=\"side-innhold\"><h1>Slippkalender</h1>"
        html += ("<p>N\u00e5r de neste settene kommer, og hvor langt de norske "
                 "butikkene har kommet med forh\u00e5ndssalg. F\u00f8lg et sett i appen, "
                 "s\u00e5 f\u00e5r du beskjed i det den f\u00f8rste butikken \u00e5pner.</p>")
        if kommende:
            html += "<h2>Kommer</h2>" + "".join(_post(r) for r in kommende)
        else:
            html += '<p class="hjelp">Ingen bekreftede slipp framover akkurat n\u00e5.</p>'
        if tidligere:
            html += "<h2>Nylig sluppet</h2>" + "".join(_post(r) for r in tidligere[-6:])
        html += ('<p><a class="hovedknapp smal" href="/">Se hva som er p\u00e5 lager</a></p>'
                 "</main>")
        return _svar_html(request, html)

    @router.get("/p/{produkt_id}")
    async def produktside(request: Request, produkt_id: str):
        rader = await _hent(PRODUKT_SQL, produkt_id)
        if not rader:
            # En ekte side, ikke {"detail":"Not Found"}. Disse URL-ene deles
            # i Facebook-grupper og paa Discord, og de overlever produktet:
            # en vare kan bli avpublisert lenge etter at lenken ble delt.
            # Statuskoden er fortsatt 404 -- Google skal ikke indeksere den
            # -- men mennesket som klikket skal faa en vei videre.
            return Response(content=_ikke_funnet(), status_code=404,
                            media_type="text/html; charset=utf-8")
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

        # Brodsmuler. Google viser dem i stedet for den raa adressen i
        # treffet, og de forteller hvor siden hoerer hjemme.
        jsonld = [jsonld, {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Pokepuls",
                 "item": BASE + "/"},
                {"@type": "ListItem", "position": 2,
                 "name": p["set_label"], "item": f"{BASE}/p/{produkt_id}"},
                {"@type": "ListItem", "position": 3, "name": navn},
            ],
        }]

        sosken = await _hent(SOSKEN_SQL, produkt_id, produkt_id)

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

        if sosken:
            kropp.append(f'<h2>Mer fra {_e(p["set_label"])}</h2>'
                         '<ul class="side-sosken">'
                         + "".join(
                             f'<li><a href="/p/{_e(r["id"])}">{_e(r["type_label"])}'
                             + (f' ({_e(REGION_ORD.get(r["region"], ""))})'
                                if r["region"] != "en" else "")
                             + "</a>"
                             + (f' <span class="side-sosken-inne">{r["inne"]} inne</span>'
                                if r["inne"] else "")
                             + "</li>" for r in sosken)
                         + "</ul>")

        kropp.append('<p class="side-mer"><a href="/butikker">Alle butikkene vi '
                     'følger</a> · <a href="/kalender">Slippkalender</a></p>')

        kropp.append("</main>" + SIDEFOT)
        return Response("".join(kropp), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "public, max-age=300, "
                                                  "stale-while-revalidate=3600"})

    app.include_router(router)
