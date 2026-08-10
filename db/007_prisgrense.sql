-- Prisgrense PER ABONNEMENT.
--
-- HVORFOR DEN GLOBALE IKKE HOLDT
--
-- users.varsel_maks_pris_ore har ligget der siden 002 og hindret varsler over
-- et tak. Taket gjaldt HELE kontoen. Foelger du 28 varer -- boosterpakker til
-- 119 kr og booster boxes til 6 000 -- finnes det ingen enkelt verdi som gir
-- mening. Setter du 1 000, hoerer du aldri om en boks igjen. Setter du 6 000,
-- filtrerer den ingenting.
--
-- Det du faktisk vil si er «denne boksen er interessant under 3 999». Altsaa
-- per vare, ikke per konto.
--
-- Den globale beholdes uroert. Den virker for den som bare vil ha et absolutt
-- tak, og aa fjerne noe som allerede virker for eksisterende brukere er
-- ikke verdt det.
--
-- HVORDAN DE TO SPILLER SAMMEN
--
-- En hendelse kan treffe deg gjennom flere abonnementer samtidig: du foelger
-- baade produktet og hele settet. Regelen er at et abonnement UTEN grense
-- slipper alt gjennom -- se overvak/varsler.py. Grunnen er at det er den
-- minst overraskende retningen: du skal aldri miste et varsel du har bedt om
-- bredt, fordi du satte en grense et annet sted.
--
-- Idempotent, som resten.

ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS maks_pris_ore INTEGER
  CHECK (maks_pris_ore IS NULL OR maks_pris_ore > 0);

COMMENT ON COLUMN subscriptions.maks_pris_ore IS
  'Varsle bare naar prisen er lik eller lavere. NULL = ingen grense.';

-- ------------------------------------------------------------- premium
--
-- premium_until har ligget i users siden dag én uten aa bli lest av noe som
-- helst. Den fylles av Stripe-webhooken naar den kommer. Indeksen er for
-- den daglige jobben som skal senke folk tilbake til free naar perioden er
-- ute -- uten den blir det en full tabellskanning per kjoring.
CREATE INDEX IF NOT EXISTS users_premium_until_idx ON users (premium_until)
  WHERE premium_until IS NOT NULL;
