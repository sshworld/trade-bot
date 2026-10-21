#!/bin/bash
# Runner side of a CI deploy: archive live_v6 at $SHA, upload it to the VPS forced-command entry, which starts the
# deploy DETACHED on the server (TA J) and returns a job id; then poll `job <id>` until it is done.
# A dropped SSH connection only interrupts polling — the server-side job runs to the end (incl. rollback / stop +
# alert on failure). The target (live/testnet) is decided by WHICH key is used (environment secret), not here.
# Env: SHA, VPS_SSH_KEY, VPS_HOST, VPS_KNOWN_HOSTS; optional DRY_RUN=1, POLL_S (15), MAX_POLL_MIN (85),
# ACTION=deploy|rollback. Never echoes secrets.
set -euo pipefail
ACTION=${ACTION:-deploy}
D=$(mktemp -d); trap 'rm -rf "$D"' EXIT
umask 077
printf '%s\n' "$VPS_SSH_KEY" > "$D/key"
printf '%s\n' "$VPS_KNOWN_HOSTS" > "$D/known_hosts"
S() { ssh -i "$D/key" -o IdentitiesOnly=yes -o UserKnownHostsFile="$D/known_hosts" -o StrictHostKeyChecking=yes \
          -o BatchMode=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=4 -o ConnectTimeout=20 "root@$VPS_HOST" "$@"; }
EXTRA=""; [ "${DRY_RUN:-0}" = 1 ] && EXTRA=" dry-run"
if [ "$ACTION" = deploy ]; then
  [[ "${SHA:-}" =~ ^[0-9a-f]{40}$ ]] || { echo "bad SHA"; exit 2; }
  git archive --format=tar "$SHA" live_v6 > "$D/app.tar"
  SUM=$(sha256sum "$D/app.tar" | cut -d' ' -f1)
  OUT=$(S "deploy $SHA $SUM$EXTRA" < "$D/app.tar")
elif [ "$ACTION" = rollback ]; then
  OUT=$(S "rollback$EXTRA" < /dev/null)
else
  echo "bad ACTION"; exit 2
fi
ID=$(sed -n 's/^JOB \([0-9]\{8\}T[0-9]\{6\}Z-[0-9a-f]\{6\}\)$/\1/p' <<<"$OUT" | head -1)
[ -n "$ID" ] || { echo "$OUT"; echo "::error::server did not start a job"; exit 1; }
echo "server job $ID started (detached on the VPS)"
shown=0; fails=0; deadline=$(( $(date +%s) + ${MAX_POLL_MIN:-85} * 60 ))
while :; do
  sleep "${POLL_S:-15}"
  if R=$(S "job $ID" < /dev/null 2>&1); then
    fails=0
    body=$(sed '/^JOB_STATE /d' <<<"$R")
    n=$(printf '%s\n' "$body" | wc -l)
    [ "$n" -gt "$shown" ] && printf '%s\n' "$body" | tail -n +"$((shown + 1))"
    shown=$n
    st=$(sed -n 's/^JOB_STATE //p' <<<"$R" | tail -1)
    if [[ "$st" =~ ^done\ rc=([0-9]+)$ ]]; then
      rc=${BASH_REMATCH[1]}
      [ "$rc" = 0 ] && echo "job $ID finished OK" || echo "::error::job $ID failed rc=$rc (see log above)"
      exit "$rc"
    fi
  else
    fails=$((fails + 1)); echo "poll failed ($fails) — the server job keeps running; retrying"
    [ "$fails" -ge 40 ] && { echo "::error::lost contact with the VPS for ~10 min; job $ID result unknown"; exit 1; }
  fi
  [ "$(date +%s)" -ge "$deadline" ] && { echo "::error::job $ID still running after ${MAX_POLL_MIN:-85} min"; exit 1; }
done
