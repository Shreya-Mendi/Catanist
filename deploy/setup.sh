#!/usr/bin/env bash
# MARA: Deception console — one-shot Ubuntu setup (idempotent).
# Run as root from the repo root:  sudo bash deploy/setup.sh
set -euo pipefail
APP=/opt/mara
id -u mara &>/dev/null || useradd -r -m -d $APP -s /usr/sbin/nologin mara
apt-get update -qq && apt-get install -y -qq python3-venv python3-pip rsync
mkdir -p $APP && rsync -a --exclude .venv --exclude .git ./ $APP/
cd $APP
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt tinker
chown -R mara:mara $APP
install -m 644 deploy/mara-console.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable mara-console
echo "Setup done. Next:"
echo "  1) create /opt/mara/.env with OPENAI_API_KEY / GOOGLE_API_KEY / TINKER_API_KEY"
echo "  2) whitelist users:  cd /opt/mara && sudo -u mara .venv/bin/python run.py adduser <name>"
echo "  3) systemctl start mara-console   → http://<instance>:8756"
