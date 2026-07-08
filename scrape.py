"""
Pokemon-lagerscanner for norske nettbutikker.

Scanner Ark, Cardcenter, Nille, Norli og PokeMadness for Pokemon-produkter
og lagrer resultatet som JSON (docs/data.json) som dashboardet leser.

Kjør lokalt:
    pip install -r requirements.txt
    playwright install chromium
    python scrape.py
"""

import json
import re
import time
import datetime
from dataclasses import dataclass, asdict
from urllib.request import urlopen, Request

from playwright.sync_api import sync_playwright

# Hvor lenge vi venter mellom hver butikk (vær snill mot serverne deres)
DELAY_BETWEEN_SITES = 3

# User-Agent som identifiserer boten ærlig (god praksis ved scraping)
USER_AGENT = "PokemonLagerBot/1.0 (privat prosjekt, kontakt: <legg inn din e-post>)"

IN_STOCK_WORDS = ["på lager", "på nettlager", "legg i handlekurv", "legg i handlevogn", "kjøp nå"]
OUT_OF_STOCK_WORDS = ["utsolgt", "ikke på lager", "ikke tilgjengelig", "sold out"]

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
    in_stock: bool | None  # None = vi klarte ikke å avgjøre lagerstatus
    url: str


def classify_stock(text: str) -> bool | None:
    """Gir True (på lager), False (utsolgt) eller None (usikker) basert på tekst."""
    t = text.lower()
    has_out = any(w in t for w in OUT_OF_STOCK_WORDS)
    has_in = any(w in t for w in IN_STOCK_WORDS)
    if has_out and not has_in:
        return False
    if has_in and not has_out:
        return True
    # Noen sider viser begge (f.eks. "utsolgt"-knapp med samme klasse som "legg i kurv")
    # da stoler vi mest på "utsolgt" fordi det ofte er selve knappe-teksten
    if has_out:
        return False
    return None


def get_norli_online_stock(page) -> bool | None:
    """Norli skiller mellom nettlager og lager i fysiske butikker (klikk-og-hent).
    Vi vil kun vite om varen kan kjøpes på nett akkurat nå, så vi leter
    spesifikt etter nettlager-teksten ("På lager" / "Ikke på lager") og
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
                    if ((t === 'På lager' || t === 'Ikke på lager') && !el.className.includes('clickPickup')) {
                        return t;
                    }
                }
                return null;
            }
            """
        )
    except Exception:
        return None
    if text == "På lager":
        return True
    if text == "Ikke på lager":
        return False
    # Andre statuser (f.eks. "Forventes i salg <dato>") betyr at varen ikke
    # kan kjøpes på nett akkurat nå.
    return False


# ---------------------------------------------------------------------------
# CARDCENTER.NO — Shopify har et offentlig produkt-API, mye mer robust enn
# å scrape HTML. Vi bruker det direkte i stedet for Playwright her.
# ---------------------------------------------------------------------------
CARDCENTER_COLLECTIONS = [
    "pokemon",
    "pokemon-booster-pakker",
    "booster-boxer",
    "elite-trainer-boxer",
    "collection-bokser",
]


def scrape_cardcenter() -> list[Product]:
    products = []
    seen_urls = set()
    for handle in CARDCENTER_COLLECTIONS:
        url = f"https://cardcenter.no/collections/{handle}/products.json?limit=250"
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"[cardcenter] Feil ved henting av {handle}: {e}")
            continue

        for p in data.get("products", []):
            product_url = f"https://cardcenter.no/products/{p['handle']}"
            if product_url in seen_urls:
                continue
            seen_urls.add(product_url)
            variants = p.get("variants", [])
            available = any(v.get("available") for v in variants)
            price = variants[0]["price"] if variants else "?"
            products.append(
                Product(
                    store="Cardcenter",
                    name=p["title"],
                    price=f"{price} kr",
                    in_stock=available,
                    url=product_url,
                )
            )
        time.sleep(1)
    return products


