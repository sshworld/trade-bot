# Deploy 950438b (fix: 4h bar decision never ran) — PREPARED, NOT EXECUTED (needs 성헌's OK)

Current: `/opt/tradebot/app/current → fae64af` (= 0f0a4cc tree), unit `live_v6-live`, state `/var/lib/live_v6-live/mainnet.json`.
New app dir: `/opt/tradebot/app/950438b` (code = commit 950438b; this file is a later doc-only commit).

Code: trading code (every non-test `live_v6/*.py`, `heartbeat_ping.sh`, `live_v6.service`) is byte-identical to 950438b in
later commits on main (only tests, requirements and docs changed). Check before step 2:
`git diff --stat 950438b HEAD -- live_v6 ':!live_v6/tests' ':!*.md' ':!live_v6/requirements*.txt'` → empty.
Server env layout (read-only check 2026-10-21 09:53 KST): `live_v6-live` reads `EnvironmentFile=/etc/tradebot/live.env`
(BINANCE_API_KEY/SECRET) + `/etc/tradebot/telegram.env` (TELEGRAM_BOT_TOKEN/CHAT_ID); `HEARTBEAT_URL` exists ONLY in
`/etc/tradebot/heartbeat.env`, used by `heartbeat-ping.service` (timer, 5 min). Keep it that way.

## 0. When
* Not within 15 min of a 4h boundary (KST 01/05/09/13/17/21 :00) — restart then verify, and the next close must be ≥ 20 min away.
* Bot flat preferred (it is flat today). Exchange stops are never touched by a restart either way.

## 1. Pre-checks
### 1a. Box: full suite with pylint REQUIRED (TA condition c — the W0101 check must run, not skip)
```bash
cd /workspace/trade-bot-v6 && /workspace/.venv-live6/bin/pip install -q -r live_v6/requirements-dev.txt
LIVE_V6_REQUIRE_PYLINT=1 /workspace/.venv-live6/bin/python -m pytest live_v6/tests -m "not testnet and not slow" -rs
#   expect: all passed, test_static.py::test_pylint_w0101_unreachable PASSED, "SKIPPED" list empty
/workspace/.venv-live6/bin/python -m pytest live_v6/tests -m slow                   # 2 passed (H7 / H7-T replay)
```

### 1b. VPS (root): bot must NOT carry HEARTBEAT_URL (TA condition a)
The engine's in-process DeadMan (runner.py:80 → deadman.py:22) GETs `HEARTBEAT_URL` every 60 s while it *believes* it is
healthy. On the same check URL that overwrites heartbeat_ping.sh's `/fail` within a minute and hides exactly the
"engine thinks it is fine but no 4h decision ran" failure. `HEARTBEAT_URL` belongs ONLY to heartbeat-ping.service.
```bash
systemctl show live_v6-live -p EnvironmentFiles -p Environment | grep -c HEARTBEAT_URL                 # expect 0
for f in $(systemctl show live_v6-live -p EnvironmentFiles --value | grep -o '/[^ ]*'); do
  echo "$f: $(grep -c '^[[:space:]]*\(export[[:space:]]\+\)\?HEARTBEAT_URL=' "$f")"; done           # expect 0 for each
ls /etc/systemd/system/live_v6-live.service.d/ 2>/dev/null && grep -rc HEARTBEAT_URL /etc/systemd/system/live_v6-live.service.d/  # no drop-in sets it
grep -c '^HEARTBEAT_URL=' /etc/tradebot/heartbeat.env                                                  # expect 1 (external pinger keeps it)
tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value live_v6-live)/environ | grep -c ^HEARTBEAT_URL=   # expect 0 (running bot)
```
If any bot-side count is non-zero: delete that line from the bot's env file / drop-in (never print the value; e.g.
`sed -i '/^[[:space:]]*\(export[[:space:]]\+\)\?HEARTBEAT_URL=/d' <file>`), `systemctl daemon-reload`; it takes effect
with the restart in step 3. Never add HEARTBEAT_URL to live.env / telegram.env. (A separate bot-only check URL would
also be acceptable, but only under a different variable name wired by a reviewed code change — not today.)

### 1c. VPS: clock in sync (TA condition 3; signed requests -1021, 4h bar timing)
```bash
timedatectl show -p NTPSynchronized --value                                   # must be: yes
systemctl is-active chrony 2>/dev/null; systemctl is-active systemd-timesyncd   # which one runs (today: timesyncd)
# chrony:            chronyc tracking | grep 'System time'            → |offset| < 0.100 s
# systemd-timesyncd: timedatectl timesync-status | grep -E 'Server|Offset'  → |Offset| < 100ms (us/ms units)
timedatectl timesync-status 2>/dev/null | awk '/Offset:/{v=$2; u=v; gsub(/[-+0-9.]/,"",u); gsub(/[^-+0-9.]/,"",v);
  ms=(u=="us")?v/1000:(u=="ms")?v:(u=="s")?v*1000:(u=="ns")?v/1e6:1e9; if(ms<0)ms=-ms; print "offset_ms", ms, (ms<100?"OK":"FAIL")}'
```
Not synced or ≥ 100 ms → stop, fix NTP (`systemctl restart systemd-timesyncd` or chrony), re-check; do not deploy.

