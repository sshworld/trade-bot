# H15 logger redeploy — 77469af (routed /market URL) — 2026-10-22 01:51 KST — RUNNING, events arriving

TA approved `77469af` at 01:50 KST. Times KST (VPS clock UTC, converted). No orders, no API keys, live bot untouched.
Note: commit `49d347a` (collection-quality rule) sits on this branch between `77469af` and this evidence; it is **not deployed**
(pending TA review). The server runs `77469af` only.

## Install
* `git archive 77469af h15_logger` sha256 `2d54a4c6c4c0810fbb04c0e4314a329eb190e364fb507fab475c7154b1fd1f74` (box = VPS copy).
  Diff vs `36653c2`: `logger.py` (+3/−1, `WS_URL`) and `tests/test_logger.py` (1 line) only.
* Previous tree kept for rollback: `/opt/h15-logger/app` → `/opt/h15-logger/app-36653c2`; new tree extracted to
  `/opt/h15-logger/app` (root-owned), `/opt/h15-logger/RELEASE` = `77469af`. Venv unchanged (websockets 17.3).
* Installed `WS_URL` = `wss://fstream.binance.com/market/stream?streams=btcusdt@forceOrder/…/dogeusdt@forceOrder`.
* Unit file unchanged (`cmp` with release copy: identical). `STOPPED` marker removed, `systemctl start h15-logger`
  → **started 01:51:29 KST**, MainPID 55378. Journal: `watchdog baseline: live bot pid 51227 NRestarts 0`.

## Liquidation events (watch 01:51:29 – 02:02:22 KST)
* Logger journal 02:01:30: `rows 54 msgs 5 bad 0 oi rounds 2 skipped 0` (10 min after start).
* liq CSV at 02:02:10: 60 rows (10 full minutes × 6 coins), **7 events**, 0 late: BTC 3, ETH 2, SOL 1, XRP 1, BNB 0, DOGE 0.
  Non-zero rows:
  ```
  1792601520000,BTCUSDT,2618.32,0.00,3,0,2280.48,0     # 01:52 KST
  1792601520000,SOLUSDT,177.56,0.00,1,0,177.56,0       # 01:52 KST
  1792602000000,ETHUSDT,581.94,0.00,1,0,581.94,0       # 02:00 KST
  1792602060000,ETHUSDT,233.15,0.00,1,0,233.15,0       # 02:01 KST
  1792602060000,XRPUSDT,2237.91,0.00,1,0,2237.91,0     # 02:01 KST
  ```
* Independent reference: `/market/ws/!forceOrder@arr` (all coins) on the VPS, 600 s, 01:51:40–02:01:40 KST: 282 msgs all coins,
  6-coin subset BTC 3, SOL 1, ETH 1 — **the same events the logger recorded** (the 2nd ETH and the XRP event came after the reference
  window ended). Raw lines (logger stores no raw JSON by design; these are from the reference connection):
  ```
  recv_ms=1792601552094 {"e":"forceOrder","E":1792601552092,"o":{"s":"BTCUSDT","S":"SELL","o":"LIMIT","f":"IOC","q":"0.001","p":"84151.40","ap":"84469.10","X":"FILLED","l":"0.001","z":"0.001","T":1792601551088,"ps":"BTCUSDT","st":1}}
  recv_ms=1792601552165 {"e":"forceOrder","E":1792601552163,"o":{"s":"SOLUSDT","S":"SELL","o":"LIMIT","f":"IOC","q":"1.64","p":"107.7500","ap":"108.2700","X":"FILLED","l":"1.64","z":"1.64","T":1792601551159,"ps":"SOLUSDT","st":1}}
  recv_ms=1792601555204 {"e":"forceOrder","E":1792601555201,"o":{"s":"BTCUSDT","S":"SELL","o":"LIMIT","f":"IOC","q":"0.027","p":"84127.70","ap":"84462.30","X":"FILLED","l":"0.027","z":"0.027","T":1792601554198,"ps":"BTCUSDT","st":1}}
  recv_ms=1792601558089 {"e":"forceOrder","E":1792601558087,"o":{"s":"BTCUSDT","S":"SELL","o":"LIMIT","f":"IOC","q":"0.003","p":"84123.30","ap":"84455.00","X":"FILLED","l":"0.003","z":"0.003","T":1792601557081,"ps":"BTCUSDT","st":1}}
  recv_ms=1792602001171 {"e":"forceOrder","E":1792602001169,"o":{"s":"ETHUSDT","S":"SELL","o":"LIMIT","f":"IOC","q":"0.232","p":"2498.68","ap":"2508.36","X":"FILLED","l":"0.232","z":"0.232","T":1792602000164,"ps":"ETHUSDT","st":1}}
  ```
  Cross-check: BTC 0.001×84469.10 + 0.027×84462.30 + 0.003×84455.00 = 2618.32 = logger `ll_usd`; max single 2280.48 ✓;
  SOL 1.64×108.27 = 177.56 ✓; ETH 0.232×2508.36 = 581.94 ✓. All `S=SELL` → counted as long liquidations ✓.

## Resources (02:02 KST)
* cgroup MemoryCurrent 18.9 MB, MemoryPeak 20.1 MB (MemoryMax 104857600); VmRSS/VmHWM 30.5 MB (in-process cap 60 MB); CPU 0.95 s total.
* Caps / priority unchanged from the 36653c2 install (same unit): MemoryHigh 80M, MemoryMax 100M, swap 0, OOMScoreAdjust 1000,
  Nice 19 / idle, CPUWeight 10 (bot 100), CPUQuota 25 %, IOWeight 10 (bot 100) / idle, TasksMax 16.
* OI: 2 rounds this run (6 rows each, 0 skipped, 0 errors) → 1.2 weight/min = **0.05 % of 2400**. IP total
  `X-MBX-USED-WEIGHT-1M` at 02:02:10 = 65 (2.7 %).
* Disk: data dir 32 KB (cap 256 MB); / free ≈ 16.6 GB (floor 2 GB). Host PSI cpu some avg60 1.26 %, memory 0.00; MemAvailable 482 MB.
* Logger journal WARNING/ERROR lines since start: 0.

## Bot before / after
| | before (01:51 KST) | after (02:02:22 KST) |
|---|---|---|
| live_v6-live | PID 51227, NRestarts 0, active | PID 51227, NRestarts 0, active |
| live_v6-citest | PID 49518, NRestarts 0, active | PID 49518, NRestarts 0, active |
* `verify_stops_live.py` 02:02 KST: exit 0, pass true, 0 positions, 0 open orders, 0 algo orders.
* Bot journal 01:48–02:02 KST: 0 Traceback/CRITICAL/ERROR/🚨 lines.

## Rollback / stop
`sudo systemctl stop h15-logger` (the live bot is independent). Previous tree: `/opt/h15-logger/app-36653c2` (known-bad URL; do not use).
