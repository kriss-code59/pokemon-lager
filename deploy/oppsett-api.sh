#!/usr/bin/env bash
# Setter opp API, frontend og ingest pa pokepuls-serveren.
#
# Forutsetter at deploy/oppsett-server.sh allerede har kjort (Postgres,
# nginx, certbot, brukeren pokepuls).
#
# Idempotent: kan kjores pa nytt etter hver kodeendring. Kjores som root:
#   bash deploy/oppsett-api.sh
set -euo pipefail

BRUKER="pokepuls"
HJEM="/home/$BRUKER"
REPO="$HJEM/pokemon-lager"
VENV="$HJEM/venv"
DB="pokepuls"
LOGG() { echo -e "\n=== $* ==="; }

if [[ $EUID -ne 0 ]]; then echo "Ma kjores som root"; exit 1; fi

LOGG "1/7 Repo"
if [[ ! -d "$REPO/.git" ]]; then
  sudo -u "$BRUKER" git clone https://github.com/kriss-code59/pokemon-lager.git "$REPO"
else
  sudo -u "$BRUKER" git -C "$REPO" pull --ff-only
fi

LOGG "2/7 Python-miljo"
[[ -d "$VENV" ]] || sudo -u "$BRUKER" python3 -m venv "$VENV"
sudo -u "$BRUKER" "$VENV/bin/pip" install -q --upgrade pip
sudo -u "$BRUKER" "$VENV/bin/pip" install -q -r "$REPO/api/requirements.txt"

LOGG "3/7 Database"
# Peer-autentisering over unix-socket: ingen passord som kan lekke, og
# databasen lytter aldri pa nettet.
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$BRUKER'" \
  | grep -q 1 || sudo -u postgres createuser "$BRUKER"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'" \
  | grep -q 1 || sudo -u postgres createdb -O "$BRUKER" "$DB"
sudo -u postgres psql -q -d "$DB" -c "GRANT ALL ON SCHEMA public TO $BRUKER"
# Utvidelsene krever superbruker; skjemaet ellers gjor det ikke.
sudo -u postgres psql -q -d "$DB" -c "CREATE EXTENSION IF NOT EXISTS citext"
sudo -u postgres psql -q -d "$DB" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto"
sudo -u "$BRUKER" psql -q -d "$DB" -f "$REPO/db/001_skjema.sql"

LOGG "4/7 Miljofil"
if [[ ! -f /etc/pokepuls.env ]]; then
  cat > /etc/pokepuls.env <<EOF
# Unix-socket, ikke TCP: databasen skal aldri vaere naabar utenfra.
POKEPULS_DSN=postgresql:///$DB
PYTHONUNBUFFERED=1
EOF
fi
chmod 640 /etc/pokepuls.env
chown root:"$BRUKER" /etc/pokepuls.env

LOGG "5/7 systemd"
install -m 644 "$REPO/deploy/pokepuls-api.service" /etc/systemd/system/pokepuls-api.service
systemctl daemon-reload
systemctl enable --now pokepuls-api
sleep 2
systemctl is-active --quiet pokepuls-api || { journalctl -u pokepuls-api -n 40 --no-pager; exit 1; }

LOGG "6/7 nginx"
install -m 644 "$REPO/deploy/nginx-pokepuls.conf" /etc/nginx/sites-available/pokepuls
ln -sf /etc/nginx/sites-available/pokepuls /etc/nginx/sites-enabled/pokepuls
rm -f /etc/nginx/sites-enabled/default
# nginx ma kunne lese web/ gjennom /home/pokepuls.
chmod 755 "$HJEM"
nginx -t
systemctl reload nginx

LOGG "7/7 Cron for skanning og ingest"
install -m 755 -o "$BRUKER" -g "$BRUKER" \
  "$REPO/deploy/pokepuls-cron-scrape.sh" "$REPO/deploy/pokepuls-cron-scrape.sh"
cat > /etc/cron.d/pokepuls <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
# Skanning + ingest hvert 20. minutt. timeout og flock -n er ikke pynt:
# uten dem blokkerte en hengende kjoring 132 pafolgende i august 2026.
*/20 * * * * pokepuls timeout -k 60 2400 flock -n /tmp/pokepuls-scrape.lock /home/pokepuls/pokemon-lager/deploy/pokepuls-cron-scrape.sh >> /home/pokepuls/scrape.log 2>&1
# Dodmannsknapp hvert 15. minutt. EGEN jobb uten delt las, slik at den
# fortsatt lever nar scraperen henger. Det er hele poenget med den.
*/15 * * * * pokepuls /home/pokepuls/venv/bin/python /home/pokepuls/pokemon-lager/overvak/dodmannsknapp.py >> /home/pokepuls/dodmannsknapp.log 2>&1
EOF
chmod 644 /etc/cron.d/pokepuls

echo
echo "Ferdig. Sjekk:"
echo "  curl -s localhost/api/health | jq"
echo "  systemctl status pokepuls-api --no-pager"
echo
echo "TLS nar DNS peker hit:"
echo "  certbot --nginx -d pokepuls.no -d www.pokepuls.no --agree-tos -m <e-post> --redirect"
