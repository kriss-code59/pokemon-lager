"""
Pokemon-lagerscanner for norske nettbutikker.

Scanner ca. 35 norske nettbutikker (se SHOPIFY_STORES og PLAYWRIGHT_SITES) for
Pokemon-produkter og lagrer resultatet som JSON (docs/data.json) som
dashboardet leser. I tillegg lagres alle lagerhendelser (nye varer, restock,
utsolgt, prisendring) i docs/history.json (brukes av statistikk-/
nyheter-sidene), og de enkleste hendelsene (restock/nye varer, siste 14
dager) i docs/changes.json (brukes av forsidens "Nylig restocket"-seksjon).

De fleste butikkene bruker en av fire kjente plattformer, som lar oss bruke
generiske scrapere i stedet for a skreddersy en per butikk:
  - Shopify (offentlig products.json-API) -- se scrape_shopify_store()
  - "24Nettbutikk" (norsk plattform, schema.org-markup) -- se scrape_nettbutikk24()
  - QuickButik (norsk/nordisk plattform, data-s-title/data-s-price-attributter
    direkte pa produktkortet) -- se scrape_quickbutik()
  - WooCommerce (instock/outofstock-klasser direkte pa produktkortet,
    uavhengig av tema) -- se scrape_woocommerce()
Butikker med egne/uvanlige plattformer (Ark, Nille, Outland, Lekekassen,
Maxgaming) bruker enten en egen funksjon eller generiske CSS-selektorer i
PLAYWRIGHT_SITES (card_selector/name_selector/price_selector).

Norli, PokeMadness og CardCollect blokkerer automatiske nettleserbesok, eller
krever mer arbeid enn de andre (Norli: HTTP 403, PokeMadness:
Cloudflare-utfordring, CardCollect: klientrendret Nuxt-app uten
skrapbar HTML/API vi har verifisert). Vi bygger ikke inn teknikker for a
omga blokkeringer (ingen fingerprint-triksing e.l.), sa disse butikkene
vises i stedet som "sjekk manuelt" i dashboardet, med en direkte lenke til
butikkens Pokemon-side -- se MANUAL_CHECK_STORES.

Kjor lokalt:
    pip install -r requirements.txt
    playwright install chromium
    python scrape.py
"""

import json
import re
import time
import datetime
import unicodedata
from dataclasses import dataclass, asdict
from urllib.request import urlopen, Request

from playwright.sync_api import sync_playwright

# Hvor lenge vi venter mellom hver butikk (vaer snill mot serverne deres)
DELAY_BETWEEN_SITES = 3

# User-Agent som identifiserer boten aerlig (god praksis ved scraping)
USER_AGENT = "PokemonLagerBot/1.0 (privat prosjekt, kontakt: <legg inn din e-post>)"

IN_STOCK_WORDS = ["pa lager", "pa nettlager", "legg i handlekurv", "legg i handlevogn", "kjop na"]
OUT_OF_STOCK_WORDS = ["utsolgt", "ikke pa lager", "ikke tilgjengelig", "sold out"]

# Matcher norske prisformater som "249,00 kr", "249 kr", "kr 249,-"
PRICE_PATTERN = re.compile(r"(\d[\d\s]*[.,]?\d*)\s*,?-?\s*kr\b|kr\s*(\d[\d\s]*[.,]?\d*)", re.IGNORECASE)


def extract_price_fallback(text: str) -> str | None:
    match = PRICE_PATTERN.search(text)
    if match:
        return match.group(0).strip()
    return None


@dataclass
class Product:
    store: str
    name: str
    price: str
    in_stock: bool | None  # None = vi klarte ikke a avgjore lagerstatus
    url: str
    store_count: int | None = None  # antall fysiske butikker med varen (kun noen butikker oppgir dette)


_NORWEGIAN_LETTER_MAP = str.maketrans({
    "æ": "ae", "Æ": "AE",  # ae-ligatur
    "ø": "o", "Ø": "O",  # o-skra (dekomponeres ikke av NFKD)
})


def strip_diacritics(text: str) -> str:
    """Fjerner norske diakritiske tegn (bl.a. a-ring, o-skra, ae-ligatur) sa vi
    kan matche mot IN_STOCK_WORDS/OUT_OF_STOCK_WORDS, som er skrevet uten dem
    (denne fila er ren ASCII av design). Uten dette ville f.eks. ekte
    sidetekst "Pa lager" (med a-ring) aldri matche monsteret "pa lager" (uten).
    ae og o-skra dekomponeres ikke av NFKD (de er egne bokstaver, ikke
    grunnbokstav+aksent i Unicode), sa de ma erstattes eksplisitt."""
    text = text.translate(_NORWEGIAN_LETTER_MAP)
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def classify_stock(text: str) -> bool | None:
    """Gir True (pa lager), False (utsolgt) eller None (usikker) basert pa tekst."""
    t = strip_diacritics(text.lower())
    has_out = any(w in t for w in OUT_OF_STOCK_WORDS)
    has_in = any(w in t for w in IN_STOCK_WORDS)
    if has_out and not has_in:
        return False
    if has_in and not has_out:
        return True
    if has_out:
        return False
    return None


def get_norli_online_stock(page) -> bool | None:
    """Norli skiller mellom nettlager og lager i fysiske butikker (klikk-og-hent).
    Vi vil kun vite om varen kan kjopes pa nett akkurat na, sa vi leter
    spesifikt etter nettlager-teksten ("Pa lager" / "Ikke pa lager") og
    ignorerer klikk-og-hent-status for fysiske butikker (som har klassenavn
    som inneholder "clickPickup")."""
    try:
        text = page.evaluate(
            """
            () => {
                const els = [...document.querySelectorAll('b, strong, span, div')];
                for (const el of els) {
                    if (el.children.length > 0) continue;
                    const t = el.textContent.trim();
                    if ((t === 'Pa lager' || t === 'Ikke pa lager') && !el.className.includes('clickPickup')) {
                        return t;
                    }
                }
                return null;
            }
            """
        )
    except Exception:
        return None
    if text == "Pa lager":
        return True
    if text == "Ikke pa lager":
        return False
    return False


def diagnose_possible_block(page) -> str | None:
    """Sjekker om siden ser ut som en bot-blokkerings-/captcha-side i stedet for
    den vanlige nettbutikk-siden. Brukes KUN til logging/diagnostikk slik at vi
    kan se i kjoringsloggen hva som faktisk skjedde -- vi provver ALDRI a omga
    en slik blokkering (ingen fingerprint-triksing e.l., det bygger vi ikke inn)."""
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        snippet = page.inner_text("body")[:300]
    except Exception:
        snippet = ""
    combined = (title + " " + snippet).lower()
    block_markers = [
        "captcha", "cloudflare", "just a moment", "attention required",
        "access denied", "forbidden", "unusual traffic", "blocked",
        "robot", "are you human", "verify you are human",
    ]
    hits = [m for m in block_markers if m in combined]
    if hits:
        return f"tittel='{title}', mistenkelige ord: {', '.join(hits)}"
    return None


