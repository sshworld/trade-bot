# TA R4 — unknown positions are never market-closed (branch fix-unknown-position, base main 0d82b19)

## Root cause (testnet canary, 2026-10-21 13:00:03 KST)
DOGEUSDT 9628 (opened by a drill directly through V6Engine.enter, outside the H7-T model) was market-closed by the
canary bot at the 4h close: `model_sync` (orderId 2369898332, reduceOnly MARKET). Mechanism in 0d82b19:
reconcile() journaled any unknown exchange position into st["pos"] (`_adopt`, model_entry_open=None) → the strategy
saw a live position its model does not hold → `exit_(sym, "model_sync")` → close(). Same path for a lost / corrupted
state file: the bot's OWN positions would be dumped at the next 4h close.

## Change (engine.py, strategies/base.py, strategies/v6_h7.py, tools/adopt_position.py)
1. Positions not in the state file go to st["unknown"], never st["pos"] → the strategy never sees them (no model_sync /
   signal_exit); breach / stop-failure closes only run for st["pos"]; `close()` refuses any symbol not in st["pos"];
   flatten-all closes st["pos"] only (and alerts that unknown positions were left with their stop).
2. Detection: 🚨 once (Notifier: Telegram only on mainnet; testnet/tests log only), entries blocked for THAT coin
   (skip `unknown_position`, no global block), risk = |mark − stop| × qty / capital (floor 1 %) in the portfolio-risk
   sum and in max positions.
3. No exchange stop → closePosition STOP_MARKET MARK_PRICE at the model's exit line (20-bar low for a long / high for
   a short; `V6H7.exit_line`); price already beyond the line (or the line would trigger) → 1×ATR14(4h) from the mark.
   An existing stop is never moved or cancelled. No channel/ATR yet → flagged unprotected (dead-man stops pinging),
   retried every reconcile, never closed.
4. Resolution manual: closed by hand → cleared + ✅; or ops adopts it: `python -m live_v6.tools.adopt_position`
   (dry run by default; `--apply` only with `--unit` stopped; long only; backup first).

## Other close paths reviewed
| path | closes unknown positions? | now |
|---|---|---|
| strategy `model_sync` / `signal_exit` (on_bar_close) | YES (via `_adopt` → st["pos"]) — the R4 bug | no: unknown never in st["pos"] |
| `breach_check` → close(stop_breach) (mark stream + 5 s reconcile) | YES after `_adopt` | no: only st["pos"]; close() refuses unknown |
| `protect` → close(sl_failed) → flatten-all | YES after `_adopt` | no: unknown handled by `_unknown_position` (retry, never close) |
| `emergency_flatten_all` (−25 % halt, unprotectable position, API dead) | YES: closed every non-zero exchange position, journaled or not | **changed (reported): closes st["pos"] only**; unknown keep their stop + 🚨 |
| `check_api_dead` | only st["pos"] unprotected | unchanged (unknown unprotected never triggers a flatten) |
| `check_halts` (−25 %) | equity = account equity → includes an unknown position's unrealised PnL | unchanged (TA spec'd); note: an unknown position's loss can trigger the halt, which then flattens only the journaled positions |
| reconcile flat branch: cancel own stale stops | only when the exchange position is 0 | unchanged |
| `enter()` cancels own leftover stops | only when the exchange position is 0 | unchanged; entry for an unknown coin refused first |
| `dust_entry` close | own fresh entry only | unchanged |
| backend/app/trading/live_v1 (old engine, not deployed) | also auto-adopts unknown positions | not changed (out of scope) |

## Tests (LIVE_V6_REQUIRE_PYLINT=1, offline incl. slow): 149 passed, 51 testnet-marked deselected (no testnet keys on the box)
tests/test_unknown_position.py (13): long / short × without / with an existing stop, beyond-line ATR stop, state file
deleted + restart (own position not closed over two 4h closes, same stop id), coin-only block + portfolio risk,
flatten-all/close skip unknown, manual resolution, no model data → unprotected flag not close, adopt tool (dry run,
apply needs stopped unit, refuses short / non-unknown). All 10 engine tests fail on 0d82b19.

