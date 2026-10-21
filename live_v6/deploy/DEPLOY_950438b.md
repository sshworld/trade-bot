# Deploy 950438b (fix: 4h bar decision never ran) — PREPARED, NOT EXECUTED (needs 성헌's OK)

Current: `/opt/tradebot/app/current → fae64af` (= 0f0a4cc tree), unit `live_v6-live`, state `/var/lib/live_v6-live/mainnet.json`.
New app dir: `/opt/tradebot/app/950438b` (code = commit 950438b; this file is a later doc-only commit).

## 0. When
* Not within 15 min of a 4h boundary (KST 01/05/09/13/17/21 :00) — restart then verify, and the next close must be ≥ 20 min away.
* Bot flat preferred (it is flat today). Exchange stops are never touched by a restart either way.

## 1. Pre-checks (VPS, root)
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
```

## 5. External heartbeat (only AFTER step 4 passed — the new script /fails without meta.health)
```bash
cp -p /opt/tradebot/heartbeat_ping.sh /root/heartbeat_ping.sh.bak
install -m 755 -o root -g root /opt/tradebot/app/950438b/live_v6/deploy/heartbeat_ping.sh /opt/tradebot/heartbeat_ping.sh
systemctl start heartbeat-ping.service && journalctl -u heartbeat-ping.service -n 3 --no-pager   # "heartbeat: ok"
```

## 6. Telegram commands (성헌 sends from his chat)
`/status`, `/today`, `/more` → replies within ~1 min. Log: `/var/lib/live_v6-live/mainnet_commands.jsonl`.
`journalctl -u live_v6-live | grep tgcmd` must not show repeating `409 conflict` (= another poller / webhook on the token).

## 7. TA check at the NEXT 4h close (within 5 min after it)
Run the step-4 python block again (boundary = that close): `last_bar_close == close` and all 6 `last_open == close − 4h`,
`health.ok`. Also `grep '"bar_close_stale"\|4시간 봉 마감' /var/log/tradebot/alerts-live.jsonl` → nothing.

## Rollback
Only for a crash loop / import error: `ln -sfn /opt/tradebot/app/fae64af /opt/tradebot/app/current.new && mv -T … current &&
systemctl restart live_v6-live` and restore `/root/heartbeat_ping.sh.bak`. ⚠️ fae64af has the frozen-bar bug (no entries
ever) — rollback = safe but not trading. State is compatible both ways (new keys `meta.health`, `meta.last_bar_close`).