# ---------------------------------------------------------------------------
# SHOPIFY-BUTIKKER -- alle Shopify-butikker har et offentlig products.json-API
# per samling, mye mer robust enn a scrape HTML. Vi bruker det direkte i
# stedet for Playwright for alle disse butikkene.
#
# "variant_mode" styrer hvordan vi haandterer produkter med flere Shopify-
# varianter:
#   - "each": hver variant blir en egen Product med variant-id i URL-en
#     (Shopify sitt ?variant=-format). Naadvendig naar varianter kan vaere
#     reelt ULIKE produkter (f.eks. "Booster Box" og "Booster Pack" paa
#     samme produktoppfoering, eller ulike sett/tilstander for loskort) --
#     ellers ville vi blande sammen pris/lagerstatus for ulike varer, og
#     flere varianter ville kollidert i "url"-noekkelen som resten av koden
#     (lagerhendelser, produktside-oppslag) bruker til aa identifisere varer.
#   - "first": kun variants[0] sin pris brukes, og lagerstatus er "noen
#     variant tilgjengelig". Egnet naar variantene kun er stoerrelse/farge
#     av samme vare (Cardcenter sitt opprinnelige oppsett).
#
# "require_pokemon_title" brukes for butikker der samlingene ogsaa inneholder
# andre spill/tilbehoer (f.eks. Braspill er en generell brettspillbutikk) --
# da hopper vi over produkter som ikke har "pokemon" i tittelen.
# ---------------------------------------------------------------------------
SHOPIFY_STORES = [
    {
        "store": "Cardcenter",
        "base_url": "https://cardcenter.no",
        "collections": ["pokemon", "pokemon-booster-pakker", "booster-boxer", "elite-trainer-boxer", "collection-bokser"],
        "variant_mode": "first",
    },
    {
        "store": "Pokelageret",
        "base_url": "https://pokelageret.no",
        "collections": ["pokemon"],
        "variant_mode": "each",
    },
    {
        "store": "Arcticloot",
        "base_url": "https://arcticloot.no",
        "collections": ["pokemon-tcg", "pokemon-single-kort", "japansk-pokemon", "mega-pokemon"],
        "variant_mode": "each",
    },
    {
        "store": "BoosterKongen",
        "base_url": "https://boosterkongen.no",
        "collections": ["engelske-pokemon-produkter", "japanske-pokemon-produkter", "kinesiske-pokemon-produkter"],
        "variant_mode": "each",
    },
    {
        "store": "Braspill",
        "base_url": "https://braspill.no",
        "collections": ["engelsk", "japansk", "kinesisk-pokemon", "singles"],
        "variant_mode": "each",
        # Braspill er en generell brettspill-/TCG-butikk -- disse samlingene
        # inneholder ogsaa andre spill (bl.a. One Piece) og tilbehoer/frakt.
        "require_pokemon_title": True,
    },
    {
        "store": "Cardstore",
        # OBS: www.cardstore.no er en separat "headless" Shopify Hydrogen-
        # butikk der /products.json ikke virker -- den klassiske butikken
        # med API ligger paa store.cardstore.no.
        "base_url": "https://store.cardstore.no",
        "collections": ["pokemon"],
        "variant_mode": "each",
    },
    {
        "store": "EpiCards",
        "base_url": "https://epicards.no",
        "collections": ["pokemon-kort"],
        "variant_mode": "each",
    },
    {
        "store": "LABOGE",
        "base_url": "https://laboge.no",
        "collections": [""],  # hele butikken er Pokemon-fokusert
        "variant_mode": "each",
    },
    {
        "store": "NorthTCG",
        "base_url": "https://northtcg.no",
        "collections": ["pokemon-page"],
        "variant_mode": "each",
    },
    {
        "store": "Packs of Norway",
        "base_url": "https://packsofnorway.no",
        "collections": [""],  # hele butikken er (semi-)vintage Pokemon-pakker
        "variant_mode": "each",
    },
    {
        "store": "PokeNordic",
        "base_url": "https://pokenordic.no",
        "collections": ["engelsk-japanske-produkter"],
        "variant_mode": "each",
    },
    {
        "store": "Pokebua",
        "base_url": "https://pokebua.no",
        "collections": [""],  # hele butikken er Pokemon (sealed + graderte kort)
        "variant_mode": "each",
    },
    {
        "store": "Pokefriends",
        "base_url": "https://pokefriends.no",
        "collections": ["all"],  # hele butikken er Pokemon-fokusert
        "variant_mode": "each",
    },
    {
        "store": "Pokelink",
        "base_url": "https://pokelink.no",
        "collections": ["alle"],
        "variant_mode": "each",
    },
    {
        "store": "Pokesingles",
        "base_url": "https://pokesingles.no",
        "collections": ["all"],  # loskort-marked, hele butikken er Pokemon
        "variant_mode": "each",
    },
    {
        "store": "Pokestore",
        "base_url": "https://pokestore.no",
        # Pokestore selger ogsaa Magic/One Piece/Yu-Gi-Oh/Weiss Schwarz --
        # "alt-pokemon" er samlingen som samler alt Pokemon-relatert.
        "collections": ["alt-pokemon"],
        "variant_mode": "each",
    },
    {
        "store": "RetroWorld",
        "base_url": "https://retroworld.no",
        "collections": ["pokemon-tcg"],
        "variant_mode": "each",
    },
    {
        "store": "Spillbua",
        "base_url": "https://spillbua.no",
        "collections": ["pokemon-tcg"],
        "variant_mode": "each",
    },
]


def scrape_shopify_collection(
    store: str, base_url: str, handle: str, variant_mode: str, require_pokemon_title: bool = False
) -> list[Product]:
    """Henter alle produkter i en Shopify-samling via det offentlige
    products.json-APIet, med paginering (viktig for store kataloger som
    Pokesingles). Tom handle ("") betyr "hele butikken" (products.json paa
    rot-nivaa) for butikker der ALT de selger er Pokemon."""
    products = []
    page_num = 1
    while True:
        collection_part = f"collections/{handle}/" if handle else ""
        url = f"{base_url}/{collection_part}products.json?limit=250&page={page_num}"
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"[{store}] Feil ved henting av {handle or 'produkter'} (side {page_num}): {e}")
            break

        page_products = data.get("products", [])
        if not page_products:
            break

        for p in page_products:
            title = p.get("title", "")
            if require_pokemon_title and "pokemon" not in title.lower() and "pokémon" not in title.lower():
                continue

            variants = p.get("variants", [])
            if variant_mode == "each":
                for v in variants:
                    variant_title = (v.get("title") or "").strip()
                    name = title if variant_title in ("", "Default Title") else f"{title} - {variant_title}"
                    product_url = f"{base_url}/products/{p['handle']}?variant={v['id']}"
                    products.append(
                        Product(
                            store=store,
                            name=name,
                            price=f"{v.get('price', '?')} kr",
                            in_stock=v.get("available"),
                            url=product_url,
                        )
                    )
            else:
                product_url = f"{base_url}/products/{p['handle']}"
                available = any(v.get("available") for v in variants)
                price = variants[0]["price"] if variants else "?"
                products.append(
                    Product(store=store, name=title, price=f"{price} kr", in_stock=available, url=product_url)
                )

        if len(page_products) < 250:
            break
        page_num += 1
        if page_num > 20:  # sikkerhetsgrense (5000 produkter i én samling)
            break
        time.sleep(0.5)

    return products


