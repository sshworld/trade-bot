#!/bin/bash
# Runner side of a CI deploy: archive live_v6 at $SHA and stream it to the VPS forced-command entry.
# The target (live/testnet) is decided by WHICH key is used (environment secret), not by this script.
# Env: SHA, VPS_SSH_KEY, VPS_HOST, VPS_KNOWN_HOSTS; optional DRY_RUN=1. Never echoes secrets.
set -euo pipefail
[[ "${SHA:-}" =~ ^[0-9a-f]{40}$ ]] || { echo "bad SHA"; exit 2; }
D=$(mktemp -d); trap 'rm -rf "$D"' EXIT
umask 077
printf '%s\n' "$VPS_SSH_KEY" > "$D/key"
printf '%s\n' "$VPS_KNOWN_HOSTS" > "$D/known_hosts"
git archive --format=tar "$SHA" live_v6 > "$D/app.tar"
SUM=$(sha256sum "$D/app.tar" | cut -d' ' -f1)
EXTRA=""; [ "${DRY_RUN:-0}" = 1 ] && EXTRA=" dry-run"
ssh -i "$D/key" -o IdentitiesOnly=yes -o UserKnownHostsFile="$D/known_hosts" -o StrictHostKeyChecking=yes \
    -o BatchMode=yes -o ServerAliveInterval=30 -o ConnectTimeout=20 "root@$VPS_HOST" \
    "deploy $SHA $SUM$EXTRA" < "$D/app.tar"