### 1d. VPS: bot state + stops
```bash
systemctl is-active live_v6-live
python3 /opt/tradebot/verify_stops_live.py; echo exit=$?          # exit 0 = every position protected
cp -p /var/lib/live_v6-live/mainnet.json /root/mainnet.json.bak-$(date -u +%Y%m%dT%H%M%SZ)
```

## 2. Upload (from the box)
```bash
cd /workspace/trade-bot-v6 && git archive --format=tar 950438b live_v6 > /tmp/app-950438b.tar
# paramiko/sftp: put /tmp/app-950438b.tar → /tmp/ on the VPS, then on the VPS:
mkdir -p /opt/tradebot/app/950438b && tar -xf /tmp/app-950438b.tar -C /opt/tradebot/app/950438b
chown -R tradebot:tradebot /opt/tradebot/app/950438b && rm /tmp/app-950438b.tar
cd /opt/tradebot/app/950438b && sudo -u tradebot /opt/tradebot/.venv/bin/python -c \
  "import live_v6.runner, live_v6.tgcmd, live_v6.engine as e, inspect; s=inspect.getsource(e.V6Engine.tick); assert 'self.on_bar_close()' in s; print('import ok, tick calls on_bar_close')"
```

## 3. Swap + restart
```bash
ln -sfn /opt/tradebot/app/950438b /opt/tradebot/app/current.new && mv -T /opt/tradebot/app/current.new /opt/tradebot/app/current
echo 950438b > /opt/tradebot/app/DEPLOYED
systemctl restart live_v6-live && sleep 30
```

## 4. Post-restart verification (within 2 min)
```bash
journalctl -u live_v6-live --since "-2 min" --no-pager | grep -v "HTTP Request" | tail -20   # "▶️ live_v6 시작 … 진입 가능", no Traceback, no 🚨 모델 재구성
journalctl -u live_v6-live --since "-2 min" --no-pager | grep -c "HTTP Request"               # expect 0 (httpx → WARNING)
python3 - <<'P'
import json, time
H4 = 4*3600*1000; d = json.load(open('/var/lib/live_v6-live/mainnet.json')); m = d['meta']
T = int(time.time()*1000)//H4*H4
lo = {s: x['last_open'] for s, x in d['strategy']['models'].items()}
print('last_bar_close', m.get('last_bar_close'), 'boundary', T, 'models', lo, 'health', m.get('health'))
assert m.get('last_bar_close') == T and set(lo.values()) == {T - H4} and m['health']['ok'], 'NOT CAUGHT UP'
print('OK: caught up')
P
python3 /opt/tradebot/verify_stops_live.py; echo exit=$?
# dead-man: the NEW bot process has no HEARTBEAT_URL and makes no in-process pings
P=$(systemctl show -p MainPID --value live_v6-live); tr '\0' '\n' < /proc/$P/environ | grep -c ^HEARTBEAT_URL=   # expect 0
journalctl -u live_v6-live --since "-2 min" --no-pager | grep -c 'live_v6.deadman'                    # expect 0 (no ping attempts)
```
Non-zero env count → stop the rollout of step 5, remove the variable (§1b) and restart again in a safe window.

## 5. External heartbeat (only AFTER step 4 passed — the new script /fails without meta.health)
```bash
cp -p /opt/tradebot/heartbeat_ping.sh /root/heartbeat_ping.sh.bak
install -m 755 -o root -g root /opt/tradebot/app/950438b/live_v6/deploy/heartbeat_ping.sh /opt/tradebot/heartbeat_ping.sh
systemctl start heartbeat-ping.service && journalctl -u heartbeat-ping.service -n 3 --no-pager   # "heartbeat: ok"
systemctl show heartbeat-ping.service -p EnvironmentFiles --value | grep -c /etc/tradebot/heartbeat.env  # expect 1
```
Healthchecks.io event log for the check: from now on only the curl pings of heartbeat_ping.sh (User-Agent `curl/…`, ~5 min
apart); a `python-httpx` ping or 1-minute cadence = the bot still pings → back to §1b.

## 6. Telegram commands (성헌 sends from his chat)
`/status`, `/today`, `/more` → replies within ~1 min. Log: `/var/lib/live_v6-live/mainnet_commands.jsonl`.
`journalctl -u live_v6-live | grep tgcmd` must not show repeating `409 conflict` (= another poller / webhook on the token).

## 7. TA check at the NEXT 4h close (within 5 min after it)
Run the step-4 python block again (boundary = that close): `last_bar_close == close` and all 6 `last_open == close − 4h`,
`health.ok`. Re-run the §4 dead-man lines (env count 0, no `live_v6.deadman` in the journal since the restart). Also `grep '"bar_close_stale"\|4시간 봉 마감' /var/log/tradebot/alerts-live.jsonl` → nothing.

## Rollback
Only for a crash loop / import error: `ln -sfn /opt/tradebot/app/fae64af /opt/tradebot/app/current.new && mv -T … current &&
systemctl restart live_v6-live` and restore `/root/heartbeat_ping.sh.bak`. Before that restart run §1d (stops) and after it the §4
stops + dead-man lines (fae64af also has DeadMan: the bot env must still lack HEARTBEAT_URL). ⚠️ fae64af has the frozen-bar bug (no entries
ever) — rollback = safe but not trading. State is compatible both ways (new keys `meta.health`, `meta.last_bar_close`).
