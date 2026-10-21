#!/bin/bash
# ONE-TIME manual install of the CI deploy plumbing on the VPS (root). Run from a checkout of the reviewed commit:
#   bash live_v6/deploy/ci/install_vps_ci.sh <path-to-repo-checkout>
# Installs: /opt/tradebot/ci/{ci_deploy.sh,ci_deploy_entry.sh,verify_stops_testnet.py} (root:root 0755),
# /etc/systemd/system/live_v6-citest.service (NOT started here). Does not touch live_v6-live, its env, state or code.
# /etc/tradebot/citest.env (testnet keys, 0640 root:tradebot) and the authorized_keys lines are added separately.
set -euo pipefail
SRC=${1:?repo checkout}
install -d -m 755 -o root -g root /opt/tradebot/ci
install -m 755 -o root -g root "$SRC/live_v6/deploy/ci/ci_deploy.sh" /opt/tradebot/ci/ci_deploy.sh
install -m 755 -o root -g root "$SRC/live_v6/deploy/ci/ci_deploy_entry.sh" /opt/tradebot/ci/ci_deploy_entry.sh
install -m 755 -o root -g root "$SRC/live_v6/tools/verify_stops.py" /opt/tradebot/ci/verify_stops_testnet.py
install -m 644 -o root -g root "$SRC/live_v6/deploy/ci/live_v6-citest.service" /etc/systemd/system/live_v6-citest.service
install -d -m 750 -o tradebot -g tradebot /opt/tradebot-ci-testnet /opt/tradebot-ci-testnet/app
install -d -m 700 -o root -g root /root/ci-backups
systemctl daemon-reload
echo "installed; citest unit not started"
