# 2026-10-22 01:39:18 KST — BNBUSDT "레버리지 10x 설정 실패 — 진입 건너뜀 | read-back 20x" (live, 2eb429b)

- Journal (live_v6-live, PID 51227, NRestarts 0): 16:39:18.793 UTC `skip BNBUSDT leverage: set 10x failed: read-back 20x` + 🚨.
- Path (engine.enter): positions() [/fapi/v2/positionRisk] showed 20x → POST /fapi/v1/leverage 10 returned 2xx (no
  exception; body discarded by 2eb429b) → positions() again [/fapi/v2/positionRisk] still 20x → skip + 🚨.
- Read-only check 01:52 KST (GET only): /fapi/v1/symbolConfig BNBUSDT leverage 10, /fapi/v2/positionRisk BNBUSDT 10.
  The set DID apply; the immediate positionRisk read lagged it. BNB was at the 20x account default (never set before).
- No ACCOUNT_CONFIG_UPDATE evidence exists: the mainnet user stream subscribes only to USER_EVENTS (stream.py), which
  does not include ACCOUNT_CONFIG_UPDATE, and parse_user drops unknown events.
- Fix (this branch): set_leverage returns the leverage echoed in the response; if positionRisk still disagrees AND the
  response echoed the requested value, confirm on GET /fapi/v1/symbolConfig. Real mismatch → same skip + 🚨 (detail
  now includes symbolConfig and the set response). No other behaviour change.

---
# TA review of 1ffa86c (02:19 KST 10/22) — conditions before live

## Progress checkpoints (KST)
- 02:24 offline: fail-safe fix + tests written; offline suite (LIVE_V6_REQUIRE_PYLINT=1, -m "not testnet and not slow")
  189 passed, 53 deselected (167 before + 22 new).
- 02:25 code commit e2695d9 (pushed to fix-leverage-readback). Code frozen from here; later commits = evidence only.
- 02:26–02:27 testnet drill on e2695d9: PASS (§4).
- 02:28–02:38 51 testnet set on e2695d9: 45 passed, 6 skipped (offline params of testnet tests), 0 failed (§5).

## 1. symbolConfig failure is fail-safe — FOUND A HOLE in 1ffa86c, fixed
- 1ffa86c engine.py:672 `cfg_lev = self.x("leverage", sym)` sat inside `try … except ExchangeError`. Every transport /
  HTTP failure (timeout, 5xx, 429, 418, local backoff/ban refusal, 4xx reject) is an ExchangeError subclass → skip + 🚨
  (OK). BUT exchange.py `leverage()` parsed with `int(r["leverage"])` / `r.get(...)`: a 200 with a malformed body (row
  without `leverage`, non-numeric leverage, non-dict row) raised KeyError / ValueError / AttributeError, which escaped
  `enter()` and `execute()` (engine.py:405-424) → the remaining coins' entries of that bar were never attempted
  (last_bar_close already committed). Reproduced on 1ffa86c by
  `test_symbolconfig_failure_skips_alerts_and_next_bar_enters[exception-positionRisk_lags]` (KeyError escapes) and
  `test_symbolconfig_failure_on_one_coin_does_not_stop_the_others_in_the_bar[exception]`.
- Fix: exchange.py `leverage()` converts any parse failure into ExchangeError; `set_leverage()` returns None for an
  unparseable echo; engine `_confirm_leverage()` never raises (ExchangeError → reason text; any other Exception →
  log.exception + reason text). State before the skip point: no intent journaled, no pre-armed stop, no order, no
  journal row (the leverage gate runs before `_prearm`), so a skip leaves nothing half-done.