def scrape_shopify_store(config: dict) -> list[Product]:
    store = config["store"]
    base_url = config["base_url"]
    variant_mode = config.get("variant_mode", "each")
    require_pokemon_title = config.get("require_pokemon_title", False)
    products: list[Product] = []
    seen_urls = set()

    for handle in config["collections"]:
        batch = scrape_shopify_collection(store, base_url, handle, variant_mode, require_pokemon_title)
        for prod in batch:
            if prod.url in seen_urls:
                continue
            seen_urls.add(prod.url)
            products.append(prod)
        time.sleep(1)

    print(f"[{store}] Fant {len(products)} produkter totalt.")
    return products


# ---------------------------------------------------------------------------
# Generiske sider som trenger en ekte nettleser (Playwright): Ark, Norli og
# PokeMadness. Nille har sin egen dedikerte funksjon (scrape_nille) siden den
# viser pris/lagerstatus direkte i kategorikortene pa en helt annen mate.
#
# VIKTIG: Nettbutikker endrer ofte HTML-strukturen sin. Selektorene under er
# basert pa struktur observert i juli 2026. Hvis boten slutter a finne
# produkter pa en side, ma selektorene oppdateres -- bruk "Inspiser
# element" i nettleseren pa siden for a finne riktige klassenavn.
# ---------------------------------------------------------------------------

# poke-shop.no organiserer Pokemon-produkter i faste underkategorier (samme
# type inndeling som PokeMadness brukte: boosterbokser, boosterpakker osv.).
POKE_SHOP_CATEGORIES = [
    "https://poke-shop.no/butikk/alle-produkter/boosterbokser-1",
    "https://poke-shop.no/butikk/alle-produkter/boosterpakker-1",
    "https://poke-shop.no/butikk/alle-produkter/elite-trainer-box",
    "https://poke-shop.no/butikk/alle-produkter/spesialbokser",
    "https://poke-shop.no/butikk/alle-produkter/blistere-tins-1",
    "https://poke-shop.no/butikk/alle-produkter/decks",
    "https://poke-shop.no/butikk/alle-produkter/mystery-box",
    "https://poke-shop.no/butikk/alle-produkter/spill",
]

# Outland sitt Pokemon-univers har over 1000 produkter (klaer, figurer osv.),
# sa vi filtrerer pa nettsiden til kun TCG-relaterte formater (booster,
# boks-sett, deck, tin, blister) for a matche det de andre butikkene viser.
OUTLAND_URL = (
    "https://www.outland.no/c/brands/pokemon/q/category_uid/MjE2/book_cover/"
    "Blister,Boks-set,Booster%20Display,Booster%20Pack,Deck%20Boks,"
    "Theme%20Deck,Tin%20Boks"
)

PLAYWRIGHT_SITES = [
    {
        "store": "Ark",
        "urls": [
            "https://www.ark.no/merkevarer/pokemon",
        ],
        "card_selector": "article, li.product, div.product-item, [data-testid='product-card']",
        "name_selector": "h2, h3, .product-title, [data-testid='product-title']",
        "price_selector": ".price, [data-testid='price']",
    },
    {
        "store": "Nille",
        "urls": [
            "https://www.nille.no/category/pokemon/",
        ],
        # Nille viser pris, nettlager-status ("PA NETTLAGER" / "IKKE PA
        # NETTLAGER") og antall fysiske butikker direkte i produktkortene pa
        # kategorisiden -- se scrape_nille(), som leser dette direkte i
        # stedet for a besoke hver produktside. Tidligere ble lagerstatus
        # lest fra hele produktsideteksten, som feilaktig tolket "IKKE PA
        # NETTLAGER" som "pa lager" fordi teksten inneholder delstrengen
        # "PA NETTLAGER".
        "custom_scraper": "nille",
    },
    {
        "store": "Outland",
        "urls": [OUTLAND_URL],
        # Outland viser bade nettlager-status og antall fysiske butikker
        # direkte i kategorikortene, men siden bruker en virtualisert liste
        # som laster inn flere produkter etter hvert som man scroller (samme
        # utfordring som Nille) -- se scrape_outland().
        "custom_scraper": "outland",
    },
    {
        "store": "Lekekassen",
        "urls": ["https://lekekassen.no/samlekort/pokemon-kort"],
        # Magento -- server-rendret HTML, standard Magento-klassenavn.
        "card_selector": "li.product.product-item, div.product-item-info",
        "name_selector": "a.product-item-link",
        "price_selector": ".price-wrapper .price, .price-box .price",
    },
    {
        "store": "Maxgaming",
        "urls": ["https://www.maxgaming.no/no/hjem-fritid/samlekortspill/pokemon"],
        # Egen/proprietaer plattform -- se scrape_maxgaming() (lagerstatus-
        # teksten er usynlig for Playwright sin inner_text(), sa vi trenger
        # en egen funksjon som bruker text_content() i stedet).
        "custom_scraper": "maxgaming",
    },
]

# ---------------------------------------------------------------------------
# "24NETTBUTIKK" -- en norsk nettbutikkplattform (bl.a. poke-shop.no,
# boosterpakker.no, cardkings.no, emken.no) som bruker schema.org-markup
# (itemprop="availability") for lagerstatus direkte i kategorikortene -- se
# scrape_nettbutikk24(). Samme funksjon dekker alle butikker paa plattformen.
# ---------------------------------------------------------------------------
NETTBUTIKK24_SITES = [
    {
        "store": "PokeShop",
        "urls": POKE_SHOP_CATEGORIES,
        "custom_scraper": "nettbutikk24",
    },
    {
        "store": "Boosterpakker",
        "urls": [
            "https://boosterpakker.no/butikk/boosterpakker",
            "https://boosterpakker.no/butikk/booster-bokser",
            "https://boosterpakker.no/butikk/collection-bokser",
            "https://boosterpakker.no/butikk/japanske-enkeltkort",
            "https://boosterpakker.no/butikk/graderte-kort",
        ],
        "custom_scraper": "nettbutikk24",
    },
    {
        "store": "Card Kings",
        "urls": [
            "https://cardkings.no/butikk/pokemon",
            "https://cardkings.no/butikk/japansk-pokemon",
            "https://cardkings.no/butikk/kinesisk-pokemon",
            "https://cardkings.no/butikk/single-kort",
        ],
        "custom_scraper": "nettbutikk24",
    },
    {
        "store": "Emken",
        "urls": [
            "https://www.emken.no/butikk/spill-samling/pokemon/kort/boosterpakker",
            "https://www.emken.no/butikk/spill-samling/pokemon/kort/collection-bokser",
            "https://www.emken.no/butikk/spill-samling/pokemon/kort/elite-trainer-box",
            "https://www.emken.no/butikk/spill-samling/pokemon/kort/single-kort/alle-kort",
        ],
        "custom_scraper": "nettbutikk24",
    },
]

