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

LOGG "1/8 Repo"
if [[ ! -d "$REPO/.git" ]]; then
  sudo -u "$BRUKER" git clone https://github.com/kriss-code59/pokemon-lager.git "$REPO"
else
  # Scraperen skriver docs/data.json lokalt, mens EC2 fortsatt committer sin
  # egen versjon til git. Da stopper --ff-only pa en lokal endring. Sannheten
  # ligger uansett i Postgres, sa den lokale filen kastes.
  # Uten dette stopper hver eneste pull etter forste deploy: skriptet
  # chmod-er deploy/*.sh, git ser modusendringen som en lokal endring, og
  # --ff-only nekter. Kjorebiten trengs ikke lenger (cron kaller /bin/bash),
  # men chmod-en er billig forsikring -- sa vi ber git om a ignorere modus.
  sudo -u "$BRUKER" git -C "$REPO" config core.fileMode false
  sudo -u "$BRUKER" git -C "$REPO" checkout -- . 2>/dev/null || true
  sudo -u "$BRUKER" git -C "$REPO" pull --ff-only
fi

LOGG "2/8 Python-miljo"
[[ -d "$VENV" ]] || sudo -u "$BRUKER" python3 -m venv "$VENV"
sudo -u "$BRUKER" "$VENV/bin/pip" install -q --upgrade pip
sudo -u "$BRUKER" "$VENV/bin/pip" install -q -r "$REPO/api/requirements.txt"

LOGG "3/8 Database"
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

# Tabeller opprettet av postgres i en tidligere okt kan ikke endres av
# pokepuls. CREATE TABLE IF NOT EXISTS gar da stille forbi, mens CREATE
# INDEX feiler med "must be owner of table" -- og skjemaet blir halvveis
# anvendt uten at noe stopper. Normaliser eierskap forst.
sudo -u postgres psql -q -d "$DB" -Atc "
  SELECT 'ALTER TABLE '||quote_ident(tablename)||' OWNER TO $BRUKER;'
    FROM pg_tables WHERE schemaname='public' AND tableowner <> '$BRUKER'
  UNION ALL
  SELECT 'ALTER SEQUENCE '||quote_ident(sequencename)||' OWNER TO $BRUKER;'
    FROM pg_sequences WHERE schemaname='public' AND sequenceowner <> '$BRUKER'
" | sudo -u postgres psql -q -d "$DB"

# ON_ERROR_STOP: et skjema som feiler halvveis skal stoppe oppsettet, ikke
# etterlate en database som ser ferdig ut.
sudo -u "$BRUKER" psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$REPO/db/001_skjema.sql"
# 002 avhenger av tabellene i 001 (users, events, push_endpoints) og maa
# derfor kjores etter. Begge er idempotente.
sudo -u "$BRUKER" psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$REPO/db/002_varsler.sql"
# 003: glemt passord, feedback og kontosletting -- alt som ma finnes for
# fremmede kan lage konto her.
sudo -u "$BRUKER" psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$REPO/db/003_deling.sql"
# 004: forhandssalg og bestillingsvarer skal ikke telle som «pa lager».
# Etterfyller ogsa de eksisterende radene, sa fiksen er synlig med en gang
# og ikke forst etter at hver enkelt vare er sett pa nytt.
sudo -u "$BRUKER" psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$REPO/db/004_forhandssalg.sql"

LOGG "4/8 Miljofil"
if [[ ! -f /etc/pokepuls.env ]]; then
  cat > /etc/pokepuls.env <<EOF
# Unix-socket, ikke TCP: databasen skal aldri vaere naabar utenfra.
POKEPULS_DSN=postgresql:///$DB
PYTHONUNBUFFERED=1
EOF
fi
chmod 640 /etc/pokepuls.env
chown root:"$BRUKER" /etc/pokepuls.env

