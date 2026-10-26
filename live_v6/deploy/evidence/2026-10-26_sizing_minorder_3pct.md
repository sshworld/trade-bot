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

## 6. What testnet must exercise next (not done here)

1. Min-qty entry on a testnet symbol (q0 < minimum): entry, closePosition stop, `qty_floor` log/Telegram line, exit.
2. 3%-cap skip (`min_order_risk_over_cap`) and 5%-sum skip (`total_risk_cap`) with no order sent.
3. Filter violations per rejection type on the real testnet API: −4164 (below minNotional), −2019 (margin), −2021 (stop would trigger), −1013 (LOT / MARKET_LOT / PERCENT_PRICE) → pre-arm cancelled, no position, no leftover stop; entry filled + stop rejected → full flatten + 🚨.
4. Real `BinanceREST.mark_price` (premiumIndex) and the freshly-read exchangeInfo/bracket path (never exercised against a real endpoint yet).
5. Re-run the 51 testnet tests (`-m testnet`) — `fakes.py` changed and the engine entry path changed.