# ---------------------------------------------------------------------------
# QUICKBUTIK -- en nordisk nettbutikkplattform (Cardhouse, Mystic Trades,
# Pokecandy) som skriver produktnavn/pris direkte som data-attributter
# (data-s-title/data-s-price) paa kortelementet, uavhengig av tema -- se
# scrape_quickbutik().
# ---------------------------------------------------------------------------
QUICKBUTIK_SITES = [
    {
        "store": "Cardhouse",
        "urls": [
            "https://cardhouse.no/engelsk/pokemon-booster-pakker",
            "https://cardhouse.no/engelsk/pokemon-elite-trainer-box",
            "https://cardhouse.no/engelsk/pokemon-bundles",
            "https://cardhouse.no/japansk/pokemon-japanske-booster-bokser",
        ],
    },
    {
        "store": "Mystic Trades",
        "urls": [
            "https://mystictrades.no/pokemon",
            "https://mystictrades.no/pokemon/display-booster-box",
            "https://mystictrades.no/pokemon/booster-packs-bundles",
            "https://mystictrades.no/pokemon/premium-collections-etb-upc",
        ],
    },
    {
        "store": "Pokecandy",
        "urls": [
            "https://pokecandy.no/pokemon-engelsk",
            "https://pokecandy.no/pokemon-japansk",
            "https://pokecandy.no/pokemon-kinesisk",
            "https://pokecandy.no/pokemon-etbupccollections",
        ],
    },
]

# ---------------------------------------------------------------------------
# WOOCOMMERCE -- WordPress-baserte butikker (Collectible, Gameninja,
# Kanoncon, Neo Tokyo, Playlot, Spillmonster). WooCommerce legger alltid til
# klassen "instock"/"outofstock" direkte paa produktkortet uavhengig av
# tema, sa vi leser lagerstatus derfra i stedet for temaspesifikk norsk
# tekst -- se scrape_woocommerce().
# ---------------------------------------------------------------------------
WOOCOMMERCE_SITES = [
    {"store": "Collectible", "urls": ["https://collectible.no/pokemon-kort/"]},
    {"store": "Gameninja", "urls": ["https://www.gameninja.no/produktkategori/samlekortspill/pokemon/"]},
    {"store": "Kanoncon", "urls": ["https://www.kanoncon.no/avdeling/tcg/pokemon/"]},
    # Bruker den brede foreldrekategorien ("pokemon"), ikke den smale
    # "pokemon-tcg"-underkategorien -- underkategorien har bare ~8 produkter,
    # mens foreldrekategorien dekker det meste av Neo Tokyo sitt Pokemon-utvalg.
    {"store": "Neo Tokyo", "urls": ["https://www.neo-tokyo.no/produktkategori/pokemon/"]},
    {"store": "Playlot", "urls": ["https://playlot.no/produktkategori/pokemon/"]},
    {"store": "Spillmonster", "urls": ["https://spillmonster.no/product-category/pokemon-tcg/"]},
]

PLAYWRIGHT_SITES = (
    PLAYWRIGHT_SITES
    + NETTBUTIKK24_SITES
    + [{**site, "custom_scraper": "quickbutik"} for site in QUICKBUTIK_SITES]
    + [{**site, "custom_scraper": "woocommerce"} for site in WOOCOMMERCE_SITES]
)

# Norli og PokeMadness blokkerer automatiserte besok (se docstring ovenfor).
# Vi lister dem her med en direkte lenke, slik at dashboardet kan vise dem
# under "Sjekk manuelt" i stedet for a late som om vi har fersk lagerdata
# fra dem.
MANUAL_CHECK_STORES = [
    {
        "store": "Norli",
        "url": "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort",
        "reason": "Norli svarer med HTTP 403 Forbidden til automatiske besok.",
    },
    {
        "store": "PokeMadness",
        "url": "https://www.pokemadness.no/",
        "reason": "PokeMadness viser en Cloudflare-utfordring (\"Vent litt...\") til automatiske besok.",
    },
    {
        "store": "CardCollect",
        "url": "https://www.cardcollect.no/pokemon",
        "reason": "Klientrendret Nuxt-app -- data lastes via en intern GraphQL-lignende "
                  "API med markorbasert paginering (909+ produkter) som ikke er "
                  "verifisert stabil nok til automatisk scraping enna.",
    },
]

# Vanlige tekster pa "godta cookies"-knapper i norske nettbutikker.
COOKIE_BUTTON_TEXTS = [
    "Godta alle", "Godta alle cookies", "Aksepter alle", "Aksepter",
    "Godta", "OK", "Jeg forstar", "Tillat alle",
]


def dismiss_cookie_banner(page, attempts: int = 6, wait_ms: int = 1000):
    """Provver a klikke bort cookie-banner. Noen bannere dukker opp med en
    liten forsinkelse etter at siden er lastet, sa vi provver flere ganger
    over noen sekunder. Kall med lave attempts/wait_ms nar samtykke allerede
    er gitt tidligere i samme nettleserokt (f.eks. pa produktdetaljsider)."""
    for _ in range(attempts):
        for text in COOKIE_BUTTON_TEXTS:
            try:
                btn = page.get_by_role("button", name=text, exact=False)
                if btn.count() > 0:
                    btn.first.click(timeout=2000)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue
        page.wait_for_timeout(wait_ms)


def scroll_to_load_lazy_content(page, rounds: int = 8, pause_ms: int = 700):
    """Mange norske nettbutikker laster produkter i puljer nar man scroller.
    Vi bruker et EKTE scrollhjul-event (page.mouse.wheel) i stedet for a
    endre window.scrollY direkte via JavaScript."""
    for _ in range(rounds):
        page.mouse.wheel(0, 2200)
        page.wait_for_timeout(pause_ms)


import os


def safe_screenshot(page, store: str, suffix: str = ""):
    try:
        os.makedirs("debug_screenshots", exist_ok=True)
        safe_name = store.lower().replace(" ", "_") + suffix
        page.screenshot(path=f"debug_screenshots/{safe_name}.png", full_page=True)
        print(f"[{store}] Lagret skjermbilde: debug_screenshots/{safe_name}.png")
    except Exception as e:
        print(f"[{store}] Klarte ikke ta skjermbilde: {e}")


def extract_href(card, page_url: str) -> str | None:
    href = card.get_attribute("href")
    if not href:
        link_el = card.query_selector("a")
        href = link_el.get_attribute("href") if link_el else None
    if href and href.startswith("/"):
        from urllib.parse import urljoin
        href = urljoin(page_url, href)
    return href


