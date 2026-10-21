# R4 testnet run (7dda201, evidence 2cf9309) — root cause of the 6 failures, skips, test deps
Author: Developer agent, 2026-10-21 17:40 KST. Base: origin/fix-unknown-position @ 2cf9309. Nothing deployed.
Tests and expected values are NOT changed on this branch; the proposed test change is a diff for TA review only:
`2026-10-21_R4_proposed_test_changes.diff` (validated offline: with it applied the offline suite is 157 passed).

## 1. entry_orders mismatch (3 tests) — TEST ISOLATION / COUNTING BUG, not a bot bug
Failed: test_no_averaging (2≠1), test_kill_after_fill_then_restart (2≠1), test_restart_multiple_positions_rearms_all (3≠1).
* `Backend.entry_orders(sym, t0)` (conftest.py:84) counts distinct order ids of BUY userTrades since t0, and the tests
  set `t0 = now − 5000 ms` (test_faults.py:104/128/196/213/238/484). The testnet account is shared by all tests of the
  run, which run back to back (≈1–3 s each), so the window also contains the PREVIOUS test's entry (each test uses its
  own signal time from unique_T(), i.e. a distinct clientOrderId, closed by a `v6tclean…` reduceOnly SELL).
* Exchange order history (read-only allOrders + userTrades, DOGE/SOL/XRP, 17:20–17:31 KST): 47 entry orders
  (BUY MARKET, not reduceOnly), 47 distinct clientOrderIds (one per signal), 0 duplicate clientOrderIds, 0 BUY orders
  outside the engine prefix, 0 orphan trades. No entry was sent twice.
* Re-run of ONLY these 3 tests against live code 0d82b19 on testnet (VPS, ops, citest stopped and restarted by trap,
  one pytest call per test with 15 s between): 3/3 PASSED (17:34:44–17:35:21 KST). Order history of that window: exactly
  one entry BUY per test and symbol — DOGE v6tDOGE1792571684 / …701 / …719, SOL v6tSOL1792571720, XRP v6tXRP1792571722,
  each followed by its v6tclean close. With 15 s spacing the −5 s window no longer reaches the previous test → passes.
* Mainnet verdict: no duplicate-entry path found for 0d82b19 or 7dda201. The entry/client-id/exchange code and these
  tests are identical in both commits (7dda201 only changes the unknown-position handling).
* Proposed fix (diff): t0 = exchange server time taken after fixture cleanup, no backward margin; count allOrders BUY,
  not reduceOnly, clientOrderId prefix `v6t` (not `v6tclean`), time ≥ t0.

## 2. 429/418 (3 tests) — STALE TEST EXPECTATION (predates 002c069), not a bot bug
Failed: test_http_faults_map_to_unavailable[http429], [http418]: "next call fine" got
`RateLimited: … rate-limit backoff 10s/120s (not sent)`; test_overreaction_429_once: second reconcile refused the same way.
Design since 002c069 (09:24 KST): Retry-After honoured (default 429 → 10 s, 418 → 120 s).
* `exchange.py:144 _req`: `if clock() < backoff_until and not critical: raise RateLimited("… (not sent)")` — non-critical
  calls (account, book, entry MARKET, klines…) are refused LOCALLY during the backoff → new entries blocked. ✔
* `critical=True` (sent DURING the backoff, never waiting): positionRisk, openOrders/openAlgoOrders, reduceOnly MARKET
  (position close), algoOrder (stop placement), get_order, cancel (algo/std).
* engine.tick (engine.py ~1283): during the backoff → block RATE_LIMIT, no reconcile/on_bar_close; mark-stream
  breach_check still closes reduceOnly; ensure_stop still places stops. After the backoff → unblock + `_dirty=True` →
  reconcile on the FIRST tick after (re-arms a missing stop, resumes entries).
Evidence (offline): test_rate_limit.py::test_rest_418_backoff_only_protective_calls_sent,
::test_engine_418_blocks_entries_keeps_protection_never_flattens, and new test_rate_limit_resume.py:
::test_missing_stop_rearmed_on_first_tick_after_backoff (418, 120 s ban, stop disappears inside the ban → still missing
after 115 s of ticks, re-armed on the first tick after the ban), ::test_reduce_only_close_and_stop_sent_during_backoff.
Caveat for TA: a stop that disappears DURING a backoff is detected by the paused reconcile only after the backoff
(≤ Retry-After; 418 default 120 s). Meanwhile the mark-stream breach_check is the protection (reduceOnly close is
critical). Option if TA wants it: let reconcile run a protective-only pass (positions + openOrders are critical) during
the backoff. Not implemented here.
Proposed test fix (diff): assert `RateLimited … not sent` during the backoff, then simulate Retry-After elapsed
(`backoff_until = 0`) before "next call fine" / second reconcile.

## 3. Skips (6) — the [offline] parametrisations of testnet-only tests; expected
`-m testnet` selects the whole test function (function-level `@pytest.mark.testnet`), so BOTH backend params are
collected; the [offline] instance skips itself with "testnet only". Their [testnet] instances RAN and passed.
| test | skip at |
|---|---|
| test_gate_sigkill.py::test_gate_sigkill_multiple_positions_all_stops_present[offline] | :54 |
| test_gate_sigkill.py::test_gate_sigkill_right_after_entry_fill[offline] | :69 |
| test_streams.py::test_testnet_market_stream_drop_and_resubscribe[offline] | :305 |
| test_streams.py::test_testnet_user_stream_fill_and_keepalive[offline] | :333 |
| test_streams.py::test_testnet_overreaction_ws_down_30s[offline] | :362 |
| test_streams.py::test_testnet_market_stream_killed_stale_guard[offline] | :404 |
So "51" = 45 real testnet cases (39 passed + 6 failed) + 6 offline shadows. Earlier 51-test runs today (runs 1–2)
never got past collection (ModuleNotFoundError numpy, then pandas) → no earlier skip list exists to compare.
(DEPLOY_950438b.md "SKIPPED list empty" refers to the OFFLINE suite, not `-m testnet`.)

## 4. Test deps
requirements-dev.txt now pins numpy==2.5.4, pandas==3.0.6. Proposed run-script change (before stopping citest):
```bash
[ -x ~/.venv-tbtest/bin/python ] || python3 -m venv ~/.venv-tbtest
~/.venv-tbtest/bin/pip install -q -r live_v6/requirements-dev.txt          # always, from the archived commit (idempotent)
~/.venv-tbtest/bin/python -c 'import numpy, pandas, pytest, httpx, websockets' || { echo "test venv incomplete"; exit 1; }
```
