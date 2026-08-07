-- Pokepuls: skill forhaandssalg og bestillingsvarer fra ekte lager.
-- Idempotent. Kjores av deploy/oppsett-api.sh etter 003.
--
-- Se katalog/tilgjengelighet.py for hvorfor dette maatte til. Kort versjon:
-- butikkene setter available=true paa forhaandssalg, saa en vare du ikke kan
-- faa i hus sto som «Paa lager» -- og utloste restock-varsel.

ALTER TABLE listings ADD COLUMN IF NOT EXISTS bestillingstype TEXT
  CHECK (bestillingstype IN ('forhandssalg', 'bestillingsvare'));

-- Delvis indeks: de aller fleste radene er NULL (vanlige varer), og det er
-- de faa som IKKE er det vi stadig filtrerer paa.
CREATE INDEX IF NOT EXISTS listings_bestilling_idx
  ON listings (product_id, bestillingstype) WHERE bestillingstype IS NOT NULL;

-- Etterfyll fra titlene vi allerede har.
--
-- Uten dette ville fiksen forst blitt synlig etter neste ingest, og bare for
-- varer som fortsatt ligger ute. Regelen her MAA speile
-- katalog.tilgjengelighet.bestillingstype() -- den er sannheten, denne er en
-- engangsopprydding. Rekkefolgen er den samme: bestillingsvare forst, fordi
-- «BESTILLINGSVARE» ogsaa inneholder «BESTILLING».
UPDATE listings SET bestillingstype = 'bestillingsvare'
 WHERE bestillingstype IS NULL
   AND title ~* '(bestillingsvare|bestillings\s*vare|skaffevare|restordre|backorder)';

UPDATE listings SET bestillingstype = 'forhandssalg'
 WHERE bestillingstype IS NULL
   AND title !~* 'pre[[:space:]-]?release'
   AND title ~* '(forh[åa]ndsbestilling|forh[åa]ndssalg|forh[åa]ndsreservasjon|pre[[:space:]_-]?order|[\[\(][[:space:]]*bestilling[[:space:]]*[\]\)])';