LOGG "5/8 VAPID-nokler for Web Push"
# Noklene lages EN gang og skal aldri byttes: bytter du dem, blir hvert
# eneste eksisterende push-abonnement ugyldig, og alle brukere maa trykke
# "Sla pa varsler" pa nytt uten a faa vite hvorfor varslene sluttet.
# Derfor: bare hvis de ikke finnes allerede.
if ! grep -q "^POKEPULS_VAPID_PRIVATE=" /etc/pokepuls.env; then
  echo "Lager nye VAPID-nokler."
  ( cd "$REPO" && sudo -u "$BRUKER" "$VENV/bin/python" -m varsling.vapid ) \
    >> /etc/pokepuls.env
  echo "POKEPULS_VAPID_SUBJECT=mailto:norgekriss@gmail.com" >> /etc/pokepuls.env
  chmod 640 /etc/pokepuls.env
  chown root:"$BRUKER" /etc/pokepuls.env
else
  echo "VAPID-nokler finnes allerede. Rorer dem ikke."
fi
grep -q "^POKEPULS_VAPID_PUBLIC=" /etc/pokepuls.env \
  || { echo "FEIL: klarte ikke lage VAPID-nokler"; exit 1; }

# Admin-lasen. To laser er poenget: role='admin' i databasen holder ikke
# alene, adressen ma OGSA staa her. En feil UPDATE eller en SQL-injeksjon
# skal ikke vaere nok til a gi noen innsyn i alle brukerne.
if ! grep -q "^POKEPULS_ADMIN_EPOST=" /etc/pokepuls.env; then
  echo "POKEPULS_ADMIN_EPOST=kristian.bo@icloud.com" >> /etc/pokepuls.env
  chmod 640 /etc/pokepuls.env
  chown root:"$BRUKER" /etc/pokepuls.env
fi

# RESEND_API_KEY settes IKKE herfra -- den er en hemmelighet som Kristian
# limer inn selv:
#   sudo sh -c 'echo "RESEND_API_KEY=re_..." >> /etc/pokepuls.env'
#   sudo systemctl restart pokepuls-api
# Mangler den, virker alt annet som for; glemt-passord svarer bare at
# e-post ikke er satt opp enna.
grep -q "^RESEND_API_KEY=" /etc/pokepuls.env \
  || echo "MERK: RESEND_API_KEY mangler -- glemt-passord er av."

LOGG "6/8 systemd"
install -m 644 "$REPO/deploy/pokepuls-api.service" /etc/systemd/system/pokepuls-api.service
systemctl daemon-reload
systemctl enable pokepuls-api
# RESTART, ikke "enable --now": kjorer tjenesten allerede, gjor --now
# ingenting, og da svarer serveren fortsatt med den GAMLE koden etter en
# deploy. Det tok en runde med "hvorfor finnes ikke det nye endepunktet".
systemctl restart pokepuls-api
sleep 2
systemctl is-active --quiet pokepuls-api || { journalctl -u pokepuls-api -n 40 --no-pager; exit 1; }

LOGG "7/8 nginx"
# certbot skriver TLS-blokka rett inn i denne filen. Kopierer vi repoets
# versjon over den, forsvinner sertifikatet og hele siden blir utilgjengelig
# pa https -- det skjedde ved forste deploy etter at TLS var satt opp.
# Snippeten inneholder alt som endrer seg (produktsider, sidekart, admin).
# Den installeres ALLTID -- ogsa nar certbot eier hovedkonfigen.
install -d -m 755 /etc/nginx/snippets
install -m 644 "$REPO/deploy/nginx-sider.conf" /etc/nginx/snippets/pokepuls-sider.conf

