-- Pokepuls: det som ma finnes for fremmede kan bruke siden.
-- Idempotent, som 001 og 002. Kjores av deploy/oppsett-api.sh.
--
-- Tre hull som alle er ufarlige sa lenge du er eneste bruker, og alle blir
-- til supporthenvendelser i det du deler lenken:
--
--   1. Glemmer noen passordet sitt, er de permanent utestengt.
--   2. Vil noen slette kontoen sin, ma du gjore det med SQL.
--   3. Har noen noe a si, finnes det ingen plass a si det.

-- --------------------------------------------------------- engangstokener
-- Glemt passord og e-postverifisering. EN tabell, ikke to, fordi de har
-- nøyaktig samme livslop: lages, sendes pa e-post, brukes én gang, dor.
--
-- Selve tokenet lagres aldri -- bare sha256 av det, akkurat som sesjoner.
-- Lekker tabellen, kan ingen bruke innholdet til a overta en konto.
CREATE TABLE IF NOT EXISTS engangstokener (
  token_hash TEXT PRIMARY KEY,
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN ('passord', 'epost')),
  expires_at TIMESTAMPTZ NOT NULL,
  brukt_at   TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS token_bruker_idx ON engangstokener (user_id, kind);
CREATE INDEX IF NOT EXISTS token_utlop_idx  ON engangstokener (expires_at);

-- ------------------------------------------------------------- feedback
-- Kun fra innloggede brukere: da vet vi alltid hvem som sa det, og kan
-- svare. Prisen er at vi ikke horer fra dem som ikke gadd a lage konto --
-- det er et bevisst valg, ikke en forglemmelse.
CREATE TABLE IF NOT EXISTS feedback (
  id         BIGSERIAL PRIMARY KEY,
  -- ON DELETE SET NULL, ikke CASCADE: sletter noen kontoen sin, skal
  -- tilbakemeldingen deres fortsatt telle. Den er ikke lenger personlig
  -- naar den ikke peker pa en person.
  user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
  epost      TEXT,                    -- kopi, sa vi kan svare etter sletting
  tekst      TEXT NOT NULL CHECK (length(tekst) BETWEEN 3 AND 4000),
  slag       TEXT NOT NULL DEFAULT 'annet'
             CHECK (slag IN ('feil', 'onske', 'butikk', 'annet')),
  side       TEXT,                    -- hvor i appen de var
  user_agent TEXT,
  status     TEXT NOT NULL DEFAULT 'ny'
             CHECK (status IN ('ny', 'lest', 'gjort', 'avvist')),
  notat      TEXT,                    -- ditt eget notat, ikke synlig for dem
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feedback_tid_idx    ON feedback (created_at DESC);
CREATE INDEX IF NOT EXISTS feedback_status_idx ON feedback (status, created_at DESC);

-- --------------------------------------------------------- kontosletting
-- Sletting er ekte sletting (ON DELETE CASCADE fra users), men vi vil vite
-- HVOR MANGE som slutter, og helst hvorfor. Raden inneholder ingen
-- personopplysninger -- det er hele poenget.
CREATE TABLE IF NOT EXISTS slettede_kontoer (
  id         BIGSERIAL PRIMARY KEY,
  grunn      TEXT,
  dager_aktiv INT,
  antall_fulgt INT,
  slettet_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
