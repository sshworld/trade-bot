#!/bin/bash
# External dead-man heartbeat for live_v6-live (systemd heartbeat-ping.timer, every 5 min). Pings Healthchecks.io only
# if the bot is alive AND trading decisions are current; otherwise pings URL/fail with the reason. Never prints the URL.
# Signal: unit active; state file rewritten within MAX_AGE s; meta.health.ok (engine healthy(): reconcile OK, not
# halted, no unprotected position, no stale-bar block) written within MAX_AGE s; INDEPENDENT bar-progress check:
# meta.last_bar_close and every model's last_open current once BAR_GRACE s have passed after a 4h boundary
# (live bug 2026-10-20: the state file stayed fresh while no 4h bar was ever committed).
set -u
MAX_AGE=300
BAR_GRACE=600
STATE=${HB_STATE:-/var/lib/live_v6-live/mainnet.json}
[ -n "${HEARTBEAT_URL:-}" ] || { echo "heartbeat: HEARTBEAT_URL missing"; exit 1; }
reason=""
age=""
if [ "$(systemctl is-active live_v6-live 2>/dev/null)" != "active" ]; then
  reason="live_v6-live not active"
elif ! m=$(stat -c %Y "$STATE" 2>/dev/null); then
  reason="state file missing"
else
  age=$(( $(date +%s) - m ))
  if [ "$age" -gt "$MAX_AGE" ]; then
    reason="state file stale ${age}s"
  else
    reason=$(python3 - "$STATE" "$MAX_AGE" "$BAR_GRACE" <<'PY'
import json, sys, time
st, max_age, grace = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
H4 = 4 * 3600 * 1000
try:
    d = json.load(open(st))
except Exception as e:
    print(f"state unreadable {type(e).__name__}"); sys.exit()
now = int(time.time() * 1000)
m = d.get("meta", {})
h = m.get("health") or {}
if not h:
    print("no health record (old build?)"); sys.exit()
if now - int(h.get("t", 0)) > max_age * 1000:
    print(f"health record stale {(now - int(h.get('t', 0))) // 1000}s"); sys.exit()
if not h.get("ok"):
    print("engine unhealthy: " + ",".join(h.get("blocks") or []) or "engine unhealthy"); sys.exit()
T = now // H4 * H4
if now - T > grace * 1000:
    lbc = int(m.get("last_bar_close") or 0)
    lag = [s for s, x in (d.get("strategy", {}).get("models") or {}).items() if int(x.get("last_open", -1)) < T - H4]
    if lbc < T or lag:
        print(f"4h bar not committed: last_bar_close={lbc} boundary={T} lagging={','.join(lag)}"); sys.exit()
print("")
PY
)
  fi
fi
if [ -z "$reason" ]; then
  if curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "ok age=${age}s" "$HEARTBEAT_URL" 2>/dev/null; then
    echo "heartbeat: ok (state age ${age}s)"; exit 0
  fi
  echo "heartbeat: ping failed (network/HC down); bot looked healthy"; exit 1
else
  curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "$reason" "$HEARTBEAT_URL/fail" 2>/dev/null \
    && echo "heartbeat: FAIL sent ($reason)" || echo "heartbeat: FAIL ($reason), fail-ping also failed"
  exit 1
fi
