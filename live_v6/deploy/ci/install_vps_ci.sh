#!/bin/bash
# Manual install / upgrade (v1 → v2) of the CI deploy plumbing on the VPS. Run as root (ops: sudo) from an extracted
# copy of the REVIEWED commit (INSTALL_CI_V2.md §2):
#   sudo bash <dir>/live_v6/deploy/ci/install_vps_ci.sh <dir>
# Installs (previous copies kept under /opt/tradebot/ci/backup-<ts>/):
#   /opt/tradebot/ci/{ci_deploy.sh,ci_deploy_entry.sh,ci_job.sh}            root:root 0755
#   /opt/tradebot/verify_stops_live.py                                        root:tradebot 0750
#   /etc/systemd/system/tradebot-ci-confirm.{service,timer}                   (v2: every 5 min, marker 30 min after restart)
#   /etc/systemd/system/live_v6-live.service.d/10-ci-halt-guard.conf          (unchanged content; applies at the next start)
# Does NOT touch live_v6-live (code, env, state), does not start / stop / restart any bot unit, does not touch
# authorized_keys / sshd, the testnet canary (live_v6-citest) or its venv.
set -euo pipefail
SRC=${1:?usage: install_vps_ci.sh <dir holding live_v6/>}
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 2; }
CI=$SRC/live_v6/deploy/ci
for f in ci_deploy.sh ci_deploy_entry.sh ci_job.sh tradebot-ci-confirm.service tradebot-ci-confirm.timer live_v6-live.ci-halt-guard.conf; do
  [ -f "$CI/$f" ] || { echo "missing $CI/$f"; exit 2; }
done
[ -f "$SRC/live_v6/tools/verify_stops_live.py" ] || { echo "missing live_v6/tools/verify_stops_live.py"; exit 2; }
for f in ci_deploy.sh ci_deploy_entry.sh ci_job.sh; do bash -n "$CI/$f"; done
grep -q '— v2, strategy-agnostic' "$CI/ci_deploy.sh" || { echo "ci_deploy.sh is not v2"; exit 2; }
id tradebot >/dev/null 2>&1 || { echo "user tradebot missing (live bot user)"; exit 2; }

TS=$(date -u +%Y%m%dT%H%M%SZ)
BK=/opt/tradebot/ci/backup-$TS
install -d -m 755 -o root -g root /opt/tradebot/ci "$BK"
for f in ci_deploy.sh ci_deploy_entry.sh ci_job.sh; do [ -f /opt/tradebot/ci/$f ] && cp -p /opt/tradebot/ci/$f "$BK/"; done
[ -f /opt/tradebot/verify_stops_live.py ] && cp -p /opt/tradebot/verify_stops_live.py "$BK/"
for f in tradebot-ci-confirm.service tradebot-ci-confirm.timer; do [ -f /etc/systemd/system/$f ] && cp -p /etc/systemd/system/$f "$BK/"; done
echo "previous copies → $BK"

for f in ci_deploy.sh ci_deploy_entry.sh ci_job.sh; do install -m 755 -o root -g root "$CI/$f" /opt/tradebot/ci/$f; done
install -m 750 -o root -g tradebot "$SRC/live_v6/tools/verify_stops_live.py" /opt/tradebot/verify_stops_live.py
install -d -m 755 -o root -g root /etc/systemd/system/live_v6-live.service.d
install -m 644 -o root -g root "$CI/live_v6-live.ci-halt-guard.conf" /etc/systemd/system/live_v6-live.service.d/10-ci-halt-guard.conf
for f in tradebot-ci-confirm.service tradebot-ci-confirm.timer; do install -m 644 -o root -g root "$CI/$f" /etc/systemd/system/$f; done
install -d -m 711 -o root -g root /var/lib/tradebot-ci /var/lib/tradebot-ci/stage
install -d -m 700 -o root -g root /var/lib/tradebot-ci/uploads /root/ci-backups
install -d -m 750 -o root -g root /var/log/tradebot/ci-jobs
systemctl daemon-reload
systemctl enable tradebot-ci-confirm.timer >/dev/null
systemctl restart tradebot-ci-confirm.timer          # timer only; no bot unit is started, stopped or restarted
sha256sum /opt/tradebot/ci/ci_deploy.sh /opt/tradebot/ci/ci_deploy_entry.sh /opt/tradebot/ci/ci_job.sh /opt/tradebot/verify_stops_live.py
systemctl list-timers tradebot-ci-confirm.timer --no-pager | head -3
echo "installed v2; no bot unit started, stopped or restarted. Next: INSTALL_CI_V2.md §3 (adopt the running release)."
