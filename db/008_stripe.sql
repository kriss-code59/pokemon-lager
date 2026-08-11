-- Stripe-abonnement.
--
-- HVA SOM LAGRES, OG HVA SOM IKKE GJOR DET
--
-- Ingen kortnumre, ingen utlopsdato, ingen navn, ingen adresse. Alt det
-- ligger hos Stripe, og det er hele poenget med aa bruke dem. Vi lagrer to
-- ID-er og en dato: hvem kunden er hos Stripe, hvilket abonnement det
-- gjelder, og hvor lenge det er betalt for.
--
-- HVORFOR EN EGEN TABELL OG IKKE BARE KOLONNER PAA users
--
-- Fordi den skal kunne slettes uten aa roere kontoen. Sier noen opp og ber
-- om sletting, skal Stripe-koblingen kunne forsvinne mens kontoen lever
-- videre som gratisbruker.
--
-- Idempotent, som resten.

CREATE TABLE IF NOT EXISTS stripe_kunder (
  user_id            UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  stripe_customer_id TEXT UNIQUE NOT NULL,
  abonnement_id      TEXT,
  status             TEXT,
  gjelder_til        TIMESTAMPTZ,
  opprettet          TIMESTAMPTZ NOT NULL DEFAULT now(),
  endret             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS stripe_abonnement_idx
  ON stripe_kunder (abonnement_id) WHERE abonnement_id IS NOT NULL;

-- ------------------------------------------------------------ hendelser
--
-- Stripe leverer webhooks MINST én gang, ikke NOYAKTIG én gang. Kommer den
-- samme hendelsen to ganger -- og det gjor den, ved nettverksfeil eller
-- naar vi svarer for sent -- skal den andre ikke telle. Uten dette kan en
-- gjentatt `checkout.session.completed` gi to maaneder for én betaling.
--
-- Primaernokkelen ER sperren: INSERT ... ON CONFLICT DO NOTHING, og gikk
-- den ikke inn, har vi sett hendelsen for.
CREATE TABLE IF NOT EXISTS stripe_hendelser (
  id        TEXT PRIMARY KEY,
  type      TEXT NOT NULL,
  mottatt   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Rydding: vi trenger bare nok historikk til aa fange gjentakelser, og
-- Stripe gir opp aa levere etter tre dogn. En maaned er rikelig.
CREATE INDEX IF NOT EXISTS stripe_hendelser_tid_idx ON stripe_hendelser (mottatt);
