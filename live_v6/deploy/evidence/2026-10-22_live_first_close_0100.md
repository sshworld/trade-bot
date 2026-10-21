# LIVE first real 4h close after the 2eb429b deploy — 01:00 KST 2026-10-22 (TA condition 4)

Read-only checks on the VPS as `ops@198.13.39.149` (sudo -n), 01:26:26–01:26:53 KST (16:26 UTC). No orders, no restarts, nothing changed on the server.

| check | result |
|---|---|
| release | `/opt/tradebot/app/current` → `/opt/tradebot/app/2eb429b`; `DEPLOYED` = `2eb429b` |
| process | `live_v6-live` active/running, MainPID **51227**, NRestarts **0** (same as at deploy 21:48:55 KST) |
| bar close | `meta.last_bar_close` = 1792598400000 (= 16:00 UTC / **01:00 KST** boundary) |
| 6 models | BTC, ETH, SOL, BNB, XRP, DOGE `last_open` = 1792584000000 (= boundary − 4h), 55 bars each → **all caught up** |
| current bar | all 6 `strategy.bar.open` = 1792598400000, entered/stopped/missed false |
| health | `health.ok` true, `blocks` [], t = 16:26:33 UTC; `intents` {}, `unknown` {}, `pos` {} |
| verify_stops | `sudo python3 /opt/tradebot/verify_stops_live.py` → **pass true, exit 0**; 0 positions, 0 open orders, 0 open algo orders; all 6 ISOLATED (BTC 5x, others 20x) |
| journal since restart | Traceback/ERROR/CRITICAL/🚨/모델 재구성 = **0** (16 lines total) |
| heartbeat | `heartbeat-ping.timer` active, last trigger 16:24:28 UTC |

Journal lines after the restart (all WARNING-level notices): ▶️ start 21:48:56; 💓 heartbeat 22:41:23; `skip BTCUSDT min_notional: qty 0.000 notional 0.0000 < minQty 0.001/minNotional 100` at 23:35:30 KST (an entry signal sized below the $100 floor at balance 117.47 USDT, so no order — expected sizing behaviour, logged in `meta.skips`); 📊 daily settlement 00:00:00 KST (balance 117.47, 0 closes, 1 skip).

**Condition 4: PASS.** No rollback needed; 0d82b19 stays as the rollback target.
