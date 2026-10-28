# Deploy runbook — H34 paper recorder (NOT deployed; execute only after 성헌/TA approval)

Target: the existing 1 CPU / 1 GB VPS (Vultr Tokyo) next to `live_v6`. The recorder is stdlib-only (system `python3`), ~26 MB RSS,
~2–3 ms CPU per 15-minute cycle (see the build note). It runs as its own user from its own directory, writes only
`/var/lib/h34_paper`, and has no credential of any kind. Nothing below touches `live_v6`, `/var/lib/live_v6`, `/etc/live_v6.env`
or the h15 logger.

## 0. Before you start
* Approval to deploy (성헌) and TA's lock for the rules to record (H34-B / H34-B-S are locked; the rest stay `enabled:false`).
* Decide the start: the recorder must be running from the first bar after the lock (15:03 KST, 2026-10-28). If it starts later it
  **catches up from the public klines** (up to ~15 days back) and flags those records `late`; beyond that it logs
  `catch_up_window_exceeded` and ledger_score returns INCONCLUSIVE (C7) rather than FAIL.

## 1. Create user and code (read-only for the service)
```bash
sudo useradd -r -M -d /nonexistent -s /usr/sbin/nologin h34paper              # no home, no shell, no sudo
sudo git clone --branch h34-paper https://github.com/sshworld/trade-bot.git /opt/h34-paper
sudo chown -R root:root /opt/h34-paper && sudo chmod -R go-w /opt/h34-paper    # service user cannot modify its own code
python3 --version                                                              # >= 3.10 (VPS: 3.12). No pip, no venv needed.
```

## 2. Pre-flight (no service yet)
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://fapi.binance.com/fapi/v1/time       # expect 200 (451 = region blocked: stop)
cd /opt/h34-paper && sudo -u h34paper env PYTHONPATH=. python3 -m h34_paper.recorder run \
     --config h34_paper/deploy/h34_paper.json --state-dir /tmp/h34_dry --once       # one pass into a scratch dir; exit code 0
sudo -u h34paper cat /tmp/h34_dry/status.json && sudo rm -rf /tmp/h34_dry
systemd-analyze verify /opt/h34-paper/h34_paper/deploy/h34-paper-recorder.service
```
(`--once` records for real if bars are due — use a scratch `--state-dir` as above, never `/var/lib/h34_paper`, for the dry run.)

## 3. Install and start
```bash
sudo cp /opt/h34-paper/h34_paper/deploy/h34-paper-recorder.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now h34-paper-recorder
journalctl -u h34-paper-recorder -f          # expect: "start: rules on ['H34-B', 'H34-B-S'] … next bar 2026-10-28 15:00:00 KST"
```

## 4. Verify it is lower than the bot
```bash
systemctl show h34-paper-recorder -p Nice -p CPUWeight -p CPUQuotaPerSecUSec -p MemoryMax -p OOMScoreAdjust -p IOSchedulingClass
ps -o pid,ni,cls,rss,cmd -C python3          # recorder: NI 19, class IDL; live_v6 untouched
systemctl status live_v6 h34-paper-recorder  # live_v6 state unchanged, no restart
```

## 5. Operate
```bash
python3 -m h34_paper.recorder status --state-dir /var/lib/h34_paper     # lag_s should stay < ~120 s; open_positions; skipped_by_limit
tail -n 5 /var/lib/h34_paper/trades.csv
python3 /opt/h34-paper/tools/ledger_score.py --dir /var/lib/h34_paper   # verdict score (weekly, or on TA's request)
```
Alarm conditions: `lag_s` growing for > 10 min (feed down), repeated `cycle failed` in the journal, any `missing_signal_bar` /
`catch_up_window_exceeded` event, service restarting. None of them can affect trading: the recorder places no orders.

Back up `/var/lib/h34_paper/{trades.jsonl,events.jsonl,state.json}` weekly (`cp` to a dated folder). The ledger is the evidence for the
verdict: never edit it by hand.

## 6. Change rules / config
Edit `h34_paper.json` in a **new commit** (rule on/off, limits), `git pull` in `/opt/h34-paper`, `sudo systemctl restart h34-paper-recorder`.
Restart is safe at any time (state is replaced atomically; ledger writes are idempotent). Turning a rule off with a position open winds
that position down; turning a PLANNED rule on fails at start-up with a clear message (service stays down, nothing recorded silently).
Do not change rule parameters: they are code, locked by TA.

## 7. Stop / rollback
```bash
sudo systemctl disable --now h34-paper-recorder && sudo rm /etc/systemd/system/h34-paper-recorder.service && sudo systemctl daemon-reload
# keep /var/lib/h34_paper (evidence); to remove everything: sudo rm -rf /opt/h34-paper /var/lib/h34_paper && sudo userdel h34paper
```
