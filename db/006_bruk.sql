-- Sidevisninger: AGGREGAT, ikke besoek.
--
-- SPOERSMAALET TABELLEN FINNES FOR AA SVARE PAA
--
-- «Virker det aa be folk installere?» Ikke «hvem var her», ikke «hvor lenge
-- ble de». Derfor er standalone en egen DIMENSJON og ikke et tall ved siden
-- av: hele poenget er aa kunne dele dagen i to og sammenligne.
--
-- HVORFOR PERSONVERNET LIGGER I SKJEMAET OG IKKE I KODEN
--
-- Personvernerklaeringen lover «ingen Google Analytics, ingen sporings-
-- piksler, ingen sporing». Det loftet holdes ikke av at koden over er
-- velmenende -- kode endres. Det holdes av at det ikke FINNES en kolonne aa
-- legge en IP, en bruker-id, en enhets-id eller et tidspunkt finere enn
-- dagen i. Skulle en senere okt (menneske eller maskin) ville lagre hvem,
-- maa den endre tabellen forst. Da er det en bevisst handling med et
-- diff-spor, ikke en gliding.
--
-- Merk ogsaa hva som IKKE er her: ingen referrer, ingen user agent, ingen
-- oktid. Hver av dem er isolert sett harmlos og til sammen er de et
-- fingeravtrykk.
--
-- RADANTALLET ER BUNDET
--
-- Primaernokkelen er (dag, side, standalone), og `side` hvitlistes i
-- api/bruk.py. Da er det oevre taket dager x ~6 sider x 2 -- omtrent 4 400
-- rader i aaret. Uten hvitlisten kunne hvem som helst sendt tilfeldige
-- strenger og fylt disken; det er ikke teoretisk paa et aapent endepunkt.
--
-- Idempotent, som resten av migrasjonene.

CREATE TABLE IF NOT EXISTS sidevisninger (
  dag        DATE    NOT NULL DEFAULT current_date,
  side       TEXT    NOT NULL,
  standalone BOOLEAN NOT NULL,
  antall     INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (dag, side, standalone)
);

-- Admin leser «siste 30 dager» hver gang fanen aapnes. Med noen tusen rader
-- gaar det uansett, men indeksen koster ingenting og gjor at spoerringen
-- ikke degraderer den dagen tabellen har staatt i to aar.
CREATE INDEX IF NOT EXISTS sidevisninger_dag_idx ON sidevisninger (dag DESC);
