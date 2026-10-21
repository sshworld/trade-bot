# H15 logger deploy — 2026-10-22 (KST) — 36653c2 — STOPPED after 12 min: legacy WS URL delivers no data

TA approval: deploy H15 logger under the agreed limits (2026-10-22 01:28 KST). VPS 198.13.39.149 (Tokyo, 1 vCPU / 955 MB).
Times KST (VPS clock UTC, converted). No orders, no API keys, live bot untouched.

## Result
* **Deployed 01:30:29 KST** (`h15-logger.service` start), release `36653c2` (`git archive` sha256 `d142eb69…f988`, 13 files),
  `/opt/h15-logger/RELEASE` = `36653c2`.
* **Stopped by ops 01:42:40 KST** (`systemctl stop`, no code fault): the websocket was connected (ESTAB to fstream 443) but
  received **0 messages in 12 min**. Cause: `WS_URL` uses the legacy mainnet path `wss://fstream.binance.com/stream?streams=…`.
  Binance retired the legacy `/ws` `/stream` paths on 2026-04-23; they still accept connections but push only "public"-category
  data — `@forceOrder` is "market" (Binance "Important WebSocket Change Notice"). live_v6 already uses `/market` + `/private`.
* Side-by-side probe from the VPS (logger venv, nice 19, read-only public streams):
  | window | legacy 6-sym `/stream` | `/market` 6-sym `/stream` | `/market/ws/!forceOrder@arr` |
  |---|---|---|---|
  | 90 s (01:41 KST) | 0 | – | 41 msgs (all symbols) |
  | 240 s (01:43–01:47 KST) | 0 | **2 (ETH 1, BTC 1)** | 108 msgs; 6-sym subset = ETH 1, BTC 1 (identical) |
* The 12 min of liq rows (16:31–16:42 UTC) claimed "fully connected, zero liquidations" → **invalid**; moved to
  `/var/lib/h15-logger/invalid-36653c2-legacy-url/liq_2026-10-21_1631-1642UTC.csv`; a closing `disconnect` row with the reason
  was appended to `gaps.csv`. OI rows (REST, valid) kept in `oi/2026-10-21.csv`.
* `STOPPED` marker written → the unit (enabled) exits 75 at any start/boot until ops remove it.
* Fix prepared, **not deployed**: commit `77469af` (`WS_URL` → `wss://fstream.binance.com/market/stream?streams=…`, test updated;
  34/34 offline tests pass). Needs TA review; re-arm = install `77469af` app tree, `rm /var/lib/h15-logger/STOPPED`,
  `systemctl start h15-logger`, outside 4h-close ±15 min.

## Pre-deploy
* Offline tests on the box at `36653c2`: **34 passed** (py3.13 venv, websockets 17.3, pytest 9.1.1). pylint (C,R disabled) 9.97/10.
  No rebase on `2eb429b` needed: `0d82b19..36653c2` touches only `h15_logger/` (no `live_v6` file changed).
* Bot baseline (01:29 KST): `live_v6-live` MainPID **51227** NRestarts **0** active; `live_v6-citest` MainPID **49518** NRestarts **0** active
  (`citest.service` itself does not exist / inactive). Host: MemAvailable 503 MB, / 17 GB free, PSI cpu some avg60 0.72, mem 0.00.

## Install (all new files except the needrestart line)
* user `h15log` (system, nologin, uid 995); app `/opt/h15-logger/app/h15_logger` (root-owned, read-only); own venv
  `/opt/h15-logger/.venv` (`websockets==17.3` only; installed with nice 19 / ionice idle); data `/var/lib/h15-logger` (StateDirectory, 0750).
* unit `/etc/systemd/system/h15-logger.service` = repo `h15_logger/deploy/h15-logger.service` (sha256 `f2fa5230…eb4e`, identical); enabled.
* needrestart: existing patterns `^live_v6 ^heartbeat-ping ^tradebot ^ci-` did **not** cover `h15-logger` → appended
  `$nrconf{override_rc}{qr(^h15-logger)} = 0;` to `/etc/needrestart/conf.d/90-tradebot.conf` (perl-parsed OK; `restart = "l"` unchanged).
  Backup of the previous file: `/etc/needrestart/90-tradebot.conf.bak-20261022`.

