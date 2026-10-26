# sizing-minorder-3pct — TESTNET evidence (2026-10-26 KST)

Branch `sizing-minorder-3pct` (code under test: `bd7a789`, on top of pushed `994e138`). Author: sshworld. Nothing deployed, nothing pushed to main,
no VPS service touched, no mainnet key used (`BINANCE_API_KEY/SECRET` removed from the process, `LIVE_V6_FORBID_MAINNET=1`, base URL
`https://testnet.binancefuture.com`). The testnet keys came from the box env (`BINANCE_TESTNET_*`) and were never printed (artifacts grep-checked for the
key string; request signatures redacted).

## 0. Telegram: nothing was sent
* Drill (`live_v6/tests/drill_sizing_testnet.py`): `Notifier(mode="testnet")` → `.live == False`, empty token/chat id, `TELEGRAM_*`/heartbeat env removed, and
  `notify._http_post` (the ONLY Telegram path) replaced by a tripwire that raises. Result: `telegram_posts = 0` (`drill_results.json`). Every alert record
  has `sent=False` (the "[tg:testnet] …" lines in `drill_log.txt` are log-only). Alerts 🚨 are only logged/queued.
* The 51-test run uses the harness's `NullNotifier` (mode "null") — no network path at all.
* `notify.Notifier.send` talks to Telegram only when `mode == "live"`.

## 1. Deviations from the 10/21 recipe (please note)
1. **Symbols swapped.** The 10/21 harness uses DOGE/SOL/XRP and its per-test cleanup flattens + cancels everything on those symbols. The testnet account is
   **shared with the VPS canary `citest`** (BTC/ETH/SOL/BNB/XRP/DOGE), so I did not touch any of the six. The drill used **ADAUSDT** (and ALLUSDT for the LOT_SIZE
   case); the 51-test run used a temp copy of the tree with `DOGEUSDT→ADAUSDT, SOLUSDT→LTCUSDT, XRPUSDT→TRXUSDT` (tests/conftest/bot_proc only; `FILT_STEP`
   adjusted; no assertion changed). The 6 `[offline]` variants of the 51 are "testnet only" skips and were run in the unmodified tree (no network).
2. I did not stop `citest` (no VPS access/changes). Account-wide final check: 0 non-zero positions on **all** symbols, 0 open orders, 0 algo orders.

## 2. Drill results (`drill_results.json`, `drill_stdout.txt`; run 2 = DRILL PASS, 10:24–10:29 KST)
Real `V6Engine` + real `BinanceREST` against testnet. Only the *inputs* are injectable (wallet via an `account` wrapper; the "precheck bypass" is a
`market`/`stop` wrapper that changes qty/trigger AFTER the engine sized and pre-armed validly). Sizing inputs (exchangeInfo, brackets, book, mark price) are always read live.
After every case: positionRisk / openOrders / algo orders checked flat, `st["pos"]` and intents empty, the skip reason logged, alert records `sent=False`.

| # | case | result | key facts |
|---|---|---|---|
| 4 | read path: `BinanceREST.mark_price` + fresh exchangeInfo / brackets / book / account | PASS | mark 0.20387226 (`Decimal`), book 0.20380/0.20390, tick 0.0001, step 1, minQty 1, minNotional 5, market max 10 000 000, PERCENT_PRICE 0.95..1.05, 8 brackets (0..10 000: mmr 0.65%, 75×); engine's fresh calls in order: `exchange_info, brackets, book, mark_price, account` |
| 1 | **min-qty entry (`qty_floor`) → full sequence → full exit** (wallet injected 10 USDT) | PASS | q0 = 8 < minimum → **qty 26**, fill 0.20390, **notional 5.3014**, **stop 0.1978**, 10×, stop loss 0.1586 USDT, **loss incl. fees+slippage 0.1692 = 1.692 % of wallet** (log: 1.68 %; cap 3 %); fresh recompute (ref 0.2039, mark 0.20402) q_min 26 / 5.3014 / 1.692 %. Call order: `positions, open_orders, exchange_info, brackets, book, mark_price, account, positions, exchange_info, brackets, book, mark_price, account, stop(pre-arm), get_order, market, stop(closePosition), open_orders, cancel(pre-arm), positions` — then one full reduceOnly exit → flat. |
| 2a | skip: tiny wallet 2 USDT | PASS | no order; `skip ADAUSDT min_order_risk_over_cap: q0=1 < exchange minimum; min qty 26 (minNotional 5, minQty 1) loses 0.1676 = 8.38% of wallet 2.00 > 3%`; calls = reads only |
| 2b | skip: high ATR (stop 30 % of price, wallet 10) | PASS | no order; `min_order_risk_over_cap: q0=0 < exchange minimum; min qty 26 … loses 1.6002 = 16.00% of wallet 10.00 > 3%` (q0=0 goes to the min-qty path → spec label, not `qty_zero`) |
| 3a | **−4164** min notional (bypass: qty 1 sent instead of 25) | PASS | exchange `-4164: Order's notional must be no smaller than 5`; pre-arm live at send, **cancelled**; skip `entry_rejected`; 🚨 "진입 주문 거절 — 선행 손절 취소, 포지션·기록 없음" (queued, `sent=False`); flat |
| 3b | **−2019** margin (bypass: leverage 1×, qty 30 000) | PASS | `-2019: Margin is insufficient.` → same handling |
| 3c | **−2021** on the PRE-ARM stop (trigger 5 % above mark) | PASS | `WouldTrigger -2021` → skip `stop_prearm`, **no entry sent**, nothing to cancel, flat |
| 3d | entry fills, closePosition stop rejected (−2021) → **full flatten + 🚨** | PASS | market filled 25, stop `-2021`, one reduceOnly flatten, CRITICAL "🚨 진입 체결 후 손절 거절 — 전량 청산", exit reason `stop_rejected_after_fill`, net −0.0116 USDT, pre-arm cancelled, flat |
| 3e | LOT_SIZE-class: qty off-step 26.5 | PASS | testnet answers **−1111** (precision) → `entry_rejected`, pre-arm cancelled, flat |
| 3f | MARKET_LOT_SIZE-class: qty above market max 10 000 001 | PASS | **−4005** → same |
| 3g | LOT_SIZE below minQty (ALLUSDT, qty 5 < 10) | PASS | **−4004** → same |
| 3h | tick/precision: pre-arm trigger with 7 decimals | PASS | **−1111** → `stop_prearm`, no entry, flat |
| 3i | raw probes (no engine): −1013 / PERCENT_PRICE / tick | informational | see §3 |

