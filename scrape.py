"""
Pokemon-lagerscanner for norske nettbutikker.

Scanner Ark, Cardcenter, Nille, Norli og PokeMadness for Pokemon-produkter
og lagrer resultatet som JSON (docs/data.json) som dashboardet leser.
I tillegg lagres nye lagerhendelser (restock / nye varer) i docs/changes.json,
som brukes av "Nytt siden sist"-siden i dashboardet.

Kjor lokalt:
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


def classify_stock(text: str) -> bool | None:
    """Gir True (pa lager), False (utsolgt) eller None (usikker) basert pa tekst."""
    t = text.lower()
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
# CARDCENTER.NO -- Shopify har et offentlig produkt-API, mye mer robust enn
# a scrape HTML. Vi bruker det direkte i stedet for Playwright her.
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
# Generiske sider som trenger en ekte nettleser (Playwright): Ark, Norli og
# PokeMadness. Nille har sin egen dedikerte funksjon (scrape_nille) siden den
# viser pris/lagerstatus direkte i kategorikortene pa en helt annen mate.
#
# VIKTIG: Nettbutikker endrer ofte HTML-strukturen sin. Selektorene under er
# basert pa struktur observert i juli 2026. Hvis boten slutter a finne
# produkter pa en side, ma selektorene oppdateres -- bruk "Inspiser
# element" i nettleseren pa siden for a finne riktige klassenavn.
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
        "store": "Norli",
        "urls": [
            "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort",
        ],
        # Norli bruker Algolia (InstantSearch) til produktlisten. "ais-Hits-item"
        # er et stabilt klassenavn fra selve sokebiblioteket (ikke et
        # generert/hashet klassenavn), sa det er mer robust enn a gjette pa
        # butikkens egne CSS-klasser.
        "card_selector": "li.ais-Hits-item a[href]",
        "name_selector": None,
        "price_selector": None,
        "visit_product_pages": True,
        "detail_name_selector": "h1",
        "detail_price_selector": "[class*='productPriceDetail']",
        # Norli skiller mellom nettlager og butikklager (klikk-og-hent). Vi
        # bruker en egen funksjon (get_norli_online_stock) i stedet for
        # generisk tekst-sniffing, for a unnga a blande de to.
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
        # PokeMadness (PrestaShop) sine produktsider ender alltid pa ".html".
        # I stedet for a gjette CSS-klassenavn i listevisningen, henter vi
        # bare produktlenkene her og besoker hver side separat -- mer robust
        # mot design-endringer.
        "card_selector": "a[href$='.html']",
        "name_selector": None,
        "price_selector": ".price",
        "visit_product_pages": True,
        "product_url_pattern": r"/\d+-[^/]+\.html$",
        "detail_name_selector": "h1",
        "detail_price_selector": ".product-prices .price, .current-price .price",
        "detail_stock_selector": ".product-add-to-cart",
        "paginate": True,
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
    endre window.scrollY direkte via JavaScript -- flere sider (bl.a. Nille)
    lytter spesifikt pa scroll-/wheel-hendelser for a vite nar de skal laste
    inn flere produkter, og reagerer ikke pa en JS-satt scrollposisjon."""
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
    virtualisert liste som KUN laster inn flere produkter ved et ekte
    scrollhjul-event (wheel) -- en JS-satt scrollposisjon (window.scrollBy)
    trigger ikke innlasting av flere produkter, sa vi bruker
    page.mouse.wheel() her, som sender en ekte wheel-hendelse."""
    store = site["store"]
    url = site["urls"][0]
    collected: dict[str, Product] = {}

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
        dismiss_cookie_banner(page)
    except Exception as e:
        print(f"[{store}] Kunne ikke laste {url}: {e}")
        return []

    expected_total = None
    try:
        body_text = page.inner_text("body")
        m = re.search(r"(\d+)\s+produkter", body_text)
        if m:
            expected_total = int(m.group(1))
            print(f"[{store}] Siden oppgir {expected_total} produkter totalt.")
    except Exception:
        pass

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
    for _ in range(60):
        before = len(collected)
        collect_visible_cards()
        if expected_total is not None and len(collected) >= expected_total:
            break
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(900)
        stagnant_rounds = stagnant_rounds + 1 if len(collected) == before else 0
        if stagnant_rounds >= 8:
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
    now = datetime.datetime.now().isoformat(timespec="seconds")
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


def update_changes_log(new_events: list, max_entries: int = 300, max_age_days: int = 14) -> list:
    path = "docs/changes.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f).get("changes", [])
    except Exception:
        existing = []

    combined = new_events + existing
    cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days)

    filtered = []
    for e in combined:
        try:
            when = datetime.datetime.fromisoformat(e["detected_at"])
        except Exception:
            when = datetime.datetime.now()
        if when >= cutoff:
            filtered.append(e)

    filtered = filtered[:max_entries]

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"changes": filtered}, f, ensure_ascii=False, indent=2)

    return filtered


def main():
    all_products: list = []
    previous_by_url = load_previous_products()

    print("Scanner Cardcenter (via API)...")
    all_products += scrape_cardcenter()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="nb-NO")
        page = context.new_page()

        for site in PLAYWRIGHT_SITES:
            print(f"Scanner {site['store']}...")
            if site.get("custom_scraper") == "nille":
                all_products += scrape_nille(page, site)
            else:
                all_products += scrape_with_browser(page, site)

        browser.close()

    new_events = compute_new_stock_events(all_products, previous_by_url)
    changes = update_changes_log(new_events)

    output = {
        "last_updated": datetime.datetime.now().isoformat(timespec="seconds"),
        "products": [asdict(p) for p in all_products],
    }

    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    in_stock_count = sum(1 for p in all_products if p.in_stock)
    print(f"\nFerdig. {len(all_products)} produkter funnet totalt, "
          f"{in_stock_count} pa lager. Lagret til docs/data.json")
    print(f"{len(new_events)} nye lagerhendelser siden forrige kjoring "
          f"(totalt {len(changes)} lagret i docs/changes.json).")


if __name__ == "__main__":
    main()
