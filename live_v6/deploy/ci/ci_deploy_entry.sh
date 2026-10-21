#!/bin/bash
# SSH forced-command entry for the CI deploy keys. Installed ONCE, by hand, to /opt/tradebot/ci/ci_deploy_entry.sh.
# authorized_keys:  command="/opt/tradebot/ci/ci_deploy_entry.sh <live|testnet>",no-port-forwarding,no-pty,
#                   no-agent-forwarding,no-X11-forwarding,no-user-rc ssh-ed25519 AAAA… tradebot-ci-<target>
# The TARGET comes from authorized_keys (one key per target), never from the client. Accepted SSH_ORIGINAL_COMMAND:
#   deploy <sha40> <sha256-of-tar> [dry-run]   (tar of `git archive <sha> live_v6` on stdin, ≤ 20 MB)
#   rollback [dry-run]
#   status
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
TARGET=${1:-}
[[ "$TARGET" =~ ^(live|testnet)$ ]] || { echo "entry: bad target" >&2; exit 2; }
CMD=${SSH_ORIGINAL_COMMAND:-}
LOG=/var/log/tradebot/ci-deploy.log
mkdir -p /var/log/tradebot
echo "[$(date -u +%FT%TZ)] target=$TARGET from=${SSH_CLIENT%% *} cmd=$(printf '%s' "$CMD" | tr -cd 'a-z0-9 -' | cut -c1-140)" >> "$LOG"
DEPLOY=/opt/tradebot/ci/ci_deploy.sh
if [[ "$CMD" =~ ^deploy\ ([0-9a-f]{40})\ ([0-9a-f]{64})(\ dry-run)?$ ]]; then
  SHA=${BASH_REMATCH[1]}; SUM=${BASH_REMATCH[2]}; DRY=${BASH_REMATCH[3]:+--dry-run}
  TAR=$(mktemp /tmp/ci-upload.XXXXXX.tar); trap 'rm -f "$TAR"' EXIT
  head -c 20000001 > "$TAR"
  [ "$(stat -c %s "$TAR")" -le 20000000 ] || { echo "entry: upload too large" >&2; exit 2; }
  echo "$SUM  $TAR" | sha256sum -c --status || { echo "entry: sha256 mismatch" >&2; exit 2; }
  "$DEPLOY" deploy "$TARGET" "$SHA" "$TAR" ${DRY:+"$DRY"} 2>&1 | tee -a "$LOG"; exit "${PIPESTATUS[0]}"
elif [[ "$CMD" =~ ^rollback(\ dry-run)?$ ]]; then
  "$DEPLOY" rollback "$TARGET" ${BASH_REMATCH[1]:+--dry-run} 2>&1 | tee -a "$LOG"; exit "${PIPESTATUS[0]}"
elif [[ "$CMD" == status ]]; then
  "$DEPLOY" status "$TARGET" 2>&1 | tee -a "$LOG"; exit "${PIPESTATUS[0]}"
fi
echo "entry: command not allowed" >&2; exit 2
