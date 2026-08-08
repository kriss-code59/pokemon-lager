-- «Foelg alt» med demping.
--
-- HVORFOR DEMPING ER EN DEL AV FUNKSJONEN, IKKE EN INNSTILLING
--
-- Katalogen ga 433 restock, 105 prisendringer og 202 utsolgt paa ett doegn.
-- En knapp som foelger alt uten tak er derfor ikke en funksjon, det er en
-- maate aa faa folk til aa skru av varsler permanent den forste kvelden.
-- Taket er 5 i timen som standard; resten samles i ETT varsel.
--
-- Idempotent, som resten av migrasjonene.

-- ------------------------------------------------- 1. baade NULL = alt
-- Grunnskjemaet krevde at minst ett av product_id/set_id var satt. «Alt»
-- er nettopp fravaeret av begge, saa den regelen maa byttes ut. Den nye
-- regelen forbyr det som faktisk er tvetydig: baade produkt OG sett satt.
DO $$
DECLARE n TEXT;
BEGIN
  SELECT conname INTO n FROM pg_constraint
   WHERE conrelid = 'subscriptions'::regclass AND contype = 'c'
     AND pg_get_constraintdef(oid) ILIKE '%product_id IS NOT NULL%OR%set_id IS NOT NULL%';
  IF n IS NOT NULL THEN
    EXECUTE format('ALTER TABLE subscriptions DROP CONSTRAINT %I', n);
  END IF;
END $$;

ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subs_maal_check;
ALTER TABLE subscriptions ADD CONSTRAINT subs_maal_check
  CHECK (NOT (product_id IS NOT NULL AND set_id IS NOT NULL));

-- Én «foelg alt» per bruker. Uten denne kan et dobbelttrykk gi to rader,
-- og da teller hver hendelse to ganger mot kvoten.
CREATE UNIQUE INDEX IF NOT EXISTS subs_alle_idx ON subscriptions (user_id)
  WHERE product_id IS NULL AND set_id IS NULL;

-- ------------------------------------------------------ 2. timeskvoten
ALTER TABLE users ADD COLUMN IF NOT EXISTS
  varsel_maks_per_time SMALLINT NOT NULL DEFAULT 5;

-- Én rad per bruker, nullstilt naar klokketimen ruller over. Vi lagrer de
-- fem forste dempede titlene slik at samlevarselet kan si HVA du gikk
-- glipp av, ikke bare hvor mange.
CREATE TABLE IF NOT EXISTS varsel_kvote (
  user_id      UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  time_start   TIMESTAMPTZ NOT NULL DEFAULT date_trunc('hour', now()),
  sendt        SMALLINT NOT NULL DEFAULT 0,
  dempet       SMALLINT NOT NULL DEFAULT 0,
  dempet_tekst TEXT[]   NOT NULL DEFAULT '{}'
);