## Limits applied (written in README / unit / logger.py `Caps`; nothing new invented) — read back live
| limit | written value | systemd / cgroup read-back |
|---|---|---|
| memory hard cap (spec 100 MB) | MemoryMax=100M | MemoryMax=104857600, cgroup memory.max 104857600 |
| memory high | MemoryHigh=80M | 83886080 |
| swap | MemorySwapMax=0 | memory.swap.max 0 |
| in-process RSS cap | 60 MB → exit 1 | (Caps.rss_max_mb 60) |
| OOM | OOMScoreAdjust=1000 | /proc/PID/oom_score_adj 1000 (bot −900) |
| CPU | Nice=19, CPUSchedulingPolicy=idle, CPUWeight=10, CPUQuota=25% | Nice=19, policy 5 (idle, ps CLS IDL), cpu.weight 10 (bot 100), cpu.max 25000/100000 |
| IO | IOWeight=10, IOSchedulingClass=idle | io.weight 10 (bot 100), ionice idle |
| tasks / fds | TasksMax=16, LimitNOFILE=256 | pids.max 16, 256 |
| disk | data dir ≤ 256 MB, fs free ≥ 2048 MB (watchdog stop) | data dir 24–32 KB; / free 16.6 GB |
| IP weight | OI 6×w1 / 5 min; skip round if IP used ≥ 240 (10 % of 2400) | see below |
| 429/418 | STOPPED + exit 75 (RestartPreventExitStatus=75) | RestartPreventExitStatus=75 |
| bot affected | watchdog 30 s: bot PID/NRestarts/state change, MemAvailable < 150 MB, PSI cpu > 40 % / mem > 5 % (2 strikes) | baseline logged `live bot pid 51227 NRestarts 0` |
| no keys | UnsetEnvironment BINANCE_API_KEY BINANCE_API_SECRET TELEGRAM_BOT_TOKEN HEARTBEAT_URL; preflight refuses | process env keys: LANG PATH USER LOGNAME HOME INVOCATION_ID JOURNAL_STREAM STATE_DIRECTORY SYSTEMD_EXEC_PID MEMORY_PRESSURE_WATCH MEMORY_PRESSURE_WRITE PYTHONDONTWRITEBYTECODE — 0 secret-like keys |

## Measured while running (01:30–01:42 KST)
* Memory: cgroup MemoryCurrent 17.9–18.7 MB, MemoryPeak 19.9 MB (journal: 18.9 MB peak); VmRSS/VmHWM 30.4 MB. CPU 1.02 s total.
* OI: 2 rounds (01:35:07, 01:40:07 KST), 6 rows each, all HTTP 200, 0 skipped, 0 errors → logger weight 6 / 5 min = 1.2/min =
  **0.05 % of 2400**. IP total `X-MBX-USED-WEIGHT-1M` (shared with the bot; 1-weight `/fapi/v1/ping` samples) 398 (16.6 %, 01:29),
  103 (4.3 %, 01:35), 167 (7.0 %, 01:40). Note: when the IP total is ≥ 240 the logger skips the OI round by design.
* Liquidations: **0 events** (legacy URL, see above). Data dir 24 KB.
* Host during run: PSI cpu some avg60 0.72→1.75 %, memory 0.00; MemAvailable 490–526 MB.

## Bot before / after
| | before (01:29 KST) | after (01:47:58 KST) |
|---|---|---|
| live_v6-live | PID 51227, NRestarts 0, active | PID 51227, NRestarts 0, active |
| live_v6-citest | PID 49518, NRestarts 0, active | PID 49518, NRestarts 0, active |
* `verify_stops_live.py` (read-only): pass true, exit 0, 0 positions, 0 open orders, 0 algo orders (01:36 and 01:48 KST).
* Bot journal 01:29–01:48 KST: one `CRITICAL 🚨 레버리지 10x 설정 실패 — 진입 건너뜀 | BNBUSDT read-back 20x` at **01:39:18 KST**
  (entry skipped safely; Telegram alert sent). Bot-side: `set_leverage` returned OK but the immediate `positions` read-back still
  showed 20x. Not attributable to the logger (no keys, no account endpoints; its only REST calls were 6 public OI requests at
  01:35:07; IP weight 7 % at 01:40). Reported to TA separately.
