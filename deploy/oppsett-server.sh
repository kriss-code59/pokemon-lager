#!/usr/bin/env bash
# Grunnoppsett for pokepuls-serveren.
#
# Idempotent: trygg a kjore flere ganger.
# Kjores som root pa en fersk Ubuntu:  bash deploy/oppsett-server.sh
#
# VIKTIG om brannmuren: port 22 apnes FOR ufw slas pa. Motsatt rekkefolge
# laser deg ute av din egen server, og pa en skymaskin uten fysisk konsoll
# er det en dyr feil.
set -euo pipefail

BRUKER="pokepuls"
LOGG() { echo -e "\n=== $* ==="; }

if [[ $EUID -ne 0 ]]; then echo "Ma kjores som root"; exit 1; fi

LOGG "1/8 Pakkeliste og oppgraderinger"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq

LOGG "2/8 Basispakker"
apt-get install -y -qq \
  git curl ca-certificates gnupg ufw fail2ban unattended-upgrades \
  python3 python3-venv python3-pip build-essential \
  postgresql postgresql-contrib nginx certbot python3-certbot-nginx \
  htop ncdu jq tzdata

LOGG "3/8 Tidssone"
timedatectl set-timezone Europe/Oslo

LOGG "4/8 Swap (2 GB)"
# Chromium + Postgres pa 4 GB blir trangt under topper. Swap er ikke en
# erstatning for RAM, men hindrer at OOM-killeren dreper Postgres midt i en
# skriving. swappiness lavt sa vi bare bruker den nar det virkelig trengs.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
sysctl -qw vm.swappiness=10
grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf

LOGG "5/8 Brukeren $BRUKER"
# Applikasjonen skal ALDRI kjore som root. Scraperen laster ned og tolker
# HTML fra 40 fremmede nettsteder -- den skal ha minst mulig a rutte med.
if ! id -u "$BRUKER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$BRUKER"
fi
usermod -aG sudo "$BRUKER"
install -d -m 700 -o "$BRUKER" -g "$BRUKER" "/home/$BRUKER/.ssh"
if [[ -f /root/.ssh/authorized_keys ]]; then
  cp /root/.ssh/authorized_keys "/home/$BRUKER/.ssh/authorized_keys"
  chown "$BRUKER:$BRUKER" "/home/$BRUKER/.ssh/authorized_keys"
  chmod 600 "/home/$BRUKER/.ssh/authorized_keys"
fi
# Passordfri sudo, ellers kan ikke automatiserte kjoringer gjore vedlikehold
echo "$BRUKER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-$BRUKER
chmod 440 /etc/sudoers.d/90-$BRUKER

LOGG "6/8 SSH-herding"
# Kun nokler. Passordpalogging pa en offentlig IP blir forsokt brutforcet
# innen minutter -- det er ikke en teori, det skjer alltid.
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
sshd -t && systemctl reload ssh

LOGG "7/8 Brannmur"
ufw allow 22/tcp    comment 'SSH'
ufw allow 80/tcp    comment 'HTTP (Lets Encrypt)'
ufw allow 443/tcp   comment 'HTTPS'
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
ufw status verbose

LOGG "8/8 fail2ban og automatiske sikkerhetsoppdateringer"
systemctl enable --now fail2ban
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades

LOGG "FERDIG"
echo "Bruker:    $BRUKER"
echo "Postgres:  $(sudo -u postgres psql -tAc 'select version()' | cut -c1-40)"
echo "Swap:      $(free -h | awk '/Swap/{print $2}')"
echo "Brannmur:  $(ufw status | head -1)"
