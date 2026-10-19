#!/usr/bin/env bash
# rkhunter + chkrootkit (Debian/Ubuntu apt) and Lynis (CISOfy apt repo), then the rkhunter baseline.
# fastpi: ./install-audit-tools.sh    beefy: ssh beefy 'bash -s' < install-audit-tools.sh
set -euo pipefail

KEYRING=/etc/apt/keyrings/cisofy-software-public.gpg
LIST=/etc/apt/sources.list.d/cisofy-lynis.list

echo "==> CISOfy apt source for Lynis"
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://packages.cisofy.com/keys/cisofy-software-public.key | sudo gpg --dearmor --yes -o "$KEYRING"
echo "deb [signed-by=$KEYRING] https://packages.cisofy.com/community/lynis/deb/ stable main" | sudo tee "$LIST" >/dev/null

echo "==> packages"
sudo apt-get update -qq
# --no-install-recommends: rkhunter recommends a mail transport agent, which nothing here needs.
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends rkhunter chkrootkit lynis
sudo lynis show version | sed 's/^/    lynis /'

echo "==> packaged daily chkrootkit timer off (security-audit.timer runs it weekly)"
sudo systemctl disable --now chkrootkit.timer 2>/dev/null || true

echo "==> rkhunter refreshes its baseline after every apt run (Debian's APT_AUTOGEN), so package upgrades are not reported as changed binaries"
sudo sed -i 's/^APT_AUTOGEN=.*/APT_AUTOGEN="true"/' /etc/default/rkhunter

echo "==> rkhunter file-properties baseline"
sudo rkhunter --propupd --nocolors >/dev/null
echo "    baseline written to /var/lib/rkhunter/db/rkhunter.dat"
