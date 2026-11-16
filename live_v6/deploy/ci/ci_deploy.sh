#!/bin/bash
# CI deploy / rollback for live_v6 on the VPS (runs as root) — v2, strategy-agnostic.
# Installed ONCE, by hand, to /opt/tradebot/ci/ci_deploy.sh (root:root 0755) — a deploy never replaces this script,
# ci_job.sh or the entry wrapper (no self-update from pushed code; see INSTALL_CI_V2.md).
# Runs DETACHED from any SSH session: ci_deploy_entry.sh → ci_job.sh start → systemd-run --collect → ci_job.sh run →
# this script, output to a job log file only. The CI client (gh_ssh_deploy.sh) polls `job <id>`.
#
#   ci_deploy.sh deploy   <live|testnet> <sha40> <tarfile> [--dry-run]
#   ci_deploy.sh rollback <live|testnet> [--dry-run]
#   ci_deploy.sh status   <live|testnet>
#   ci_deploy.sh confirm  <live|testnet>          (root timer tradebot-ci-confirm.timer, every 5 min)
#   ci_deploy.sh adopt    <live|testnet> <sha40>  (ops by hand only — NOT reachable through the SSH entry: mark the
#                                                  running, hand-deployed release as a rollback target)
#
# v2 (2026-11-16) vs v1 (origin/ci-deploy, H7-T 4h era): no 4h restart window, no last_bar_close / 6-coin checks, no
# ta-pass tag gate (a merge to main is the approval). A planned restart only happens while the bot has NO in-flight
# entry intent (incl. a resting post-only entry); verification is "unit up, stable, state rewritten, meta.health ok,
# clean journal, every open position has an exchange stop". The rollback marker is granted 30 min after the restart.
#
# Safety:
#  1. never places orders, never flattens, never touches exchange stops: it only swaps a symlink and runs
#     systemctl restart / stop on the target unit;
#  2. a planned restart (deploy, manual rollback) waits until state.intents is empty (an entry in flight or a post-only
#     entry still resting), else refuses — nothing changed. The automatic reaction to a failed deploy never waits;
#  3. exchange stops must cover every open position (verify-stops exit 0) right BEFORE a restart and BEFORE a rollback;
#  4. the bot must be running and healthy before a deploy (fresh meta.health.ok, or a persisted halt with no other
#     block); a stopped / unhealthy bot is never restarted by CI — nothing changed (exit 15);
#  5. rollback ONLY to a release carrying the v2 marker (live: .ci_verified, testnet: .citest_verified_v2) for the SAME
#     strategy the unit runs. A deploy that passes verification gets <marker>.pending; `confirm` (timer) grants the
#     marker 30 min after the restart if the same process is still up, healthy, clean and protected. Old v1 markers
#     (.ta_pass_verified — H7-T code) are never rollback targets;
#  6. rollback fails / no marked release / stops not verified → systemctl stop + CI_HALTED + Telegram + Healthchecks
#     /fail + non-zero exit. Stopping the bot leaves exchange stops in place; nothing is closed;
#  7. Telegram (live only; token from /etc/tradebot/telegram.env, never printed, never in argv) on every deploy result.
#
# Exit codes: 0 ok · 2 usage/archive · 4 manual rollback: no target · 5 stops not verified · 6 rollback not verified
#   (stopped) · 7 lock busy · 8 import check · 9 deploy failed, rolled back · 10 no rollback target (stopped) ·
#   11 intents did not clear · 12 TimeoutStopSec · 13 CI_HALTED · 14 confirm failed · 15 bot not running / unhealthy
#
# Test harness only: CI_ROOT=<dir> prefixes every path and CI_TEST_BIN=<dir> is put first on PATH (fake systemctl,
# journalctl, curl, …). Neither can reach a CI run: the SSH entry passes no environment and ci_job.sh starts this
# script through systemd-run with a clean one.
set -euo pipefail
umask 022

R=${CI_ROOT:-}
if [ -n "$R" ]; then
  [ "$R" != / ] && [ -d "$R" ] && [ -d "${CI_TEST_BIN:-}" ] || { echo "CI_ROOT / CI_TEST_BIN invalid (test harness only)" >&2; exit 2; }
  export PATH="$CI_TEST_BIN:$PATH"
else
  export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  [ "$(id -u)" = 0 ] || { echo "must run as root" >&2; exit 2; }
fi

ACTION=${1:-}; TARGET=${2:-}
DRY=0; for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done
VERIFY_TIMEOUT=${CI_VERIFY_TIMEOUT:-360}    # s: unit up + state rewritten (1m strategies save at every bar) + health ok
POLL_S=${CI_POLL_S:-10}
STABLE_S=${CI_STABLE_S:-45}                 # s: same MainPID / NRestarts after verification (no restart loop)
INTENT_WAIT=${CI_INTENT_WAIT:-30}           # s between intent checks
INTENT_TRIES=${CI_INTENT_TRIES:-12}         # 12 × 30 s = 6 min ≥ post-only entry timeout (300 s default)
HEALTH_MAX_AGE=${CI_HEALTH_MAX_AGE:-300}    # s: meta.health at most this old (pre-check, confirm; = heartbeat_ping MAX_AGE)
CONFIRM_AFTER=${CI_CONFIRM_AFTER:-1800}     # s after the restart: confirm grants the rollback marker
CONFIRM_DEADLINE=${CI_CONFIRM_DEADLINE:-3600}   # s after the restart: soft confirm failures are retried until then
MIN_STOP_TIMEOUT_S=20                       # the unit's TimeoutStopSec must leave the runner time to finish
SIM_FAIL=${CI_SIMULATE_VERIFY_FAIL:-0}            # testnet drill: post-restart verification of the deploy fails
SIM_STOPS=${CI_SIMULATE_STOPS_FAIL:-0}            # testnet drill: verify-stops reports "unprotected"
SIM_RB_FAIL=${CI_SIMULATE_ROLLBACK_VERIFY_FAIL:-0} # testnet drill: verification of the rollback fails
STAGE_ROOT=$R/var/lib/tradebot-ci/stage
LOCK=$R/run/tradebot-ci.lock
SANDBOX_DENY="-/etc/tradebot -/var/lib/live_v6-live -/opt/tradebot/app -/var/log/tradebot -/root -/var/lib/tradebot-ci/uploads"