- Tests (tests/test_leverage_failsafe.py): 6 failure modes (exception, timeout, rejected, http429, http418,
  backoff_active) × positionRisk ok / lagging = 12 cases: enter() returns False without raising, skip_log reason
  `leverage` with "symbolConfig failed", 🚨 "레버리지 … 진입 건너뜀" (418 also its own IP-ban 🚨), no position / intent /
  stop / order, risk book unchanged, then after backoff/ban + recovery ticks the SAME coin enters normally with a stop.
  Plus: same-bar DOGE fails / SOL still enters; REST-level: 10 failure bodies/statuses all raise ExchangeError
  subclasses; nothing sent during backoff/ban.

## Gate rule (aligned with TA's wording "설정 응답과 symbolConfig가 모두 요청값과 같을 때만 진입")
- 1ffa86c read symbolConfig only when positionRisk disagreed. Now: whenever POST /fapi/v1/leverage was sent, entry
  requires set response == requested AND symbolConfig == requested; one log line always records all three values
  (`<SYM> leverage Nx: set response Nx, positionRisk Mx, symbolConfig Kx`). No set needed (already at the target) →
  unchanged (positionRisk read-back only). Cost: one extra GET (weight 1) only on an entry that changes leverage.

## 2. Liquidation guard leverage — already the confirmed value (no code change needed)
- The only liquidation computation is the sizing guard: sizing.py:64 `lev = choose_leverage(...)` (planned leverage from
  stop distance, bracket max, MMR) → sizing.py:67 `liquidation_ok(stop_frac, lev, mmr, 0.7)` (rules.py:79-81,
  stop ≤ 0.7 × (1/L − MMR)) → sizing.py:72 margin `notional / lev` → Sized.lev. Unchanged 2eb429b → 1ffa86c → now.
- positionRisk's `leverage` is NOT an input to sizing; it is only read in the gate (1ffa86c engine.py:666/669; now
  engine.py:686/689/692-693). The gate makes sz.lev the exchange-confirmed leverage before any order: now via
  `_confirm_leverage` (engine.py:620-642: set response == sz.lev AND symbolConfig == sz.lev), else skip. The journaled
  `lev` (engine.py:715 intent, :786 position) is sz.lev = confirmed. No liqPrice from positionRisk is used anywhere.
- Test: test_liq_guard_and_margin_use_confirmed_leverage_not_stale_positionrisk (positionRisk lags at 20x, set +
  symbolConfig 10x → journal lev 10 == exchange, liquidation_ok at 10x).

## 3. Why test_leverage_really_unchanged_still_skips_with_alert fails on 2eb429b — confirmed: detail text only
- Run of the new tests against 2eb429b engine.py + exchange.py: the old engine DOES skip + 🚨 (same behaviour); the test
  fails only at `assert f"symbolConfig {old}x" in skip_log[-1][3]`:
  `AssertionError: assert 'symbolConfig 20x' in 'set 10x failed: read-back 20x'` — 2eb429b never reads symbolConfig.
- Correction to the earlier "2 of 4 fail on old code": with BOTH old files 3 fail — also
  test_rest_set_leverage_echo_and_symbolconfig_parse (`set_leverage` returned None in 2eb429b: body discarded).

