#!/bin/bash
# Kjores av cron pa EC2-instansen hvert 20. minutt. Speiler "Commit og push
# oppdatert data"-steget (og natt-sjekken) i .github/workflows/scrape.yml,
# slik at oppforselen er identisk uansett om skanningen trigges av GitHub
# Actions eller av denne instansen.
set -euo pipefail

REPO_DIR="/home/ubuntu/pokemon-lager"
cd "$REPO_DIR"

# TZ='Europe/Oslo' haandterer sommer/vintertid automatisk (se scrape.yml).
HOUR=$(TZ='Europe/Oslo' date +%H)
if [[ 10#$HOUR -ge 22 || 10#$HOUR -lt 4 ]]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) skip - natt i Norge (time=$HOUR)"
  exit 0
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) start"

git pull --quiet

export NTFY_TOPIC="${NTFY_TOPIC:-pokemon-lager-sk82sw9vyl}"
timeout -k 60 2400 python3 -u scrape.py

git config user.name "pokemon-lagerbot"
git config user.email "actions@github.com"
git add docs/data.json docs/changes.json docs/history.json
if ! git diff --quiet --cached; then
  git commit -m "Oppdater lagerstatus [automatisk - EC2]"
  git push
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) committed and pushed changes"
else
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) no changes"
fi