def scrape_nille(page, site: dict) -> list[Product]:
    """Nille viser faktisk pris, nettlager-status og antall fysiske butikker
    direkte i produktkortene pa kategorisiden -- vi trenger derfor ikke
    besoke hver produktside (mye raskere enn for). Kategorisiden bruker en
    virtualisert liste som laster inn flere produkter etter hvert som man
    scroller. Vi flytter musepekeren til midten av siden forst, og bruker et
    ekte scrollhjul-event (page.mouse.wheel) -- en JS-satt scrollposisjon
    (window.scrollBy) trigger ikke innlasting av flere produkter."""
    store = site["store"]
    url = site["urls"][0]
    collected: dict[str, Product] = {}

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        dismiss_cookie_banner(page)
        page.wait_for_timeout(1000)
        page.mouse.move(400, 400)
    except Exception as e:
        print(f"[{store}] Kunne ikke laste {url}: {e}")
        return []

    expected_total = None
    for _ in range(5):
        try:
            body_text = page.inner_text("body")
            m = re.search(r"(\d+)\s+produkter", body_text)
            if m:
                expected_total = int(m.group(1))
                print(f"[{store}] Siden oppgir {expected_total} produkter totalt.")
                break
        except Exception:
            pass
        page.wait_for_timeout(500)

    def collect_visible_cards():
        cards = page.query_selector_all('div[class*="itemCard--"]')
        for card in cards:
            try:
                link_el = card.query_selector("a[href*='/produkter/']")
                href = link_el.get_attribute("href") if link_el else None
                if not href:
                    continue
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                if href in collected:
                    continue

                name_el = card.query_selector("h2")
                name = name_el.inner_text().strip() if name_el else None
                if not name:
                    continue

                price_el = card.query_selector('[class*="price--"]')
                price = price_el.inner_text().strip() if price_el else "?"

                stock_el = card.query_selector('[class*="stockStatus--"]')
                stock_text = stock_el.inner_text().strip().upper() if stock_el else ""
                if "IKKE" in stock_text:
                    in_stock = False
                elif "NETTLAGER" in stock_text:
                    in_stock = True
                else:
                    in_stock = None

                collected[href] = Product(
                    store=store, name=name, price=price, in_stock=in_stock, url=href,
                )
            except Exception as e:
                print(f"[{store}] Feil ved lesing av produktkort: {e}")

    stagnant_rounds = 0
    for _ in range(80):
        before = len(collected)
        collect_visible_cards()
        if expected_total is not None and len(collected) >= expected_total:
            break
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1100)
        stagnant_rounds = stagnant_rounds + 1 if len(collected) == before else 0
        if stagnant_rounds >= 10:
            break

    collect_visible_cards()

    if not collected:
        print(f"[{store}] Fant ingen produktkort pa {url} -- selektorene ma sannsynligvis oppdateres.")
        diag = diagnose_possible_block(page)
        if diag:
            print(f"[{store}] Mulig blokkering oppdaget: {diag}")
        safe_screenshot(page, store)
    else:
        extra = f" av {expected_total} oppgitt" if expected_total else ""
        print(f"[{store}] Fant {len(collected)} produkter direkte pa kategorisiden{extra}.")

    return list(collected.values())


def scrape_nettbutikk24(page, site: dict) -> list[Product]:
    """"24Nettbutikk" er en norsk nettbutikkplattform som flere butikker
    bruker (poke-shop.no, boosterpakker.no, cardkings.no, emken.no m.fl.) --
    samme CSS-klasser og markup uansett butikk, sa denne funksjonen er
    stedsuavhengig (site["store"]/site["urls"] styrer hvilken butikk).
    Plattformen viser pris og lagerstatus direkte i produktkortene pa hver
    kategoriside, ved hjelp av standard schema.org-markup
    (<link itemprop="availability" href=".../InStock" eller ".../SoldOut">).
    Dette er mer palitelig enn a lete etter norsk tekst, og kategoriene her
    er sma nok (under 60 produkter hver) til at vi ikke trenger scrolling
    eller paginering."""
    store = site["store"]
    products: dict[str, Product] = {}

    for url in site["urls"]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            dismiss_cookie_banner(page)
        except Exception as e:
            print(f"[{store}] Kunne ikke laste {url}: {e}")
            continue

        cards = page.query_selector_all("article.productlist__product")
        if not cards:
            diag = diagnose_possible_block(page)
            if diag:
                print(f"[{store}] Fant ingen produktkort pa {url}. Mulig blokkering: {diag}")
            else:
                print(f"[{store}] Fant ingen produktkort pa {url} -- selektorene ma sjekkes.")
            safe_screenshot(page, store, "_" + url.rstrip("/").split("/")[-1])

        for card in cards:
            try:
                link_el = card.query_selector("a.productlist__product-wrap")
                href = link_el.get_attribute("href") if link_el else None
                if href and href.startswith("/"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                if not href or href in products:
                    continue

                name_el = card.query_selector(".productlist__product__headline")
                name = name_el.inner_text().strip() if name_el else None
                if not name:
                    continue

                price_el = card.query_selector(".price__display")
                price = (price_el.inner_text().strip() + " kr") if price_el else "?"

                avail_el = card.query_selector('link[itemprop="availability"]')
                avail = avail_el.get_attribute("href") if avail_el else ""
                if avail and "InStock" in avail:
                    in_stock = True
                elif avail:
                    in_stock = False
                else:
                    in_stock = None

                products[href] = Product(
                    store=store, name=name, price=price, in_stock=in_stock, url=href,
                )
            except Exception as e:
                print(f"[{store}] Feil ved lesing av produktkort: {e}")

        time.sleep(1)

    print(f"[{store}] Fant {len(products)} produkter totalt.")
    return list(products.values())


def scrape_quickbutik(page, site: dict) -> list[Product]:
    """QuickButik er en nordisk nettbutikkplattform (bl.a. Cardhouse, Mystic
    Trades og Pokecandy) som skriver produktnavn og pris direkte som
    data-attributter (data-s-title/data-s-price) paa selve
    produktkort-elementet, uavhengig av hvilket tema butikken bruker -- vi
    kan derfor lese dem direkte i stedet for a matche temaspesifikke
    CSS-klasser."""
    store = site["store"]
    products: dict[str, Product] = {}

    for url in site["urls"]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            dismiss_cookie_banner(page)
        except Exception as e:
            print(f"[{store}] Kunne ikke laste {url}: {e}")
            continue

        cards = page.query_selector_all("[data-s-title][data-s-price]")
        if not cards:
            diag = diagnose_possible_block(page)
            if diag:
                print(f"[{store}] Fant ingen produktkort pa {url}. Mulig blokkering: {diag}")
            else:
                print(f"[{store}] Fant ingen produktkort pa {url} -- selektorene ma sjekkes.")
            safe_screenshot(page, store, "_" + url.rstrip("/").split("/")[-1])

        for card in cards:
            try:
                name = card.get_attribute("data-s-title")
                price_raw = card.get_attribute("data-s-price")
                if not name or not price_raw:
                    continue

                href = extract_href(card, url)
                if not href or href in products:
                    continue

                # text_content() (rat DOM-tekstinnhold) i stedet for inner_text()
                # (kun det Playwright regner som synlig rendret tekst) -- enkelte
                # QuickButik-tema (som Cardhouse) skjuler "Sold out"/"Pa lager"-
                # merket for inner_text() pa samme mate som Maxgaming (se
                # scrape_maxgaming()).
                in_stock = classify_stock(card.text_content())

                products[href] = Product(
                    store=store, name=name.strip(), price=f"{price_raw} kr", in_stock=in_stock, url=href,
                )
            except Exception as e:
                print(f"[{store}] Feil ved lesing av produktkort: {e}")

        time.sleep(1)

    print(f"[{store}] Fant {len(products)} produkter totalt.")
    return list(products.values())


WOOCOMMERCE_NAME_SELECTOR = (
    ".woocommerce-loop-product__title a, .wd-entities-title a, "
    "a.woocommerce-LoopProduct-link, h2.woocommerce-loop-product__title a, "
    ".product-title a, .elementor-heading-title a"
)
WOOCOMMERCE_PRICE_SELECTOR = ".price ins .woocommerce-Price-amount, .price .woocommerce-Price-amount"


def scrape_woocommerce(page, site: dict) -> list[Product]:
    """Generisk scraper for WooCommerce-baserte butikker (Collectible,
    Gameninja, Kanoncon, Neo Tokyo, Playlot, Spillmonster). WooCommerce
    legger alltid til klassen "instock" eller "outofstock" direkte pa
    produktkort-elementet uavhengig av tema, sa vi leser lagerstatus derfra
    i stedet for a lete etter temaspesifikk norsk tekst. Kategorisidene
    paginerer med standard WordPress-URLer (/page/2/, /page/3/ osv.), som vi
    folger til en side ikke gir nye produkter."""
    store = site["store"]
    products: dict[str, Product] = {}

    for base_url in site["urls"]:
        for page_num in range(1, 16):
            url = base_url if page_num == 1 else f"{base_url.rstrip('/')}/page/{page_num}/"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1500)
                if page_num == 1:
                    dismiss_cookie_banner(page)
            except Exception as e:
                print(f"[{store}] Kunne ikke laste {url}: {e}")
                break

            try:
                page.wait_for_selector("li.product, div.product.type-product", timeout=15000)
            except Exception:
                pass
            cards = page.query_selector_all("li.product, div.product.type-product")

            if not cards and page_num == 1:
                # Elementor-baserte tema (som Gameninja) kan bruke litt tid pa
                # a rendre inn produktgrid-widgeten -- prov en gang til.
                print(f"[{store}] Fant ingen produktkort ved forste forsok pa {url}, provver pa nytt...")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3000)
                    dismiss_cookie_banner(page)
                    page.wait_for_selector("li.product, div.product.type-product", timeout=15000)
                except Exception:
                    pass
                cards = page.query_selector_all("li.product, div.product.type-product")

            if not cards:
                if page_num == 1:
                    diag = diagnose_possible_block(page)
                    if diag:
                        print(f"[{store}] Fant ingen produktkort pa {url}. Mulig blokkering: {diag}")
                    else:
                        print(f"[{store}] Fant ingen produktkort pa {url} -- selektorene ma sjekkes.")
                    safe_screenshot(page, store, "_" + url.rstrip("/").split("/")[-1])
                break

            new_found = 0
            for card in cards:
                try:
                    link_el = card.query_selector(WOOCOMMERCE_NAME_SELECTOR)
                    if not link_el:
                        continue
                    name = link_el.inner_text().strip()
                    href = link_el.get_attribute("href")
                    if not name or not href or href in products:
                        continue

                    price_el = card.query_selector(WOOCOMMERCE_PRICE_SELECTOR)
                    if price_el:
                        price = price_el.inner_text().strip()
                    else:
                        # Enkelte Elementor-baserte tema (som Gameninja) rendrer
                        # prisen som ren tekst uten standard WooCommerce-klasser.
                        price = extract_price_fallback(card.inner_text()) or "?"

                    card_class = card.get_attribute("class") or ""
                    if "outofstock" in card_class:
                        in_stock = False
                    elif "instock" in card_class:
                        in_stock = True
                    else:
                        in_stock = None

                    products[href] = Product(store=store, name=name, price=price, in_stock=in_stock, url=href)
                    new_found += 1
                except Exception as e:
                    print(f"[{store}] Feil ved lesing av produktkort: {e}")

            if new_found == 0:
                break
            time.sleep(1)

    print(f"[{store}] Fant {len(products)} produkter totalt.")
    return list(products.values())