## Testnet drill on live_v6-citest (TESTNET keys only; live_v6-live untouched: MainPID 12861, NRestarts 0)
## R4 drill 2026-10-21T04:44:43Z: CI deploy of fix-unknown-position 2c1eb769bc0f0d9792722cde08cb8f4182d3cc17 to the TESTNET canary live_v6-citest (CI testnet key)
server job 20261021T044446Z-1554d0 started (detached on the VPS)
[2026-10-21T04:44:47Z] [testnet] action=deploy dry_run=0 current=ca87f853d7cb9c3d3d1bd62246e08a06b72fc5cb unit=active
import ok, tick calls on_bar_close
[2026-10-21T04:44:47Z] [testnet] import check OK for 2c1eb769bc0f0d9792722cde08cb8f4182d3cc17 (user=tradebot-ci, sandbox: no network, denied: -/etc/tradebot -/var/lib/live_v6-live -/opt/tradebot/app -/var/log/tradebot -/root -/var/lib/tradebot-ci/uploads -/opt/tradebot)
[2026-10-21T04:44:47Z] [testnet] time window OK (04:44 UTC: ≥900s after the last 4h close, ≥1200s before the next)
[2026-10-21T04:44:47Z] [testnet] unit live_v6-citest TimeoutStopUSec=30s (SIGTERM → runner finishes the current event; SIGKILL after this)
  verify-stops: pass=True positions=0 []
[2026-10-21T04:44:47Z] [testnet] verify-stops exit=0
[2026-10-21T04:44:47Z] [testnet] state: no in-flight intents
[2026-10-21T04:44:47Z] [testnet] state backed up
[2026-10-21T04:44:47Z] [testnet] installed /opt/tradebot-ci-testnet/app/2c1eb769bc0f0d9792722cde08cb8f4182d3cc17
[2026-10-21T04:44:47Z] [testnet] symlink current → 2c1eb769bc0f0d9792722cde08cb8f4182d3cc17
[2026-10-21T04:44:52Z] [testnet] restarted live_v6-citest at 04:44:47Z; verifying strictly (≤240s)
[2026-10-21T04:45:02Z] [testnet]   state: health ok, last_bar_close=1792555200000 boundary=1792555200000 models=6 all caught up, positions=0
  verify-stops: pass=True positions=0 []
[2026-10-21T04:45:47Z] [testnet] verify-stops exit=0
[2026-10-21T04:45:47Z] [testnet] verification PASSED
[2026-10-21T04:45:47Z] [testnet] marker PENDING for 2c1eb769bc0f0d9792722cde08cb8f4182d3cc17: .citest_verified is granted only after the first real 4h close after this restart is processed for all 6 coins (confirm timer, close + 5 min); rollback target meanwhile: 660eea8eac39a0962ef86ff3f083939e9ddaa6a2
[2026-10-21T04:45:47Z] [testnet] DEPLOYED 2c1eb769bc0f0d9792722cde08cb8f4182d3cc17 (previous: ca87f853d7cb9c3d3d1bd62246e08a06b72fc5cb). Heartbeat script NOT changed (manual step, runbook §5).
job 20261021T044446Z-1554d0 finished OK
## R4-1 2026-10-21T04:45:59Z: open a TESTNET DOGEUSDT position by hand, outside the model, without a stop
OPEN (manual, outside the model, NO stop): {'orderId': 2369930402, 'clientOrderId': 'drillR4open1792557961', 'status': 'FILLED', 'executedQty': '100', 'avgPrice': None, 'updateTime': 1792557961774, 'http': None, 'body': None} 13:46:01.774 KST
position: [('100', '0.08145999999999999', '0.08146219', 'isolated')]
open algo stops: []
open std orders: 0
orders last 3h (non-algo): [(2369898332, 'v6DOGE1792545935x0', 'SELL', 'FILLED', 'reduceOnly=True', '9628', '13:00:03.812 KST'), (2369930402, 'drillR4open1792557961', 'BUY', 'NEW', 'reduceOnly=False', '100', '13:46:01.774 KST')]

