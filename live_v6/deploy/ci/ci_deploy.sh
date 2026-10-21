#!/bin/bash
# CI deploy / rollback for live_v6 on the VPS (runs as root). Installed ONCE, by hand, to /opt/tradebot/ci/ci_deploy.sh
# (root:root 0755) — a deploy never replaces this script, ci_job.sh or the entry wrapper (no self-update from pushed code).
# Runs DETACHED from any SSH session (TA J): ci_deploy_entry.sh → ci_job.sh start → systemd-run --collect → ci_job.sh run
# → this script, output to a job log file only. The CI client polls `job <id>`.
#
#   ci_deploy.sh deploy   <live|testnet> <sha40> <tarfile> [--dry-run]
#   ci_deploy.sh rollback <live|testnet> [--dry-run]
#   ci_deploy.sh status   <live|testnet>
#
# Safety (TA review ci-deploy 2026-10-21, runbook DEPLOY_950438b.md):
#  * never places orders, never flattens, never touches exchange stops: it only swaps a symlink and runs
#    systemctl restart / stop on the target unit;
#  * PLANNED restarts (deploy, manual rollback) only inside the 4h-boundary window (≥15 min after a UTC 4h close and
#    ≥20 min before the next); the AUTOMATIC reaction to a failed deploy (rollback or stop) never waits (TA E);
#  * exchange stops must cover every open position (verify-stops exit 0) BEFORE a restart and BEFORE a rollback;
#  * no restart while the state file has in-flight entry intents (waits, then refuses);
#  * rollback ONLY to a release carrying the verified marker (live: .ta_pass_verified, written only after the full
#    strict verification of a gate-approved ta-pass-* commit; testnet: .citest_verified) and the rollback is verified
#    strictly as well. No marked release / rollback not verified / stops not verified → systemctl stop + Healthchecks
#    /fail + log + non-zero exit (TA H). Stopping the bot leaves exchange stops in place; nothing is closed.
set -euo pipefail
umask 022
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ACTION=${1:-}; TARGET=${2:-}
DRY=0; for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done
H4=14400
PRE_GAP=${CI_PRE_GAP:-900}          # seconds after a 4h close before a planned restart is allowed
POST_GAP=${CI_POST_GAP:-1200}       # seconds that must remain before the next 4h close
MAX_WAIT=${CI_MAX_WAIT:-2700}       # wait at most this long for the window, else refuse
VERIFY_TIMEOUT=${CI_VERIFY_TIMEOUT:-240}
STABLE_S=${CI_STABLE_S:-45}
INTENT_WAIT=${CI_INTENT_WAIT:-30}   # recommendation: no restart while state.intents is non-empty
INTENT_TRIES=${CI_INTENT_TRIES:-10}
MIN_STOP_TIMEOUT_S=20               # recommendation: the unit's TimeoutStopSec must leave the runner time to finish
SIM_FAIL=${CI_SIMULATE_VERIFY_FAIL:-0}            # testnet drill: post-restart verification of the deploy fails
SIM_STOPS=${CI_SIMULATE_STOPS_FAIL:-0}            # testnet drill: verify-stops reports "unprotected"
SIM_RB_FAIL=${CI_SIMULATE_ROLLBACK_VERIFY_FAIL:-0} # testnet drill: verification of the rollback fails
STAGE_ROOT=/var/lib/tradebot-ci/stage
SANDBOX_DENY="-/etc/tradebot -/var/lib/live_v6-live -/opt/tradebot/app -/var/log/tradebot -/root -/var/lib/tradebot-ci/uploads"

case "$TARGET" in
  live)
    APP=/opt/tradebot/app; UNIT=live_v6-live; STATE=/var/lib/live_v6-live/mainnet.json
    STOPS_CMD=(python3 /opt/tradebot/verify_stops_live.py); STOPS_ENV=""
    MARK=.ta_pass_verified; ALERT_ENV=/etc/tradebot/heartbeat.env
    IMPORT_USER=tradebot; IMPORT_PY=/opt/tradebot/.venv/bin/python
    BACKUP_DIR=/root/ci-backups/live ;;
  testnet)
    APP=/opt/tradebot-ci-testnet/app; UNIT=live_v6-citest; STATE=/var/lib/live_v6-citest/testnet.json
    STOPS_CMD=(python3 /opt/tradebot/ci/verify_stops_testnet.py); STOPS_ENV=/etc/tradebot/citest.env
    MARK=.citest_verified; ALERT_ENV=/etc/tradebot/ci-alert-testnet.env     # DUMMY Healthchecks URL, never the live one
    IMPORT_USER=tradebot-ci; IMPORT_PY=/opt/tradebot-ci-testnet/.venv/bin/python
    SANDBOX_DENY="$SANDBOX_DENY -/opt/tradebot"
    BACKUP_DIR=/root/ci-backups/testnet ;;
  *) echo "usage: $0 deploy|rollback|status live|testnet [sha40 tarfile] [--dry-run]" >&2; exit 2 ;;
