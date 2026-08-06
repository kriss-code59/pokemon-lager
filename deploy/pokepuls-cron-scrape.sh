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

# INGEN NATTPAUSE.
#
# Den fantes fordi "butikkene fyller ikke pa kl. 03". Det stemmer for de
# norske butikkenes egne pafyll -- men ikke for det vi er her for:
#
#   * Forhandssalg apner nesten alltid presis, og presis er ofte 00:00.
#   * De japanske og kinesiske leddene jobber pa asiatisk tid. En vare som
#     dukker opp hos en importor kl. 04 norsk tid, sto ute i seks timer for
#     vi i det hele tatt sa etter den.
#   * Seks timer uten skanning er seks timer der en restock kan komme OG
#     bli utsolgt uten at det finnes et spor av den i historikken.
#
# Kostnaden ved a kjore er en server som allerede er betalt for og et
# hoflig antall treff mot butikkene. Kostnaden ved a la vaere er det ene
# varselet du ville hatt.
#
# Stille natt hoerer hjemme et annet sted: paa VARSLENE, per bruker
# (users.varsel_stille_natt). Vi samler data doegnet rundt, men vekker
# ingen. Se overvak/varsler.py.

echo "$(date -u +%FT%TZ) start skanning"
timeout -k 60 2400 "$VENV/bin/python" -u scrape.py

echo "$(date -u +%FT%TZ) start ingest"
POKEPULS_DSN="${POKEPULS_DSN:-postgresql:///pokepuls}" \
  "$VENV/bin/python" -u ingest/ingest.py --data docs/data.json

echo "$(date -u +%FT%TZ) ferdig"
