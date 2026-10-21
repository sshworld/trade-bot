# BNBUSDT leverage read-back 🚨 — 2026-10-22 01:39:18 KST (live_v6-live, release 2eb429b)

Status: investigation complete (read-only on VPS). Fix on branch `fix-leverage-readback` (local worktree
/workspace/fix-leverage-readback, NOT deployed). Push pending user approval at time of writing.

## Log evidence (journalctl -u live_v6-live; VPS clock UTC)
```
2026-10-21T16:39:18 WARNING  live_v6.engine skip BNBUSDT leverage: set 10x failed: read-back 20x
2026-10-21T16:39:18 CRITICAL live_v6.engine 🚨 레버리지 10x 설정 실패 — 진입 건너뜀 | BNBUSDT read-back 20x
2026-10-21T16:39:18 WARNING  live_v6.notify [tg:live] 🚨 레버리지 10x 설정 실패 — 진입 건너뜀 / BNBUSDT read-back 20x
```
- Only occurrence ever: full journal grep for read-back/leverage → this one event. State skip_log since start: 1×
  BTC min_notional (23:35 KST), 1× BNB leverage (01:39 KST). alerts-live.jsonl: same single 🚨, sent=true.
- PID 51227, NRestarts 0 (unchanged since deploy 21:48:55 KST). Positions 0, open orders 0.

## Code path (2eb429b engine.enter, exchange.py)
1. `positions()` = GET /fapi/v2/positionRisk → BNB leverage 20 (≠ sz.lev 10)
2. `set_leverage()` = POST /fapi/v1/leverage → 2xx, response body DISCARDED (not logged)
3. `positions()` again = GET /fapi/v2/positionRisk → still 20 → skip + 🚨
Read-back endpoint = /fapi/v2/positionRisk (deprecated v2; v3 has no leverage field and returns [] when flat).

## Raw responses
- Raw set-leverage response and raw read-back response: NOT available — 2eb429b does not log either body
  (set_leverage returns nothing; positions() logs nothing). Log level shows WARNING+ only.

## ACCOUNT_CONFIG_UPDATE (TA addition 1)
- No such line can exist: mainnet user stream URL subscribes `events=ORDER_TRADE_UPDATE/ACCOUNT_UPDATE/ALGO_UPDATE/
  STRATEGY_UPDATE/CONDITIONAL_ORDER_TRIGGER_REJECT/listenKeyExpired` (stream.py USER_EVENTS); ACCOUNT_CONFIG_UPDATE is
  not subscribed and parse_user() would drop it anyway. Journal 16:20–16:52 UTC has only the 3 lines above.
- So a user leverage change in the app cannot be proven or excluded from bot logs. But it is not needed to explain the
  event: see below.

## Current leverage (read-only GET, 01:52 KST)
| coin | symbolConfig | positionRisk v2 | margin |
|---|---|---|---|
| BTC | 5 | 5 | ISOLATED |
| ETH | 20 | 20 | ISOLATED |
| SOL | 20 | 20 | ISOLATED |
| BNB | **10** | **10** | ISOLATED |
| XRP | 20 | 20 | ISOLATED |
| DOGE | 20 | 20 | ISOLATED |
One-way mode (dualSidePosition=false). 20x = Binance default (never set by bot); BTC 5x set earlier.

## Root cause
The set call DID apply (BNB is 10x now on both endpoints; nothing else sets leverage to 10x). The immediate
/fapi/v2/positionRisk read-back returned the pre-change value (stale/lagging snapshot). Bot-side read-back race,
not a failed set and not (necessarily) a user change: if the user had set 20x at 01:28–01:39, the bot's 10x set
would still have applied and the result would be the same.

## Going forward
- BNB: not blocked. BNB is now 10x; next BNB entry needing 10x skips the set call and passes. Only blocked again if a
  future sizing needs a different leverage (same race).
- Same race can hit ETH/SOL/XRP/DOGE (still at default 20x) on their first entry, and any coin whenever sz.lev changes.
- 🚨 repeat rate: at most once per coin per 4h bar. h7t marks `b["entered"]=True` before the order; the skipped
  signal is consumed (model goes virtual-long), no retry that bar → that trade is missed. No per-tick spam.

## Fix (branch fix-leverage-readback from 2eb429b)
- exchange.set_leverage returns the leverage echoed in the response body.
- new exchange.leverage(sym) = GET /fapi/v1/symbolConfig?symbol=…
- engine: if positionRisk read-back ≠ requested AND set response echoed the requested value → confirm on
  symbolConfig; proceed only if it matches. Otherwise unchanged skip + 🚨 (detail now includes symbolConfig + set
  response). WARNING log line records set response / positionRisk / symbolConfig values.
- Tests: tests/test_leverage_readback.py (4 new). Offline suite with LIVE_V6_REQUIRE_PYLINT=1:
  167 passed, 53 deselected (testnet/slow). New lag test fails on 2eb429b engine (reproduces incident).