# ---------------------------------------------------------------------------
# Generiske sider som trenger en ekte nettleser (Playwright): Ark, Nille,
# Norli og PokeMadness. Vi definerer per side hvilken URL og hvilke
# CSS-selektorer som brukes for å finne produktkort.
#
# VIKTIG: Nettbutikker endrer ofte HTML-strukturen sin. Selektorene under er
# basert på struktur observert i juli 2026. Hvis boten slutter å finne
# produkter på en side, må selektorene oppdateres — bruk "Inspiser
# element" i nettleseren på siden for å finne riktige klassenavn.
# ---------------------------------------------------------------------------

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
        # Nille sin kategoriside viser ikke pris/lagerstatus i selve
        # produktkortene — bare bilde + navn. Vi henter derfor kun
        # produktlenker her, og besøker hver produktside separat
        # (se visit_product_pages under) for å finne ekte pris og status.
        "card_selector": "a[href*='/produkter/']",
        "name_selector": None,  # brukes ikke når visit_product_pages er på
        "price_selector": ".price, [class*='price'], [data-testid='price']",
        "visit_product_pages": True,
        "detail_name_selector": "h1",
        "detail_price_selector": ".price, [class*='price'], [data-testid='price']",
    },
    {
        "store": "Norli",
        "urls": [
            "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort",
        ],
        # Norli bruker Algolia (InstantSearch) til produktlisten. "ais-Hits-item"
        # er et stabilt klassenavn fra selve søkebiblioteket (ikke et
        # generert/hashet klassenavn), så det er mer robust enn å gjette på
        # butikkens egne CSS-klasser.
        "card_selector": "li.ais-Hits-item a[href]",
        "name_selector": None,
        "price_selector": None,
        "visit_product_pages": True,
        "detail_name_selector": "h1",
        "detail_price_selector": "[class*='productPriceDetail']",
        # Norli skiller mellom nettlager og butikklager (klikk-og-hent). Vi
        # bruker en egen funksjon (get_norli_online_stock) i stedet for
        # generisk tekst-sniffing, for å unngå å blande de to.
        "stock_mode": "norli",
    },
    {
        "store": "PokeMadness",
        "urls": [
            "https://www.pokemadness.no/34-booster-pakker",
            "https://www.pokemadness.no/119-booster-boks",
            "https://www.pokemadness.no/121-elite-trainer-boks",
            "https://www.pokemadness.no/123-collection-bokser",
            "https://www.pokemadness.no/124-blisters",
            "https://www.pokemadness.no/125-premium-collection",
        ],
        # PokeMadness (PrestaShop) sine produktsider ender alltid på ".html".
        # I stedet for å gjette CSS-klassenavn i listevisningen, henter vi
        # bare produktlenkene her og besøker hver side separat (samme
        # metode som for Nille) — mer robust mot design-endringer.
        "card_selector": "a[href$='.html']",
        "name_selector": None,
        "price_selector": ".price",
        "visit_product_pages": True,
        "product_url_pattern": r"/\d+-[^/]+\.html$",  # ekte produktlenker har et tall-ID, f.eks. /1922-navn.html
        "detail_name_selector": "h1",
        # VIKTIG FIKS: den forrige selektoren (".price, [class*='price']")
        # traff en tom, skjult div ("search_results...") FØR selve prisen i
        # DOM-rekkefølgen, så pris ble ofte lest som tom. Vi avgrenser derfor
        # til prisblokken i selve produktinfoen.
        "detail_price_selector": ".product-prices .price, .current-price .price",
        # VIKTIG FIKS: lagerstatus ble tidligere lest fra HELE sideteksten,
        # som også viser "Utsolgt" for anbefalte/relaterte produkter lenger
        # ned på siden — det ga falske "utsolgt"-treff for varer som faktisk
        # var på lager. Vi avgrenser derfor til kjøp-knapp-blokken, som viser
        # nøyaktig "På lager <antall> Produkter" eller "Utsolgt" for DENNE varen.
        "detail_stock_selector": ".product-add-to-cart",
        # Kategoriene kan i prinsippet ha flere sider med resultater.
        "paginate": True,
    },
]

# Vanlige tekster på "godta cookies"-knapper i norske nettbutikker.
# Vi prøver å klikke disse automatisk, fordi et cookie-banner ofte blokkerer
# resten av siden fra å laste riktig (og dermed gir 0 treff).
COOKIE_BUTTON_TEXTS = [
    "Godta alle", "Godta alle cookies", "Aksepter alle", "Aksepter",
    "Godta", "OK", "Jeg forstår", "Tillat alle",
]