esac
if [ "$SIM_FAIL$SIM_STOPS$SIM_RB_FAIL" != 000 ] && [ "$TARGET" != testnet ]; then echo "CI_SIMULATE_* drills are testnet-only" >&2; exit 2; fi

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] [$TARGET] $*"; }
die() { log "FAIL: $1"; exit "${2:-1}"; }

# ── releases ───────────────────────────────────────────────────────────────────────────────────────────────────────
# New releases live in $APP/<sha40> (recommendation: full sha). Older hand-deployed releases use 7-char names; their
# full sha comes from .ci_complete or the marker.
current_dir() { if [ -L "$APP/current" ]; then basename "$(readlink "$APP/current")"; else echo none; fi; }
release_sha() {   # $1 = dir name → full sha if known, else the dir name
  local d=$APP/$1 s=""
  [ -f "$d/.ci_complete" ] && s=$(head -1 "$d/.ci_complete")
  [ -z "$s" ] && [ -f "$d/$MARK" ] && s=$(sed -n 's/^sha=//p' "$d/$MARK" | head -1)
  [[ "$s" =~ ^[0-9a-f]{40}$ ]] && echo "$s" || echo "$1"
}
marker_ok() {     # $1 = dir name: marker present, root-owned, and its sha matches the directory
  local d=$APP/$1 s
  [ -f "$d/$MARK" ] && [ "$(stat -c %u "$d/$MARK")" = 0 ] || return 1
  s=$(sed -n 's/^sha=//p' "$d/$MARK" | head -1)
  [[ "$s" =~ ^[0-9a-f]{40}$ ]] && [[ "$s" == "$1"* ]]
}
verified_target() {   # newest release with a valid marker, excluding $1 (the failed / current one)
  local d best="" bt="" t
  for d in "$APP"/*/; do
    d=$(basename "$d"); [ "$d" = "$1" ] && continue
    [ "$(release_sha "$d")" = "$(release_sha "$1" 2>/dev/null)" ] && continue
    marker_ok "$d" || continue
    t=$(sed -n 's/^verified_at_utc=//p' "$APP/$d/$MARK" | head -1)
    if [ -z "$best" ] || [[ "$t" > "$bt" ]]; then best=$d; bt=$t; fi
  done
  echo "$best"
}
write_marker() {  # $1 = dir name, $2 = sha40, $3 = verify summary — only after a STRICT verification passed
  local f=$APP/$1/$MARK
  { echo "sha=$2"; echo "target=$TARGET"; echo "verified_at_utc=$(ts)"; echo "verified_by=ci_deploy.sh strict"
    python3 - "$STATE" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); m = d.get("meta", {})
lo = {s: x.get("last_open") for s, x in (d.get("strategy", {}).get("models") or {}).items()}
print("last_bar_close=%s" % m.get("last_bar_close")); print("models_last_open=%s" % ",".join(sorted({str(v) for v in lo.values()})))
print("models=%d" % len(lo)); print("health_ok=%s" % str(bool((m.get("health") or {}).get("ok"))).lower())
PY
    echo "stops_exit=0"; } > "$f.tmp"
  chown root:root "$f.tmp"; chmod 644 "$f.tmp"; mv -f "$f.tmp" "$f"
  log "marker $MARK written for $1 ($3)"
}

# ── checks ─────────────────────────────────────────────────────────────────────────────────────────────────────────
verify_stops() {   # exit 0 = every open position has a protective exchange stop. Read-only signed GETs; output is
  local out rc     # summarised (the checker never prints keys).
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
    print("  verify-stops: pass=%s positions=%d %s%s" % (d.get("pass"), len(pos), [(p.get("symbol"), p.get("positionAmt"), p.get("protected")) for p in pos], (" error=" + d["error"]) if d.get("error") else ""))
except Exception:
    print("  verify-stops: unparseable output (%d bytes)" % len(t))' || true
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

wait_window() {    # PLANNED restarts only (deploy, manual rollback). Never called on the failure path (TA E).
  local w; w=$(in_window)
  [ "$w" -eq 0 ] && { log "time window OK ($(date -u +%H:%M) UTC: ≥${PRE_GAP}s after the last 4h close, ≥${POST_GAP}s before the next)"; return 0; }
  [ $DRY = 1 ] && { log "DRY-RUN: outside window, a real run would wait ${w}s"; return 0; }
  [ "$w" -gt "$MAX_WAIT" ] && die "outside the 4h-boundary window, would need to wait ${w}s > ${MAX_WAIT}s — refusing (nothing changed)" 3
  log "inside the 4h-boundary guard — waiting ${w}s"; sleep "$w"
  [ "$(in_window)" -eq 0 ] || die "still outside window after waiting (nothing changed)" 3
}

intents_count() { python3 -c 'import json,sys
try: print(len(json.load(open(sys.argv[1])).get("intents") or {}))
except FileNotFoundError: print(0)
except Exception: print(-1)' "$STATE"; }

wait_no_intents() {   # recommendation: never restart in the middle of an entry (enter → _upgrade_stop)
  local i n
  for i in $(seq 1 "$INTENT_TRIES"); do
    n=$(intents_count)
    [ "$n" = 0 ] && { log "state: no in-flight intents"; return 0; }
    log "state: $n in-flight intent(s) (or unreadable=-1) — waiting ${INTENT_WAIT}s ($i/$INTENT_TRIES)"
    sleep "$INTENT_WAIT"
  done
  return 1
}

check_stop_timeout() {   # recommendation: TimeoutStopSec of the target unit
  local us; us=$(systemctl show "$UNIT" -p TimeoutStopUSec --value)
  log "unit $UNIT TimeoutStopUSec=$us (SIGTERM → runner finishes the current event; SIGKILL after this)"
  python3 - "$us" "$MIN_STOP_TIMEOUT_S" <<'PY' || die "TimeoutStopSec of $UNIT is below ${MIN_STOP_TIMEOUT_S}s — refusing" 12
import re, sys
v, need = sys.argv[1], int(sys.argv[2]); s = 0.0
for n, u in re.findall(r"([\d.]+)(min|ms|us|s|h)", v):
    s += float(n) * {"h": 3600, "min": 60, "s": 1, "ms": 1e-3, "us": 1e-6}[u]
sys.exit(0 if v == "infinity" or s >= need else 1)
PY
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
if strict and (lbc != T or len(lo) != 6 or set(lo.values()) != {T - H4}):
    print("bars not caught up: last_bar_close=%s boundary=%s models=%s" % (lbc, T, lo)); sys.exit(1)
print("health ok, last_bar_close=%s boundary=%s models=%d all caught up, positions=%d" % (lbc, T, len(lo), len(d.get("pos") or {})))
PY
}

journal_clean() {  # $1 = since epoch
  local bad
  bad=$(journalctl -u "$UNIT" --since "@$1" --no-pager -o cat 2>/dev/null | grep -E "Traceback|CRITICAL|모델 재구성" | head -5 || true)
  [ -z "$bad" ] && return 0
  log "journal problems:"; printf '%s\n' "$bad" | cut -c1-300; return 1
}

restarts() { systemctl show "$UNIT" -p NRestarts --value 2>/dev/null || echo 0; }

restart_and_verify() {   # strict verification (TA H: deploys AND rollbacks); $1 = simulate failure (0/1)
  local sim=$1 t0 r0 pid deadline msg=""
  t0=$(date -u +%s)
  systemctl restart "$UNIT"
  r0=$(restarts); deadline=$(( t0 + VERIFY_TIMEOUT ))
  log "restarted $UNIT at $(date -u -d "@$t0" +%H:%M:%SZ); verifying strictly (≤${VERIFY_TIMEOUT}s)"
  while :; do
    sleep 10
    if [ "$(systemctl is-active "$UNIT")" = active ] && msg=$(state_check "$t0" 1); then
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
  [ "$sim" = 1 ] && { log "SIMULATED verification failure (testnet drill)"; return 1; }
  VERIFIED_MSG=$msg
  log "verification PASSED"
}

swap_to() {   # $1 = release dir name
  ln -sfn "$APP/$1" "$APP/current.new" && mv -T "$APP/current.new" "$APP/current"
  echo "$1" > "$APP/DEPLOYED"
  log "symlink current → $1"
}

alert_fail() {     # Healthchecks /fail with a reason. The URL is read from $ALERT_ENV and never printed.
  local reason=$1 url
  url=$( (set -a; . "$ALERT_ENV" 2>/dev/null; set +a; printf '%s' "${HEARTBEAT_URL:-}") ) || true
  [ -n "$url" ] || { log "ALERT: no HEARTBEAT_URL in $ALERT_ENV — alert NOT sent"; return 1; }
  if curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "ci-deploy[$TARGET]: $reason" "$url/fail" 2>/dev/null; then
    log "ALERT: Healthchecks /fail sent ($ALERT_ENV)"
  else
    log "ALERT: Healthchecks /fail could NOT be sent"; return 1
  fi
}

stop_and_alert() {   # $1 = reason, $2 = exit code. Never touches exchange stops / positions.
  log "STOPPING $UNIT — reason: $1 (exchange stops stay in place; nothing is closed or cancelled)"
  verify_stops || log "NOTE: verify-stops ≠ 0 while stopping — check exchange stops by hand"
  systemctl stop "$UNIT" || true
  log "unit $UNIT is now: $(systemctl is-active "$UNIT" || true)"
  echo "$(ts) $1" > "$APP/CI_HALTED"
  alert_fail "$1 — $UNIT STOPPED, manual action required" || true
  die "$1 — $UNIT stopped" "$2"
}

do_rollback() {    # $1 = reason, $2 = auto(1: failure path, no window wait) / manual(0), $3 = dir to exclude
  local reason=$1 auto=$2 bad=$3 prev
  SIM_FAIL=0
  prev=$(verified_target "$bad")
  log "rollback candidates: verified ($MARK) releases other than $bad → ${prev:-none}"
  if [ -z "$prev" ]; then
    [ "$auto" = 1 ] && stop_and_alert "no $MARK release to roll back to ($reason)" 10
    die "no $MARK release to roll back to — manual rollback refused, nothing changed" 4
  fi
  log "ROLLBACK to $prev ($(release_sha "$prev")) (reason: $reason)"
  if ! verify_stops; then
    [ "$auto" = 1 ] && stop_and_alert "stops NOT verified before rollback ($reason)" 5
    die "stops NOT verified — manual rollback ABORTED, nothing changed" 5
  fi
  [ "$auto" = 1 ] && log "automatic reaction to a failed deploy — NOT waiting for the time window (TA E)" || wait_window
  [ $DRY = 1 ] && { log "DRY-RUN: would swap current → $prev and restart $UNIT (strict verify)"; return 0; }
  [ "$auto" = 1 ] || { wait_no_intents || die "in-flight intents did not clear — manual rollback refused, nothing changed" 11; }
  swap_to "$prev"; echo "$bad" > "$APP/PREVIOUS"
  if restart_and_verify "$SIM_RB_FAIL"; then
    log "rollback to $prev verified (strict: health, bars caught up, stable, journal clean, stops)"
  else
    stop_and_alert "rollback to $prev did NOT verify ($reason)" 6
  fi
}

mkdir -p /run/lock
exec 9>/run/tradebot-ci.lock
flock -n 9 || die "another CI deploy is running" 7
log "action=$ACTION dry_run=$DRY current=$(current_dir) unit=$(systemctl is-active "$UNIT" || true)"

case "$ACTION" in
  status)
    cur=$(current_dir)
    log "current=$cur sha=$(release_sha "$cur") marker=$(marker_ok "$cur" && echo yes || echo no) rollback_target=$(verified_target "$cur") window_wait=$(in_window)s intents=$(intents_count)"
    [ -f "$APP/CI_HALTED" ] && log "CI_HALTED: $(cat "$APP/CI_HALTED")"
    verify_stops || true; state_check 0 1 || true ;;
  rollback)
    do_rollback "manual request" 0 "$(current_dir)" ;;
  deploy)
    SHA=${3:-}; TAR=${4:-}
    [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "bad sha" 2
    [ -f "$TAR" ] || die "tar missing" 2
    CUR=$(current_dir)
    if [ "$(release_sha "$CUR")" = "$SHA" ] && [ "$(systemctl is-active "$UNIT")" = active ]; then
      log "$SHA already current ($CUR) and $UNIT active — no-op (marker: $(marker_ok "$CUR" && echo present || echo MISSING))"; exit 0
    fi
    # 1. archive checks (recommendation: regular files and directories only — no symlinks, hardlinks, devices)
    LIST=$(tar -tvf "$TAR") || die "unreadable archive" 2
    BADT=$(awk '{print substr($1,1,1)}' <<<"$LIST" | grep -vE '^[-d]$' | sort -u | tr '\n' ' ' || true)
    [ -z "$BADT" ] || die "archive contains non-regular entries (types: $BADT) — symlinks/hardlinks/devices refused" 2
    NAMES=$(tar -tf "$TAR")
    BADP=$(grep -vE '^live_v6(/|$)' <<<"$NAMES" || true; grep -E '(^|/)\.\.(/|$)' <<<"$NAMES" || true)
    [ -z "$BADP" ] || die "archive contains paths outside live_v6/ or '..'" 2
    # 2. stage + sandboxed import check (TA K: never the live user/paths for untagged code; no network)
    mkdir -p "$STAGE_ROOT"; chmod 711 "$STAGE_ROOT"
    STAGE=$(mktemp -d "$STAGE_ROOT/$TARGET.XXXXXX"); trap 'rm -rf "$STAGE"' EXIT
    tar -xf "$TAR" -C "$STAGE" --no-same-owner --no-same-permissions
    chown -R root:root "$STAGE"; chmod -R u=rwX,go=rX "$STAGE"
    systemd-run --quiet --wait --pipe --collect --unit="tradebot-ci-import-$TARGET-$$" \
      -p User="$IMPORT_USER" -p Group="$IMPORT_USER" -p WorkingDirectory="$STAGE" \
      -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes -p PrivateNetwork=yes \
      -p "InaccessiblePaths=$SANDBOX_DENY" -p MemoryMax=200M -p RuntimeMaxSec=120 \
      -E PYTHONDONTWRITEBYTECODE=1 "$IMPORT_PY" -c \
      "import live_v6.runner, live_v6.tgcmd, live_v6.engine as e, inspect; s=inspect.getsource(e.V6Engine.tick); assert 'self.on_bar_close()' in s; print('import ok, tick calls on_bar_close')" \
      || die "import check failed — nothing changed" 8
    log "import check OK for $SHA (user=$IMPORT_USER, sandbox: no network, denied: $SANDBOX_DENY)"
    # 3. pre-checks (planned restart)
    wait_window
    check_stop_timeout
    verify_stops || die "stops NOT verified for every open position — deploy ABORTED before restart (nothing changed)" 5
    if [ $DRY = 1 ]; then
      log "DRY-RUN would: wait for no in-flight intents, back up $STATE → $BACKUP_DIR/, install $APP/$SHA, swap current → $SHA, systemctl restart $UNIT, strict verify, write $MARK; on failure: rollback to $(verified_target "$CUR" | sed 's/^$/<none: stop + alert>/') without waiting"
      exit 0
    fi
    wait_no_intents || die "in-flight intents did not clear — deploy refused before restart (nothing changed)" 11
    # 4. backup + install (root-owned, read-only for the bot)
    mkdir -p "$BACKUP_DIR" "$APP"
    [ -f "$STATE" ] && cp -p "$STATE" "$BACKUP_DIR/$(basename "$STATE").bak-$(date -u +%Y%m%dT%H%M%SZ)-pre-${SHA:0:12}" && log "state backed up"
    find "$BACKUP_DIR" -maxdepth 1 -type f -printf '%T@ %p\n' | sort -rn | tail -n +31 | cut -d' ' -f2- | xargs -r rm -f
    if [ ! -f "$APP/$SHA/.ci_complete" ]; then
      rm -rf "${APP:?}/$SHA.tmp"; mkdir -p "$APP/$SHA.tmp"; cp -a "$STAGE/." "$APP/$SHA.tmp/"
      rm -f "$APP/$SHA.tmp/$MARK"; echo "$SHA" > "$APP/$SHA.tmp/.ci_complete"
      chown -R root:root "$APP/$SHA.tmp"; chmod -R u=rwX,go=rX "$APP/$SHA.tmp"
      rm -rf "${APP:?}/${SHA:?}"; mv -T "$APP/$SHA.tmp" "$APP/$SHA"
      log "installed $APP/$SHA"
    else
      log "$APP/$SHA already installed (reusing; marker $(marker_ok "$SHA" && echo present || echo absent))"
    fi
    [ "$CUR" != none ] && echo "$CUR" > "$APP/PREVIOUS"     # informational only — rollback uses the marker
    # 5. swap + restart + strict verify
    swap_to "$SHA"
    if restart_and_verify "$SIM_FAIL"; then
      write_marker "$SHA" "$SHA" "$VERIFIED_MSG"
      rm -f "$APP/CI_HALTED"
      log "DEPLOYED $SHA (previous: $CUR). Heartbeat script NOT changed (manual step, runbook §5)."
      exit 0
    fi
    # 6. failure → act immediately (TA E): rollback to a marked release, else stop + alert (TA H)
    log "post-restart verification FAILED for $SHA — reacting now (no window wait)"
    do_rollback "verification failed for $SHA" 1 "$SHA"
    alert_fail "deploy of $SHA failed verification; rolled back to $(current_dir) (verified)" || true
    die "deploy of $SHA failed; rolled back to $(current_dir)" 9 ;;
  *) die "unknown action" 2 ;;
esac
