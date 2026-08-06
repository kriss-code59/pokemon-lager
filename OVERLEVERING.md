# Pokepuls — overlevering

Sist oppdatert: 2026-08-06, kveld. Denne filen erstatter alle tidligere
overleveringer. Les punkt 1 før du gjør noe annet.

---

## 1. Status: alt er deployet og live

Scraperen går, koden er pushet, `deploy/oppsett-api.sh` er kjørt, VAPID-nøkler
er laget, og databasen er migrert. **Det som gjenstår er to ting bare du kan
gjøre:**

### a) Slå på varsler på telefonen din — 2 minutter

1. Åpne **pokepuls.no** i Safari på iPhone
2. **Del → Legg til på Hjem-skjerm** (iOS gir ikke Web Push til en side som
   ikke ligger der — det er ikke noe vi kan omgå)
3. Åpne Pokepuls fra hjemskjermen, logg inn
4. Konto-ikonet øverst til høyre → **🔔 Slå på varsler** → **Send et testvarsel**

Du er allerede satt til `admin`, så **Åpne admin** dukker opp samme sted.

### b) Meld pokepuls.no inn i Google Search Console

Sidene finnes nå — Google vet det ikke. Verifiser eierskap og send inn
`https://pokepuls.no/sitemap.xml` (462 produktsider). Sjekk en av dem med
Rich Results Test; JSON-LD-en skal gi pris og «på lager» rett i søketreffet.

Verifiser at alt fortsatt står (alt svarte riktig 2026-08-06 kl. 23:20):

```bash
curl -s https://pokepuls.no/api/health | jq          # ok: true
curl -s https://pokepuls.no/api/push/nokkel | jq     # paa: true
curl -s https://pokepuls.no/robots.txt               # ikke app-skallet
curl -s https://pokepuls.no/sitemap.xml | grep -c loc
```

---

## 2. Hva som ble gjort denne økten

**Scraperen sto i 28 timer og går igjen.** Årsaken var den i forrige
overlevering: cron kunne ikke kjøre skriptet fordi kjørebiten forsvant.
Fikset på serveren *og* varig i `oppsett-api.sh` — cron kaller nå
`/bin/bash <skript>`, så filmodus ikke lenger betyr noe.

**Varsler du faktisk mottar.** Hele Web Push-kjeden er bygget: VAPID-nøkler,
`/api/push/*`, push-håndtering i `sw.js`, av/på-knapp i appen med
iOS-forklaring, og en cron-sender som leser nye hendelser og matcher dem mot
følgelisten.

**Varseltekst med prissvar.** Samme form som PokéSnag, fordi den formen er
riktig:

```
🛒 Mythic: På lager
Prismatic Evolutions / Booster Bundle
1 399 kr · ✅ billigst på lager
```

Andre linje er hele poenget. Uten den må du åpne siden for å vite om
varselet var verdt å få, og da har det ikke spart deg for noe. Den svarer
på tre måter: `⚠️ finnes billigere: 899 kr hos Kanoncon`,
`✅ billigst på lager`, eller — når bare én butikk har varen —
`billigst kjøpbar siste 7 døgn: 999 kr`.

**Dødmannsknappen varsler nå deg.** Den fyrte som den skulle 5. august, inn
i et ntfy-topic ingen fulgte med på. Nå pusher den til alle med
`role='admin'` — samme kanal du har på telefonen for restock, og som du
merker med en gang hvis den slutter å virke. Den leser også `scrape_runs` i
Postgres i stedet for `docs/data.json`, som kan skrives selv om ingest feiler.
ntfy er igjen som reserve, men bare hvis `NTFY_TOPIC` er satt.

**Admin på `/admin.html`,** bak `role='admin'` (endepunktene svarer 404 til
alle andre — en side som sier «forbudt» bekrefter at den finnes). Tre faner:
drift (kjøringer, butikker, hendelser, varsler sendt), brukere (hvem de er,
hva de følger, hvilke enheter, hvilke varsler de har fått), og katalog — der
du kan koble en umatchet tittel til et kanonisk produkt i nettleseren.
Koblingen lagres i `manual_matches` og overlever neste ingest.