case "$TARGET" in
  live)
    APP=$R/opt/tradebot/app; UNIT=live_v6-live; STATE=$R/var/lib/live_v6-live/mainnet.json
    STOPS_CMD=(python3 "$R/opt/tradebot/verify_stops_live.py"); STOPS_ENV=""
    MARK=.ci_verified; REVOKED=.ci_revoked
    ALERT_ENV=$R/etc/tradebot/heartbeat.env; TG_ENV=$R/etc/tradebot/telegram.env
    IMPORT_USER=tradebot; IMPORT_PY=/opt/tradebot/.venv/bin/python
    BACKUP_DIR=$R/root/ci-backups/live ;;
  testnet)
    APP=$R/opt/tradebot-ci-testnet/app; UNIT=live_v6-citest; STATE=$R/var/lib/live_v6-citest/testnet.json
    STOPS_CMD=(python3 "$R/opt/tradebot/ci/verify_stops_testnet.py"); STOPS_ENV=$R/etc/tradebot/citest.env
    MARK=.citest_verified_v2; REVOKED=.citest_revoked_v2
    ALERT_ENV=$R/etc/tradebot/ci-alert-testnet.env; TG_ENV=""     # DUMMY Healthchecks URL; no Telegram for testnet
    IMPORT_USER=tradebot-ci; IMPORT_PY=/opt/tradebot-ci-testnet/.venv/bin/python
    SANDBOX_DENY="$SANDBOX_DENY -/opt/tradebot"
    BACKUP_DIR=$R/root/ci-backups/testnet ;;
  *) echo "usage: $0 deploy|rollback|status|confirm|adopt live|testnet [sha40 [tarfile]] [--dry-run]" >&2; exit 2 ;;
esac
if [ "$SIM_FAIL$SIM_STOPS$SIM_RB_FAIL" != 000 ] && [ "$TARGET" != testnet ]; then echo "CI_SIMULATE_* drills are testnet-only" >&2; exit 2; fi

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] [$TARGET] $*"; }
die() { log "FAIL: $1"; exit "${2:-1}"; }
now_s() { date -u +%s; }
now_ms() { python3 -c 'import time; print(int(time.time() * 1000))'; }
mtime() { python3 -c 'import os,sys; print(int(os.stat(sys.argv[1]).st_mtime))' "$1" 2>/dev/null || echo 0; }
owner_ok() {      # root-owned (test harness: owned by the test user)
  local want=0; [ -n "$R" ] && want=$(id -u)
  [ "$(python3 -c 'import os,sys; print(os.stat(sys.argv[1]).st_uid)' "$1")" = "$want" ]
}
replace() { python3 -c 'import os,sys; os.replace(sys.argv[1], sys.argv[2])' "$1" "$2"; }   # atomic rename (also a symlink)
env_get() {       # $1 = env file, $2 = VAR → value (last assignment; surrounding quotes stripped). Never logged.
  [ -r "$1" ] || return 0
  sed -nE "s/^[[:space:]]*(export[[:space:]]+)?$2=//p" "$1" | tail -1 | sed -E "s/^[\"'](.*)[\"'][[:space:]]*$/\1/"
}

# ── notifications ───────────────────────────────────────────────────────────────────────────────────────────────────
tg_send() {       # $1 = text. Live only. Token / chat id from $TG_ENV; the token goes to curl via stdin (-K -), so it is
  local tok chat msg   # never in argv, the job log or GitHub.
  [ -n "$TG_ENV" ] || { log "telegram: off for $TARGET (log only)"; return 0; }
  tok=$(env_get "$TG_ENV" TELEGRAM_BOT_TOKEN); chat=$(env_get "$TG_ENV" TELEGRAM_CHAT_ID)
  [ -n "$tok" ] && [ -n "$chat" ] || { log "telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing in $TG_ENV — NOT sent"; return 1; }
  msg=$(python3 -c 'import sys; print(sys.argv[1][:3500])' "$1")
  if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$tok" \
       | curl -fsS -m 10 --retry 2 -o /dev/null -K - --data-urlencode "chat_id=$chat" --data-urlencode "text=$msg" 2>/dev/null; then
    log "telegram: sent"
  else
    log "telegram: send FAILED"; return 1
  fi
}

alert_fail() {    # Healthchecks /fail with a reason (URL from $ALERT_ENV, never printed / never in argv).
  local url; url=$(env_get "$ALERT_ENV" HEARTBEAT_URL)
  [ -n "$url" ] || { log "ALERT: no HEARTBEAT_URL in $ALERT_ENV — Healthchecks /fail NOT sent"; return 1; }
  if printf 'url = "%s/fail"\n' "$url" | curl -fsS -m 10 --retry 3 -o /dev/null -K - --data-raw "ci-deploy[$TARGET]: $1" 2>/dev/null; then
    log "ALERT: Healthchecks /fail sent"
  else
    log "ALERT: Healthchecks /fail could NOT be sent"; return 1
  fi
}