def scrape_maxgaming(page, site: dict) -> list[Product]:
    """Maxgaming sin lagerstatus-tekst ("Pa lager") ligger i DOM-en, men
    Playwright sin inner_text() -- som kun tar med det den regner som synlig
    rendret tekst -- plukker den ikke opp her (sannsynligvis en CSS-detalj i
    temaet deres). Vi bruker derfor text_content() (rene DOM-tekstinnhold,
    uavhengig av synlighet) for a lese lagerstatus paalitelig."""
    store = site["store"]
    products: dict[str, Product] = {}
    url = site["urls"][0]

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        dismiss_cookie_banner(page)
    except Exception as e:
        print(f"[{store}] Kunne ikke laste {url}: {e}")
        return []

    cards = page.query_selector_all("div.PT_Wrapper")
    if not cards:
        diag = diagnose_possible_block(page)
        if diag:
            print(f"[{store}] Fant ingen produktkort pa {url}. Mulig blokkering: {diag}")
        else:
            print(f"[{store}] Fant ingen produktkort pa {url} -- selektorene ma sjekkes.")
        safe_screenshot(page, store)

    for card in cards:
        try:
            href = extract_href(card, url)
            if not href or href in products:
                continue

            name_el = card.query_selector("div.PT_Beskr")
            name = " ".join(name_el.text_content().split()) if name_el else None
            if not name:
                continue

            price_el = card.query_selector("span.PT_PrisNormal")
            price = price_el.text_content().strip() if price_el else "?"

            status_el = card.query_selector("[class*='PT_text_Lagerstatus']")
            in_stock = classify_stock(status_el.text_content()) if status_el else None

            products[href] = Product(store=store, name=name, price=price, in_stock=in_stock, url=href)
        except Exception as e:
            print(f"[{store}] Feil ved lesing av produktkort: {e}")

    print(f"[{store}] Fant {len(products)} produkter totalt.")
    return list(products.values())


def scrape_outland(page, site: dict) -> list[Product]:
    """Outland viser nettlager-status og antall fysiske butikker direkte i
    kategorikortene (f.eks. "Pa nettlager" + "Tilgjengelig i 5 butikker"),
    men bruker en virtualisert liste som laster inn flere produkter etter
    hvert som man scroller -- samme utfordring som Nille, sa vi bruker
    samme teknikk (ekte scrollhjul-event + oppgitt totalantall som
    stoppekriterium)."""
    store = site["store"]
    url = site["urls"][0]
    collected: dict[str, Product] = {}

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        dismiss_cookie_banner(page)
        page.wait_for_timeout(1000)
        page.mouse.move(400, 400)
    except Exception as e:
        print(f"[{store}] Kunne ikke laste {url}: {e}")
        return []

    expected_total = None
    for _ in range(5):
        try:
            body_text = page.inner_text("body")
            m = re.search(r"(\d+)\s+produkter", body_text)
            if m:
                expected_total = int(m.group(1))
                print(f"[{store}] Siden oppgir {expected_total} produkter totalt.")
                break
        except Exception:
            pass
        page.wait_for_timeout(500)

    def classify(texts: list) -> bool | None:
        joined = [t.lower() for t in texts]
        positive = any(
            ("nettlager" in t and "ikke" not in t) or ("tilgjengelig i" in t) or t.startswith("kun ")
            for t in joined
        )
        negative = any("ikke pa lager" in t for t in joined)
        if positive:
            return True
        if negative:
            return False
        return None

    def store_count_from(texts: list) -> int | None:
        for t in texts:
            m = re.search(r"tilgjengelig i (\d+) butikk", t.lower())
            if m:
                return int(m.group(1))
        return None

    def collect_visible_cards():
        cards = page.query_selector_all('[class*="ProductListItem-root"]')
        for card in cards:
            try:
                link_el = card.query_selector("a[href]")
                href = link_el.get_attribute("href") if link_el else None
                if not href:
                    continue
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                if href in collected:
                    continue

                name_el = card.query_selector('[class*="ProductListItem-title"]')
                name = name_el.inner_text().strip() if name_el else None
                if not name:
                    continue

                price_el = card.query_selector('[class*="ProductListPrice-root"]')
                price = price_el.inner_text().strip() if price_el else "?"

                stock_els = card.query_selector_all('[class*="StockMessage-status"]')
                stock_texts = [e.inner_text().strip() for e in stock_els]

                collected[href] = Product(
                    store=store, name=name, price=price,
                    in_stock=classify(stock_texts), url=href,
                    store_count=store_count_from(stock_texts),
                )
            except Exception as e:
                print(f"[{store}] Feil ved lesing av produktkort: {e}")

    stagnant_rounds = 0
    for _ in range(80):
        before = len(collected)
        collect_visible_cards()
        if expected_total is not None and len(collected) >= expected_total:
            break
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1100)
        stagnant_rounds = stagnant_rounds + 1 if len(collected) == before else 0
        if stagnant_rounds >= 10:
            break

    collect_visible_cards()

    if not collected:
        print(f"[{store}] Fant ingen produktkort pa {url} -- selektorene ma sannsynligvis oppdateres.")
        diag = diagnose_possible_block(page)
        if diag:
            print(f"[{store}] Mulig blokkering oppdaget: {diag}")
        safe_screenshot(page, store)
    else:
        extra = f" av {expected_total} oppgitt" if expected_total else ""
        print(f"[{store}] Fant {len(collected)} produkter direkte pa kategorisiden{extra}.")

    return list(collected.values())


