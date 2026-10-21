#!/bin/bash
# CI deploy / rollback for live_v6 on the VPS (runs as root). Installed ONCE, by hand, to /opt/tradebot/ci/ci_deploy.sh
# (root:root 0755) — a deploy never replaces this script or the entry wrapper (no self-update from pushed code).
# Called only via ci_deploy_entry.sh (SSH forced command) or by root for maintenance.
#
#   ci_deploy.sh deploy   <live|testnet> <sha40> <tarfile> [--dry-run]
#   ci_deploy.sh rollback <live|testnet> [--dry-run]
#   ci_deploy.sh status   <live|testnet>
#
# Safety (TA conditions, runbook DEPLOY_950438b.md):
#  * never places orders, never flattens, never touches exchange stops: it only swaps a symlink and restarts the unit;
#  * restart / rollback only inside the 4h-boundary window (≥15 min after a UTC 4h close and ≥20 min before the next);
#  * exchange stops must cover every open position (verify-stops exit 0) BEFORE the restart and BEFORE any rollback —
#    otherwise abort without restarting;
#  * state file backed up before the swap; idempotent (same sha already current + active → no-op);
#  * post-restart verification (unit active, no restart loop, fresh meta.health.ok, bar decisions caught up, no
#    Traceback/CRITICAL in the journal, stops still verified); failure → automatic rollback to the previous sha.
#  * the new heartbeat script is NOT installed here (manual step after a verified restart, runbook §5).
set -euo pipefail
umask 022
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ACTION=${1:-}; TARGET=${2:-}
DRY=0; for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done
VENV_PY=/opt/tradebot/.venv/bin/python
H4=14400
PRE_GAP=${CI_PRE_GAP:-900}          # seconds after a 4h close before a restart is allowed
POST_GAP=${CI_POST_GAP:-1200}       # seconds that must remain before the next 4h close
MAX_WAIT=${CI_MAX_WAIT:-2700}       # wait at most this long for the window, else refuse
VERIFY_TIMEOUT=${CI_VERIFY_TIMEOUT:-240}
STABLE_S=${CI_STABLE_S:-45}
SIM_FAIL=${CI_SIMULATE_VERIFY_FAIL:-0}   # testnet-only drill: force post-restart verification to fail (rollback demo)
SIM_STOPS=${CI_SIMULATE_STOPS_FAIL:-0}   # testnet-only drill: verify-stops reports "unprotected" (abort demo)

case "$TARGET" in
  live)
    APP=/opt/tradebot/app; UNIT=live_v6-live; STATE=/var/lib/live_v6-live/mainnet.json
    STOPS_CMD=(python3 /opt/tradebot/verify_stops_live.py); STOPS_ENV=""
    BACKUP_DIR=/root/ci-backups/live ;;
  testnet)
    APP=/opt/tradebot-ci-testnet/app; UNIT=live_v6-citest; STATE=/var/lib/live_v6-citest/testnet.json
    STOPS_CMD=(python3 /opt/tradebot/ci/verify_stops_testnet.py); STOPS_ENV=/etc/tradebot/citest.env
    BACKUP_DIR=/root/ci-backups/testnet ;;
  *) echo "usage: $0 deploy|rollback|status live|testnet [sha40 tarfile] [--dry-run]" >&2; exit 2 ;;
esac
if [ "$SIM_FAIL$SIM_STOPS" != 00 ] && [ "$TARGET" != testnet ]; then echo "CI_SIMULATE_* drills are testnet-only" >&2; exit 2; fi

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] [$TARGET] $*"; }
die() { log "FAIL: $1"; exit "${2:-1}"; }
run() { if [ $DRY = 1 ]; then log "DRY-RUN would: $*"; else log "+ $*"; "$@"; fi; }
current_sha() { if [ -L "$APP/current" ]; then basename "$(readlink "$APP/current")"; else echo none; fi; }

verify_stops() {   # exit 0 = every open position has a protective exchange stop. Read-only signed GETs; output is
  local out rc     # summarised (no keys are ever printed by the checker).
  if [ -n "$STOPS_ENV" ]; then
    # shellcheck source=/dev/null
    out=$( (set -a; . "$STOPS_ENV"; set +a; "${STOPS_CMD[@]}") 2>&1 ) && rc=0 || rc=$?
  else
    out=$("${STOPS_CMD[@]}" 2>&1) && rc=0 || rc=$?
  fi
  printf '%s\n' "$out" | python3 -c '
import json,sys
t=sys.stdin.read()
try:
    d=json.loads(t[t.index("{"):])
    pos=d.get("positions") or d.get("open_positions") or []
    print("  verify-stops: pass=%s positions=%d %s" % (d.get("pass"), len(pos), [(p.get("symbol"), p.get("positionAmt"), p.get("protected")) for p in pos]))
except Exception:
    print("  verify-stops raw tail:", t[-400:].replace("\n"," "))' || true
  [ "$SIM_STOPS" = 1 ] && { log "SIMULATED: verify-stops reports an unprotected position (testnet drill)"; rc=1; }
  log "verify-stops exit=$rc"
  return $rc
}

