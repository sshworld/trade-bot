# 2026-10-26 — skip label `qty_zero`, 4h-bar INFO log line, and sizing evidence (A)/(B)

Branch `fix-skip-label-barlog` (base `e2695d9`, the code live_v6-live runs). Not merged, not deployed. No trading-logic change.
All times KST (Asia/Seoul, UTC+9) unless marked UTC. Wallet = 117.46733957 USDT (server `mainnet.json`, 2026-10-26 ≈08:54 KST).
Data: public Binance futures endpoints fetched from the VPS (this box is geo-blocked) → `2026-10-26_skip_label_barlog/fetch_vps.py` (raw 4 MB JSON not committed).
Scripts + raw outputs are in `2026-10-26_skip_label_barlog/` (`table_A.py`, `replay_recent.py`, `*.txt`, `*.json`).

## 1. What changed in code (C)
1. `sizing.size_entry`: `qty <= 0` after step rounding → skip `qty_zero` (detail: `qty 0 after step … rounding (risk R / stop distance D = raw); exchange min qty M`). `min_notional` is now only a real `qty*price < minNotional` skip (qty > 0). Check order unchanged (the new check sits where the old one effectively fired, before `min_notional`; every case that skipped before still skips). The skip_log, the Telegram/daily settlement skip counts and `Engine.skip` already key on the reason string, so they pick up `qty_zero` without further change (tested).
2. `engine._log_bar_close` (INFO, once per completed 4h bar per model, after the bar state is saved): `bar_close model=h7t bar_open=<KST> <SYM>=<no_signal|in_position|entered|skip:<reason>|exit:<reason>> …`; `engine.enter` logs one `entered SYM long qty … fill … stop … lev …x risk … USDT (…%)` INFO line. New `Strategy.bar_decisions` (default `no_signal`) / `H7T.bar_decisions` read the existing state and skip_log; no key, balance, order-id or token appears (tested).
3. `runner.setup_logging()` (factored out of `run()`, same behaviour + `websockets` pinned to WARNING).
4. Test harness only: `replay/sim_exchange.py` `set_leverage` now echoes the leverage and `SimExchange.leverage()` exists. e2695d9's leverage fail-safe (needs set echo + symbolConfig) made `test_replay_matches_research_trades` fail on **e2695d9 itself** (the sim returned None → every entry skipped as `leverage`). Not a bot change.

### Why the journal only had WARNING+
`runner.run()` already calls `logging.basicConfig(level=os.getenv("LIVE_V6_LOG","INFO"))` and the unit has no `LIVE_V6_LOG` and `PYTHONUNBUFFERED=1`; so the handler/level were fine. The journal had no INFO because the code emitted (almost) no INFO lines — skips and alerts are `log.warning`. After this change the journal gets ≈6 lines/day per model (one per 4h bar) + one per entry; httpx/httpcore/websockets stay at WARNING (no per-request flood). Test: `test_setup_logging_emits_info_to_stderr_and_mutes_http_libs` (subprocess, `LIVE_V6_LOG` unset).

