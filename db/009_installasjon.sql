-- Én push-registrering per nettleser, ikke én per service worker-generasjon.
--
-- PROBLEMET, MALT I DRIFT 14. AUGUST
--
-- En bruker hadde TRE endepunkter: opprettet 7., 9. og 13. august. Alle med
-- feil_pa_rad = 0 og last_ok_at samme time. Alle levende. Hvert varsel gikk
-- altsaa ut i tre kopier til samme person.
--
-- Aarsaken er at nettleseren kan bytte push-abonnement naar service workeren
-- oppdateres -- og den oppdateres ved hver cache-bump. Tolv deployer paa én
-- dag ga tre nye abonnementer. sw.js har en `pushsubscriptionchange`-lytter
-- som skal melde av det gamle, men den hendelsen fyrer ikke paalitelig,
-- saerlig ikke paa iOS.
--
-- Den vanlige oppryddingen hjelper ikke: den sletter DODE endepunkter (410
-- Gone fra pushtjenesten). Disse er ikke dode. De virker alle sammen.
--
-- LOSNINGEN
--
-- Nettleseren husker en id i localStorage som overlever
-- service worker-bytter. Registrerer den seg paa nytt, vet serveren at det
-- er SAMME nettleser og kan fjerne den forrige raden.
--
-- Det er ikke sporing: id-en lages av nettleseren, sendes bare til oss, og
-- brukes bare til aa gjenkjenne en enhet som allerede er innlogget hos oss.
-- Den kan ikke kobles til noe utenfor.
--
-- Idempotent, som resten.

ALTER TABLE push_endpoints ADD COLUMN IF NOT EXISTS installasjon TEXT;

CREATE INDEX IF NOT EXISTS push_installasjon_idx
  ON push_endpoints (user_id, installasjon) WHERE installasjon IS NOT NULL;