in_window() {      # prints seconds to wait (0 = ok now)
  local now since until
  now=$(date -u +%s); since=$(( now % H4 )); until=$(( H4 - since ))
  if [ "$since" -lt "$PRE_GAP" ]; then echo $(( PRE_GAP - since ))
  elif [ "$until" -lt "$POST_GAP" ]; then echo $(( until + PRE_GAP ))
  else echo 0; fi
}

wait_window() {
  local w; w=$(in_window)
  [ "$w" -eq 0 ] && { log "time window OK ($(date -u +%H:%M) UTC: ≥${PRE_GAP}s after the last 4h close, ≥${POST_GAP}s before the next)"; return 0; }
  [ $DRY = 1 ] && { log "DRY-RUN: outside window, a real run would wait ${w}s"; return 0; }
  [ "$w" -gt "$MAX_WAIT" ] && die "outside the 4h-boundary window, would need to wait ${w}s > ${MAX_WAIT}s — refusing" 3
  log "inside the 4h-boundary guard — waiting ${w}s"; sleep "$w"
  [ "$(in_window)" -eq 0 ] || die "still outside window after waiting" 3
}

state_check() {    # $1 = restart epoch; strict=1 → also require bar decisions caught up for the current boundary
  python3 - "$STATE" "$1" "${2:-1}" <<'PY'
import json, os, sys, time
st, t0, strict = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1"
H4 = 4 * 3600 * 1000
try:
    if os.stat(st).st_mtime < t0: print("state not rewritten since restart"); sys.exit(1)
    d = json.load(open(st)); m = d.get("meta", {})
except Exception as e:
    print("state unreadable:", type(e).__name__); sys.exit(1)
h = m.get("health")
if not isinstance(h, dict):
    print("meta.health missing"); sys.exit(1 if strict else 0)
if int(h.get("t") or 0) < t0 * 1000: print("meta.health older than restart"); sys.exit(1)
if not h.get("ok"): print("meta.health.ok=false blocks=%s" % h.get("blocks")); sys.exit(1)
T = int(time.time() * 1000) // H4 * H4
lo = {s: x.get("last_open") for s, x in (d.get("strategy", {}).get("models") or {}).items()}
lbc = m.get("last_bar_close")
if strict and (lbc != T or not lo or set(lo.values()) != {T - H4}):
    print("bars not caught up: last_bar_close=%s boundary=%s models=%s" % (lbc, T, lo)); sys.exit(1)
print("health ok, last_bar_close=%s boundary=%s models=%d all caught up" % (lbc, T, len(lo)))
PY
}

journal_clean() {  # $1 = since epoch
  local bad
  bad=$(journalctl -u "$UNIT" --since "@$1" --no-pager -o cat 2>/dev/null | grep -E "Traceback|CRITICAL|모델 재구성" | head -5 || true)
  [ -z "$bad" ] && return 0
  log "journal problems:"; printf '%s\n' "$bad" | cut -c1-300; return 1
}

restarts() { systemctl show "$UNIT" -p NRestarts --value 2>/dev/null || echo 0; }

restart_and_verify() {   # $1 strict(1)/weak(0); returns 0 if healthy
  local strict=$1 t0 r0 pid deadline msg
  t0=$(date -u +%s)
  systemctl restart "$UNIT"
  r0=$(restarts); deadline=$(( t0 + VERIFY_TIMEOUT ))
  log "restarted $UNIT at $(date -u -d "@$t0" +%H:%M:%SZ); verifying (≤${VERIFY_TIMEOUT}s)"
  while :; do
    sleep 10
    if [ "$(systemctl is-active "$UNIT")" = active ] && msg=$(state_check "$t0" "$strict"); then
      log "  state: $msg"; break
    fi
    log "  waiting: unit=$(systemctl is-active "$UNIT") ${msg:-}"
    [ "$(date -u +%s)" -ge $deadline ] && { log "verification timeout"; return 1; }
  done
  pid=$(systemctl show "$UNIT" -p MainPID --value)
  sleep "$STABLE_S"
  [ "$(systemctl is-active "$UNIT")" = active ] || { log "unit not active after ${STABLE_S}s"; return 1; }
  [ "$(restarts)" = "$r0" ] && [ "$(systemctl show "$UNIT" -p MainPID --value)" = "$pid" ] || { log "restart loop detected"; return 1; }
  journal_clean "$t0" || return 1
  verify_stops || { log "stops not verified after restart"; return 1; }
  [ "$SIM_FAIL" = 1 ] && { log "SIMULATED verification failure (testnet drill)"; return 1; }
  log "verification PASSED"
}

swap_to() {   # $1 = sha7 dir name
  ln -sfn "$APP/$1" "$APP/current.new" && mv -T "$APP/current.new" "$APP/current"
  echo "$1" > "$APP/DEPLOYED"
  log "symlink current → $1"
}