### Rejection types that testnet does NOT produce — exact reasons and the offline tests that cover them
Raw probes (3i, real testnet answers): qty below minQty `-4004`; qty 0 `-4003`; off-step qty `-1111`; qty above max `-4005`; stop trigger with 5 decimals but off the 0.0001 tick
**ACCEPTED** (algo STOP_MARKET id …332, cancelled by sweep); trigger with 7 decimals `-1111`; reduceOnly stop at 0.5×mark (far outside PERCENT_PRICE) **ACCEPTED**;
closePosition stop with no position `-4509`. A literal **−1013 "Filter failure"** was never returned by this testnet for MARKET/STOP_MARKET:
* **PRICE_FILTER (tick)** — testnet accepts any price within `pricePrecision` for conditional orders and uses −1111 beyond it; no −1013.
* **PERCENT_PRICE** — not enforced on conditional/MARKET orders (the far stop was accepted); there is no limit price to violate on a MARKET entry.
* **LOT_SIZE / MARKET_LOT_SIZE** — surfaced as −4004 / −1111 / −4005 (covered live above) instead of −1013.
Covered offline (all in `live_v6/tests/test_sizing_minorder.py`, fake exchange raising `OrderRejected(-1013, …)` and the pure gate):
`test_entry_rejected_cancels_prearm_and_leaves_no_state[-1013 LOT_SIZE | -1013 MARKET_LOT_SIZE | -4164 | -2019 | -2021 | -4003]`,
`test_prearm_rejected_means_no_entry[OrderRejected(-1013, PRICE_FILTER)]`, `test_entry_fills_but_stop_rejected_flattens_everything_and_alerts[-1013 PRICE_FILTER …]`,
`test_gate_other_labels_are_distinct` (`tick`, `percent_price` both directions + edge, `stop_trigger`, `bracket`, `filter_read_failed`),
`test_boundary_min_notional_plus_minus_one_tick`, `test_boundary_min_qty_plus_minus_one_step`.

## 3. The 51 testnet tests (`pytest live_v6/tests -m testnet -v`)
Same marker/selection as 10/21 (51 collected = 45 `[testnet]` + 6 `[offline]` "testnet only" variants).

| | 10/21 (7dda201) | now (this branch) |
|---|---|---|
| passed | 39 | **45** |
| failed | 6 | **0** |
| skipped | 6 | **6** (the `[offline]` variants, "testnet only") |

* Run 1 (45 tests, ADA/LTC/TRX, 10:30–10:50 KST, 19 m 57 s): 43 passed, 2 failed — `test_gate_sigkill_multiple_positions_all_stops_present` and `…_right_after_entry_fill`
  with `KeyError: 'ADAUSDT'` in `bot_proc.py:53`: **my symbol-swap harness error** (`bot_proc.py` still hard-coded the old symbols). After swapping `bot_proc.py` too, those two re-ran
  alone: **2 passed** (77 s). No bot/product failure. Raw log: `testnet51_run1_ADA_LTC_TRX.txt`.
* The 6 failures of 10/21 now pass: `test_no_averaging`, `test_kill_after_fill_then_restart`, `test_restart_multiple_positions_rearms_all` (the `entry_orders` window-overlap isolation
  issue — tests unchanged, so this is timing luck/longer gaps between tests, not a fix) and `test_http_faults_map_to_unavailable[http429|http418]` + `test_overreaction_429_once`
  (stale 10/21 expectations vs the 002c069 backoff design; `499407e` landed after that run). I did not change any test or expected value. The isolation weakness in the 3 `entry_orders` tests is still there.
* Offline: `LIVE_V6_REQUIRE_PYLINT=1 pytest live_v6/tests -m 'not testnet and not slow'` → **287 passed**, 53 deselected.

## 4. Final state
Flat: 0 non-zero positions on **all** symbols (positionRisk unfiltered), 0 open orders, 0 algo orders (checked after the last test, 10:54 KST). Leftover test orders from an early drill attempt
(an off-tick stop probe and one real entry in drill run 1) were removed by the sweep; none remain.

## 5. Bugs found
None in product code from the testnet runs. Drill-script bugs fixed (read-path `eng.startup()`; 3h trigger precision) — test tooling only.
