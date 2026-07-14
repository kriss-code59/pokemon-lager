# Pokemon Lagerbot 🔍

Scanner ~36 norske nettbutikker for Pokemon-produkter og viser resultatet i
et enkelt dashboard, med push-varsler (ntfy) for nye produkter og restock —
se "Varsler"-siden i dashboardet for å velge nøyaktig hva du vil varsles om.
Butikklisten er kuratert fra pokejakt.no sin butikkoversikt pluss et par
ekstra (Nille, Norli) — se `SHOPIFY_STORES` og `PLAYWRIGHT_SITES` i
`scrape.py` for den fullstendige listen. Ark, Cardcenter, Nille, PokeShop,
Outland, Pokelageret, Arcticloot, BoosterKongen, Boosterpakker, Braspill,
Card Kings, Cardhouse, Cardstore, Collectible, Emken, EpiCards, Gameninja,
Kanoncon, LABOGE, Lekekassen, Maxgaming, Mystic Trades, Neo Tokyo, NorthTCG,
Packs of Norway, Playlot, PokeNordic, Pokebua, Pokecandy, Pokefriends,
Pokelink, Pokesingles, Pokestore, RetroWorld, Spillbua og Spillmonster
scrapes automatisk (Norli, PokeMadness og CardCollect blokkerer automatiske
besøk eller krever mer arbeid — se "Sjekk manuelt" i dashboardet).

## Sider i dashboardet

- **Hjem** (`index.html`) — full oversikt over alle produkter, med søk,
  filtrering og sortering.
- **Utforsk** (`explorer.html`) — produkter gruppert på tvers av butikker og
  sortert etter størst prisforskjell, for rask "beste kjøp"-jakt.
- **Nyheter** (`updates.html`) — nye produkter, restock, utsolgt-hendelser og
  prisendringer, med filtrering på type og butikk.
- **Statistikk** (`statistics.html`) — restocks over tid, mest restockede
  produkter, gjennomsnittlig restock-intervall, butikkaktivitet og
  pristrender.
- **Produktside** (`product.html`) — sammenligning på tvers av butikker,
  prishistorikk-graf og en enkel restock-prognose basert på tidligere
  intervaller.
- **Varsler** (`settings.html`) — velg nøyaktig hvilke produkter/butikker du
  vil ha push-varsler for, se "Varslingsinnstillinger" under.

All historikk (lagerstatus, pris, tidspunkt, butikk) lagres hendelsesbasert i
`docs/history.json` (opptil 400 dager) — se `compute_extra_events()` og
`update_history_log()` i `scrape.py`.

## Slik kommer du i gang (5 minutter)

1. **Opprett et GitHub-repo** og last opp disse filene (eller `git push` fra denne mappen).
2. Gå til **Settings → Pages** i repoet, og sett kilden til `main` branch, mappe `/docs`.
   Etter noen minutter er dashboardet live på `https://dittbrukernavn.github.io/repo-navn/`.
3. Gå til **Settings → Actions → General** og sørg for at "Read and write permissions"
   er slått på for GITHUB_TOKEN (trengs for at boten kan committe oppdatert data).
4. Det er det! Workflowen (`.github/workflows/scrape.yml`) kjører automatisk
   ca. hvert 5. minutt (unntatt 22:00-04:00 norsk tid) og oppdaterer
   `docs/data.json`, `docs/changes.json` og `docs/history.json`, som
   dashboardet leser.

Du kan også trigge en kjøring manuelt: gå til **Actions**-fanen → "Scan Pokemon-lager" → "Run workflow".

## Push-varsler (ntfy)

