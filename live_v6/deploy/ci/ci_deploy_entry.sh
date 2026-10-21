#!/bin/bash
# SSH forced-command entry for the CI deploy keys. Installed ONCE, by hand, to /opt/tradebot/ci/ci_deploy_entry.sh.
# /root/.ssh/authorized_keys (TA F):
#   restrict,command="/opt/tradebot/ci/ci_deploy_entry.sh <live|testnet>" ssh-ed25519 AAAA… tradebot_ci_<target>
# sshd: PermitRootLogin forced-commands-only (root can ONLY run these forced commands; admin access = user `ops`).
# The TARGET comes from authorized_keys (one key per target), never from the client. Accepted SSH_ORIGINAL_COMMAND:
#   deploy <sha40> <sha256-of-tar> [dry-run]   tar of `git archive <sha> live_v6` on stdin (≤ 20 MB) → "JOB <id>"
#   rollback [dry-run]                         → "JOB <id>"
#   job <id>                                   → job log + "JOB_STATE running|done rc=N"
#   status                                     → current release, marker, rollback target, stops, state (synchronous,
#                                                read-only)
# Deploy / rollback bodies run DETACHED (ci_job.sh → systemd-run --collect), so a dropped SSH session cannot interrupt
# them (TA J). The client polls `job <id>`.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
TARGET=${1:-}
[[ "$TARGET" =~ ^(live|testnet)$ ]] || { echo "entry: bad target" >&2; exit 2; }
CMD=${SSH_ORIGINAL_COMMAND:-}
LOG=/var/log/tradebot/ci-deploy.log
UP=/var/lib/tradebot-ci/uploads
mkdir -p /var/log/tradebot "$UP"; chmod 700 "$UP"
echo "[$(date -u +%FT%TZ)] target=$TARGET from=${SSH_CLIENT%% *} cmd=$(printf '%s' "$CMD" | tr -cd 'a-zA-Z0-9 -' | cut -c1-140)" >> "$LOG"
JOB=/opt/tradebot/ci/ci_job.sh
if [[ "$CMD" =~ ^deploy\ ([0-9a-f]{40})\ ([0-9a-f]{64})(\ dry-run)?$ ]]; then
  SHA=${BASH_REMATCH[1]}; SUM=${BASH_REMATCH[2]}; DRY=${BASH_REMATCH[3]:+--dry-run}
  TAR=$(mktemp "$UP/$TARGET-$SHA.XXXXXX.tar")
  head -c 20000001 > "$TAR"
  [ "$(stat -c %s "$TAR")" -le 20000000 ] || { rm -f "$TAR"; echo "entry: upload too large" >&2; exit 2; }
  echo "$SUM  $TAR" | sha256sum -c --status || { rm -f "$TAR"; echo "entry: sha256 mismatch (incomplete upload?) — nothing started" >&2; exit 2; }
  "$JOB" start "$TARGET" deploy "$SHA" "$TAR" ${DRY:+"$DRY"} || { rc=$?; rm -f "$TAR"; exit $rc; }
elif [[ "$CMD" =~ ^rollback(\ dry-run)?$ ]]; then
  exec "$JOB" start "$TARGET" rollback ${BASH_REMATCH[1]:+--dry-run}
elif [[ "$CMD" =~ ^job\ ([0-9]{8}T[0-9]{6}Z-[0-9a-f]{6})$ ]]; then
  exec "$JOB" show "$TARGET" "${BASH_REMATCH[1]}"
elif [[ "$CMD" == status ]]; then
  /opt/tradebot/ci/ci_deploy.sh status "$TARGET" 2>&1 | tee -a "$LOG"; exit "${PIPESTATUS[0]}"
else
  echo "entry: command not allowed" >&2; exit 2
fi
