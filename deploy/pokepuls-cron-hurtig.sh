#!/bin/bash
# HURTIGRUNDEN -- bare Shopify-butikkene, hvert tredje minutt.
#
# Den fulle runden tar 9,5 minutter, og nesten alt av det er Chromium som
# tegner nettsider. Shopify-butikkene svarer med ferdig JSON paa sekunder;
# i den fulle runden staar de og venter paa noe de ikke har med aa gjore.
#
# Her kjorer de alene. Tiden fra en restock skjer til vi vet om den gaar fra
# «opptil ti minutter» til «opptil tre» -- for de butikkene der det meste av
# norsk Pokemon-lager faktisk ligger. Det er hele forskjellen paa aa vaere
# forst med varselet og aa vaere nummer to.
#
# Egen fil (docs/data-hurtig.json), egen laas. Den fulle runden eier
# data.json, changes.json og history.json, og hurtigrunden roerer dem ikke.
set -euo pipefail

REPO="/home/pokepuls/pokemon-lager"
VENV="/home/pokepuls/venv"
cd "$REPO"

echo "$(date -u +%FT%TZ) start hurtigskanning"
timeout -k 30 240 "$VENV/bin/python" -u scrape.py --hurtig

# INGEST DELER LAAS MED DEN FULLE RUNDEN.
#
# De to skanningene skal gjerne gaa samtidig -- det er derfor de har hver
# sin laas. Men de skriver til de SAMME tabellene, og to ingest-kjoringer
# som beregner hendelser mot listings samtidig kan hver for seg se en vare
# som «ny paa lager» og lage varselet to ganger.
#
# -w 300: vent heller enn aa hoppe over. En hurtigrunde som star i ko bak en
# full ingest er fortsatt ferskere enn ingen hurtigrunde.
echo "$(date -u +%FT%TZ) start ingest (venter paa laas om noen holder den)"
POKEPULS_DSN="${POKEPULS_DSN:-postgresql:///pokepuls}" \
  flock -w 300 /tmp/pokepuls-ingest.lock \
  "$VENV/bin/python" -u ingest/ingest.py --data docs/data-hurtig.json

echo "$(date -u +%FT%TZ) ferdig"