## 2. (A) per-coin table (prices from VPS ≈08:54 KST 10/26)
ATR14 = Wilder RMA on 4h bars (the model's `atr` from `mainnet.json`, cross-checked by recomputing from klines — BNB differs 7.8860 vs 7.8854). sd = 2×ATR, stop distance rounded toward entry by `stop_price`. Bot qty = `floor_qty(0.5%·wallet / sd)` (`sizing.size_entry`, risk_pct 0.5). Fee-inclusive risk = loss + notional×2×0.0005 (taker both sides), compared with 1% of wallet by `size_entry` (`risk_cap`).

| coin | exch minQty / step / minNotional (live eff.) | price | ATR14(4h) | sd=2×ATR (% px) | 0.5%-risk qty raw → floored → bot result |
|---|---|---|---|---|---|
| BTC | 0.001 / 0.001 / 50 (100) | 80020.10 | 706.100417 | 1412.200833 (1.765%) | 0.00041590 → 0.000 → **min_notional** |
| ETH | 0.001 / 0.001 / 20 (20) | 2322.97 | 32.982672 | 65.965344 (2.839%) | 0.00890444 → 0.008 → **min_notional** |
| SOL | 0.01 / 0.01 / 5 (5) | 101.1600 | 1.530882 | 3.061763 (3.025%) | 0.19194010 → 0.19 → **OK** |
| BNB | 0.01 / 0.01 / 5 (5) | 738.010 | 7.886034 | 15.772068 (2.137%) | 0.03724393 → 0.03 → **OK** |
| XRP | 0.1 / 0.1 / 5 (5) | 1.2944 | 0.018636 | 0.037273 (2.874%) | 15.78862091 → 15.7 → **OK** |
| DOGE | 1 / 1 / 5 (5) | 0.076780 | 0.001290 | 0.002579 (3.347%) | 228.53568010 → 228 → **OK** |

Scenarios (leverage 10x for all; `choose_leverage` + liquidation guard + margin pass in every row — none of them blocks; what blocks is the 1% fee-inclusive `risk_cap` for BTC):

| coin | scenario | qty | notional USDT | loss at stop USDT | % wallet | % wallet incl. fees | vs 1.5% / 3% cap (loss only) | e2695d9 `size_entry` (fee-incl. 1% cap etc.) |
|---|---|---|---|---|---|---|---|---|
| BTC | S1 min qty + $100 floor (BTC only live) | 0.002 | 160.04 | 2.8244 | 2.404% | 2.541% | ✗1.5/≤3 ✓ | risk_cap (leverage/margin/liq. fine when fee cap relaxed: OK, lev 10x, margin 16.00) |
| BTC | S2 exchange minimum only | 0.001 | 80.02 | 1.4122 | 1.202% | 1.270% | ≤1.5 ✓/≤3 ✓ | risk_cap (leverage/margin/liq. fine when fee cap relaxed: OK, lev 10x, margin 8.00) |
| BTC | S1' $100 floor on every coin | 0.002 | 160.04 | 2.8244 | 2.404% | 2.541% | ✗1.5/≤3 ✓ | risk_cap (leverage/margin/liq. fine when fee cap relaxed: OK, lev 10x, margin 16.00) |
| ETH | S1 min qty + $100 floor (BTC only live) | 0.009 | 20.91 | 0.5936 | 0.505% | 0.523% | ≤1.5 ✓/≤3 ✓ | OK |
| ETH | S2 exchange minimum only | 0.009 | 20.91 | 0.5936 | 0.505% | 0.523% | ≤1.5 ✓/≤3 ✓ | OK |
| ETH | S1' $100 floor on every coin | 0.044 | 102.21 | 2.9022 | 2.471% | 2.558% | ✗1.5/≤3 ✓ | risk_cap (leverage/margin/liq. fine when fee cap relaxed: OK, lev 10x, margin 10.22) |
| SOL | S1 min qty + $100 floor (BTC only live) | 0.05 | 5.06 | 0.1530 | 0.130% | 0.135% | ≤1.5 ✓/≤3 ✓ | OK |
| SOL | S2 exchange minimum only | 0.05 | 5.06 | 0.1530 | 0.130% | 0.135% | ≤1.5 ✓/≤3 ✓ | OK |
| SOL | S1' $100 floor on every coin | 0.99 | 100.15 | 3.0294 | 2.579% | 2.664% | ✗1.5/≤3 ✓ | risk_cap (leverage/margin/liq. fine when fee cap relaxed: OK, lev 10x, margin 10.01) |
| BNB | S1 min qty + $100 floor (BTC only live) | 0.01 | 7.38 | 0.1577 | 0.134% | 0.141% | ≤1.5 ✓/≤3 ✓ | OK |
| BNB | S2 exchange minimum only | 0.01 | 7.38 | 0.1577 | 0.134% | 0.141% | ≤1.5 ✓/≤3 ✓ | OK |
| BNB | S1' $100 floor on every coin | 0.14 | 103.32 | 2.2078 | 1.880% | 1.967% | ✗1.5/≤3 ✓ | risk_cap (leverage/margin/liq. fine when fee cap relaxed: OK, lev 10x, margin 10.33) |
| XRP | S1 min qty + $100 floor (BTC only live) | 3.9 | 5.05 | 0.1451 | 0.124% | 0.128% | ≤1.5 ✓/≤3 ✓ | OK |
| XRP | S2 exchange minimum only | 3.9 | 5.05 | 0.1451 | 0.124% | 0.128% | ≤1.5 ✓/≤3 ✓ | OK |
| XRP | S1' $100 floor on every coin | 77.3 | 100.06 | 2.8756 | 2.448% | 2.533% | ✗1.5/≤3 ✓ | risk_cap (leverage/margin/liq. fine when fee cap relaxed: OK, lev 10x, margin 10.01) |
| DOGE | S1 min qty + $100 floor (BTC only live) | 66 | 5.07 | 0.1696 | 0.144% | 0.149% | ≤1.5 ✓/≤3 ✓ | OK |
| DOGE | S2 exchange minimum only | 66 | 5.07 | 0.1696 | 0.144% | 0.149% | ≤1.5 ✓/≤3 ✓ | OK |
| DOGE | S1' $100 floor on every coin | 1303 | 100.04 | 3.3487 | 2.851% | 2.936% | ✗1.5/≤3 ✓ | risk_cap (leverage/margin/liq. fine when fee cap relaxed: OK, lev 10x, margin 10.00) |

Reading: ETH/SOL/BNB/XRP/DOGE at the exchange minimum are 0.12–0.51% of wallet — far below 1.5%/3%. BTC at the exchange minimum (0.001) costs 1.20% (1.27% with fees): passes 1.5% and 3% but fails e2695d9's 1% fee-inclusive cap; at the $100 floor (0.002) it costs 2.40% (2.54% with fees): fails 1.5% and 1% caps, passes 3%. A $100 floor on all coins would force 1.9–2.9% risk per coin (S1').
Leverage alone does not remove the minimum: leverage changes margin, not qty·stop-distance loss. A smaller loss than BTC min-qty 0.001 × 1412 = 1.41 USDT is impossible at BTC's step.

