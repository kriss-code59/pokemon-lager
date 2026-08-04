-- Pokepuls: grunnskjema.
-- Idempotent (IF NOT EXISTS) sa den trygt kan kjores pa nytt.
--
-- Designet med to ting i tankene som IKKE bygges na, men som ikke skal
-- kreve omskriving senere: betalte abonnementer (users.role) og en
-- markedsplass (peker mot products.id).

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------- katalog
CREATE TABLE IF NOT EXISTS sets (
  id           TEXT PRIMARY KEY,              -- 'pitch-black'
  label        TEXT NOT NULL,
  region       TEXT NOT NULL CHECK (region IN ('en','jp','cn','ko')),
  release_date DATE,
  logo_url     TEXT
);

CREATE TABLE IF NOT EXISTS product_types (
  id         TEXT PRIMARY KEY,                -- 'booster-box'
  label      TEXT NOT NULL,
  sort_order INT NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS stores (
  id       TEXT PRIMARY KEY,                  -- 'cardcenter'
  name     TEXT NOT NULL,
  base_url TEXT,
  -- Butikker som blokkerer automatiske besok maa sjekkes manuelt.
  -- Vi omgaar ikke blokkeringer; vi lenker til dem i stedet.
  manual_only BOOLEAN NOT NULL DEFAULT FALSE,
  active   BOOLEAN NOT NULL DEFAULT TRUE
);

-- Kanonisk produkt = sett x type x region. Se katalog/matcher.py.
CREATE TABLE IF NOT EXISTS products (
  id        TEXT PRIMARY KEY,                 -- 'pitch-black:booster-box:en'
  set_id    TEXT NOT NULL REFERENCES sets(id),
  type_id   TEXT NOT NULL REFERENCES product_types(id),
  region    TEXT NOT NULL,
  msrp_ore  INT,                              -- heltall i ore, aldri tekst
  image_url TEXT
);
CREATE INDEX IF NOT EXISTS products_set_idx ON products (set_id);

-- ------------------------------------------------------------- oppforinger
CREATE TABLE IF NOT EXISTS listings (
  id          BIGSERIAL PRIMARY KEY,
  store_id    TEXT NOT NULL REFERENCES stores(id),
  product_id  TEXT REFERENCES products(id),   -- NULL = ikke mappet enna
  url         TEXT NOT NULL UNIQUE,
  title       TEXT NOT NULL,
  price_ore   INT,
  in_stock    BOOLEAN,                        -- NULL = ukjent, ikke "utsolgt"
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- last_ok_at skiller "butikken sier utsolgt" fra "skanningen feilet".
  -- Uten dette skillet ser en feilet skanning ut som at hele katalogen
  -- forsvant, og neste vellykkede kjoring sender tusenvis av falske
  -- "nytt produkt"-varsler. Se carry_forward_failed_stores() i scrape.py.
  last_ok_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS listings_product_idx ON listings (product_id) WHERE product_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS listings_store_idx   ON listings (store_id);
CREATE INDEX IF NOT EXISTS listings_instock_idx ON listings (product_id, in_stock) WHERE in_stock;

-- --------------------------------------------------------------- hendelser
-- Append-only. Erstatter history.json, som var 6,4 MB og ble skrevet om i
-- sin helhet ved hver kjoring for a legge til en handfull rader.
CREATE TABLE IF NOT EXISTS events (
  id             BIGSERIAL PRIMARY KEY,
  listing_id     BIGINT REFERENCES listings(id) ON DELETE CASCADE,
  product_id     TEXT REFERENCES products(id),
  store_id       TEXT REFERENCES stores(id),
  kind           TEXT NOT NULL CHECK (kind IN ('ny','restock','utsolgt','prisendring')),
  price_ore      INT,
  prev_price_ore INT,
  detected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_tid_idx     ON events (detected_at DESC);
CREATE INDEX IF NOT EXISTS events_produkt_idx ON events (product_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS events_kind_idx    ON events (kind, detected_at DESC);

-- --------------------------------------------------------------- brukere
-- role og premium_until finnes fra dag en. Betaling senere blir da en
-- webhook som setter to felter, ikke en omskriving av datamodellen.
CREATE TABLE IF NOT EXISTS users (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email             CITEXT NOT NULL UNIQUE,
  password_hash     TEXT NOT NULL,            -- argon2id
  email_verified_at TIMESTAMPTZ,
  role              TEXT NOT NULL DEFAULT 'free' CHECK (role IN ('free','premium','admin')),
  premium_until     TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,                -- aldri selve token
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);

-- Hva brukeren vil ha varsel om: enten et produkt eller et helt sett.
CREATE TABLE IF NOT EXISTS subscriptions (
  id         BIGSERIAL PRIMARY KEY,
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id TEXT REFERENCES products(id) ON DELETE CASCADE,
  set_id     TEXT REFERENCES sets(id) ON DELETE CASCADE,
  kinds      TEXT[] NOT NULL DEFAULT '{restock,ny}',
  -- fast_lane = premium-godet: tettere polling pa utvalgte produkter.
  -- PokeSnag begrenser dette til 30 produkter per bruker (fastLaneCap).
  fast_lane  BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (product_id IS NOT NULL OR set_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS subs_user_idx     ON subscriptions (user_id);
CREATE INDEX IF NOT EXISTS subs_produkt_idx  ON subscriptions (product_id) WHERE product_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS subs_fastlane_idx ON subscriptions (fast_lane) WHERE fast_lane;

-- Web Push-endepunkter (VAPID). En bruker kan ha flere enheter.
CREATE TABLE IF NOT EXISTS push_endpoints (
  id         BIGSERIAL PRIMARY KEY,
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint   TEXT NOT NULL UNIQUE,
  p256dh     TEXT NOT NULL,
  auth       TEXT NOT NULL,
  user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_ok_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS push_user_idx ON push_endpoints (user_id);

-- ------------------------------------------------------------------ drift
-- Helsestatus per skanning, sa dodmannsknappen og dashbordet kan se om en
-- kjoring var komplett eller bare delvis vellykket.
CREATE TABLE IF NOT EXISTS scrape_runs (
  id             BIGSERIAL PRIMARY KEY,
  started_at     TIMESTAMPTZ NOT NULL,
  finished_at    TIMESTAMPTZ,
  product_count  INT,
  store_count    INT,
  failed_stores  TEXT[],
  carried_stores TEXT[],
  ok             BOOLEAN
);
CREATE INDEX IF NOT EXISTS runs_tid_idx ON scrape_runs (started_at DESC);