## R4-2 2026-10-21T04:46:27Z: ~25 s later — exchange state + canary journal
position: [('100', '0.08145999999999999', '0.08145000', 'isolated')]
open algo stops: [(1000000249403424, 'v6DOGEu1792557963s0', 'STOP_MARKET', 'SELL', '0.07619', 'closePosition=True', 'MARK_PRICE', '13:46:03.035 KST')]
open std orders: 0
orders last 3h (non-algo): [(2369898332, 'v6DOGE1792545935x0', 'SELL', 'FILLED', 'reduceOnly=True', '9628', '13:00:03.812 KST'), (2369930402, 'drillR4open1792557961', 'BUY', 'FILLED', 'reduceOnly=False', '100', '13:46:01.774 KST')]
-- canary journal (live_v6-citest) since the open --
2026-10-21T04:46:03+00:00 vultr python[33168]: 2026-10-21 04:46:03,064 WARNING live_v6.engine DOGEUSDT unknown position 100: stop 0.076190 placed (20-bar channel exit line)
2026-10-21T04:46:03+00:00 vultr python[33168]: 2026-10-21 04:46:03,068 CRITICAL live_v6.engine 🚨 기록 없는 포지션 발견 — DOGEUSDT 자동 청산 안 함 · 이 코인 신규 진입 차단 · 수동 처리 필요 | DOGEUSDT 롱 100 @ 0.08145999999999999 · 손절 0.076190 (20-bar channel exit line) · 포트폴리오
2026-10-21T04:46:03+00:00 vultr python[33168]: 2026-10-21 04:46:03,068 WARNING live_v6.notify [tg:testnet] 🧪[TESTNET·모의] 🚨 기록 없는 포지션 발견 — DOGEUSDT 자동 청산 안 함 · 이 코인 신규 진입 차단 · 수동 처리 필요
2026-10-21T04:46:03+00:00 vultr python[33168]: DOGEUSDT 롱 100 @ 0.08145999999999999 · 손절 0.076190 (20-bar channel exit line) · 포트폴리오 위험에 포함 1.00% · 해결: 직접 청산 또는 ops가 adopt_position 으로 등록
state unknown: {"DOGEUSDT": {"side": 1, "detected_ms": 1792557963018, "stop_seq": 1, "amt": "100", "qty": "100", "entry_px": "0.08145999999999999", "stop_px": "0.07619", "stop_cid": "v6DOGEu1792557963s0", "stop_src": "20-bar channel exit line", "stop_line": "0.07619", "stop_atr": "0.001222665632981268", "risk_usdt": "0.52600900", "risk_frac": 0.01}} | pos: []
MainPID=12861
NRestarts=0