## 4. Testnet drill — PASS (code e2695d9, VPS ~/tb-e2695d9…, live_v6-citest stopped 02:26:49–02:27:06 KST)
`python -m live_v6.tests.drill_leverage_readback` (tests/drill_leverage_readback.py), CI testnet key, DOGEUSDT; Notifier
token/chat empty, mode testnet → nothing sent to Telegram. VPS log stamps are UTC (17:26 UTC = 02:26 KST).
```
17:26:54 pre-check leftovers: positions none | open orders none
17:26:54 manual set DOGEUSDT 20x response: {"symbol": "DOGEUSDT", "leverage": 20, "maxNotionalValue": "900000"}
17:26:55 before: positionRisk 20 | symbolConfig raw (signed GET): [{"symbol": "DOGEUSDT", "marginType": "ISOLATED", "isAutoAddMargin": false, "leverage": 20, "maxNotionalValue": "900000"}]
17:26:56 enter() returned True | skip_log tail []
17:26:56 ENTERED DOGEUSDT qty 9321 entry_px 0.083200 lev 10 stop_px 0.08071 cid v6tDOGE1792603616 entry_order_id 2370411200
17:26:56 exchange stops: [('algo', '1000000250428238', 'v6tDOGE1792603616s0', '0.08071', True)]
17:26:56 after: positionRisk 10 | symbolConfig 10
17:26:56 entry order (GET): {"orderId": 2370411200, "status": "FILLED", "clientOrderId": "v6tDOGE1792603616", "avgPrice": "0.083200", "executedQty": "9321", "type": "MARKET", "reduceOnly": false, "side": "BUY", "updateTime": 1792603616480}
17:27:01 FINAL leftovers: positions none | open orders none
17:27:01 ENGINE LOG: 2026-10-21 17:26:56,396 WARNING live_v6.engine DOGEUSDT leverage 10x: set response 10x, positionRisk 10x, symbolConfig 10x
17:27:01 notifier records: 3 | sent to Telegram: 0 | new 🚨 during the entry: 0
17:27:01 DRILL PASS
```
Bot-client raw REST (signature/timestamp stripped), in order:
- POST /fapi/v1/leverage {DOGEUSDT, 10} → `{"symbol":"DOGEUSDT","leverage":10,"maxNotionalValue":"1800000"}` (t 1792603616356)
- GET /fapi/v2/positionRisk → DOGEUSDT `"leverage":"10"` (t …367; no lag on testnet this time)
- GET /fapi/v1/symbolConfig {symbol: DOGEUSDT}, signed → `[{"symbol":"DOGEUSDT","marginType":"ISOLATED","isAutoAddMargin":false,"leverage":10,"maxNotionalValue":"1800000"}]` (t …386)
- POST /fapi/v1/algoOrder pre-arm reduceOnly STOP_MARKET 9321 @0.08071 → algoId 1000000250428233
- POST /fapi/v1/order MARKET BUY 9321 cid v6tDOGE1792603616 → orderId 2370411200 FILLED avg 0.083200
- POST /fapi/v1/algoOrder closePosition STOP_MARKET @0.08071 → algoId 1000000250428238; pre-arm 1000000250428233 cancelled
- cleanup: engine reduceOnly MARKET SELL 9321 cid v6tDOGE1792603616x0 → orderId 2370411207 FILLED; positions/open orders 0
- live_v6-live PID 51227 NRestarts 0 before and after; citest restarted active (PID 57304, still ca87f853).
Full output: 2026-10-22_leverage_readback_drill.txt.

## 5. 51 testnet set on the final code head e2695d9 — 45 passed, 6 skipped, 0 failed
- VPS ~/tb-e2695d9…, ~/.venv-tbtest: `pip install -r live_v6/requirements-dev.txt` OK; `import numpy, pandas, pylint` OK
  (numpy 2.5.4, pandas 3.0.6). live_v6-citest stopped 02:28 → restarted active at 02:38 KST (PID 57986, still ca87f853).
- `pytest live_v6/tests -m testnet -v`: collected 248 / 197 deselected / 51 selected → **45 passed, 6 skipped, 593.5 s,
  rc 0**. The 6 skips are the `[offline]` parameters of testnet-marked tests ("testnet only"), same 51-structure as R4
  (39+6 failed+6 skipped = 51 on 2026-10-21 attempt 3).
- After: testnet DOGE/SOL/XRP positions none, open orders none. live_v6-live PID 51227 NRestarts 0 before and after.
- Full log: 2026-10-22_leverage_readback_testnet51.txt.

## State / not done
- NOT deployed to live. Live = 2eb429b, PID 51227, NRestarts 0 throughout.
- citest's own testnet BTCUSDT/BNBUSDT positions (its state file) were not touched; the drill and the 51 only use
  DOGE/SOL/XRP and both ended at 0 positions / 0 open orders there.