def scrape_product_detail_pages(page, site: dict, product_urls: list[str]) -> list[Product]:
    """For sider der listevisningen ikke viser pris/lagerstatus palitelig:
    besok hver produktside for seg og les det derfra (tregere, men riktig)."""
    results = []
    for url in product_urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            dismiss_cookie_banner(page, attempts=1, wait_ms=300)
        except Exception as e:
            print(f"[{site['store']}] Kunne ikke laste produktside {url}: {e}")
            safe_screenshot(page, site["store"], "_produktside_feil")
            continue

        try:
            name_el = page.query_selector(site["detail_name_selector"])
            name = name_el.inner_text().strip() if name_el else None
            if not name:
                continue

            price_el = page.query_selector(site["detail_price_selector"])
            price = price_el.inner_text().strip() if price_el else None
            full_text = page.inner_text("body")
            if not price:
                price = extract_price_fallback(full_text) or "?"

            if site.get("stock_mode") == "norli":
                in_stock = get_norli_online_stock(page)
            else:
                stock_selector = site.get("detail_stock_selector")
                if stock_selector:
                    stock_el = page.query_selector(stock_selector)
                    stock_text = stock_el.inner_text() if stock_el else full_text
                else:
                    stock_text = full_text
                in_stock = classify_stock(stock_text)

            results.append(
                Product(
                    store=site["store"],
                    name=name,
                    price=price,
                    in_stock=in_stock,
                    url=url,
                )
            )
        except Exception as e:
            print(f"[{site['store']}] Feil ved lesing av produktside {url}: {e}")

        time.sleep(1.5)
    return results


MAX_PAGES_PER_CATEGORY = 15


def scrape_with_browser(page, site: dict) -> list[Product]:
    results = []
    for i, base_url in enumerate(site["urls"]):
        suffix = f"_{i}" if len(site["urls"]) > 1 else ""

        page_urls_to_try = [base_url]
        if site.get("paginate"):
            page_urls_to_try += [f"{base_url}?page={n}" for n in range(2, MAX_PAGES_PER_CATEGORY + 1)]

        collected_product_urls = []
        seen = set()

        for page_num, url in enumerate(page_urls_to_try, start=1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                dismiss_cookie_banner(page)
                scroll_to_load_lazy_content(page)
                page.wait_for_timeout(1000)
            except Exception as e:
                print(f"[{site['store']}] Kunne ikke laste {url} ferdig: {e}. "
                      f"Provver likevel a lese det som lastet, og tar skjermbilde.")
                safe_screenshot(page, site["store"], suffix + "_error")

            try:
                page.wait_for_selector(site["card_selector"], timeout=15000)
            except Exception:
                pass

            cards = page.query_selector_all(site["card_selector"])

            if not cards and page_num == 1:
                print(f"[{site['store']}] Fant ingen produktkort ved forste forsok pa {url}, provver pa nytt...")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3000)
                    dismiss_cookie_banner(page)
                    scroll_to_load_lazy_content(page)
                    page.wait_for_selector(site["card_selector"], timeout=15000)
                except Exception:
                    pass
                cards = page.query_selector_all(site["card_selector"])

            if not cards:
                if page_num == 1:
                    diag = diagnose_possible_block(page)
                    if diag:
                        print(f"[{site['store']}] Fant ingen produktkort pa {url} etter to forsok. "
                              f"Mulig blokkering oppdaget: {diag}")
                    else:
                        print(f"[{site['store']}] Fant ingen produktkort pa {url} "
                              f"-- selektor '{site['card_selector']}' ma sannsynligvis oppdateres. "
                              f"Apne siden i nettleseren, hoyreklikk pa et produkt -> Inspiser, "
                              f"og oppdater 'card_selector' i scrape.py.")
                    safe_screenshot(page, site["store"], suffix)
                break

            if site.get("visit_product_pages"):
                url_pattern = site.get("product_url_pattern")
                compiled_pattern = re.compile(url_pattern) if url_pattern else None
                new_links_found = 0
                for card in cards:
                    href = extract_href(card, url)
                    if not href or href in seen:
                        continue
                    if compiled_pattern and not compiled_pattern.search(href):
                        continue
                    seen.add(href)
                    collected_product_urls.append(href)
                    new_links_found += 1

                if not site.get("paginate") or new_links_found == 0:
                    break
            else:
                for card in cards:
                    try:
                        name_el = card.query_selector(site["name_selector"])
                        name = name_el.inner_text().strip() if name_el else None
                        if not name:
                            continue

                        price_el = card.query_selector(site["price_selector"])
                        price = price_el.inner_text().strip() if price_el else None

                        href = extract_href(card, url)

                        full_text = card.inner_text()
                        if not price:
                            price = extract_price_fallback(full_text) or "?"
                        in_stock = classify_stock(full_text)

                        results.append(
                            Product(
                                store=site["store"],
                                name=name,
                                price=price,
                                in_stock=in_stock,
                                url=href or url,
                            )
                        )
                    except Exception as e:
                        print(f"[{site['store']}] Feil ved parsing av produktkort: {e}")
                break

        if site.get("visit_product_pages") and collected_product_urls:
            print(f"[{site['store']}] Fant {len(collected_product_urls)} produktlenker, besoker hver side...")
            results += scrape_product_detail_pages(page, site, collected_product_urls)

        time.sleep(DELAY_BETWEEN_SITES)
    return results


