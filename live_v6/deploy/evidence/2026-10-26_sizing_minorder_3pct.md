# Sizing v2.1 — minimum-order rule with 3% loss cap (branch `sizing-minorder-3pct`, base `4d8d16c`)

Spec: TA `sizing-spec-minorder-3pct.md` (v2.1). Scope of this change: **offline only** — no deploy, no testnet run, no orders.
Written 2026-10-26 (KST). Replay data: public Binance futures klines fetched through the VPS at 2026-10-26 10:04 KST.

## 1. What changed

| area | change |
|---|---|
| `rules.py` | `SymbolRules` now carries LOT `maxQty`, `MARKET_LOT_SIZE` (min/step/max), `PERCENT_PRICE` (up/down) from the exchangeInfo just read. `order_step/order_min_qty/order_max_qty` = the market-order limits. **`min_notional_floor` removed** (`from_exchange_info`, `rules_from_info`, `Settings`): the effective minimum is the exchange `MIN_NOTIONAL`. A missing required filter raises → skip `filter_read_failed`. |
| `sizing.py` | `size_entry` = q0 path (`floor_step(0.5% · W / D)`, today's 0.5% and fee-inclusive 1% caps, 2.5% open-risk cap) **or** `qty_floor` path (only when q0 is below the exchange minimum): `q_min = ceil_step(minNotional / (P·0.98))` ≥ minQty; enter only if `(q·D + q·P·(2·0.0005+0.0004+0.0003))/W ≤ 3%`, else `min_order_risk_over_cap`; open-risk sum ≤ 5% else `total_risk_cap`. New **pure** `precheck_order(...)` (no I/O). |
| `engine.py` | `_size_fresh`: every sizing pass re-reads `exchange_info`, leverage bracket, book, mark price (when PERCENT_PRICE exists), account; any failure → skip `filter_read_failed`, **no order**. `enter()` sizes twice (before and after the leverage confirm; the 2nd pass uses the confirmed leverage) so qty/minNotional/margin/bracket are recomputed right before the order. Rejection sequence fixed (see §4). |
| `exchange.py` | `BinanceREST.mark_price(symbol)` (premiumIndex). |
| `strategies/h7t.py` | bar-close line reports `entered:qty_floor` for a minimum-quantity entry. |
| tests | `fakes.py` now enforces real LOT/MARKET_LOT/MIN_NOTIONAL/margin rejections (-1013/-4164/-2019); new `tests/test_sizing_minorder.py` (70 tests); old qty_zero/BTC-floor assertions updated. |

Unchanged: −25% halt, no averaging / no scaling / no partial close, stop on the exchange first and never moved once placed, signals older than 5 s dropped, leverage method (`choose_leverage` + 70% liq guard, confirmed value only), same-side halving at ≥3 positions.

Pre-order check (`precheck_order`), label order — each label is distinct:
`filter_read_failed` → `qty_zero` → `qty_step` → `below_min_qty` → `max_qty` (MARKET_LOT_SIZE) → `below_min_notional` (at price −2%) → `percent_price` → `tick` → `stop_trigger` (−2021, vs min(bid, mark)) → `bracket` → `margin` (qty·P/L + qty·P·0.0010 ≤ 0.9·available).

Other skip labels of the sizing path: `min_order_risk_over_cap`, `total_risk_cap` (qty_floor 5% sum), `risk_cap_portfolio` (q0 2.5%), `risk_cap` (q0 0.5%/1% fee-inclusive), `leverage`, `liq_guard`. Order labels: `stop_prearm`, `entry_rejected`.

Only fixed constants in the sizing path are ratios: 0.5% risk, 1% fee-inclusive cap, 2.5%/5% open risk, 3% min-qty loss cap, 2% price buffer, 90% margin use, 0.10% margin fee buffer, taker fee 0.05%, slippage 0.04%/0.03%, 70% liq ratio (`test_no_hardcoded_price_constants_in_sizing_path` scans the AST).

## 2. Spec ambiguities — chosen (safer) reading — questions for TA

1. **Label names.** Used the spec's `min_order_risk_over_cap` and `total_risk_cap`; the PM's `loss_cap`/`open_risk_cap` are aliases (same events). `risk_cap_portfolio` kept for the q0 2.5% cap. *Ask: OK to keep the spec names?*
2. **`qty_zero`.** Spec says "수량 0은 별도 사유 qty_zero" but not when it applies in the new flow (q0 = 0 now goes to the minimum-quantity path). Chosen: `qty_zero` is the pure gate's label for qty 0; a q0 = 0 case whose minimum quantity breaks the 3% cap is logged as `min_order_risk_over_cap` with `q0=0 (qty_zero)` in the detail (the rule that actually stopped the trade). *Ask: or should such a skip be labelled `qty_zero`?*
3. **q0 "sufficient".** q0 counts as sufficient only if `q0 ≥ minQty` and `q0·P·0.98 ≥ minNotional`. A q0 inside the 2% buffer band (passes minNotional at P but not at 0.98P) therefore goes to the minimum-quantity path (3% cap) rather than being skipped or sent with a possible −4164.
4. **Loss formula uses D = the passed stop distance** (2·ATR before tick rounding), P = current ask. Conservative vs. the tick-rounded stop. The q0 path keeps today's fee model (notional·2·0.0005 ≤ 1%).
5. **Open-risk ledger.** A q0 position stores its stop risk (≤0.5%), a qty_floor position stores its full loss incl. costs. q0 entries are checked against 2.5% (spec: unchanged) counting open qty_floor positions at their stored risk; qty_floor entries against 5%. *Ask: should q0 entries also be allowed up to 5% when only q0 positions are open? (not done — spec keeps 2.5%).*
6. **Margin check applies to q0 too** (margin+fees ≤ 90% of min(available, strategy-equity room)) — slightly stricter than before.
7. **PERCENT_PRICE** is checked for a market order against the entry reference price using a freshly read mark price; mark read failure → `filter_read_failed`.
8. **Entry rejected / stop rejected.** Entry definitively rejected → cancel the pre-arm, remove the intent, skip `entry_rejected` + 🚨 info alert, nothing left. Entry filled and the closePosition stop **definitively rejected or would-trigger** → flatten the full position at once (`reduceOnly`) + 🚨, **even if the pre-arm stop is still alive** (this differs from the previous “keep pre-arm” behaviour; literal reading of the requirement). Outcome *unknown* (network) → pre-arm kept and verified live via `find_stop`, otherwise `protect()`.
9. **Missing `MARKET_LOT_SIZE` or an empty bracket list → `filter_read_failed`** (the old MMR fallback is no longer used in the new path).
10. **"Latest ATR14(4h)"** = the stop distance of the touch event that the strategy passes in (signal ≤ 5 s old); the engine does not re-fetch klines at order time.
11. **Two-pass sizing.** Pass 1 chooses leverage; pass 2 (after the leverage read-back) re-reads everything and sizes with the confirmed leverage; if the confirmed leverage is above the new bracket max → `leverage` skip.
12. Same-side halving at ≥ 3 open positions is kept (0.25% risk); a halved q0 below the minimum again goes to the qty_floor path.

## 3. Offline test results

Command: `LIVE_V6_REQUIRE_PYLINT=1 pytest live_v6/tests -m 'not testnet and not slow'`

| | passed | failed | deselected (testnet) |
|---|---|---|---|
| base `4d8d16c` | not re-measured here (≈204 incl. the pre-change tests) | – | 53 |
| this branch | **273** | **0** | 53 |

New file `test_sizing_minorder.py`: 70 tests —
boundary per coin (BTC/ETH/SOL/BNB/XRP/DOGE): min qty ±1 step, minNotional ±1 tick (at price −2%), margin ±1%, 3% loss cap boundary (smallest wallet that passes vs −0.02 USDT), max qty, tick, stop_trigger (price/bid/mark), bracket, percent_price, filter_read_failed;
property sweep (6 coins × price ×0.5–1.5 × ATR ×0.3–3 × wallet 50–1000 USDT = 750 cases, asserts ≥200 entries and ≥10 `min_order_risk_over_cap` skips; every entry re-verified by the pure gate, qty multiple of step, ≥ minQty, notional ≥ minNotional at −2%, margin ≤ 90%, loss ≤ 3%, qty_floor quantity is the smallest allowed);
read-failure skips (`exchange_info` / `brackets` / `book` / `mark_price` / `account` unavailable, malformed exchangeInfo) → `filter_read_failed`, no `market`/`stop` call;
re-read proof (pre-order call sequence, wallet changing between pass 1 and 2);
rejection sequences with the simulated exchange: entry rejected by −4164 / −2019 / −1013 (LOT, MARKET_LOT) / −2021 / −4003 → pre-arm cancelled, no state, next signal works; pre-arm rejected (−2021, −1013 PRICE_FILTER, −4130) → no entry; entry fills + closePosition stop rejected (−2021, −1013 PRICE_FILTER, −4509) → full flatten + 🚨, no stop/position/intent left; stop outcome unknown → never naked; one entry + one exit;
BTC 10/21 live case end-to-end (min qty 0.001, `qty_floor` log line, Telegram text, `floor_log`);
no-hard-coded-constants test (AST) + BTC floor gone + exchangeInfo values drive qty.
No mutation testing was run.

## 4. Order-sequence (verified in tests)

leverage confirm → fresh re-read + pre-checks → pre-arm reduceOnly stop → single MARKET entry → closePosition stop → cancel pre-arm.
- pre-arm not confirmed → no entry (`stop_prearm`).
- entry rejected → pre-arm cancelled immediately, intent removed, `entry_rejected`.
- entry filled but exchange stop rejected → reduceOnly full flatten + 🚨 (`stop_rejected_after_fill`).

## 5. Same-bar replay (10/20 18:41 KST → 10/26 10:04 KST, live engine + H7T on real 1m bars)

Scripts/outputs next to this file: `replay_new.py`, `replay_results_new.json`, `out_new.txt`, `out_old_newdata.txt` (old = `4d8d16c`).

| bar (KST) | coin | `4d8d16c` (deployed) | **this branch** |
|---|---|---|---|
| 10/21 23:35 | BTCUSDT | skip `qty_zero` (qty 0 after step, risk 0.5873 / stop 1562) | **ENTER qty 0.001** @ 84134.3, notional 84.13, lev 10×, loss ≈ 1.43% of wallet (3% cap OK); stopped out 10/22 15:26, net −1.7081 |
| 10/22 01:39 | BNBUSDT | ENTER 0.04 @ 751.08, lev 10×, net −0.5938 | **unchanged** (ENTER 0.04, same stop exit, net −0.5938) |
| other touches | – | none | none |

Entries/skips: old 1 entry + 1 skip → new 2 entries + 0 skips. Final simulated wallet 116.87 → 115.17 (the BTC min-qty trade lost 1.71). The new result equals the earlier hypothetical "rule3" variant (qty 0.001, net −1.7081).

## 6. What testnet must exercise next — DONE, see `2026-10-26_sizing_testnet.md`

1. Min-qty entry on a testnet symbol (q0 < minimum): entry, closePosition stop, `qty_floor` log/Telegram line, exit.
2. 3%-cap skip (`min_order_risk_over_cap`) and 5%-sum skip (`total_risk_cap`) with no order sent.
3. Filter violations per rejection type on the real testnet API: −4164 (below minNotional), −2019 (margin), −2021 (stop would trigger), −1013 (LOT / MARKET_LOT / PERCENT_PRICE) → pre-arm cancelled, no position, no leftover stop; entry filled + stop rejected → full flatten + 🚨.
4. Real `BinanceREST.mark_price` (premiumIndex) and the freshly-read exchangeInfo/bracket path (never exercised against a real endpoint yet).
5. Re-run the 51 testnet tests (`-m testnet`) — `fakes.py` changed and the engine entry path changed.

## 7. TA-review items (2026-10-26, offline, same branch)

### (a) Labels
* Logs / skip records / counts use only the spec names `min_order_risk_over_cap`, `total_risk_cap`, `risk_cap_portfolio`. The aliases (`loss_cap` / `open_risk_cap`) appear only in a `#` comment in `sizing.py`.
  `test_no_alias_label_strings_in_emitted_skip_reasons` sweeps all emitted skip reasons and fails if an alias shows up.
* `qty_zero` is emitted **only** when the min-qty path itself is unreachable (`q_min <= 0`). q0 = 0 that goes to the min-qty path and exceeds 3 % is `min_order_risk_over_cap` with `q0=0` in the detail
  (live testnet case 2b above: "q0=0 < exchange minimum; min qty 26 … 16.00 % … > 3 %"). Tests: `test_q0_zero_goes_to_min_qty_path_and_is_not_labelled_qty_zero`, `test_qty_zero_only_when_min_qty_path_is_unreachable`.

### (b) Unknown-outcome stop placement — exact window
`Settings.stop_attempts = 3`, `stop_retry_delay_s = 3.0` (engine.py:82-83), two bounded rounds:
1. `_upgrade_stop`: up to **3 closePosition attempts**, each followed by an `open_orders` check; **3.0 s** sleep between attempts (2 sleeps = 6 s). Unknown outcome ≠ rejected: the pre-arm reduceOnly stop (qty ≥ filled) is kept and verified via `open_orders`/`find_stop`.
2. If not confirmed: `protect()` → `ensure_stop`: again up to **3 attempts**, **3.0 s** apart (6 s).
Total: ≤ 6 placement attempts and ≤ 12 s of deliberate waiting (+ per-call HTTP timeout 10 s ⇒ hard upper bound ≈ 2 min even if every call hangs; typical ≈ 12 s).
**New behaviour (was: wait for reconcile up to `api_dead_s = 300` s with an unprotected position):** still unconfirmed after round 2 → 🚨 `진입 후 손절 미확인(재시도 한도 초과) — 전량 청산` + `close(sym, "stop_unconfirmed")` (reduceOnly full flatten). 🚨 is only logged/queued in testnet.
Tests: `test_stop_window_constants_are_the_documented_ones`, `test_unknown_stop_outcome_with_prearm_verified_keeps_it_and_does_not_flatten`,
`test_unconfirmed_stop_after_the_bounded_window_flattens_in_full_with_alert[reads_fail|prearm_gone]`.

### (c) Mutation tests (manual mutants via `run_mutants.py`, full offline suite per mutant, file restored each time)
Baseline run: `mutation_run1_baseline.txt`; after killers: `mutation_run2_after_killers.txt` (in `2026-10-26_sizing_testnet/`). **25 mutants; 8 survived/weak at first; 0 survive now.**
Killers added (`test_sizing_minorder.py`): `test_cap_3pct_exact_boundary_enters_and_tolerance_edge_enters_just_above_skips`, `test_open_risk_cap_exact_boundaries_5pct_and_2_5pct[qty_floor|q0]`,
`test_min_notional_equality_is_allowed_in_precheck_and_q0_path`, `test_engine_second_pass_open_risk_guard_boundary[0.0-False|1e-12-False|0.0005-True]`.

| mutant | boundary | before | now | failing test(s) |
|---|---|---|---|---|
| M01 | 3% cap `>` -> `>=` (<= vs <) | SURVIVED | **killed** | test_cap_3pct_exact_boundary_enters_and_tolerance_edge_enters_just_above_skips |
| M02 | 3% cap 0.03 -> 0.031 | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_no_hardcoded_price_constants_in_sizing_path, test_property_sweep_price_atr_wallet_all_coins |
| M03 | 3% cap 0.03 -> 0.029 | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_no_hardcoded_price_constants_in_sizing_path, test_property_sweep_price_atr_wallet_all_coins |
| M04 | 5% total cap `>` -> `>=` (sizing) | SURVIVED | **killed** | test_open_risk_cap_exact_boundaries_5pct_and_2_5pct |
| M05 | 5% total cap 0.05 -> 0.051 | killed | **killed** | test_no_hardcoded_price_constants_in_sizing_path, test_open_risk_cap_exact_boundaries_5pct_and_2_5pct, test_open_risk_sum_cap_5pct_for_min_qty_and_2_5pct_for_q0 |
| M06 | 5% total cap 0.05 -> 0.049 | killed | **killed** | test_no_hardcoded_price_constants_in_sizing_path, test_open_risk_cap_exact_boundaries_5pct_and_2_5pct, test_open_risk_sum_cap_5pct_for_min_qty_and_2_5pct_for_q0 |
| M07 | 2.5% q0 cap 0.025 -> 0.026 | killed | **killed** | test_no_hardcoded_price_constants_in_sizing_path, test_open_risk_cap_exact_boundaries_5pct_and_2_5pct, test_open_risk_sum_cap_5pct_for_min_qty_and_2_5pct_for_q0 |
| M08 | 2.5% q0 cap 0.025 -> 0.024 | killed | **killed** | test_no_hardcoded_price_constants_in_sizing_path, test_open_risk_cap_exact_boundaries_5pct_and_2_5pct |
| M09 | open-risk `>` -> `>=` (engine 2nd pass, 2.5%/5%) | SURVIVED | **killed** | test_engine_second_pass_open_risk_guard_boundary |
| M10 | engine 2nd-pass cap tolerance: cap + 1e-12 -> cap + 1e-3 (cap loosened) | SURVIVED | **killed** | test_engine_second_pass_open_risk_guard_boundary |
| M11 | sizing cap tolerance 1e-12 -> 1e-3 (loosened) | killed | **killed** | test_open_risk_sum_cap_5pct_for_min_qty_and_2_5pct_for_q0 |
| M12 | margin 90% `>` -> `>=` (<= vs <) | killed | **killed** | test_boundary_margin_plus_minus_one_percent |
| M13 | margin 90% -> 91% | killed | **killed** | test_boundary_margin_plus_minus_one_percent, test_no_hardcoded_price_constants_in_sizing_path |
| M14 | margin 90% -> 89% | killed | **killed** | test_boundary_margin_plus_minus_one_percent, test_no_hardcoded_price_constants_in_sizing_path |
| M15 | price buffer 2% -> 3% (param, both sites) | killed | **killed** | test_boundary_min_notional_plus_minus_one_tick, test_property_sweep_price_atr_wallet_all_coins |
| M16 | price buffer 2% -> 1% (param, both sites) | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_boundary_min_notional_plus_minus_one_tick |
| M17 | precheck worst-price buffer only: 0.98 -> 0.97 | killed | **killed** | test_boundary_min_notional_plus_minus_one_tick |
| M18 | precheck worst-price buffer only: 0.98 -> 0.99 | killed | **killed** | test_boundary_min_notional_plus_minus_one_tick |
| M19 | size_entry worst-price buffer only: 0.98 -> 0.97 | killed | **killed** | test_min_notional_equality_is_allowed_in_precheck_and_q0_path, test_property_sweep_price_atr_wallet_all_coins |
| M20 | size_entry worst-price buffer only: 0.98 -> 0.99 | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_filter_values_drive_the_quantity, test_no_alias_label_strings_in_emitted_skip_reasons, test_q0_inside_price_buffer_band_goes_to_min_qty_path_not_skip |
| M21 | minNotional precheck `<` -> `<=` (qty*worst == minNotional rejected) | SURVIVED | **killed** | test_min_notional_equality_is_allowed_in_precheck_and_q0_path |
| M22 | minNotional precheck `<` -> `<` +1 tick (needs one step more) | killed | **killed** | test_boundary_min_notional_plus_minus_one_tick, test_boundary_min_qty_plus_minus_one_step |
| M23 | q0 path minNotional `>=` -> `>` (q0*worst == minNotional goes to qty_floor) | SURVIVED | **killed** | test_min_notional_equality_is_allowed_in_precheck_and_q0_path |
| M24 | q_min ceil_to -> floor_to (-1 tick below minNotional) | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_filter_values_drive_the_quantity, test_no_alias_label_strings_in_emitted_skip_reasons, test_q0_inside_price_buffer_band_goes_to_min_qty_path_not_skip, test_sweep_price_scale_changes_notional_not_rules |
| M25 | q_min +1 tick (one step more than needed) | killed | **killed** | test_boundary_loss_cap_3pct_per_coin, test_min_qty_entry_is_the_smallest_allowed_quantity, test_q0_inside_price_buffer_band_goes_to_min_qty_path_not_skip |

Notes: (1) `>` → `>=` on the cap compares (M01/M04/M09) is only distinguishable at *exactly* `cap + 1e-12` because the code adds a 1e-12 float tolerance; the new tests build inputs whose float value equals that bit-for-bit (`_exact_open`, `loss/Decimal(0.03+1e-12)`), so they are real kills, not equivalent mutants.
(2) M09/M10 (engine second-pass guard) sit behind the identical check in `size_entry`, so via normal inputs they cannot differ; they are killed by stubbing `size_entry`'s second-pass result so the engine guard itself decides.
(3) The margin-90 and minNotional ±1 tick mutants (M12–M18, M22) were already killed by the pre-existing boundary tests. (4) M05–M08 were also killed by the static `test_no_hardcoded_price_constants_in_sizing_path`; the new behavioural boundary test kills them independently (M08 re-run with the static test deselected still fails on `…exact_boundaries…[q0]`).

## 8. TA conditional-PASS conditions (2026-10-26 ~11:00 KST, offline/read-only)

### Condition 1 — entry rejected AND the pre-arm cancel fails (`_cancel_quiet` only logs)
**Code reading (engine.py before this commit, 3cb6bdf):** on `OrderRejected` the intent is popped and saved *first*, then `_cancel_quiet(sym, pre)` (engine.py ~L909, `except ExchangeError: log`). If the cancel fails the reduceOnly pre-arm `<cid>p` stays on the exchange.
* **Account flat:** `reconcile()` flat branch (engine.py ~L1161–1175) cancels every open order with our `cid_prefix` that is closePosition/reduceOnly and not in `pending` (= pre-arms of *unresolved* intents). The orphan is removed on the next reconcile (retries every pass while the cancel keeps failing). ✔ handled; user orders (no prefix) never match.
* **GAP FOUND — user opens a manual position in that coin while the orphan is still live:** the position has no journal → `_unknown_position(...)`. It called `find_stop(amt, orders)`, which accepts *any* reduceOnly STOP with qty ≥ |amt| and does not look at the client id. The orphan was therefore (a) **adopted as the manual position's protective stop** ("exchange (existing, untouched)", no own stop placed), or (b) when the user has his own closePosition stop, ignored but **left alive** — the flat-branch cleanup does not run for a non-flat coin. In both cases the bot's old stop (at the bot's price, qty ≥ the user's size, reduceOnly) would fire on the user's position. Demonstrated on 3cb6bdf by the new tests below (2 of the 3 failed before the fix: `assert 'v6tDOGE…p' not in [...]`).
* **Fix (separate small commit, engine.py `_is_orphan_prearm` + 8 lines in `reconcile`):** in the `j is None` branch, orphan pre-arms (our prefix, `…p`, reduceOnly, not closePosition, intent no longer exists) are hidden from `_unknown_position` (never counted as protection), and cancelled **only once the unowned position has its own confirmed stop** (the user's, or the bot's unknown-position stop) — never leaving a position with no stop. The user's orders are never touched (no `v6` prefix). `pending` pre-arms of unresolved entries are untouched.
* **Tests (offline, `test_sizing_minorder.py`):**
  `test_orphan_prearm_after_failed_cancel_is_removed_by_reconcile_when_flat` (cancel fails 3×, user's own `my_hedge_p` reduceOnly order survives, coin tradable afterwards),
  `test_orphan_prearm_never_becomes_the_stop_of_a_manual_position_in_the_same_coin` (manual position + manual closePosition stop + manual reduceOnly `my_hedge_p`: orphan gone, both manual orders and the position untouched, protection = his stop, no close),
  `test_orphan_prearm_is_not_adopted_as_protection_of_a_manual_position_without_stop` (orphan cancelled, bot places its own `v6tDOGEu…` stop),
  `test_orphan_prearm_stays_until_the_bot_has_its_own_stop_for_an_unowned_position` (own stop placement fails once → orphan kept; cancelled next pass),
  `test_unresolved_entry_keeps_its_prearm_through_a_flat_reconcile` (counter-test: unknown-outcome entry keeps its pre-arm).
  Existing: `test_entry_rejected_cancels_prearm_and_leaves_no_state`, `test_kill_before_entry_sent_cleans_prearm`.
* **Mutants (`2026-10-26_sizing_testnet/orphan_mut.py`, result `orphan_result.txt`; file restored each time): 7/7 killed.**
  O1 detection off → 3 tests fail; O2 no prefix check on the orphan test → manual `my_hedge_p` cancelled → fails; O3 no cancel next to a manual position → 3 fail; O4 cancel before own stop exists → fails;
  O5 flat branch without prefix check → fails; O6 flat branch never cancels → 3 fail (incl. existing `test_kill_before_entry_sent_cleans_prearm[offline]`); O7 flat branch ignores `pending` → fails (needed the new counter-test; first run survived).

### Condition 2 — see `2026-10-26_sizing_real6.md` (real 6 coins, wallets 117.47 / 50 / 1000).

### Condition 3 — entry_orders isolation fix: **already in the branch, nothing to apply**
The 10/21 diff (`2026-10-21_R4_proposed_test_changes.diff`) is already in this branch's history since commit `499407e` ("tests: TA-approved entry_orders + 429/418 test changes") — `Backend.entry_orders` counts allOrders BUY/non-reduceOnly created ≥ `Backend.now_ms()` (exchange time after cleanup, no backward margin; here even stricter: any client id except `v6tclean…`), `now_ms()` exists, all six `t0 = backend.now_ms()` call sites and the `RateLimited`/`backoff_until` lines are present (`git apply --check` of the diff fails only because every hunk is already applied). No commit made. The 51-test run of §3 of `2026-10-26_sizing_testnet.md` therefore already ran with the fix: `test_no_averaging`, `test_kill_after_fill_then_restart`, `test_restart_multiple_positions_rearms_all`, `test_entry_response_lost_no_duplicate`, `test_drop_during_status_query`, `test_exit_response_lost_no_duplicate` all PASSED on testnet. The testnet suite was **not re-run** after the Condition-1 engine commit (nothing to apply; the change touches only the offline-covered non-flat reconcile branch; no testnet run → citest canary untouched).

Offline suite after the changes: `LIVE_V6_REQUIRE_PYLINT=1 pytest live_v6/tests -m 'not testnet and not slow'` → **292 passed, 53 deselected** (was 287; +5 new tests).
