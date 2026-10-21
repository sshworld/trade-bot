# R4 — full 51 testnet run + TA stop-cancel drill (VPS, one session) — code 2eb429b (r4-testnet-findings)
Run: VPS 198.13.39.149, tmux `r4run`, 2026-10-21 21:29:39 → 21:39:52 KST. Raw log: `2026-10-21_R4_testnet51_drill_run.log`.
Code = 7fa2c45 + drill script only (live_v6/tests/drill_stop_cancel.py, not collected by pytest). No engine change needed.

## Prep (before citest stop)
`~/.venv-tbtest/bin/pip install -r live_v6/requirements-dev.txt` (from this commit) → `import numpy, pandas` OK
(numpy 2.5.4, pandas 3.0.6, pytest 9.1.1). Collection: 51/216 selected with `-m testnet`.

## A. 51 testnet-marked tests
**45 passed, 0 failed, 6 skipped** (576 s). The 6 skips are the `[offline]` parametrisations of testnet-only tests
(test_gate_sigkill.py:54, :69; test_streams.py:305, :333, :362, :404 — "testnet only"); their `[testnet]` twins all passed.
vs 7dda201 (39/6/6): the numpy/pandas collection failure and the 5 isolation/429-418 failures are gone.

## B. Stop-cancel drill (real engine + real user-data stream, testnet)
* Entry DOGEUSDT long qty 9438 @0.082060, stop 0.0796, cid v6tDOGE1792586363; exchange stop = algo 1000000250000559 `…s0`
  (closePosition). Our own cancel of the pre-arm `…p` → ALGO_UPDATE CANCELED → ignored (no alert), as designed.
* Manual cancel of `…s0` by a separate REST client (not via the engine) at 21:39:32.774 KST. Binance reported it as
  **ALGO_UPDATE** (no ORDER_TRADE_UPDATE for algo stops):
  `{"e":"ALGO_UPDATE","T":1792586372783,"E":1792586372786,"o":{"caid":"v6tDOGE1792586363s0","aid":1000000250000559,"at":"CONDITIONAL","o":"STOP_MARKET","s":"DOGEUSDT","S":"SELL","ps":"BOTH","f":"GTE_GTC","q":"0","X":"CANCELED","ai":"","tp":"0.0796","p":"0","V":"EXPIRE_MAKER","wt":"MARK_PRICE","pm":"NONE","cp":true,"pP":false,"R":true,"tt":0,"gtd":0,"ia":false}}`
* 🚨 alert 9 ms after the event (notify sink, mode testnet, sent=false → Telegram silent):
  `{"event_ts": "2026-10-21T12:39:32.786Z", "decision_ts": "2026-10-21T12:39:32.795Z", "delay_s": 0.009, "type": "alert", "mode": "testnet", "sent": false, "text": "🧪[TESTNET·모의] 🚨 손절 주문 CANCELED 감지 — DOGEUSDT 즉시 재등록\nv6tDOGE1792586363s0 · 손절 0.0796 · 수량 9438"}`
* Replacement stop: algo **1000000250000751** `v6tDOGE1792586363s1` (same 0.0796, closePosition), ALGO_UPDATE NEW at
  E=1792586372824 (38 ms after the cancel event); ✅ 손절 재등록 완료 recorded; `stop_lost` cleared.
* Cleanup: engine reduceOnly close (drill_end) → `…s1` EXPIRED (closePosition stop, no alert). FINAL: positions none,
  open orders none. Files: `2026-10-21_R4_drill_out/` (drill_log.txt — times there are UTC; drill_user_events.jsonl; drill_alerts.jsonl).

## After
testnet leftovers: positions none | open orders none. citest: active, PID 49518, NRestarts 0, on ca87f85.
live_v6-live: active PID 36258 NRestarts 0 before and after (never touched). Telegram: every record mode=testnet sent=false.