Boten sender push-varsler via [ntfy.sh](https://ntfy.sh) når den finner et
nytt produkt eller en restock — installer ntfy-appen (iOS/Android/nettleser)
og abonner på topic-navnet ditt, så får du varsler med en gang. Standard-topic
er `pokemon-lager-sk82sw9vyl` (generert tilfeldig).

Det sendes to ulike varseltyper (se `send_ntfy_notification()` i `scrape.py`):

- **Nytt produkt-varsel** — normal prioritet, sendes når et helt nytt
  matchende produkt dukker opp i en butikk for første gang.
- **Restock-varsel** — høy prioritet med et tydelig "RESTOCK" i tittelen,
  sendes når et produkt som var utsolgt kommer tilbake på lager (siden
  populære restocks ofte blir utsolgt igjen raskt, haster dette varselet mer).

**Merk:** ntfy-topics er offentlige med mindre du selv setter opp autentisering
— alle som gjetter/finner topic-navnet kan abonnere på det samme varselet.
Standard-topic-navnet ligger i `.github/workflows/scrape.yml`, som er
offentlig synlig i repoet. Vil du ha et privat topic-navn, sett en
repo-secret kalt `NTFY_TOPIC` (Settings → Secrets and variables → Actions)
med ditt eget, hemmelige topic-navn — den overstyrer standardverdien
automatisk uten at du trenger å endre kode.

### Varslingsinnstillinger

Gå til **Varsler**-siden i dashboardet (`settings.html`) for å velge nøyaktig
hva du vil varsles om: produkttype (kortprodukter og/eller tilbehør),
hvilke butikker, og et fritt nøkkelord-utelukkelsesfilter. Siden er statisk
(ingen backend), så endringer lagres ikke automatisk — siden bygger en
oppdatert `notification_settings.json` du laster ned/kopierer og legger inn
i repoet (erstatter `docs/notification_settings.json`), så bruker boten de
nye innstillingene fra neste kjøring.

Innstillingene styrer `send_ntfy_notification()` i `scrape.py`:

```json
{
  "enabled": true,
  "product_classes": ["card"],
  "new_product_alert": { "enabled": true },
  "restock_alert": { "enabled": true, "priority": "high" },
  "store_allowlist": [],
  "store_blocklist": [],
  "keyword_blocklist": []
}
```

- **`product_classes`** — `"card"` og/eller `"accessory"`. Hvert produkt
  klassifiseres automatisk av `classify_product_class()` basert på
  produktnavnet (kjente tilbehørs-nøkkelord som "sleeve"/"toploader"/
  "plush"/"figur"/"godteri" gir `"accessory"`, alt annet er `"card"`).
  Standard er kun `"card"` — ingen varsler for tilbehør/samleobjekter.
- **`store_allowlist`/`store_blocklist`** — tom liste betyr "alle butikker"
  for allowlist. Har du satt en allowlist, brukes ikke blocklist.
- **`keyword_blocklist`** — ekstra manuell utelukkelse på delstreng i
  produktnavnet (store-ufølsomt), for tilfeller den automatiske
  produktklassifiseringen ikke fanger opp.

Manglende fil eller manglende felt faller tilbake til standardverdiene over
(se `DEFAULT_NOTIFICATION_SETTINGS` i `scrape.py`).

## Nattemodus (22:00–04:00)

Boten skanner ikke, og dashboardet oppdaterer seg ikke automatisk, mellom
22:00 og 04:00 norsk tid (Europe/Oslo, håndterer sommer-/vintertid riktig).
Dette gjelder både GitHub Actions-workflowen og siden i nettleseren.

## Kjøre lokalt (for testing)

```bash
pip install -r requirements.txt
playwright install chromium
python scrape.py
```

Åpne så `docs/index.html` i nettleseren for å se resultatet (eller kjør
`python -m http.server` i `docs/`-mappen).

## Viktig: selektorene må vedlikeholdes

De fleste butikkene bruker en av fire kjente plattformer, så vi bruker
generiske scrapere i stedet for å skreddersy én funksjon per butikk:

- **Shopify** (`SHOPIFY_STORES` i `scrape.py`) — offentlig `products.json`-API
  per samling. Dette er stabilt og bør fungere uten endringer. Dekker bl.a.
  Cardcenter, Pokelageret, Arcticloot, BoosterKongen, Braspill, Cardstore,
  EpiCards, LABOGE, NorthTCG, Packs of Norway, PokeNordic, Pokebua,
  Pokefriends, Pokelink, Pokesingles, Pokestore, RetroWorld og Spillbua.
- **"24Nettbutikk"** (`scrape_nettbutikk24()`) — norsk plattform med
  schema.org-markup for lagerstatus. Dekker PokeShop, Boosterpakker, Card
  Kings og Emken.
- **QuickButik** (`scrape_quickbutik()`) — nordisk plattform som skriver
  navn/pris direkte som `data-s-title`/`data-s-price`-attributter. Dekker
  Cardhouse, Mystic Trades og Pokecandy.
- **WooCommerce** (`scrape_woocommerce()`) — leser `instock`/`outofstock`-
  klassen som WooCommerce alltid legger på produktkortet, uavhengig av tema.
  Dekker Collectible, Gameninja, Kanoncon, Neo Tokyo, Playlot og Spillmonster.

Butikker med egne/uvanlige plattformer (**Ark, Nille, Outland, Lekekassen,
Maxgaming**) scrapes ved å lese HTML-en direkte med en nettleser (Playwright,
generisk `card_selector`/`name_selector`/`price_selector` i
`PLAYWRIGHT_SITES`, eller en egen funksjon som `scrape_nille()`/
`scrape_outland()` for butikker med spesielle behov som scrolling). Disse
sidene endrer struktur fra tid til annen. Hvis boten plutselig finner 0
produkter på en side (sjekk loggen i Actions-kjøringen), må du:
  1. Åpne siden i nettleseren din
  2. Høyreklikk på et produktkort → "Inspiser"
  3. Finn riktig CSS-klasse/selector og oppdater `card_selector`,
     `name_selector` og `price_selector` i `scrape.py`

**Norli** (`scrape_norli()`, ikke koblet inn i `PLAYWRIGHT_SITES`) er et eget
tilfelle: kategorisiden bruker Algolia InstantSearch (`li.ais-Hits-item` er
Algolia sin egen, stabile klasse — ikke Norli sine egne CSS-modul-klasser,
som får et nytt tilfeldig hash-suffiks ved hver deploy), og ekte
nettlagerstatus hentes fra schema.org Product-JSON-LD-en
(`<script type="application/ld+json">`) på hver produktside i stedet for
CSS-klasser eller norsk statustekst — en langt mer robust tilnærming rent
teknisk. Problemet er at Norli svarer med **HTTP 403 Forbidden til kjente
sky-/datasenter-IP-områder** (bekreftet fra GitHub Actions sine byggere),
mens den fungerer fint fra en vanlig privat/hjemme-IP. Siden vi ikke bygger
inn teknikker for å omgå IP-baserte blokkeringer (se prinsippet under
"Om lovlighet og god skikk"), er Norli satt tilbake til `MANUAL_CHECK_STORES`
for automatisk kjøring — men `scrape_norli()` fungerer korrekt hvis du kjører
`scrape.py` lokalt (se "Kjøre lokalt" over) fra en ikke-blokkert IP.

**PokeMadness** blokkerer automatiske besøk (Cloudflare-utfordring), og
**CardCollect** er en klientrendret Nuxt-app der vi ikke har verifisert en
stabil nok datakilde ennå — alle tre vises som "Sjekk manuelt" i dashboardet
(`MANUAL_CHECK_STORES`) i stedet.

**Spesielt om Nille:** Nille er primært en fysisk butikkjede, og noen produktsider
viser tilgjengelighet per butikk ("finn i butikk") i stedet for ren nettlagerstatus.
Sjekk et par produkter manuelt første gang for å se om "på lager"-teksten faktisk
betyr nettlager eller bare fysisk butikk, og juster `IN_STOCK_WORDS` i `scrape.py`
om nødvendig.

## Om lovlighet og god skikk

- Sjekk alltid butikkens `robots.txt` og kjøpsvilkår før du scraper i stort omfang.
- Boten sender et ærlig User-Agent-navn og venter noen sekunder mellom hver
  side, så den ikke belaster serverne unødig.
- Dette er ment for personlig bruk (å se hva som er på lager) — ikke for
  automatisert kjøp/"botting" eller videresalg, noe som ofte er i strid med
  butikkenes vilkår.
- Kjør ikke skanningen oftere enn nødvendig (20 min er et rimelig utgangspunkt).

## Legge til flere butikker

1. Sjekk om `<butikk>/products.json` svarer med gyldig JSON — da er det en
   Shopify-butikk, og du legger den bare til i `SHOPIFY_STORES` i `scrape.py`
   (finn riktig samlings-handle via `<butikk>/collections/<handle>/products.json`
   eller `<butikk>/collections.json`).
2. Hvis ikke: sjekk om siden er WooCommerce (klasser som `woocommerce-Price-amount`,
   `instock`/`outofstock` i HTML-en) eller viser tegn til "24Nettbutikk"
   (`productlist__product`-klasser) / QuickButik (`data-s-title`/`data-s-price`-
   attributter) — legg da butikken til i `WOOCOMMERCE_SITES`, `NETTBUTIKK24_SITES`
   eller `QUICKBUTIK_SITES`, som gjenbruker en eksisterende generisk scraper.
3. Ellers: legg til et nytt objekt i `PLAYWRIGHT_SITES`-listen med riktig URL
   og `card_selector`/`name_selector`/`price_selector` (se Ark-oppføringen som
   mal), eller skriv en egen funksjon som `scrape_nille()` hvis butikken har
   uvanlige behov (f.eks. scrolling for å laste inn flere produkter).