### Rule-3pct (min exchange-allowed qty if q0 < minimum, only those entries need loss+fees ≤ 3% of wallet, total open risk ≤ 5%)
Spec read: `/workspace/specs/sizing-spec-minorder-3pct.md` (TA). Evaluated in the replay script only — **not implemented in the bot**. "Exchange minimum" = smallest qty satisfying minQty AND minNotional (ETH: q0 0.008 → notional 18.58 < 20 → 0.009).

| coin | path | qty | notional USDT | loss USDT | % wallet | % incl. fees | vs 3% | result |
|---|---|---|---|---|---|---|---|---|
| BTC | q_min (q0 0.000 < exchange min) | 0.001 | 80.02 | 1.4122 | 1.202% | 1.270% | pass | ENTER (lev 10x, margin 8.00) |
| ETH | q_min (q0 0.008 < exchange min) | 0.009 | 20.91 | 0.5936 | 0.505% | 0.523% | pass | ENTER (lev 10x, margin 2.09) |
| SOL | q0 (unchanged) | 0.19 | 19.22 | 0.5814 | 0.495% | 0.511% | pass | ENTER (lev 10x, margin 1.92) |
| BNB | q0 (unchanged) | 0.03 | 22.14 | 0.4731 | 0.403% | 0.422% | pass | ENTER (lev 10x, margin 2.21) |
| XRP | q0 (unchanged) | 15.7 | 20.32 | 0.5840 | 0.497% | 0.514% | pass | ENTER (lev 10x, margin 2.03) |
| DOGE | q0 (unchanged) | 228 | 17.51 | 0.5860 | 0.499% | 0.514% | pass | ENTER (lev 10x, margin 1.75) |

## 3. (B) same-bar replay, live code, actual 1m/4h bars 10/20 18:41 KST → 10/26 ≈08:54 KST
Harness: `live_v6.replay` (`Sim1m`, `SimExchange`, `V6Engine`, `H7T`) at commit e2695d9 (old labels), real VPS klines, model state started from klines (final ATR/hi55 equal the server's `mainnet.json` except BNB ATR 7.88537 vs 7.88603). Details in `replay_out.txt`.

| variant | entries | skips | wallet at end |
|---|---|---|---|
| A live: floor ON (BTC 100) | BNB 10/22 01:39 qty 0.04, notional 30.04, lev 10, stop-out 10/22 16:12, net −0.5938 | BTC 10/21 23:35 `min_notional` (qty 0.000 notional 0.0000 < minQty 0.001/minNotional 100) | 116.8735 |
| B floor OFF (exchange min only) | same as A | BTC 10/21 23:35 `min_notional` (…/minNotional 50) — still qty 0 | 116.8735 |
| A2 $100 floor all coins | none | BTC (qty 0), BNB (`min_notional` 30.04 < 100) | 117.4673 |
| **rule-3pct** | BTC 10/21 23:35 qty 0.001 notional 84.13 (loss 1.33% / 1.40% incl. fees, passes 3%), stopped 10/22 15:26, net −1.7081; BNB unchanged (qty 0.04, net −0.5938) | none | 115.1655 |

Answers:
* Model entries since 10/20 18:41 KST: exactly **two** — BTC 10/21 23:35 and BNB 10/22 01:39. BTC is not the only one.
* BTC 10/21 23:35: replay skip = server `skip_log` (BTC, `min_notional`, qty 0.000, notional 0.0000, minNotional 100) — match. The live tick was 23:35:30 KST; the replay uses the 1-minute bar boundary.
* BNB 10/22 01:39 KST: **enters** in both floor variants (the live skip was a `leverage` read-back lag on positionRisk, fixed by the e2695d9 fail-safe + symbolConfig); the replay models a healthy leverage echo. Only a $100 floor on all coins would block BNB.
* Lowering the floor to the exchange minimum does **not** enable BTC (qty floors to 0 < 0.001); a min-qty BTC entry additionally fails the 1% fee-inclusive cap (1.27%). Only the rule-3pct path enters it.
* Rule-3pct vs e2695d9: adds the BTC entry (−1.71 USDT net); changes nothing else; ETH/SOL/XRP/DOGE had no touches in the window.
* Hypothetical "bump risk_pct" variants (C, D, C2, D2, D3 in `replay_out.txt`): with the stock 1%-fee and 2.5% portfolio caps BTC is still skipped (`risk_cap`/`risk_cap_portfolio`) unless the caps are lifted.

Approximations: 1m granularity; stops fill at the model stop price; leverage brackets from the research snapshot; available balance = wallet; ATR/hi55 start-state recomputed from klines; healthy leverage echo.

## 4. Tests
`LIVE_V6_REQUIRE_PYLINT=1 pytest live_v6/tests -m 'not testnet and not slow'` in `/workspace/.venv-live6`: **203 passed, 1 skipped, 53 deselected** (pylint gate on; 0 failures). New: `tests/test_skip_label_barlog.py`; updated `test_units.py::test_skip_order_and_reasons`, `test_token_logs.py::test_runner_quiets_httpx_request_lines`.
