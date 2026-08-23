-- Fysiske butikker: hvor du kan gaa inn og kjope kort i dag.
--
-- HVA DENNE TABELLEN ER, OG HVA DEN IKKE ER
--
-- Den sier HVOR kjedene har utsalg. Den sier IKKE hva som staar paa hylla
-- der akkurat naa, og det skillet er hele grunnen til at kolonnene ser ut
-- som de gjor.
--
-- Vi undersokte alle 46 butikkene. Bare Outland oppgir lager i fysisk
-- butikk i det hele tatt, og de oppgir bare ANTALLET -- «Tilgjengelig i 4
-- butikker» -- ikke hvilke fire. Ingen norsk kjede vi leser rekker ut med
-- lager per filial.
--
-- Derfor lover vi ikke noe vi ikke vet. Kartet svarer paa «finnes det en
-- butikk i naerheten min», ikke «har DEN butikken varen». Det forste er
-- ekte og nyttig; det andre ville vaert et kvalifisert gjett med et kart
-- rundt, og et kart faar folk til aa tro paa presisjon som ikke finnes.
--
-- Idempotent, som resten.

CREATE TABLE IF NOT EXISTS fysiske_butikker (
  id          TEXT PRIMARY KEY,           -- «outland-bergen»
  store_id    TEXT REFERENCES stores(id), -- kobling til nettbutikken, om vi leser den
  kjede       TEXT NOT NULL,              -- «Outland»
  navn        TEXT NOT NULL,              -- «Outland Bergen»
  adresse     TEXT NOT NULL,
  poststed    TEXT NOT NULL,
  -- Koordinater i grader. NUMERIC, ikke FLOAT: en breddegrad som flyter
  -- er en prikk som flytter seg, og prikker paa et kart skal staa i ro.
  lat         NUMERIC(8, 5) NOT NULL,
  lon         NUMERIC(8, 5) NOT NULL,
  -- Butikker som ikke har aapnet enna skal vaere med i oversikten, men
  -- ikke telles som et sted du kan dra i dag.
  aapnet      BOOLEAN NOT NULL DEFAULT TRUE,
  merknad     TEXT,
  endret      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS fysiske_butikker_kjede_idx ON fysiske_butikker (kjede);

-- ---------------------------------------------------------------- lager
--
-- Antall fysiske butikker som har varen. Fra Outland: «Tilgjengelig i N
-- butikker». Ingen kjede oppgir HVILKE, saa dette er et tall og ikke en
-- liste -- og kolonnenavnet sier det, slik at ingen senere tror den kan
-- brukes til aa peke paa et kart.
ALTER TABLE listings ADD COLUMN IF NOT EXISTS antall_fysiske_butikker INT;

-- ------------------------------------------------------- Outland, 15 utsalg
--
-- Adressene er lest fra outland.no/butikker. Koordinatene er paa bynivaa,
-- ikke gateniva -- det er noyaktig nok for en prikk paa et Norgeskart, og
-- det later ikke som om vi vet mer enn vi gjor.
--
-- ON CONFLICT DO UPDATE: flytter en butikk, retter vi raden her og neste
-- deploy tar den. Ingen manuell SQL paa serveren.

INSERT INTO fysiske_butikker (id, store_id, kjede, navn, adresse, poststed, lat, lon, aapnet, merknad) VALUES
  ('outland-bergen',       'outland', 'Outland', 'Outland Bergen',       'Strandkaien 14',        'Bergen',       60.39299,  5.32415, TRUE, NULL),
  ('outland-bodo',         'outland', 'Outland', 'Outland Bodø',         'Stormyrveien 20',       'Bodø',         67.28540, 14.42510, TRUE, 'City Nord'),
  ('outland-fredrikstad',  'outland', 'Outland', 'Outland Fredrikstad',  'Jens Wilhelmsens gate 7','Kråkerøy',    59.19790, 10.93430, TRUE, 'Værstetorvet'),
  ('outland-hamar',        'outland', 'Outland', 'Outland Hamar',        'Vangsvegen 62',         'Hamar',        60.79450, 11.07690, TRUE, 'CC Hamar'),
  ('outland-jessheim',     'outland', 'Outland', 'Outland Jessheim',     'Storgata 6',            'Jessheim',     60.14170, 11.17470, TRUE, 'Jessheim Storsenter'),
  ('outland-kristiansand', 'outland', 'Outland', 'Outland Kristiansand', 'Barstølveien 35',       'Kristiansand', 58.16330,  8.06740, TRUE, 'Sørlandssenteret'),
  ('outland-oslo-grensen', 'outland', 'Outland', 'Outland Oslo Grensen', 'Grensen 5-7',           'Oslo',         59.91430, 10.74300, TRUE, NULL),
  ('outland-oslo-kirkegata','outland','Outland', 'Outland Oslo Kirkegata','Kirkegata 32',         'Oslo',         59.91060, 10.74300, TRUE, NULL),
  ('outland-oslo-kpop',    'outland', 'Outland', 'Outland Oslo K-pop',   'Kirkegata 32',          'Oslo',         59.91060, 10.74310, TRUE, 'K-pop-butikk'),
  ('outland-porsgrunn',    'outland', 'Outland', 'Outland Porsgrunn',    'Kulltangvegen 70',      'Porsgrunn',    59.13650,  9.65970, TRUE, 'Down Town'),
  ('outland-stavanger',    'outland', 'Outland', 'Outland Stavanger',    'Breigata 4',            'Stavanger',    58.97060,  5.73280, TRUE, NULL),
  ('outland-trondheim',    'outland', 'Outland', 'Outland Trondheim',    'Jomfrugata 4',          'Trondheim',    63.43050, 10.39510, TRUE, NULL),
  ('outland-tonsberg',     'outland', 'Outland', 'Outland Tønsberg',     'Fayes gate 5',          'Tønsberg',     59.26760, 10.40760, TRUE, NULL),
  ('outland-tromso',       'outland', 'Outland', 'Outland Tromsø',       'Heilovegen 9',          'Tromsø',       69.65120, 18.95530, FALSE, 'Åpner høsten 2026'),
  ('outland-alesund',      'outland', 'Outland', 'Outland Ålesund',      'Moaveien 1',            'Ålesund',      62.47170,  6.23760, TRUE, 'AMFI Moa Nord')
ON CONFLICT (id) DO UPDATE SET
  navn = EXCLUDED.navn, adresse = EXCLUDED.adresse, poststed = EXCLUDED.poststed,
  lat = EXCLUDED.lat, lon = EXCLUDED.lon, aapnet = EXCLUDED.aapnet,
  merknad = EXCLUDED.merknad, endret = now();