**Scraperen er parallellisert: 19 min → 9,5 min.** Målt på en full runde
2026-08-06 kl. 23:22 (19 597 varer, 6 414 på lager). 18 Shopify-butikker
seks om gangen i én trådpool, 18 nettleserbutikker fordelt på tre
Chromium-instanser, og de to halvdelene kjører samtidig. Justerbart uten
deploy med `POKEPULS_SHOPIFY_PARALLELL` og `POKEPULS_BROWSER_PARALLELL`.

Loggen skriver nå de åtte tregeste butikkene, og den første målingen sier
noe tydelig:

```
Tregeste butikker: Collectible 301s, Gameninja 106s, PokeShop 86s,
Ark 76s, Neo Tokyo 74s, Outland 68s, Pokecandy 64s, Playlot 62s
```

**Collectible alene er 5 av de 9,5 minuttene.** Én butikk eier halve
rundetiden. Det er den neste tingen å se på — ikke flere tråder.

**Frontend v6.** Nyeste aktivitet øverst i stedet for alfabetisk — alfabetisk
er en sortering for et arkiv, og satte «Ascended Heroes» først hver dag
uansett hva som hadde skjedd. Hvert kort viser nå laveste pris **og hvilken
butikk**, ikke «6 tilbud» (et tall om databasen, ikke om varen). Ferske
hendelser får et grønt tidsmerke. «Vestlig» heter **«Engelsk»**, som er det
butikkene og folk faktisk sier. Resten av teksten har fått æøå.

**SEO.** Hvert produkt har nå en ekte URL med ferdig HTML fra serveren:
`/p/prismatic-evolutions:booster-bundle:en`. Googlebot kan kjøre JavaScript,
men gjør det i en tregere kø — for et nytt domene uten autoritet betyr det i
praksis at en SPA ikke indekseres. Sidene har title, meta description,
canonical, Open Graph og JSON-LD `Product` + `AggregateOffer`, som er det som
gir pris og «på lager» rett i søketreffet. `/sitemap.xml` genereres fra
databasen og tar bare med produkter som faktisk har tilbud.

**Ikonene manglet.** `manifest.webmanifest` pekte på `ikon-192.png` og
`ikon-512.png` som aldri har eksistert i repoet — PWA-installasjon på Android
og varselikonet var ødelagt. Nå finnes de, pluss `ikon-badge.png`.

**Bildene: 0 → 3 762.** Admin-siden svarte på spørsmålet forrige overlevering
ikke rakk: «Med bilde: 0». Ingen av 3 900 oppføringer hadde bilde, mens
`data.json` hadde 19 197 bilde-URL-er liggende. Skjemaet hadde
`listings.image_url` fra dag én, API-et leste den, frontenden viste den —
men `ingest.py` skrev den aldri. Et felt som leses av alle og skrives av
ingen feiler helt stille: ingenting kaster, listen ser bare litt kjedelig
ut. Nå har 96 % av oppføringene ekte produktfoto.

---

## 3. Hva som er live nå

**https://pokepuls.no** — TLS fra Let's Encrypt, gyldig til 2026-11-03,
fornyer seg selv. `http://49.12.72.233` fungerer som reserveinngang.

