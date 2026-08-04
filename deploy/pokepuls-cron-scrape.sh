#!/bin/bash
# Skanning + ingest pa pokepuls-serveren.
#
# Forskjellen fra ec2-cron-scrape.sh: her committes ingenting til git.
# Sannheten ligger i Postgres. data.json skrives fortsatt, men som en lokal
# mellomstasjon -- og som fallback hvis databasen skulle vaere nede.
set -euo pipefail

REPO="/home/pokepuls/pokemon-lager"
VENV="/home/pokepuls/venv"
cd "$REPO"

# Nattpause. Butikkene fyller ikke pa kl. 03, og vi trenger ikke banke pa
# dorene deres 24/7. TZ handterer sommertid selv.
TIME=$(TZ='Europe/Oslo' date +%H)
if [[ 10#$TIME -ge 22 || 10#$TIME -lt 4 ]]; then
  echo "$(date -u +%FT%TZ) hopper over - natt i Norge (time=$TIME)"
  exit 0
fi

echo "$(date -u +%FT%TZ) start skanning"
timeout -k 60 2400 "$VENV/bin/python" -u scrape.py

echo "$(date -u +%FT%TZ) start ingest"
POKEPULS_DSN="${POKEPULS_DSN:-postgresql:///pokepuls}" \
  "$VENV/bin/python" -u ingest/ingest.py --data docs/data.json

echo "$(date -u +%FT%TZ) ferdig"