# ── releases ───────────────────────────────────────────────────────────────────────────────────────────────────────
# Releases live in $APP/<sha40> (older hand-deployed ones: 7-char names). Full sha from .ci_complete or the marker.
current_dir() { if [ -L "$APP/current" ]; then basename "$(readlink "$APP/current")"; else echo none; fi; }
release_sha() {   # $1 = dir name → full sha if known, else the dir name
  local d=$APP/$1 s=""
  [ -f "$d/.ci_complete" ] && s=$(head -1 "$d/.ci_complete")
  [ -z "$s" ] && [ -f "$d/$MARK" ] && s=$(sed -n 's/^sha=//p' "$d/$MARK" | head -1)
  [[ "$s" =~ ^[0-9a-f]{40}$ ]] && echo "$s" || echo "$1"
}
marker_ok() {     # $1 = dir: marker present, root-owned, sha matches the dir, not revoked; $2 (optional) = strategy
  local d=$APP/$1 s st
  [ -e "$d/$REVOKED" ] && return 1
  [ -f "$d/$MARK" ] && owner_ok "$d/$MARK" || return 1
  s=$(sed -n 's/^sha=//p' "$d/$MARK" | head -1)
  [[ "$s" =~ ^[0-9a-f]{40}$ ]] && [[ "$s" == "$1"* ]] || return 1
  [ -z "${2:-}" ] && return 0
  st=$(sed -n 's/^strategy=//p' "$d/$MARK" | head -1)
  [ "$st" = "$2" ]
}
verified_target() {   # $1 = dir to exclude, $2 = strategy → newest release with a valid marker for that strategy
  local d best="" bt="" t
  for d in "$APP"/*/; do
    [ -d "$d" ] || continue
    [ -L "${d%/}" ] && continue   # never the `current` symlink itself
    d=$(basename "$d"); [ "$d" = "$1" ] && continue
    [ "$(release_sha "$d")" = "$(release_sha "$1")" ] && continue
    marker_ok "$d" "$2" || continue
    t=$(sed -n 's/^verified_at_utc=//p' "$APP/$d/$MARK" | head -1)
    if [ -z "$best" ] || [[ "$t" > "$bt" ]]; then best=$d; bt=$t; fi
  done
  echo "$best"
}
write_kv_file() {   # $1 = path; stdin = content → root-owned 0644, atomic
  cat > "$1.tmp"; chown root:root "$1.tmp"; chmod 644 "$1.tmp"; replace "$1.tmp" "$1"
}
revoke_marker() {   # $1 = dir, $2 = reason. Marker moved aside; only a fresh verified deploy marks it again.
  local d=$APP/$1 now; now=$(date -u +%Y%m%dT%H%M%SZ)
  [ -d "$d" ] || return 0
  [ -f "$d/$MARK" ] && mv -f "$d/$MARK" "$d/$MARK.revoked-$now"
  rm -f "$d/$MARK.pending"
  echo "$(ts) $2" >> "$d/$REVOKED"; chown root:root "$d/$REVOKED"; chmod 644 "$d/$REVOKED"
  log "marker of $1 REVOKED ($REVOKED: $2)"
}
write_marker() {    # $1 = dir, $2 = sha40, $3 = strategy, $4 = how (one line)
  printf 'sha=%s\ntarget=%s\nstrategy=%s\nverified_at_utc=%s\nverified_by=%s\n' "$2" "$TARGET" "$3" "$(ts)" "$4" \
    | write_kv_file "$APP/$1/$MARK"
  if [ -f "$APP/$1/$REVOKED" ]; then mv -f "$APP/$1/$REVOKED" "$APP/$1/$REVOKED.cleared-$(date -u +%Y%m%dT%H%M%SZ)"; fi
  log "marker $MARK written for $1 (strategy=$3; $4)"
}
write_pending() {   # $1 = dir, $2 = sha40, $3 = strategy, $4 = pre-restart halt (one line), $5 = summary
  printf 'sha=%s\ntarget=%s\nstrategy=%s\nverified_at_utc=%s\nrestart_epoch=%s\npid=%s\nnrestarts=%s\npre_halted=%s\nsummary=%s\n' \
    "$2" "$TARGET" "$3" "$(ts)" "$RESTART_T0" "$(main_pid)" "$(restarts)" "$4" "$5" | write_kv_file "$APP/$1/$MARK.pending"
  log "marker PENDING for $1: $MARK is granted by the confirm timer ≥ ${CONFIRM_AFTER}s after the restart if the same process is still healthy; rollback target meanwhile: $(verified_target "$1" "$3" | sed 's/^$/none/')"
}

# ── unit / state ──────────────────────────────────────────────────────────────────────────────────────────────────
unit_active() { [ "$(systemctl is-active "$UNIT" 2>/dev/null || true)" = active ]; }
main_pid() { systemctl show "$UNIT" -p MainPID --value 2>/dev/null || echo 0; }
restarts() { systemctl show "$UNIT" -p NRestarts --value 2>/dev/null || echo 0; }

unit_strategy() {   # LIVE_V6_STRATEGY of the running process (/proc/<pid>/environ), else of the unit config; runner default qrmtf
  local pid v="" f
  pid=$(main_pid)
  if [ "${pid:-0}" -gt 0 ] && [ -r "$R/proc/$pid/environ" ]; then
    v=$(tr '\0' '\n' < "$R/proc/$pid/environ" | sed -n 's/^LIVE_V6_STRATEGY=//p' | tail -1)
  fi
  if [ -z "$v" ]; then
    v=$(systemctl show "$UNIT" -p Environment --value 2>/dev/null | tr ' ' '\n' | sed -n 's/^LIVE_V6_STRATEGY=//p' | tail -1)
    for f in $(systemctl show "$UNIT" -p EnvironmentFiles --value 2>/dev/null | grep -oE '/[^ ]+' || true); do
      local x; x=$(env_get "$R$f" LIVE_V6_STRATEGY); [ -n "$x" ] && v=$x   # EnvironmentFile= wins over Environment=
    done
  fi
  v=${v:-qrmtf}
  [[ "$v" =~ ^[a-z0-9_]+$ ]] || { echo "invalid"; return 1; }
  echo "$v"
}

state_counts() {    # → "intents=<n> postonly_pending=<n>" ; n=-1 if the state is unreadable
  python3 - "$STATE" <<'PY'
import json, sys
try:
    it = json.load(open(sys.argv[1])).get("intents") or {}
    print("intents=%d postonly_pending=%d" % (len(it), sum(1 for v in it.values() if isinstance(v, dict) and v.get("pending"))))
except FileNotFoundError:
    print("intents=0 postonly_pending=0")
except Exception:
    print("intents=-1 postonly_pending=-1")
PY
}

meta_halted() {     # current meta.halted as one line ("" if none)
  python3 - "$STATE" <<'PY' 2>/dev/null || true
import json, sys
try:
    print(str((json.load(open(sys.argv[1])).get("meta") or {}).get("halted") or "").replace("\n", " "))
except Exception:
    print("")
PY
}

state_check() {     # $1 = epoch ms right after `systemctl restart` returned (the old process is gone by then; 0 = no
  # "written by the new process" check): state file AND meta.health must be newer than that; $2 = halt accepted (one line, "" = none),
  # $3 = max health age in s (0 = no freshness check). Healthy = meta.health.ok; OR the bot sits in the SAME persisted
  # halt as before the restart (daily loss / manual halt → healthy() is false by design) with no block at all.
  python3 - "$STATE" "$1" "$2" "$3" <<'PY'
import json, os, sys, time
st, t1, pre_halt, max_age = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
try:
    if t1 and os.stat(st).st_mtime * 1000 <= t1:
        print("state not rewritten since restart"); sys.exit(1)
    d = json.load(open(st)); m = d.get("meta") or {}
except Exception as e:
    print("state unreadable:", type(e).__name__); sys.exit(1)
h = m.get("health")
if not isinstance(h, dict):
    print("meta.health missing"); sys.exit(1)
ht = int(h.get("t") or 0)
if t1 and ht <= t1:
    print("meta.health older than restart"); sys.exit(1)
if max_age and time.time() * 1000 - ht > max_age * 1000:
    print("meta.health stale (%ds)" % ((time.time() * 1000 - ht) // 1000)); sys.exit(1)
halted = str(m.get("halted") or "").replace("\n", " ")
blocks = h.get("blocks") or []
info = "positions=%d intents=%d" % (len(d.get("pos") or {}), len(d.get("intents") or {}))
if h.get("ok"):
    print("health ok, " + info); sys.exit(0)
if halted and halted == pre_halt and not blocks:
    print("health: same halt as before the restart (%s), no block, %s" % (halted[:80], info)); sys.exit(0)
print("meta.health.ok=false blocks=%s halted=%s" % (blocks, halted[:80] or "-")); sys.exit(1)
PY
}

journal_clean() {   # $1 = since epoch, $2 = MainPID (only THIS process' lines: a traceback of the release being replaced,
  local out bad      # e.g. while it shuts down, must not fail its successor), $3 = pattern (default Traceback|CRITICAL)
  out=$(journalctl -u "$UNIT" "_PID=$2" --since "@$1" --no-pager -o cat 2>/dev/null) || { log "journalctl failed — journal NOT verified"; return 1; }
  bad=$(printf '%s\n' "$out" | grep -E "${3:-Traceback|CRITICAL}" | head -5 || true)
  [ -z "$bad" ] && return 0
  log "journal problems (PID $2) since $1:"; printf '%s\n' "$bad" | cut -c1-300; return 1
}

verify_stops() {    # exit 0 = every open position has a protective exchange stop. Read-only signed GETs; output summarised.
  local out rc
  if [ -n "$STOPS_ENV" ]; then
    out=$( (set -a; . "$STOPS_ENV"; set +a; "${STOPS_CMD[@]}") 2>&1 ) && rc=0 || rc=$?
  else
    out=$("${STOPS_CMD[@]}" 2>&1) && rc=0 || rc=$?
  fi
  printf '%s\n' "$out" | python3 -c '
import json,sys
t=sys.stdin.read()
try:
    d=json.loads(t[t.index("{"):])
    pos=d.get("positions") or []
    print("  verify-stops: pass=%s positions=%d %s%s" % (d.get("pass"), len(pos), [(p.get("symbol"), p.get("positionAmt"), p.get("protected")) for p in pos], (" error=" + d["error"]) if d.get("error") else ""))
except Exception:
    print("  verify-stops: unparseable output (%d bytes)" % len(t))' || true
  [ "$SIM_STOPS" = 1 ] && { log "SIMULATED: verify-stops reports an unprotected position (testnet drill)"; rc=1; }
  log "verify-stops exit=$rc"
  return $rc
}

wait_quiet() {      # planned restarts only: no entry in flight (state.intents empty — this includes resting post-only entries)
  local i c
  for i in $(seq 1 "$INTENT_TRIES"); do
    c=$(state_counts)
    [ "$c" = "intents=0 postonly_pending=0" ] && { log "state: no in-flight entry ($c)"; return 0; }
    log "state: entry in flight ($c; -1 = unreadable) — waiting ${INTENT_WAIT}s ($i/$INTENT_TRIES)"
    sleep "$INTENT_WAIT"
  done
  return 1
}

check_stop_timeout() {
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

restart_and_verify() {   # $1 = simulate failure (0/1), $2 = halt accepted after the restart. Same checks for deploy AND rollback.
  local sim=$1 halt=$2 t0 t1 r0 pid pid0 i tries msg=""
  pid0=$(main_pid); t0=$(now_s)
  systemctl restart "$UNIT" || { log "systemctl restart $UNIT FAILED"; return 1; }   # (errexit is off here: caller's if)
  t1=$(now_ms); RESTART_T0=$(now_s)    # confirm counts its 30 min from here (after the old process is gone)
  r0=$(restarts); tries=$(( VERIFY_TIMEOUT / POLL_S )); [ "$tries" -ge 1 ] || tries=1
  log "restarted $UNIT; verifying (≤${VERIFY_TIMEOUT}s: active, state rewritten, meta.health)"
  for i in $(seq 1 "$tries"); do
    sleep "$POLL_S"
    if unit_active && msg=$(state_check "$t1" "$halt" 0); then log "  state: $msg"; break; fi
    log "  waiting ($i/$tries): unit=$(systemctl is-active "$UNIT" 2>/dev/null || true) ${msg:-}"
    [ "$i" -lt "$tries" ] || { log "verification timeout"; return 1; }
  done
  pid=$(main_pid)
  [ "$pid" != 0 ] && [ "$pid" != "$pid0" ] || { log "MainPID did not change across the restart ($pid0 → $pid)"; return 1; }
  sleep "$STABLE_S"
  unit_active || { log "unit not active after ${STABLE_S}s"; return 1; }
  [ "$(restarts)" = "$r0" ] && [ "$(main_pid)" = "$pid" ] || { log "restart loop detected (NRestarts / MainPID changed within ${STABLE_S}s)"; return 1; }
  msg=$(state_check "$t1" "$halt" 0) || { log "state after ${STABLE_S}s: $msg"; return 1; }
  journal_clean "$t0" "$pid" || return 1
  verify_stops || { log "stops not verified after restart"; return 1; }
  [ "$sim" = 1 ] && { log "SIMULATED verification failure (testnet drill)"; return 1; }
  VERIFIED_MSG=$msg
  log "verification PASSED ($msg)"
}

swap_to() {   # $1 = release dir name; returns ≠0 if the symlink could not be swapped
  CHANGED=1
  ln -sfn "$APP/$1" "$APP/current.new" || return 1
  replace "$APP/current.new" "$APP/current" || return 1
  [ "$(current_dir)" = "$1" ] || return 1
  echo "$1" > "$APP/DEPLOYED"
  log "symlink current → $1"
}

stop_and_alert() {   # $1 = reason, $2 = exit code. Never touches exchange stops / positions.
  log "STOPPING $UNIT — reason: $1 (exchange stops stay in place; nothing is closed or cancelled)"
  verify_stops || log "NOTE: verify-stops ≠ 0 while stopping — check exchange stops by hand"
  local state head="봇 정지" halted_file=ok
  echo "$(ts) $1" > "$APP/CI_HALTED" || halted_file=FAILED   # ExecStartPre of the unit refuses to start while this exists
  # (also after a reboot); only ops removes it, by hand. CI never deletes it. Written BEFORE the stop: Restart=always
  # must not bring the unit back.
  systemctl stop "$UNIT" || { log "systemctl stop failed — retrying once"; sleep 5; systemctl stop "$UNIT" || true; }
  state=$(systemctl is-active "$UNIT" 2>/dev/null || true)
  log "unit $UNIT is now: $state (CI_HALTED file: $halted_file)"
  [ "$state" = active ] && head="봇 정지 실패 — 아직 동작 중, 즉시 수동 정지 필요(sudo systemctl stop $UNIT)"
  tg_send "🚨 [CI 배포·$TARGET] $head — $1
포지션·거래소 손절은 그대로 둠(정리·취소 안 함). CI_HALTED 기록: $halted_file
조치: ssh ops@VPS → 원인 확인 → INSTALL_CI_V2.md §7 (CI_HALTED 해제는 사람이)" || true
  alert_fail "$1 — $UNIT stop requested (now: $state), manual action required" || true
  ALERTED=1
  die "$1 — $UNIT stop requested (now: $state)" "$2"
}

do_rollback() {    # $1 = reason, $2 = auto(1: failure path, no waiting) / manual(0), $3 = dir to exclude, $4 = strategy,
  local reason=$1 auto=$2 bad=$3 strat=$4 halt=$5 prev     # $5 = halt accepted after the restart
  SIM_FAIL=0
  prev=$(verified_target "$bad" "$strat")
  log "rollback candidates: $MARK releases for strategy $strat other than $bad → ${prev:-none}"
  if [ -z "$prev" ]; then
    [ "$auto" = 1 ] && stop_and_alert "no $MARK release (strategy $strat) to roll back to ($reason)" 10
    die "no $MARK release (strategy $strat) to roll back to — manual rollback refused, nothing changed" 4
  fi
  log "ROLLBACK to $prev ($(release_sha "$prev")) (reason: $reason)"
  if [ "$auto" != 1 ]; then
    [ $DRY = 1 ] && log "DRY-RUN: entry-in-flight check now: $(state_counts)" || \
      wait_quiet || die "an entry stayed in flight — manual rollback refused, nothing changed" 11
  fi
  if ! verify_stops; then
    [ "$auto" = 1 ] && stop_and_alert "stops NOT verified before rollback ($reason)" 5
    die "stops NOT verified — manual rollback ABORTED, nothing changed" 5
  fi
  [ $DRY = 1 ] && { log "DRY-RUN: would swap current → $prev and restart $UNIT (verify)"; return 0; }
  swap_to "$prev" || stop_and_alert "symlink swap to $prev failed during rollback ($reason)" 6
  echo "$bad" > "$APP/PREVIOUS"
  if restart_and_verify "$SIM_RB_FAIL" "$halt"; then
    log "rollback to $prev verified"
  else
    revoke_marker "$prev" "rollback target failed its own verification ($reason)" || log "could not revoke the marker of $prev"
    stop_and_alert "rollback to $prev did NOT verify ($reason)" 6
  fi
}

halted_guard() {   # after stop_and_alert the unit stays down until ops clears CI_HALTED by hand
  [ -e "$APP/CI_HALTED" ] || return 0
  die "CI_HALTED present ($(cat "$APP/CI_HALTED")) — refusing; ops must investigate and remove $APP/CI_HALTED by hand" 13
}

refuse() {         # $1 = reason, $2 = exit code — a deploy that changed NOTHING (bot keeps running the old release)
  [ $DRY = 1 ] || tg_send "⏸ [CI 배포·$TARGET] 배포 보류 — ${SHA:0:12}
사유: $1
봇은 기존 릴리스($CUR)로 그대로 동작 중. 원인 해소 뒤 GitHub Actions 에서 재실행." || true
  die "$1 — deploy refused, nothing changed" "$2"
}

release_notes() {  # $1 = staged tree → sanitised commit list (≤ 30 lines × 120 chars) from live_v6/.ci_release_notes
  python3 - "$1/live_v6/.ci_release_notes" <<'PY' 2>/dev/null || true
import sys
try:
    raw = open(sys.argv[1], encoding="utf-8", errors="replace").read(20000)
except OSError:
    sys.exit(0)
lines = ["".join(c for c in l if c.isprintable())[:120] for l in raw.splitlines() if l.strip()]
print("\n".join("- " + l for l in lines[:30]) + ("\n… (+%d)" % (len(lines) - 30) if len(lines) > 30 else ""))
PY
}

CHANGED=0; ALERTED=0; STAGE=""
on_exit() {        # safety net: an unexpected exit (set -e) after the release was swapped must never go unnoticed
  local rc=$?
  [ -n "$STAGE" ] && rm -rf "$STAGE"
  if [ "$rc" -ne 0 ] && [ "$CHANGED" = 1 ] && [ "$ALERTED" = 0 ]; then
    ALERTED=1
    log "UNEXPECTED exit rc=$rc after the release was changed (current=$(current_dir), unit=$(systemctl is-active "$UNIT" 2>/dev/null || true)) — alerting"
    tg_send "🚨 [CI 배포·$TARGET] 배포 스크립트 비정상 종료(rc=$rc) — 현재 릴리스 $(current_dir | cut -c1-12), 유닛 $(systemctl is-active "$UNIT" 2>/dev/null || true)
사람 확인 필요(/var/log/tradebot/ci-jobs/). 포지션·거래소 손절은 건드리지 않음." || true
    alert_fail "ci_deploy.sh exited rc=$rc unexpectedly after changing the release" || true
  fi
  exit "$rc"
}
trap on_exit EXIT

mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
if [ "$ACTION" = confirm ]; then flock -w 1200 9 || die "confirm: lock busy for 20 min" 7; else flock -n 9 || die "another CI job is running" 7; fi
log "action=$ACTION dry_run=$DRY current=$(current_dir) unit=$(systemctl is-active "$UNIT" 2>/dev/null || true)"

case "$ACTION" in
  status)
    cur=$(current_dir); strat=$(unit_strategy || true)
    log "current=$cur sha=$(release_sha "$cur") strategy=$strat marker=$(marker_ok "$cur" && echo yes || { [ -f "$APP/$cur/$MARK.pending" ] && echo pending || echo no; }) rollback_target=$(verified_target "$cur" "$strat" | sed 's/^$/none/') $(state_counts) halted=$(meta_halted | cut -c1-80)"
    for d in "$APP"/*/; do [ -d "$d" ] || continue; [ -L "${d%/}" ] && continue; [ -f "$d/$REVOKED" ] && log "revoked: $(basename "$d") — $(tail -1 "$d/$REVOKED")"; done
    [ -f "$APP/CI_HALTED" ] && log "CI_HALTED: $(cat "$APP/CI_HALTED")"
    verify_stops || true
    state_check 0 "$(meta_halted)" "$HEALTH_MAX_AGE" || true ;;

  confirm)   # timer, every 5 min: grant the marker ≥ CONFIRM_AFTER s after the restart (same process, healthy, clean, protected)
    cur=$(current_dir)
    for d in "$APP"/*/; do [ -d "$d" ] || continue; [ -L "${d%/}" ] && continue; d=$(basename "$d")
      [ "$d" != "$cur" ] && [ -f "$APP/$d/$MARK.pending" ] && { rm -f "$APP/$d/$MARK.pending"; log "stale pending marker of $d removed (not current)"; }
    done
    f=$APP/$cur/$MARK.pending
    [ -f "$f" ] || { log "confirm: nothing pending (current=$cur marker=$(marker_ok "$cur" && echo yes || echo no))"; exit 0; }
    t0=$(sed -n 's/^restart_epoch=//p' "$f"); pid=$(sed -n 's/^pid=//p' "$f"); nr=$(sed -n 's/^nrestarts=//p' "$f")
    strat=$(sed -n 's/^strategy=//p' "$f"); halt=$(sed -n 's/^pre_halted=//p' "$f"); sha=$(sed -n 's/^sha=//p' "$f")
    age=$(( $(now_s) - t0 ))
    [ "$age" -ge "$CONFIRM_AFTER" ] || { log "confirm: $cur pending — ${age}s since the restart (< ${CONFIRM_AFTER}s)"; exit 0; }
    hard=""     # the deployed process itself went wrong → revoke now
    unit_active || hard="unit not active"
    [ -z "$hard" ] && [ "$(main_pid)" != "$pid" ] && hard="process changed since the deploy (MainPID $pid → $(main_pid))"
    [ -z "$hard" ] && [ "$(restarts)" != "$nr" ] && hard="unit restarted since the deploy (NRestarts $nr → $(restarts))"
    [ -z "$hard" ] && { journal_clean "$t0" "$pid" "Traceback" || hard="Traceback in the journal since the restart"; }
    soft=""     # may be momentary (stream reconnect, stop being replaced) → retried until CONFIRM_DEADLINE
    if [ -z "$hard" ]; then
      msg=$(state_check 0 "$halt" "$HEALTH_MAX_AGE") || soft="$msg"
      [ -z "$soft" ] && { verify_stops || soft="stops not verified"; }
    fi
    if [ -z "$hard" ] && [ -n "$soft" ] && [ "$age" -lt "$CONFIRM_DEADLINE" ]; then
      log "confirm: $cur not yet ($soft) — retrying on the next timer run (deadline ${CONFIRM_DEADLINE}s after the restart)"; exit 0
    fi
    why=${hard:-$soft}
    if [ -n "$why" ]; then
      revoke_marker "$cur" "confirm ${age}s after the restart failed: $why"
      tg_send "⚠️ [CI 배포·$TARGET] ${cur:0:12} 30분 확인 실패 — $why
봇은 정지하지 않음(이 확인은 롤백 기준 등록만 결정). 롤백 기준은 계속 $(verified_target "$cur" "$strat" | sed 's/^$/없음/' | cut -c1-12).
확인 권장: journalctl -u $UNIT" || true
      alert_fail "release $cur did NOT earn $MARK: $why (bot not stopped by confirm)" || true
      die "confirm: $cur NOT marked — $why" 14
    fi
    crit=$(journalctl -u "$UNIT" "_PID=$pid" --since "@$t0" --no-pager -o cat 2>/dev/null | grep -c CRITICAL || true)
    write_marker "$cur" "$sha" "$strat" "ci_deploy.sh confirm ${age}s after restart, PID $pid, $msg, journal CRITICAL lines=${crit:-0}"
    rm -f "$f"
    tg_send "✅ [CI 배포·$TARGET] ${cur:0:12} 재시작 30분 확인 통과 — 이제 이 릴리스가 롤백 기준" || true
    log "confirm: $cur now carries $MARK" ;;

  adopt)     # ops by hand: mark the RUNNING hand-deployed release as a rollback target (same checks as confirm)
    SHA=${3:-}
    [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "usage: adopt <target> <sha40 of the running release>" 2
    halted_guard
    cur=$(current_dir)
    [ "$cur" != none ] && [[ "$SHA" == "$cur"* ]] || die "current release dir '$cur' does not match $SHA" 2
    unit_active || die "unit $UNIT not active" 15
    strat=$(unit_strategy) || die "LIVE_V6_STRATEGY of $UNIT is invalid" 2
    since=$(( $(now_s) - CONFIRM_AFTER ))
    journal_clean "$since" "$(main_pid)" "Traceback" || die "Traceback in the journal within ${CONFIRM_AFTER}s — not adopting" 14
    msg=$(state_check 0 "$(meta_halted)" "$HEALTH_MAX_AGE") || die "state: $msg — not adopting" 15
    verify_stops || die "stops not verified — not adopting" 5
    [ $DRY = 1 ] && { log "DRY-RUN: would write $MARK for $cur (sha $SHA, strategy $strat)"; exit 0; }
    write_marker "$cur" "$SHA" "$strat" "ci_deploy.sh adopt (ops, by hand): PID $(main_pid), $msg" ;;

  rollback)
    halted_guard
    cur=$(current_dir); strat=$(unit_strategy) || die "LIVE_V6_STRATEGY of $UNIT is invalid" 2
    do_rollback "manual request" 0 "$cur" "$strat" "$(meta_halted)"
    [ $DRY = 1 ] || tg_send "↩️ [CI 배포·$TARGET] 수동 롤백 완료 — $cur → $(current_dir) (검증 통과)" || true ;;

  deploy)
    SHA=${3:-}; TAR=${4:-}; CUR=$(current_dir)
    [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "bad sha" 2
    [ -f "$TAR" ] || die "tar missing" 2
    halted_guard
    if [ "$(release_sha "$CUR")" = "$SHA" ] && unit_active; then
      log "$SHA already current ($CUR) and $UNIT active — no-op (marker: $(marker_ok "$CUR" && echo present || echo absent))"; exit 0
    fi
    unit_active || refuse "unit $UNIT is not active — CI never starts a stopped bot (ops: check why it is down)" 15
    STRAT=$(unit_strategy) || refuse "LIVE_V6_STRATEGY of $UNIT is invalid" 2
    log "unit strategy: $STRAT"
    # 1. archive: regular files and directories only, everything under live_v6/, no '..'
    LIST=$(tar -tvf "$TAR") || refuse "unreadable archive" 2
    BADT=$(awk '{print substr($1,1,1)}' <<<"$LIST" | grep -vE '^[-d]$' | sort -u | tr '\n' ' ' || true)
    [ -z "$BADT" ] || refuse "archive contains non-regular entries (types: $BADT)" 2
    NAMES=$(tar -tf "$TAR")
    BADP=$(grep -vE '^live_v6(/|$)' <<<"$NAMES" || true; grep -E '(^|/)\.\.(/|$)' <<<"$NAMES" || true)
    [ -z "$BADP" ] || refuse "archive contains paths outside live_v6/ or '..'" 2
    # 2. stage + sandboxed import check (no network, live secrets / state / code hidden)
    mkdir -p "$STAGE_ROOT"; chmod 711 "$STAGE_ROOT"
    STAGE=$(mktemp -d "$STAGE_ROOT/$TARGET.XXXXXX")
    tar -xf "$TAR" -C "$STAGE" --no-same-owner --no-same-permissions
    chown -R root:root "$STAGE"; chmod -R u=rwX,go=rX "$STAGE"
    NOTES=$(release_notes "$STAGE")
    systemd-run --quiet --wait --pipe --collect --unit="tradebot-ci-import-$TARGET-$$" \
      -p User="$IMPORT_USER" -p Group="$IMPORT_USER" -p WorkingDirectory="$STAGE" \
      -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes -p PrivateNetwork=yes \
      -p "InaccessiblePaths=$SANDBOX_DENY" -p MemoryMax=300M -p RuntimeMaxSec=120 \
      -E PYTHONDONTWRITEBYTECODE=1 "$IMPORT_PY" -c \
      "import importlib, inspect, sys
import live_v6.runner as r, live_v6.tgcmd, live_v6.engine as e
name = sys.argv[1]
importlib.import_module('live_v6.strategies.' + name)
r.check_frozen(r.live_settings(name, use_streams=True))
assert 'self.on_bar_close()' in inspect.getsource(e.V6Engine.tick)
print('import ok: strategy', name)" "$STRAT" \
      || refuse "import check failed for strategy $STRAT" 8
    log "import check OK for $SHA (strategy $STRAT, user=$IMPORT_USER, sandbox: no network)"
    # 3. pre-checks: the bot must be up and healthy now (else the post-restart check could never pass → CI would stop it)
    check_stop_timeout
    PRE_HALT=$(meta_halted)
    msg=$(state_check 0 "$PRE_HALT" "$HEALTH_MAX_AGE") || refuse "bot not healthy before the deploy: $msg" 15
    log "pre-check: $msg${PRE_HALT:+ (persisted halt: ${PRE_HALT:0:80})}"
    if [ $DRY = 1 ]; then
      log "DRY-RUN: entry-in-flight check now: $(state_counts)"
      verify_stops || log "DRY-RUN: stops NOT verified now — a real run would refuse (exit 5)"
      log "DRY-RUN would: install $APP/$SHA, wait for no entry in flight, verify stops, back up $STATE, swap current → $SHA, restart $UNIT, verify, write $MARK.pending; on failure roll back to $(verified_target "$SHA" "$STRAT" | sed 's/^$/<none: stop + alert>/')"
      exit 0
    fi
    # 4. install (root-owned, read-only for the bot) — the running bot is not affected yet
    mkdir -p "$BACKUP_DIR" "$APP"
    if [ ! -f "$APP/$SHA/.ci_complete" ]; then
      rm -rf "${APP:?}/$SHA.tmp"; mkdir -p "$APP/$SHA.tmp"; cp -a "$STAGE/." "$APP/$SHA.tmp/"
      rm -f "$APP/$SHA.tmp/$MARK" "$APP/$SHA.tmp/$MARK.pending"; echo "$SHA" > "$APP/$SHA.tmp/.ci_complete"
      chown -R root:root "$APP/$SHA.tmp"; chmod -R u=rwX,go=rX "$APP/$SHA.tmp"
      rm -rf "${APP:?}/${SHA:?}"; replace "$APP/$SHA.tmp" "$APP/$SHA"
      log "installed $APP/$SHA"
    else
      log "$APP/$SHA already installed (reusing; marker $(marker_ok "$SHA" && echo present || echo absent))"
    fi
    # 5. quiet point: no entry in flight, stops verified — then restart at once
    for attempt in 1 2 3; do      # an entry can start while stops are checked → re-check right before the swap
      wait_quiet || refuse "an entry stayed in flight for $(( INTENT_TRIES * INTENT_WAIT ))s ($(state_counts))" 11
      verify_stops || refuse "exchange stops NOT verified for every open position" 5
      [ "$(state_counts)" = "intents=0 postonly_pending=0" ] && break
      log "an entry started during the stop check — waiting again ($attempt/3)"
      [ "$attempt" -lt 3 ] || refuse "entries kept starting during the pre-restart checks" 11
    done
    if [ -f "$STATE" ]; then
      cp -p "$STATE" "$BACKUP_DIR/$(basename "$STATE").bak-$(date -u +%Y%m%dT%H%M%SZ)-pre-${SHA:0:12}" && log "state backed up"
      ls -1t "$BACKUP_DIR" | tail -n +31 | while read -r old; do rm -f "$BACKUP_DIR/$old"; done   # keep the last 30
    fi
    [ "$CUR" != none ] && [ "$CUR" != "$SHA" ] && echo "$CUR" > "$APP/PREVIOUS"   # informational — rollback uses the marker
    if ! swap_to "$SHA"; then      # nothing restarted: put the old link back and leave the running bot alone
      [ "$CUR" != none ] && { swap_to "$CUR" || true; }
      ALERTED=1; refuse "symlink swap to $SHA failed (current=$(current_dir)) — no restart" 2
    fi
    if restart_and_verify "$SIM_FAIL" "$PRE_HALT"; then
      write_pending "$SHA" "$SHA" "$STRAT" "$PRE_HALT" "$VERIFIED_MSG"
      tg_send "✅ [CI 배포·$TARGET] 배포 완료 — ${SHA:0:12} (전략 $STRAT)
이전 릴리스: ${CUR:0:12} · 검증: $VERIFIED_MSG
30분 뒤 재확인 통과 시 롤백 기준으로 등록.
릴리즈 노트:
${NOTES:-- (없음)}" || true
      log "DEPLOYED $SHA (previous: $CUR)"
      exit 0
    fi
    # 6. failure → act now: rollback to a marked release of the same strategy, else stop + alert
    log "post-restart verification FAILED for $SHA — reacting now (no waiting)"
    revoke_marker "$SHA" "deploy verification failed" || log "could not revoke the marker of $SHA (continuing with the rollback)"
    do_rollback "verification failed for $SHA" 1 "$SHA" "$STRAT" "$PRE_HALT"
    tg_send "❌ [CI 배포·$TARGET] 배포 실패 → 롤백 완료 — ${SHA:0:12} 검증 실패, $(current_dir | cut -c1-12) 로 복귀(검증 통과)
포지션·거래소 손절은 건드리지 않음.
실패한 릴리즈 노트:
${NOTES:-- (없음)}" || true
    alert_fail "deploy of $SHA failed verification; rolled back to $(current_dir) (verified)" || true
    ALERTED=1
    die "deploy of $SHA failed; rolled back to $(current_dir)" 9 ;;

  *) die "unknown action" 2 ;;
esac
