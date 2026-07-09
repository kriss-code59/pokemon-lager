# Pokemon Lagerbot 🔍

Scanner Norli, Ark, Cardcenter og PokeMadness for Pokemon-produkter og viser
resultatet i et enkelt dashboard.

## Slik kommer du i gang (5 minutter)

1. **Opprett et GitHub-repo** og last opp disse filene (eller `git push` fra denne mappen).
2. Gå til **Settings → Pages** i repoet, og sett kilden til `main` branch, mappe `/docs`.
   Etter noen minutter er dashboardet live på `https://dittbrukernavn.github.io/repo-navn/`.
3. Gå til **Settings → Actions → General** og sørg for at "Read and write permissions"
   er slått på for GITHUB_TOKEN (trengs for at boten kan committe oppdatert data).
4. Det er det! Workflowen (`.github/workflows/scrape.yml`) kjører automatisk
   hvert 20. minutt og oppdaterer `docs/data.json`, som dashboardet leser.

Du kan også trigge en kjøring manuelt: gå til **Actions**-fanen → "Scan Pokemon-lager" → "Run workflow".

## Push-varsler (ntfy)

Boten sender et push-varsel via [ntfy.sh](https://ntfy.sh) hver gang den finner
et nytt produkt eller en restock. Standard-topic er `pokemon-lager-sk82sw9vyl`
(generert tilfeldig) — installer ntfy-appen (iOS/Android/nettleser) og
abonner på det topic-navnet, så får du varsler med en gang.

**Merk:** ntfy-topics er offentlige med mindre du selv setter opp autentisering
— alle som gjetter/finner topic-navnet kan abonnere på det samme varselet.
Standard-topic-navnet ligger i `.github/workflows/scrape.yml`, som er
offentlig synlig i repoet. Vil du ha et privat topic-navn, sett en
repo-secret kalt `NTFY_TOPIC` (Settings → Secrets and variables → Actions)
med ditt eget, hemmelige topic-navn — den overstyrer standardverdien
automatisk uten at du trenger å endre kode.

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

- **Cardcenter** bruker Shopifys offentlige `products.json`-API — dette er
  stabilt og bør fungere uten endringer.
- **Ark, Norli, Nille og PokeMadness** scrapes ved å lese HTML-en med en nettleser
  (Playwright). Disse sidene endrer struktur fra tid til annen. Hvis boten
  plutselig finner 0 produkter på en side (sjekk loggen i Actions-kjøringen),
  må du:
  1. Åpne siden i nettleseren din
  2. Høyreklikk på et produktkort → "Inspiser"
  3. Finn riktig CSS-klasse/selector og oppdater `card_selector`,
     `name_selector` og `price_selector` i `scrape.py`

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

Åpne `scrape.py` og legg til et nytt objekt i `PLAYWRIGHT_SITES`-listen med
riktig URL og selektorer, eller skriv en egen funksjon som for Cardcenter
hvis butikken har et offentlig API (Shopify-butikker gjenkjennes ofte på at
URL-ene inneholder `/collections/` og `/products/`).