do_rollback() {   # $1 = reason
  local prev; prev=$(cat "$APP/PREVIOUS" 2>/dev/null || true)
  [ -n "$prev" ] && [ -d "$APP/$prev" ] || die "no previous release recorded — cannot roll back ($1)" 4
  [ "$prev" = "$(current_sha)" ] && die "previous == current ($prev), nothing to roll back to" 4
  log "ROLLBACK to $prev (reason: $1)"
  SIM_FAIL=0   # the verify-fail drill only targets the deploy under test, never the rollback
  verify_stops || die "stops NOT verified — rollback ABORTED, no restart done. Manual check required." 5
  wait_window
  [ $DRY = 1 ] && { log "DRY-RUN: would swap current → $prev and restart $UNIT"; return 0; }
  local bad; bad=$(current_sha)
  swap_to "$prev"; echo "$bad" > "$APP/PREVIOUS"
  if restart_and_verify 0; then log "rollback to $prev verified"; else die "rollback to $prev did NOT verify — manual intervention" 6; fi
}

exec 9>/run/tradebot-ci.lock
flock -n 9 || die "another CI deploy is running" 7
log "action=$ACTION dry_run=$DRY current=$(current_sha) unit=$(systemctl is-active "$UNIT" || true)"

case "$ACTION" in
  status)
    log "previous=$(cat "$APP/PREVIOUS" 2>/dev/null || echo none) window_wait=$(in_window)s"
    verify_stops || true; state_check 0 1 || true ;;
  rollback)
    do_rollback "manual request" ;;
  deploy)
    SHA=${3:-}; TAR=${4:-}
    [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "bad sha" 2
    [ -f "$TAR" ] || die "tar missing" 2
    S7=${SHA:0:7}
    if [ "$(current_sha)" = "$S7" ] && [ "$(systemctl is-active "$UNIT")" = active ]; then
      log "$S7 already current and $UNIT active — no-op"; exit 0
    fi
    # 1. stage + import check (no changes to the running release)
    STAGE=$(mktemp -d /tmp/ci-stage.XXXXXX); trap 'rm -rf "$STAGE"' EXIT
    LIST=$(tar -tf "$TAR") || die "unreadable archive" 2
    BADP=$(grep -vE '^live_v6(/|$)' <<<"$LIST" || true; grep -E '(^|/)\.\.(/|$)' <<<"$LIST" || true)
    [ -z "$BADP" ] || die "archive contains paths outside live_v6/ or '..'" 2
    tar -xf "$TAR" -C "$STAGE" --no-same-owner
    chown -R tradebot:tradebot "$STAGE"; chmod 755 "$STAGE"
    (cd "$STAGE" && runuser -u tradebot -- env PYTHONDONTWRITEBYTECODE=1 "$VENV_PY" -c \
      "import live_v6.runner, live_v6.tgcmd, live_v6.engine as e, inspect; s=inspect.getsource(e.V6Engine.tick); assert 'self.on_bar_close()' in s; print('import ok, tick calls on_bar_close')") \
      || die "import check failed — nothing changed" 8
    log "import check OK for $S7"
    # 2. pre-checks
    wait_window
    verify_stops || die "stops NOT verified for every open position — deploy ABORTED before restart" 5
    if [ $DRY = 1 ]; then
      log "DRY-RUN would: back up $STATE → $BACKUP_DIR/, install $APP/$S7, PREVIOUS=$(current_sha), swap current → $S7, systemctl restart $UNIT, verify (strict), auto-rollback on failure"
      exit 0
    fi
    # 3. backup + install
    mkdir -p "$BACKUP_DIR" "$APP"
    [ -f "$STATE" ] && cp -p "$STATE" "$BACKUP_DIR/$(basename "$STATE").bak-$(date -u +%Y%m%dT%H%M%SZ)-pre-$S7" && log "state backed up"
    find "$BACKUP_DIR" -maxdepth 1 -type f -printf '%T@ %p\n' | sort -rn | tail -n +31 | cut -d' ' -f2- | xargs -r rm -f
    if [ ! -f "$APP/$S7/.ci_complete" ]; then
      rm -rf "$APP/$S7.tmp"; mkdir -p "$APP/$S7.tmp"; cp -a "$STAGE/." "$APP/$S7.tmp/"
      echo "$SHA" > "$APP/$S7.tmp/.ci_complete"; chown -R tradebot:tradebot "$APP/$S7.tmp"
      rm -rf "${APP:?}/${S7:?}"; mv -T "$APP/$S7.tmp" "$APP/$S7"
      log "installed $APP/$S7"
    else
      log "$APP/$S7 already installed (reusing)"
    fi
    PREV=$(current_sha)
    [ "$PREV" != none ] && [ "$PREV" != "$S7" ] && echo "$PREV" > "$APP/PREVIOUS"
    # 4. swap + restart + verify
    swap_to "$S7"
    if restart_and_verify 1; then
      log "DEPLOYED $S7 (previous: ${PREV}). Heartbeat script NOT changed (manual step, runbook §5)."
      exit 0
    fi
    log "post-restart verification FAILED for $S7"
    if [ "$PREV" = none ] || [ "$PREV" = "$S7" ]; then die "no previous release to roll back to" 4; fi
    do_rollback "verification failed for $S7"
    die "deploy of $S7 failed; rolled back to $PREV" 9 ;;
  *) die "unknown action" 2 ;;
esac