## R4-3 2026-10-21T04:46:40Z: Telegram path on testnet = log only (alerts.jsonl 'sent')
{'kind': None, 'sent': False, 'mode': 'testnet', 'live': None} 🧪[TESTNET·모의] ⏹ live_v6 종료 (거래소 손절은 그대로 유지)
{'kind': None, 'sent': False, 'mode': 'testnet', 'live': None} 🧪[TESTNET·모의] ▶️ live_v6 시작 · BinanceREST(https://testnet.binancefuture.com) · 포지션 0개 · 진입
{'kind': None, 'sent': False, 'mode': 'testnet', 'live': None} 🧪[TESTNET·모의] 🚨 기록 없는 포지션 발견 — DOGEUSDT 자동 청산 안 함 · 이 코인 신규 진입 차단 · 수동 처리 필요
DOGEUSDT 롱 10

## R4-4 2026-10-21T04:46:42Z: stop citest, DELETE its state file (moved to /root/ci-backups/testnet/), start citest
Traceback (most recent call last):
  File "/workspace/vps_ops.py", line 13, in <module>
    out=o.read().decode(); err=e.read().decode(); rc=o.channel.recv_exit_status()
UnicodeDecodeError: 'utf-8' codec can't decode bytes in position 1713-1714: invalid continuation byte
citest: active MainPID=34028 since Wed 2026-10-21 04:46:49 UTC
-rw-r--r-- 1 tradebot-ci tradebot-ci 9653 Oct 21 04:46 testnet.json.r4drill-deleted-20261021T044649Z
position: [('100', '0.08145999999999999', '0.08144000', 'isolated')]
open algo stops: [(1000000249403424, 'v6DOGEu1792557963s0', 'STOP_MARKET', 'SELL', '0.07619', 'closePosition=True', 'MARK_PRICE', '13:46:03.035 KST')]
open std orders: 0
orders last 3h (non-algo): [(2369898332, 'v6DOGE1792545935x0', 'SELL', 'FILLED', 'reduceOnly=True', '9628', '13:00:03.812 KST'), (2369930402, 'drillR4open1792557961', 'BUY', 'FILLED', 'reduceOnly=False', '100', '13:46:01.774 KST')]
-- canary journal since restart --
2026-10-21T04:46:44+00:00 vultr systemd[1]: Stopping live_v6-citest.service - live_v6 CI canary (H7-T) — Binance Futures TESTNET...
2026-10-21T04:46:49+00:00 vultr systemd[1]: Stopped live_v6-citest.service - live_v6 CI canary (H7-T) — Binance Futures TESTNET.
2026-10-21T04:46:49+00:00 vultr systemd[1]: Starting live_v6-citest.service - live_v6 CI canary (H7-T) — Binance Futures TESTNET...
2026-10-21T04:46:49+00:00 vultr systemd[1]: Started live_v6-citest.service - live_v6 CI canary (H7-T) — Binance Futures TESTNET.
2026-10-21T04:46:51+00:00 vultr python[34028]: 2026-10-21 04:46:51,991 CRITICAL live_v6.engine 🚨 기록 없는 포지션 발견 — DOGEUSDT 자동 청산 안 함 · 이 코인 신규 진입 차단 · 수동 처리 필요 | DOGEUSDT 롱 100 @ 0.08145999999999999 · 손절 0.07619 (exchange (existing, untouched)) · 포트폴리오 위험에 포함 1.00% · 해결: 직접 청산 또는 ops가 ad
2026-10-21T04:46:51+00:00 vultr python[34028]: 2026-10-21 04:46:51,992 WARNING live_v6.notify [tg:testnet] 🧪[TESTNET·모의] 🚨 기록 없는 포지션 발견 — DOGEUSDT 자동 청산 안 함 · 이 코인 신규 진입 차단 · 수동 처리 필요
2026-10-21T04:46:51+00:00 vultr python[34028]: DOGEUSDT 롱 100 @ 0.08145999999999999 · 손절 0.07619 (exchange (existing, untouched)) · 포트폴리오 위험에 포함 1.00% · 해결: 직접 청산 또는 ops가 adopt_position 으로 등록
2026-10-21T04:46:52+00:00 vultr python[34028]: 2026-10-21 04:46:52,827 WARNING live_v6.notify [tg:testnet] 🧪[TESTNET·모의] ▶️ live_v6 시작 · BinanceREST(https://testnet.binancefuture.com) · 포지션 0개 · 기록 없는 포지션 DOGEUSDT · 진입 가능
2026-10-21T04:46:53+00:00 vultr python[34028]: 2026-10-21 04:46:53,188 WARNING live_v6.notify [tg:testnet] 🧪[TESTNET·모의] 💓 작동 중 · 잔고 4732.02 USDT · 포지션 0개 · 기록 없는 포지션 DOGEUSDT · 진입 보류: stream_stale
state unknown: {"DOGEUSDT": {"side": 1, "detected_ms": 1792558011989, "stop_seq": 0, "amt": "100", "qty": "100", "entry_px": "0.08145999999999999", "stop_src": "exchange (existing, untouched)", "stop_px": "0.07619", "stop_cid": "v6DOGEu1792557963s0", "risk_usdt": "0.52504400", "risk_frac": 0.01}} | pos: [] | start_ms: 1792558012195
MainPID=12861
NRestarts=0

## R4-5 2026-10-21T04:47:46Z: cleanup — close the drill position BY HAND on the TESTNET (reduceOnly MARKET, client id drillR4close…)
CLOSE BY HAND (testnet): {'orderId': 2369931304, 'clientOrderId': 'drillR4close1792558068', 'status': 'FILLED', 'executedQty': '100', 'avgPrice': None, 'updateTime': 1792558068891, 'http': None, 'body': None} 13:47:48.891 KST
position: [('0', '0.0', '0.08144000', 'isolated')]
open algo stops: []
open std orders: 0
orders last 3h (non-algo): [(2369898332, 'v6DOGE1792545935x0', 'SELL', 'FILLED', 'reduceOnly=True', '9628', '13:00:03.812 KST'), (2369930402, 'drillR4open1792557961', 'BUY', 'FILLED', 'reduceOnly=False', '100', '13:46:01.774 KST'), (2369931304, 'drillR4close1792558068', 'SELL', 'FILLED', 'reduceOnly=True', '100', '13:47:48.891 KST')]
-- 20 s later --
position: [('0', '0.0', '0.08143419', 'isolated')]
open algo stops: []
open std orders: 0
orders last 3h (non-algo): [(2369898332, 'v6DOGE1792545935x0', 'SELL', 'FILLED', 'reduceOnly=True', '9628', '13:00:03.812 KST'), (2369930402, 'drillR4open1792557961', 'BUY', 'FILLED', 'reduceOnly=False', '100', '13:46:01.774 KST'), (2369931304, 'drillR4close1792558068', 'SELL', 'FILLED', 'reduceOnly=True', '100', '13:47:48.891 KST')]
2026-10-21T04:47:50+00:00 vultr python[34028]: 2026-10-21 04:47:50,493 WARNING live_v6.notify [tg:testnet] 🧪[TESTNET·모의] ✅ 기록 없는 포지션 해소 — DOGEUSDT 100 거래소에서 0 · 이 코인 신규 진입 재개
state unknown: {} | pos: []
MainPID=12861
NRestarts=0

## R4-6 2026-10-21T04:48:15Z: canary back to ci-deploy ca87f85 via CI (so the R1 confirm at 17:05 KST has its pending marker from a process that lives through the 17:00 close)
server job 20261021T044818Z-611c6c started (detached on the VPS)
[2026-10-21T04:48:19Z] [testnet] action=deploy dry_run=0 current=2c1eb769bc0f0d9792722cde08cb8f4182d3cc17 unit=active
import ok, tick calls on_bar_close
[2026-10-21T04:48:19Z] [testnet] import check OK for ca87f853d7cb9c3d3d1bd62246e08a06b72fc5cb (user=tradebot-ci, sandbox: no network, denied: -/etc/tradebot -/var/lib/live_v6-live -/opt/tradebot/app -/var/log/tradebot -/root -/var/lib/tradebot-ci/uploads -/opt/tradebot)
[2026-10-21T04:48:19Z] [testnet] time window OK (04:48 UTC: ≥900s after the last 4h close, ≥1200s before the next)
[2026-10-21T04:48:19Z] [testnet] unit live_v6-citest TimeoutStopUSec=30s (SIGTERM → runner finishes the current event; SIGKILL after this)
  verify-stops: pass=True positions=0 []
[2026-10-21T04:48:19Z] [testnet] verify-stops exit=0
[2026-10-21T04:48:19Z] [testnet] state: no in-flight intents
[2026-10-21T04:48:19Z] [testnet] state backed up
[2026-10-21T04:48:19Z] [testnet] /opt/tradebot-ci-testnet/app/ca87f853d7cb9c3d3d1bd62246e08a06b72fc5cb already installed (reusing; marker absent)
[2026-10-21T04:48:19Z] [testnet] symlink current → ca87f853d7cb9c3d3d1bd62246e08a06b72fc5cb
[2026-10-21T04:48:24Z] [testnet] restarted live_v6-citest at 04:48:19Z; verifying strictly (≤240s)
[2026-10-21T04:48:34Z] [testnet]   state: health ok, last_bar_close=1792555200000 boundary=1792555200000 models=6 all caught up, positions=0
  verify-stops: pass=True positions=0 []
[2026-10-21T04:49:20Z] [testnet] verify-stops exit=0
[2026-10-21T04:49:20Z] [testnet] verification PASSED
[2026-10-21T04:49:20Z] [testnet] marker PENDING for ca87f853d7cb9c3d3d1bd62246e08a06b72fc5cb: .citest_verified is granted only after the first real 4h close after this restart is processed for all 6 coins (confirm timer, close + 5 min); rollback target meanwhile: 660eea8eac39a0962ef86ff3f083939e9ddaa6a2
[2026-10-21T04:49:20Z] [testnet] DEPLOYED ca87f853d7cb9c3d3d1bd62246e08a06b72fc5cb (previous: 2c1eb769bc0f0d9792722cde08cb8f4182d3cc17). Heartbeat script NOT changed (manual step, runbook §5).
job 20261021T044818Z-611c6c finished OK
[2026-10-21T04:49:24Z] [testnet] current=ca87f853d7cb9c3d3d1bd62246e08a06b72fc5cb sha=ca87f853d7cb9c3d3d1bd62246e08a06b72fc5cb marker=pending-first-real-close manual_rollback_target=660eea8eac39a0962ef86ff3f083939e9ddaa6a2 failed_deploy_rollback_target=660eea8eac39a0962ef86ff3f083939e9ddaa6a2 window_wait=0s intents=0
MainPID=12861
NRestarts=0

