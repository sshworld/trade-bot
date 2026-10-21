#!/bin/bash
# ONE-TIME manual install / upgrade of the CI deploy plumbing on the VPS (root). Run from a checkout of the REVIEWED
# commit:   bash live_v6/deploy/ci/install_vps_ci.sh <path-to-repo-checkout>
# Installs: tradebot-ci-confirm.{service,timer} (TA R1, enabled), /opt/tradebot/ci/{ci_deploy.sh,ci_deploy_entry.sh,ci_job.sh,verify_stops_testnet.py} (root:root 0755),
#           /opt/tradebot/verify_stops_live.py (root:tradebot 0750, TA D; previous copy kept as .bak-<ts>),
#           user tradebot-ci + /opt/tradebot-ci-testnet/{app,.venv} (TA K), /etc/systemd/system/live_v6-citest.service.
# Does not touch live_v6-live, its env, state or code, and does not start/restart any unit.
# /etc/tradebot/citest.env (testnet keys), /etc/tradebot/ci-alert-testnet.env (DUMMY HEARTBEAT_URL for testnet drills)
# and the authorized_keys lines / sshd setting (README_CI §F) are separate manual steps.
set -euo pipefail
SRC=${1:?repo checkout}
TS=$(date -u +%Y%m%dT%H%M%SZ)
id tradebot-ci >/dev/null 2>&1 || useradd --system --user-group --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin tradebot-ci
install -d -m 755 -o root -g root /opt/tradebot/ci
for f in ci_deploy.sh ci_deploy_entry.sh ci_job.sh; do install -m 755 -o root -g root "$SRC/live_v6/deploy/ci/$f" /opt/tradebot/ci/$f; done
install -m 755 -o root -g root "$SRC/live_v6/tools/verify_stops.py" /opt/tradebot/ci/verify_stops_testnet.py
[ -f /opt/tradebot/verify_stops_live.py ] && cp -p /opt/tradebot/verify_stops_live.py /opt/tradebot/verify_stops_live.py.bak-$TS
install -m 750 -o root -g tradebot "$SRC/live_v6/tools/verify_stops_live.py" /opt/tradebot/verify_stops_live.py
install -m 644 -o root -g root "$SRC/live_v6/deploy/ci/live_v6-citest.service" /etc/systemd/system/live_v6-citest.service
install -d -m 755 -o root -g root /etc/systemd/system/live_v6-live.service.d   # TA R2 drop-in (applies at the next start only)
install -m 644 -o root -g root "$SRC/live_v6/deploy/ci/live_v6-live.ci-halt-guard.conf" /etc/systemd/system/live_v6-live.service.d/10-ci-halt-guard.conf
for f in tradebot-ci-confirm.service tradebot-ci-confirm.timer; do install -m 644 -o root -g root "$SRC/live_v6/deploy/ci/$f" /etc/systemd/system/$f; done   # TA R1
# canary tree: root-owned code, readable by tradebot-ci only; own venv (the live venv under /opt/tradebot is hidden)
install -d -m 750 -o root -g tradebot-ci /opt/tradebot-ci-testnet /opt/tradebot-ci-testnet/app
chown -R root:root /opt/tradebot-ci-testnet/app/*/ 2>/dev/null || true
chmod -R u=rwX,go=rX /opt/tradebot-ci-testnet/app/*/ 2>/dev/null || true
if [ ! -x /opt/tradebot-ci-testnet/.venv/bin/python ]; then
  python3 -m venv /opt/tradebot-ci-testnet/.venv
  # same package versions as the live venv (pip freeze), else the repo pins
  if [ -x /opt/tradebot/.venv/bin/pip ]; then /opt/tradebot/.venv/bin/pip freeze > /root/ci-venv-freeze.txt
  else cp "$SRC/live_v6/requirements.txt" /root/ci-venv-freeze.txt; fi
  /opt/tradebot-ci-testnet/.venv/bin/pip install -q -r /root/ci-venv-freeze.txt
fi
chown -R root:root /opt/tradebot-ci-testnet/.venv; chmod -R go-w /opt/tradebot-ci-testnet/.venv
[ -f /etc/tradebot/citest.env ] && chgrp tradebot-ci /etc/tradebot/citest.env && chmod 640 /etc/tradebot/citest.env
# /etc/tradebot is 0750 root:tradebot — tradebot-ci is NOT in group tradebot, so it cannot traverse it; PID 1 reads
# EnvironmentFile= as root, so the canary still gets citest.env.
[ -d /var/lib/live_v6-citest ] && chown -R tradebot-ci:tradebot-ci /var/lib/live_v6-citest
install -d -m 711 -o root -g root /var/lib/tradebot-ci /var/lib/tradebot-ci/stage
install -d -m 700 -o root -g root /var/lib/tradebot-ci/uploads /root/ci-backups
install -d -m 750 -o root -g root /var/log/tradebot/ci-jobs
systemctl daemon-reload
systemctl enable --now tradebot-ci-confirm.timer   # timer only (TA R1); no bot unit is started or restarted
echo "installed; no bot unit started or restarted"