| Del | Status |
|---|---|
| Server | Hetzner CX23, **49.12.72.233**, Ubuntu 26.04, Postgres 18 |
| DNS | `pokepuls.no A 49.12.72.233` TTL 3600, cPanel hos Domene AS |
| E-post | MX + `mail.pokepuls.no` urørt — går fortsatt til Domene |
| API | `/snapshot /catalog /product /history /unmatched /health` |
| Kontoer | `/api/auth/*` + `/api/watchlist` |
| Varsler | `/api/push/*` + `overvak/varsler.py`, cron hvert 5. min — **live** |
| Admin | `/admin.html` + `/api/admin/*` bak role=admin — **live** |
| Sider | `/p/<id>` (462 stk), `/sitemap.xml`, `/robots.txt` — **live** |
| Frontend | Mobil-først, 4 faner, **v=7**. 3 762 av 3 921 varer har foto |
| Scraper | 33 butikker, hvert 20. min — **går** (3 899 varer, 0 feilet) |
| Dødmannsknapp | Hvert 15. min, pusher til admin |
| Gammel EC2 | Kjører fortsatt parallelt. Skal sies opp. |

---

## 4. Slik kommer du til serveren

Sandkassen (`bash`) når **ikke** Hetzner, AWS eller api.github.com. Bare
`pypi.org` og `github.com` over git/https fungerer. Kjeden er:

```
Chrome → AWS-konsollen → EC2 Instance Connect
       (i-0706836e16d3f9732, eu-north-1, osUser=ubuntu)
       → ssh -o StrictHostKeyChecking=no -i ~/.ssh/pokepuls_ed25519 root@49.12.72.233
```

**`osUser=ubuntu`, ikke `ec2-user`** — det siste gir «Failed to connect»
uten forklaring, og koster fem minutter hver gang.

Kristian må være innlogget i AWS-konsollen; sesjonen ryker etter noen timer.

Direktelenke som hopper over navigeringen:

```
https://eu-north-1.console.aws.amazon.com/ec2-instance-connect/ssh?connType=standard&instanceId=i-0706836e16d3f9732&osUser=ubuntu&region=eu-north-1&sshPort=22
```

Jobb i terminalvinduet med `ssh root@... 'kommando'` (ett kall, ferdig
kommando) i stedet for en interaktiv økt — utdata kommer da tilbake i ett
skjermbilde og kan leses.

**Kode inn i repoet:** ingen push-tilgang fra sandkassen. Bruk GitHubs
opplastingsside i Chrome, én katalog om gangen:
`https://github.com/kriss-code59/pokemon-lager/upload/main/<mappe>`,
`file_upload` med filstien i outputs-mappa, og commit via `javascript_tool`
(`[...document.querySelectorAll('button')].find(b => b.textContent.trim() ===
'Commit changes').click()` — et vanlig klikk virker ikke).

---

## 5. Fallgruver som har kostet tid (ikke gjenta dem)

| Felle | Konsekvens | Løsning |
|---|---|---|
| GitHub-opplasting gir mode 644 | cron kan ikke kjøre skript | cron kaller `/bin/bash <skript>` — ligger i `oppsett-api.sh` nå |
| EC2 Instance Connect med `ec2-user` | «Failed to connect», ingen forklaring | `osUser=ubuntu` |
| `oppsett-api.sh` kopierte nginx-konfig over certbots TLS-blokk | hele siden nede på https | skriptet hopper over konfigen hvis den har `ssl_certificate` |
| `systemctl enable --now` på en tjeneste som alt kjører | serveren svarte med gammel kode etter deploy | `systemctl restart` |
| nginx cacher statiske filer en uke | du ser din egen gamle kode | bump `?v=` i `index.html` **og** `SKALL`/`CACHE` i `sw.js`. Vi står på **v=6** |
| `location /p/` etter `location /` i nginx | Googlebot får app-skallet i stedet for produktsiden | de nye blokkene ligger før `location /` |
| Nye VAPID-nøkler | alle push-abonnementer dør stille | `oppsett-api.sh` lager dem bare hvis de mangler |
| `chmod` i deploy-skriptet | hver `git pull` etterpå stopper på modusendring | `git config core.fileMode false` — ligger i `oppsett-api.sh` nå |
| Nye `location`-blokker i `nginx-pokepuls.conf` | de kom aldri ut i drift, fordi skriptet med vilje ikke rører certbots fil. `/robots.txt` svarte med app-skallet | alt nytt ligger i `deploy/nginx-sider.conf` og inkluderes med én linje |
| Å laste opp ny `app.js` uten å bumpe `?v=` | du tester mot din egen gamle kode i nettleseren | bump versjon **hver gang** app.js endres, ikke bare ved «release» |
| Egen DNS-cache | du ser gammel side | `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder` |

