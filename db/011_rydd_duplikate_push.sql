-- Rydd opp i duplikate push-endepunkter fra for installasjons-id-en.
--
-- HVA SOM SKJEDDE
--
-- Fram til 14. august fikk hver service worker-generasjon sitt eget
-- endepunkt. En bruker som hadde vaert innom noen ganger endte med flere
-- levende registreringer, og hvert varsel gikk ut i like mange kopier.
--
-- Installasjons-id-en loste det for NYE registreringer. Men oppryddingen
-- av gamle krevde at user_agent matchet -- og den strengen endrer seg naar
-- telefonen oppdaterer iOS. Malt i drift 23. august: én bruker hadde
-- fortsatt tre levende Apple-endepunkter, ett fra 23. og to fra 8. og 13.
--
-- REGELEN
--
-- Har en bruker minst én rad MED installasjons-id, er radene UTEN det
-- levninger. Appen har satt id-en ved hver sidelasting siden 14. august,
-- saa en rad uten den er enten dod eller registrerer seg paa nytt ved
-- neste besok.
--
-- Vi rorer ikke brukere som BARE har rader uten id -- de har ikke vaert
-- innom siden endringen, og aa slette deres eneste registrering ville
-- skrudd av varslene deres helt.
--
-- Idempotent: kjorer den igjen, finner den ingenting.

DELETE FROM push_endpoints p
WHERE p.installasjon IS NULL
  AND EXISTS (
    SELECT 1 FROM push_endpoints q
    WHERE q.user_id = p.user_id AND q.installasjon IS NOT NULL
  );
