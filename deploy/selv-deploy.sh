#!/bin/bash
# Serveren henter og deployer seg selv.
#
# HVORFOR DENNE FINNES
#
# Deployen gikk tidligere gjennom en EC2-instans som fungerte som dørapner
# til Hetzner. Den maskinen gjorde ingen nytte for seg -- den kjorte en
# gammel, overflodig scraper -- og den 2026-08-07 kvalte den seg selv paa
# den jobben og sluttet aa slippe noen inn. Da sto ferdig testet kode og
# ventet i timevis fordi en maskin som skulle skrotes hadde vondt.
#
# Loesningen er ikke en bedre doerapner. Det er aa fjerne behovet for en:
# serveren HENTER, den blir ikke DYTTET til. Da finnes det ingen
# mellommaskin som kan doe, ingen SSH-noekkel hos en tredjepart, og ingen
# sesjon som kan ryke midt i en deploy.
#
# TESTPORTEN
#
# Automatisk deploy uten test betyr at en oedelagt commit gaar rett i
# produksjon mens du sover. Derfor kjores hele pytest-suiten FOR noe
# installeres, mot den nye koden i et eget arbeidstre. Feiler den, blir
# alt staaende som det var, og du faar beskjed.
#
# Kjores av cron hvert 5. minutt. Naar ingenting er nytt, tar den under et
# sekund: én `git fetch` og en sammenligning av to commit-ider.
set -uo pipefail

REPO="/home/pokepuls/pokemon-lager"
VENV="/home/pokepuls/venv"
BRUKER="pokepuls"
LAAS="/tmp/pokepuls-selvdeploy.lock"

logg() { echo "$(date -u +%FT%TZ) $*"; }

# Samme las-prinsipp som scraperen: to deployer samtidig er verre enn en
# deploy for sent.
exec 9>"$LAAS"
flock -n 9 || { logg "en deploy kjorer allerede"; exit 0; }

cd "$REPO" || { logg "FEIL: finner ikke $REPO"; exit 1; }

# Scraperen skriver docs/data.json lokalt. Den er ikke sannheten -- den
# ligger i Postgres -- saa den kastes for at --ff-only skal ga gjennom.
sudo -u "$BRUKER" git checkout -- . 2>/dev/null

FOR=$(sudo -u "$BRUKER" git rev-parse HEAD)
sudo -u "$BRUKER" git fetch -q origin main || { logg "git fetch feilet"; exit 1; }
ETTER=$(sudo -u "$BRUKER" git rev-parse origin/main)

if [[ "$FOR" == "$ETTER" ]]; then
  exit 0            # ingenting nytt, ingen stoy i loggen
fi

logg "ny kode: ${FOR:0:8} -> ${ETTER:0:8}"

# Test FOR vi rorer det som kjorer. Et eget arbeidstre gjor at den
# kjorende koden staar helt urort mens testene gaar -- feiler de, har vi
# ikke engang tatt ned API-et et sekund.
TRE=$(mktemp -d /tmp/pokepuls-test-XXXXXX)
chmod 755 "$TRE"
if ! sudo -u "$BRUKER" git worktree add -q --detach "$TRE" "$ETTER" 2>/dev/null; then
  logg "klarte ikke lage arbeidstre -- hopper over deploy"
  rmdir "$TRE" 2>/dev/null
  exit 1
fi

logg "kjorer tester..."
if sudo -u "$BRUKER" env PYTHONDONTWRITEBYTECODE=1 \
     "$VENV/bin/python" -m pytest "$TRE/tests" -q --timeout=120 \
     > /tmp/pokepuls-testlogg.txt 2>&1; then
  TESTER_OK=1
else
  TESTER_OK=0
fi
HALE=$(tail -5 /tmp/pokepuls-testlogg.txt)

sudo -u "$BRUKER" git worktree remove --force "$TRE" 2>/dev/null
rm -rf "$TRE"

if [[ $TESTER_OK -ne 1 ]]; then
  logg "TESTENE FEILET -- deployer IKKE ${ETTER:0:8}"
  logg "$HALE"
  # Varsle deg selv gjennom den kanalen du faktisk ser paa.
  ( set -a; . /etc/pokepuls.env 2>/dev/null; set +a
    cd "$REPO" && sudo -u "$BRUKER" env \
      POKEPULS_DSN="${POKEPULS_DSN:-postgresql:///pokepuls}" \
      POKEPULS_VAPID_PRIVATE="${POKEPULS_VAPID_PRIVATE:-}" \
      POKEPULS_VAPID_PUBLIC="${POKEPULS_VAPID_PUBLIC:-}" \
      "$VENV/bin/python" - <<PY 2>/dev/null
import sys; sys.path.insert(0, "$REPO")
from overvak.dodmannsknapp import varsle
varsle("Deploy stoppet av testene",
       "Commit ${ETTER:0:8} ble IKKE deployet.\n$HALE"[:400])
PY
  ) || true
  exit 1
fi

logg "testene gronne -- deployer"
sudo -u "$BRUKER" git merge -q --ff-only origin/main || {
  logg "FEIL: --ff-only avvist. Er det lokale endringer?"; exit 1; }

bash "$REPO/deploy/oppsett-api.sh" >> /home/pokepuls/deploy.log 2>&1 && {
  logg "deployet ${ETTER:0:8}"
} || {
  logg "FEIL: oppsett-api.sh feilet. Se /home/pokepuls/deploy.log"
  exit 1
}
