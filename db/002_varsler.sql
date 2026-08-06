-- Pokepuls: varsling, admin og SEO.
-- Idempotent, som 001. Kjores av deploy/oppsett-api.sh etter 001.

-- ------------------------------------------------------------ varsling
-- Hvilke hendelser er allerede sendt til hvilken bruker.
--
-- Uten denne tabellen ville en omstart av senderen, en dobbel cron-kjoring
-- eller en manuell testkjoring sende det samme varselet pa nytt. Et varsel
-- som kommer to ganger er verre enn ingen varsel: du slutter a stole pa dem.
CREATE TABLE IF NOT EXISTS notifications_sent (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_id    BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  kanal       TEXT   NOT NULL DEFAULT 'push',
  ok          BOOLEAN NOT NULL DEFAULT TRUE,
  feil        TEXT,
  sendt_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, event_id)
);
CREATE INDEX IF NOT EXISTS varsel_tid_idx  ON notifications_sent (sendt_at DESC);
CREATE INDEX IF NOT EXISTS varsel_bruk_idx ON notifications_sent (user_id, sendt_at DESC);

-- Vannmerke: hoyeste event-id senderen har vurdert. Dette er IKKE det samme
-- som "hoyeste id i notifications_sent" -- de aller fleste hendelser har
-- ingen abonnenter, og uten et eget vannmerke ville senderen ga gjennom hele
-- hendelsestabellen pa nytt hver gang.
CREATE TABLE IF NOT EXISTS varsel_tilstand (
  id             INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  siste_event_id BIGINT NOT NULL DEFAULT 0,
  sist_kjort_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Forste gang: start pa dagens hoyeste id. Ellers ville forste kjoring
-- sende varsler for hver eneste hendelse siden mars.
INSERT INTO varsel_tilstand (id, siste_event_id)
  VALUES (1, COALESCE((SELECT max(id) FROM events), 0))
  ON CONFLICT (id) DO NOTHING;

-- Push-enheter kan doe (avinstallert PWA, utlopt abonnement). Vi sletter
-- dem ikke ved forste feil -- pushtjenester gir 5xx nar telefonen er av --
-- men etter 404/410, som betyr "denne kommer aldri tilbake".
ALTER TABLE push_endpoints ADD COLUMN IF NOT EXISTS feil_pa_rad INT NOT NULL DEFAULT 0;
ALTER TABLE push_endpoints ADD COLUMN IF NOT EXISTS sist_feil TEXT;

-- Per-bruker varselinnstillinger. Stille natt er PA som standard, fordi et
-- varsel kl. 03 om en butikk som ikke ekspederer for kl. 09 bare vekker deg.
ALTER TABLE users ADD COLUMN IF NOT EXISTS varsel_stille_natt BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS varsel_maks_pris_ore INT;

-- ---------------------------------------------------------------- admin
-- Manuelle katalogkoblinger gjort fra admin-siden. Skilles fra katalog.json
-- sa en feilkobling kan angres uten a redigere en fil pa serveren, og sa vi
-- ser hvilke som er menneskelagd nar reglene i matcher.py forbedres.
CREATE TABLE IF NOT EXISTS manual_matches (
  id         BIGSERIAL PRIMARY KEY,
  title      TEXT NOT NULL UNIQUE,
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  laget_av   UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ SEO
-- Sidekartet trenger "sist endret" per produkt. Den finnes allerede i
-- listings.last_seen_at; indeksen gjor at /sitemap.xml slipper full skann.
CREATE INDEX IF NOT EXISTS listings_sett_idx ON listings (last_seen_at DESC);