def load_previous_products() -> dict:
    try:
        with open("docs/data.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return {p["url"]: p for p in data.get("products", []) if p.get("url")}
    except Exception:
        return {}


def compute_new_stock_events(all_products: list, previous_by_url: dict) -> list:
    events = []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for p in all_products:
        prev = previous_by_url.get(p.url)
        was_in_stock = bool(prev and prev.get("in_stock") is True)
        if p.in_stock is True and not was_in_stock:
            events.append({
                "detected_at": now,
                "store": p.store,
                "name": p.name,
                "price": p.price,
                "url": p.url,
                "event": "restock" if prev is not None else "ny",
            })
    return events


def compute_extra_events(all_products: list, previous_by_url: dict) -> list:
    """Hendelsestyper utover ny/restock (se compute_new_stock_events): en vare
    som gar fra pa lager til utsolgt, og prisendringer. Disse driver IKKE
    ntfy-varsler eller forsidens "Nylig restocket"-seksjon (kun docs/history.json,
    se update_history_log), sa vi holder dem i en egen funksjon i stedet for
    a utvide compute_new_stock_events sin oppforsel."""
    events = []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for p in all_products:
        prev = previous_by_url.get(p.url)
        if prev is None:
            continue

        was_in_stock = bool(prev.get("in_stock") is True)
        if p.in_stock is False and was_in_stock:
            events.append({
                "detected_at": now,
                "store": p.store,
                "name": p.name,
                "price": p.price,
                "url": p.url,
                "event": "utsolgt",
            })

        prev_price = prev.get("price")
        if prev_price and p.price and p.price != prev_price:
            events.append({
                "detected_at": now,
                "store": p.store,
                "name": p.name,
                "price": p.price,
                "previous_price": prev_price,
                "url": p.url,
                "event": "prisendring",
            })
    return events


def _parse_iso_utc(value: str) -> datetime.datetime:
    try:
        dt = datetime.datetime.fromisoformat(value)
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)
    if dt.tzinfo is None:
        # Eldre oppforinger ble lagret uten tidssone (naiv UTC-tid fra
        # GitHub Actions-serveren). Vi antar UTC her slik at
        # sammenligningen mot cutoff blir korrekt.
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def update_changes_log(new_events: list, max_entries: int = 300, max_age_days: int = 14) -> list:
    path = "docs/changes.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f).get("changes", [])
    except Exception:
        existing = []

    combined = new_events + existing
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max_age_days)
    filtered = [e for e in combined if _parse_iso_utc(e.get("detected_at", "")) >= cutoff]
    filtered = filtered[:max_entries]

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"changes": filtered}, f, ensure_ascii=False, indent=2)

    return filtered


def update_history_log(new_events: list, max_entries: int = 20000, max_age_days: int = 400) -> list:
    """Fullstendig hendelseslogg (ny, restock, utsolgt, prisendring) med mye
    lengre levetid enn changes.json -- brukes til lagerhistorikk,
    prishistorikk, restock-statistikk og enkle restock-prediksjoner (se
    docs/statistics.html, docs/updates.html og "Historikk"-seksjonen i
    docs/product.html)."""
    path = "docs/history.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f).get("events", [])
    except Exception:
        # Forste gang history.json opprettes: bruk eksisterende changes.json
        # som utgangspunkt (ny/restock siste 14 dager) sa vi ikke mister
        # allerede innsamlet historikk.
        try:
            with open("docs/changes.json", "r", encoding="utf-8") as f:
                existing = json.load(f).get("changes", [])
        except Exception:
            existing = []

    combined = new_events + existing
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max_age_days)
    filtered = [e for e in combined if _parse_iso_utc(e.get("detected_at", "")) >= cutoff]
    filtered = filtered[:max_entries]

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"events": filtered}, f, ensure_ascii=False, indent=2)

    return filtered


def send_ntfy_notification(events: list) -> None:
    """Sender push-varsel via ntfy.sh nar nye lagerhendelser (restock / nye
    produkter) er oppdaget. Krever miljovariabelen NTFY_TOPIC (satt i
    .github/workflows/scrape.yml). Gjor ingenting hvis den mangler eller det
    ikke er noen nye hendelser denne kjoringen."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic or not events:
        return

    lines = []
    for e in events[:10]:
        tag = "NY" if e["event"] == "ny" else "RESTOCK"
        lines.append(f"[{tag}] {e['store']}: {e['name']} ({e['price']})")
    if len(events) > 10:
        lines.append(f"... og {len(events) - 10} til")
    message = "\n".join(lines)

    title = (
        f"Pokemon Lager: {len(events)} ny hendelse"
        if len(events) == 1
        else f"Pokemon Lager: {len(events)} nye hendelser"
    )

    try:
        req = Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            method="POST",
            headers={
                "Title": title,
                "Priority": "default",
                "Tags": "tada",
            },
        )
        with urlopen(req, timeout=10) as resp:
            resp.read()
        print(f"Sendte ntfy-varsel til topic '{topic}' ({len(events)} hendelser).")
    except Exception as e:
        print(f"Klarte ikke sende ntfy-varsel: {e}")


def main():
    all_products: list = []
    previous_by_url = load_previous_products()

    for config in SHOPIFY_STORES:
        print(f"Scanner {config['store']} (via Shopify-API)...")
        all_products += scrape_shopify_store(config)

    with sync_playwright() as p:
        # --disable-*-throttling/backgrounding: uten disse behandler Chromium
        # headless-fanen som en "bakgrunnsfane" og nedprioriterer timere/
        # scroll-observatorer, som gjor at sider med "last inn ved scroll"
        # (som Nille) slutter a laste inn flere produkter. Dette er rene
        # ytelsesflagg og har ingenting med a skjule at det er en bot a gjore.
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        )
        context = browser.new_context(user_agent=USER_AGENT, locale="nb-NO")
        page = context.new_page()

        for site in PLAYWRIGHT_SITES:
            print(f"Scanner {site['store']}...")
            custom = site.get("custom_scraper")
            if custom == "nille":
                all_products += scrape_nille(page, site)
            elif custom == "nettbutikk24":
                all_products += scrape_nettbutikk24(page, site)
            elif custom == "outland":
                all_products += scrape_outland(page, site)
            elif custom == "maxgaming":
                all_products += scrape_maxgaming(page, site)
            elif custom == "quickbutik":
                all_products += scrape_quickbutik(page, site)
            elif custom == "woocommerce":
                all_products += scrape_woocommerce(page, site)
            else:
                all_products += scrape_with_browser(page, site)

        browser.close()

    new_events = compute_new_stock_events(all_products, previous_by_url)
    extra_events = compute_extra_events(all_products, previous_by_url)
    changes = update_changes_log(new_events)
    history = update_history_log(new_events + extra_events)
    send_ntfy_notification(new_events)

    output = {
        "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "products": [asdict(p) for p in all_products],
        "manual_check_stores": MANUAL_CHECK_STORES,
    }

    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    in_stock_count = sum(1 for p in all_products if p.in_stock)
    print(f"\nFerdig. {len(all_products)} produkter funnet totalt, "
          f"{in_stock_count} pa lager. Lagret til docs/data.json")
    print(f"{len(new_events)} nye lagerhendelser siden forrige kjoring "
          f"(totalt {len(changes)} lagret i docs/changes.json).")
    print(f"{len(new_events) + len(extra_events)} hendelser totalt denne kjoringen "
          f"(totalt {len(history)} lagret i docs/history.json).")
    print(f"{len(MANUAL_CHECK_STORES)} butikker ma sjekkes manuelt (blokkerer automatiske besok): "
          + ", ".join(s["store"] for s in MANUAL_CHECK_STORES))


if __name__ == "__main__":
    import sys

    if "--test-notification" in sys.argv:
        # Sender en enkelt test-hendelse via ntfy uten a skanne butikkene --
        # brukes for a verifisere at NTFY_TOPIC/ntfy-oppsettet fungerer (se
        # "Send test-varsel (ntfy)"-steget i .github/workflows/scrape.yml).
        send_ntfy_notification([{
            "event": "ny",
            "store": "Testbutikk",
            "name": "Dette er en test-varsel fra Pokemon Lagerbot",
            "price": "0 kr",
        }])
    else:
        main()