def dismiss_cookie_banner(page):
    for text in COOKIE_BUTTON_TEXTS:
        try:
            btn = page.get_by_role("button", name=text, exact=False)
            if btn.count() > 0:
                btn.first.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def scroll_to_load_lazy_content(page, rounds: int = 6, pause_ms: int = 700):
    """Mange norske nettbutikker laster produkter i puljer når man scroller.
    Vi scroller stegvis mot bunnen for å tvinge frem alt innholdet."""
    for _ in range(rounds):
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
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
    """Henter href enten fra selve kortet (hvis kortet er en <a>-tag) eller
    fra en lenke inni kortet. Den forrige versjonen sjekket kun inni kortet,
    som ga feil resultat når selve produktkortet var selve <a>-taggen."""
    href = card.get_attribute("href")
    if not href:
        link_el = card.query_selector("a")
        href = link_el.get_attribute("href") if link_el else None
    if href and href.startswith("/"):
        from urllib.parse import urljoin
        href = urljoin(page_url, href)
    return href


def scrape_product_detail_pages(page, site: dict, product_urls: list[str]) -> list[Product]:
    """For sider der listevisningen ikke viser pris/lagerstatus pålitelig:
    besøk hver produktside for seg og les det derfra (tregere, men riktig)."""
    results = []
    for url in product_urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            dismiss_cookie_banner(page)
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
                # domcontentloaded i stedet for networkidle: mange JS-sider har
                # konstant bakgrunnstrafikk (analytics o.l.) som gjør at siden
                # ALDRI blir "helt stille" — networkidle timer da ut selv om
                # siden i praksis er ferdig lastet for oss.
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)  # gi JS-rammeverket tid til å rendre innhold
                dismiss_cookie_banner(page)
                scroll_to_load_lazy_content(page)
                page.wait_for_timeout(1000)  # la siste batch produkter rendres
            except Exception as e:
                print(f"[{site['store']}] Kunne ikke laste {url} ferdig: {e}. "
                      f"Prøver likevel å lese det som lastet, og tar skjermbilde.")
                safe_screenshot(page, site["store"], suffix + "_error")
                # Ikke "continue" — vi prøver å hente ut det som faktisk rakk å laste,
                # i stedet for å hoppe over siden helt.

            cards = page.query_selector_all(site["card_selector"])
            if not cards:
                if page_num == 1:
                    print(f"[{site['store']}] Fant ingen produktkort på {url} "
                          f"— selektor '{site['card_selector']}' må sannsynligvis oppdateres. "
                          f"Åpne siden i nettleseren, høyreklikk på et produkt -> Inspiser, "
                          f"og oppdater 'card_selector' i scrape.py.")
                    safe_screenshot(page, site["store"], suffix)
                break  # ingen (flere) produkter på denne siden -> stopp paginering

            if site.get("visit_product_pages"):
                # Denne siden viser ikke pris/status i listevisningen — vi henter
                # kun produktlenkene her, og besøker hver side separat under.
                url_pattern = site.get("product_url_pattern")
                compiled_pattern = re.compile(url_pattern) if url_pattern else None
                new_links_found = 0
                for card in cards:
                    href = extract_href(card, url)
                    if not href or href in seen:
                        continue
                    if compiled_pattern and not compiled_pattern.search(href):
                        continue  # ser ikke ut som en ekte produktlenke (f.eks. blogginnlegg)
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
                break  # denne butikk-typen har ingen paginering foreløpig

        if site.get("visit_product_pages") and collected_product_urls:
            print(f"[{site['store']}] Fant {len(collected_product_urls)} produktlenker, besøker hver side...")
            results += scrape_product_detail_pages(page, site, collected_product_urls)

        time.sleep(DELAY_BETWEEN_SITES)
    return results


def main():
    all_products: list[Product] = []

    print("Scanner Cardcenter (via API)...")
    all_products += scrape_cardcenter()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="nb-NO")
        page = context.new_page()

        for site in PLAYWRIGHT_SITES:
            print(f"Scanner {site['store']}...")
            all_products += scrape_with_browser(page, site)

        browser.close()

    output = {
        "last_updated": datetime.datetime.now().isoformat(timespec="seconds"),
        "products": [asdict(p) for p in all_products],
    }

    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    in_stock_count = sum(1 for p in all_products if p.in_stock)
    print(f"\nFerdig. {len(all_products)} produkter funnet totalt, "
          f"{in_stock_count} på lager. Lagret til docs/data.json")


if __name__ == "__main__":
    main()