if grep -q ssl_certificate /etc/nginx/sites-available/pokepuls 2>/dev/null; then
  echo "TLS-konfig finnes; rorer den ikke, bortsett fra include-linja."
  # Legg inn include-linja hvis den mangler. Uten dette blir nye ruter
  # liggende i repoet uten a virke: /robots.txt og /p/ falt gjennom til
  # `location /` og svarte med app-skallet i stedet.
  if ! grep -q "pokepuls-sider.conf" /etc/nginx/sites-available/pokepuls; then
    echo "Setter inn include foran location / ..."
    # Foran FORSTE `location / {`. Rekkefolgen er ikke likegyldig: en
    # prefiks-location som star etter den generelle, taper aldri -- men
    # `location /` med try_files fanger alt som ikke matcher noe mer
    # spesifikt, og da ma vare ruter vaere definert.
    perl -0pi -e "s{(\n\s*location / \{)}{\n    include snippets/pokepuls-sider.conf;\n\$1}" \
      /etc/nginx/sites-available/pokepuls
    grep -q "pokepuls-sider.conf" /etc/nginx/sites-available/pokepuls \
      || { echo "FEIL: klarte ikke sette inn include-linja. Gjor det manuelt."; exit 1; }
  fi
else
  install -m 644 "$REPO/deploy/nginx-pokepuls.conf" /etc/nginx/sites-available/pokepuls
fi
ln -sf /etc/nginx/sites-available/pokepuls /etc/nginx/sites-enabled/pokepuls
rm -f /etc/nginx/sites-enabled/default
# nginx ma kunne lese web/ gjennom /home/pokepuls.
chmod 755 "$HJEM"
nginx -t
systemctl reload nginx

LOGG "8/8 Cron for skanning, ingest og varsling"
chmod 755 "$REPO"/deploy/*.sh
cat > /etc/cron.d/pokepuls <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
# Skanning + ingest hvert 20. minutt. timeout og flock -n er ikke pynt:
# uten dem blokkerte en hengende kjoring 132 pafolgende i august 2026.
#
# /bin/bash foran skriptet er heller ikke pynt. Filer lastet opp gjennom
# GitHubs nettgrensesnitt lagres som mode 100644, og forste `git checkout`
# etter et `chmod 755` setter dem tilbake. Cron ga da "flock: Permission
# denied" og scraperen sto i 28 timer (2026-08-05). Kaller vi tolken
# eksplisitt, betyr kjorebiten ingenting.
*/20 * * * * pokepuls timeout -k 60 2400 flock -n /tmp/pokepuls-scrape.lock /bin/bash /home/pokepuls/pokemon-lager/deploy/pokepuls-cron-scrape.sh >> /home/pokepuls/scrape.log 2>&1
# Dodmannsknapp hvert 15. minutt. EGEN jobb uten delt las, slik at den
# fortsatt lever nar scraperen henger. Det er hele poenget med den.
*/15 * * * * pokepuls cd /home/pokepuls/pokemon-lager && set -a && . /etc/pokepuls.env && set +a && /home/pokepuls/venv/bin/python overvak/dodmannsknapp.py >> /home/pokepuls/dodmannsknapp.log 2>&1
# Varselsender hvert 5. minutt. Egen jobb, ikke en del av ingest: en feil i
# varslingen skal aldri kunne rulle tilbake en vellykket ingest. Den er
# billig nar det ikke er noe a sende (én sporring mot et vannmerke), og den
# tar igjen automatisk hvis en runde skulle feile.
*/5 * * * * pokepuls cd /home/pokepuls/pokemon-lager && set -a && . /etc/pokepuls.env && set +a && /home/pokepuls/venv/bin/python overvak/varsler.py --stille >> /home/pokepuls/varsler.log 2>&1
EOF
chmod 644 /etc/cron.d/pokepuls

echo
echo "Ferdig. Sjekk:"
echo "  curl -s https://pokepuls.no/api/health | jq"
echo "  curl -sI https://pokepuls.no/sitemap.xml | head -1"
echo "  sudo -u pokepuls bash -c 'set -a; . /etc/pokepuls.env; set +a; cd $REPO && $VENV/bin/python overvak/varsler.py --torrkjor'"
echo "  systemctl status pokepuls-api --no-pager"
echo
echo "TLS nar DNS peker hit:"
echo "  certbot --nginx -d pokepuls.no -d www.pokepuls.no --agree-tos -m <e-post> --redirect"