---

## 6. Hvordan varslingen henger sammen

```
scrape.py → docs/data.json → ingest/ingest.py → events (Postgres)
                                                    ↓
                                   overvak/varsler.py (cron, hvert 5. min)
                                                    ↓
                     varsel_tilstand.siste_event_id = vannmerke
                     subscriptions → hvem følger dette?
                     varsling/kontekst.py → hva koster den andre steder?
                     varsling/tekst.py → tittel + to linjer
                     varsling/send.py → pywebpush (aes128gcm)
                                                    ↓
                                    web/sw.js  →  varselet på telefonen
```

Fire ting den gjør for å ikke gjøre seg selv ubrukelig, og som ikke må
fjernes:

1. **Duplikater.** `notifications_sent` har `UNIQUE(user_id, event_id)`.
   Kjør senderen ti ganger på rad og du får fortsatt ett varsel.
2. **Storm.** Over 250 hendelser i én runde er nesten alltid en datafeil
   (en butikk som ble tom og kom tilbake), ikke at 400 varer kom inn
   samtidig. Da flyttes vannmerket uten at noe sendes. Samme resonnement som
   stormvernet i `scrape.py`, som har reddet oss før.
3. **Gamle nyheter.** Hendelser eldre enn 3 timer varsles aldri. Etter 28
   timer nede skal du ikke få 28 timer med restock-beskjeder.
4. **Døde enheter.** 404/410 fra pushtjenesten sletter abonnementet. 5xx
   gjør det ikke — da er telefonen bare av.

Stille natt (23–07 norsk tid) er på som standard per bruker. Varselet lagres
ikke til morgenen: et restock-varsel kl. 03 er verdiløst når du våkner kl. 07
og varen har vært borte i fire timer, og en kø med dårlige nyheter er verre
enn ingen.

---

## 7. Tester

```bash
python3 -m pytest tests/ -q                  # 113 passed
node --test tests/test_frontend.mjs          # 26 passed (krever: npm install jsdom)

# Selvtest mot ekte Postgres (kjøres på serveren):
sudo -u postgres createdb -O pokepuls pokepuls_test
sudo -u postgres psql -q -d pokepuls_test -c "CREATE EXTENSION IF NOT EXISTS citext; \
  CREATE EXTENSION IF NOT EXISTS pgcrypto; GRANT ALL ON SCHEMA public TO pokepuls"
cd /home/pokepuls/pokemon-lager
sudo -u pokepuls env POKEPULS_DSN=postgresql:///pokepuls_test \
  /home/pokepuls/venv/bin/python tests/selvtest.py
sudo -u postgres dropdb pokepuls_test
```

`tests/test_push_ende_til_ende.py` er verdt å kjenne til. Web Push har et
feilmodus ingen andre tester fanger: alt ser ut til å virke — 201 fra
serveren, `ok=true` i tabellen — og telefonen viser ingenting, fordi
krypteringen eller signaturen var feil og pushtjenesten kastet meldingen
uten å si ifra. Testen spiller begge roller: lager et abonnement slik en
nettleser gjør, sender gjennom vår egen kode, og **dekrypterer varselet
tilbake**. Kommer samme tekst ut, virker hele kjeden.

---

## 8. Neste steg, i prioritert rekkefølge

1. **Slå på varsler på telefonen** (punkt 1a). Ingenting av det over er
   verdt noe før varselet ligger på låseskjermen din.
2. **Google Search Console** (punkt 1b).
3. **Mål rundetiden etter parallelliseringen.** Admin → Drift viser nå
   varighet per kjøring, og loggen skriver «Skanning ferdig på X min» pluss
   de åtte tregeste butikkene. Tallet var meningsløst før (alltid «0 min»,
   fordi starttiden ble satt til når skanningen var *ferdig*) — det er
   fikset, så de første ekte målingene kommer fra kjøringene etter kl. 04.
   Er runden under ~7 min, kan intervallet ned fra 20 til 10 minutter i
   `/etc/cron.d/pokepuls`. Det halverer hvor gammelt et restock-varsel kan
   være, og det er hele poenget med produktet.
   Runden er allerede nede i 9,5 min, så intervallet **kan** ned til 10 med
   én gang. Men se på Collectible først: 301 s av 570 s går til én butikk,
   og fikser du den, er runden under 6 minutter. Flere tråder hjelper ikke
   når én bunke er så mye tyngre enn de andre — der er neste steg enten å
   fikse den butikken eller å bytte `sider[i::N]` mot en delt kø.
4. **Katalogdekning.** ~1 800 forseglede varer er umatchet. Admin-fanen
   «Katalog» sorterer dem på hvor mange butikker som selger dem, så den
   øverste koblingen gir mest dekning. Vanligste hull: Pokémon Center-esker
   (Tohoku, Hiroshima, Fukuoka), «Mega X ex Premium Collection»,
   «Pokémon Day 2026 Collection».
5. **Si opp EC2** når pokepuls har gått et døgn uten hull. Fjern samtidig
   den midlertidige brannmurregelen merket «TEMP» i `sg-0f88f2c230d345597`.
   Så lenge den lever, committer den `docs/data.json` og tvinger
   `git checkout -- docs/` inn i hver eneste deploy.
6. **E-postverifisering** når avsender er valgt (Resend/Postmark).
   `users.email_verified_at` finnes allerede.
7. **Card Kings** leverer null — selektorene må fikses.
8. **Betaling og premium.** `users.role`, `premium_until` og
   `subscriptions.fast_lane` finnes fra dag én; det som mangler er en webhook
   som setter to felter.

---

## 9. Ryddejobber

* **Testkonto:** `sudo -u pokepuls psql -d pokepuls -c "DELETE FROM users WHERE email='testkonto@pokepuls.no'"`
* **Verifiser bildene:** `SELECT count(*) FILTER (WHERE image_url IS NOT NULL), count(*) FROM listings`
  — tallet har aldri blitt sett.
* **`scrape.py` sender fortsatt ntfy** ved nye hendelser (`send_ntfy_notification`).
  Det er nå dobbelt opp med `overvak/varsler.py`. Fjern det når du har sett at
  push virker i et døgn.

---

## 10. Ting bare Kristian kan gjøre

* Logge inn i AWS-konsollen (sesjonen ryker med jevne mellomrom)
* Google Search Console: verifisere eierskap av pokepuls.no
* Konto hos Resend/Postmark for e-post
* Eventuell Cloudflare foran (krever bytte av navnetjenere hos Domene AS)

---

## 11. Arbeidsmåte som fungerer

* **Skriv oppsett som idempotente skript i repoet**, ikke kommandoer i et
  terminalvindu. `deploy/oppsett-api.sh` kan gjenskape serveren.
* **Test mot ekte data før du pusher.** Hver eneste feil i denne fila ble
  funnet av en test eller av å se på den kjørende siden — ingen av dem ble
  funnet ved å lese koden.
* **Én endring om gangen, verifiser, så neste.**
* **Se på siden etterpå.** Fire feil (filterrader som ble stående, gammel
  cache, butikknavn som løp sammen, fire volumer under samme produkt) var
  usynlige i testene og åpenbare i nettleseren.
* **Spør hva varselet skal si før du bygger det som sender det.** Formen på
  varselet — hvilke tre opplysninger, i hvilken rekkefølge — bestemte
  hvilke spørringer databasen måtte svare på, ikke omvendt.
