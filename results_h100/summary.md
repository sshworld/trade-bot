# H100 funding carry v1.1 — one-shot screen results (numbers only; verdict = TA)

Run: 2026-10-29 15:13:14 KST, code commit 75cd0ca (branch h100-funding). Window 2020-01-01..2026-09-30 UTC, 2465 days.

| criterion | value | rule | pass |
|---|---|---|---|
| C1a_liquidations_model | 13 | == 0 | False |
| C1b_one_leg_intervals_hours | 0 | == 0 | True |
| C1c_worst_intrabar_dd_from_start_or_peak | -0.154588 | > -0.25 | True |
| C2a_mean_daily_net_1x | 0.000101991 | > 0 | True |
| C2b_mean_daily_net_2x | 2.06327e-05 | > 0 | True |
| C3_block_bootstrap_LB_99.9375 | -0.000101999 | > 0 | False |
| C4a_first_half_mean | 0.000133262 | > 0 | True |
| C4b_second_half_mean | 7.07452e-05 | > 0 | True |
| C5_residual_order_or_position_violations | 0 | == 0 | True |

Counts: {"entries": 370, "sl_exits": 184, "tp_exits": 108, "liquidations": 13, "signal_exits": 65, "open_at_end": 0, "one_leg_hours": 0, "residual_violations": 0, "deferred_signal_exits": 0, "skipped_entries_missing_bar": 0}

x1: {"end_exit_cost": 0.0, "final_equity": 1.276599657306482, "ann_return": 0.03684681872563722, "mdd_close": -0.09998337641626842, "mdd_worst_intrabar": -0.15458834809544164, "mdd_worst_ts": "2021-04-18 03:00:00", "min_wallet_worst": 0.892434265431185, "min_wallet_worst_ts": "2020-08-02 04:00:00", "min_wallet_close": 0.9736217089808133, "start_drop_worst": -0.10756573456881502, "daily_mean": 0.00010199101143451404, "daily_std": 0.002409686631914263, "n_days": 2465, "time_in_market_slot_hours_pct": 23.517033133583602, "time_in_market_wallet_any_pct": 35.25693035835024, "days_with_position": 879}

x2: {"end_exit_cost": 0.0, "final_equity": 1.044683889999988, "ann_return": 0.006498371636206146, "mdd_close": -0.12869094467936137, "mdd_worst_intrabar": -0.21247975714824763, "mdd_worst_ts": "2021-04-18 03:00:00", "min_wallet_worst": 0.8208760807310844, "min_wallet_worst_ts": "2021-04-18 03:00:00", "min_wallet_close": 0.9082138128248088, "start_drop_worst": -0.17912391926891558, "daily_mean": 2.063272461112392e-05, "daily_std": 0.0023983055520569157, "n_days": 2465}

## Liquidation-bar diagnostics (info only, measured after the run, no rerun)
All 13 liquidation bars opened below the +20% SL; under the pre-registered rule (1h high >= entry x 1.31 is a liquidation, checked before SL) they count as liquidations.
ETHUSDT 2020-03-13 02:00 futures 1h high is +202% vs entry (likely a bad/wick print in v7_um_1h); kept as data, not edited.
Others: BNB 2021-02-19 14:00 (open +14.2%, high +33.9%); XRP 2021-01-07 04:00 (+15.6/+32.3), 2021-01-30 16:00 (+0.0/+36.0), 2021-02-01 03:00 (+9.3/+31.5); DOGE 2021-01-02 04:00 (+17.0/+39.1), 2021-01-02 15:00 (+9.8/+38.5), 2021-01-28 04:00 (-10.6/+35.1), 2021-02-04 07:00 (+7.5/+41.6), 2021-04-13 16:00 (+14.1/+35.0), 2021-04-15 19:00 (+17.3/+35.5), 2021-04-16 11:00 (+13.4/+33.5), 2021-10-28 06:00 (+8.5/+33.6).
Bootstrap re-derived independently from daily.csv: identical LB; bootstrap sd of mean 5.65e-05.

---

# H100 funding carry v1.1 — SPEC_NOTES (written before the run)
Sources: TA lock `prereg-lock-h100-funding-v1_1.md` (89752618a943) > QR spec `hypotheses_h100_funding_v1_1.md` (088ddd8c5c68); safety `ops-safety-rules-v1-2026-10-29.md` (48ef505e19a6).
Where the lock/spec is silent or ambiguous, the most conservative reading was taken. Nothing below was chosen after seeing results.

## Data
1. Funding: `v3_um_funding.parquet` for the 6 coins. Verified identical (max abs diff 0) to `funding.parquet` (= BTCUSDT, confirmed), `v2_<SYM>_funding.parquet` and `v7_um_funding.parquet`. Prints used through 2026-09-30 16:00 UTC.
2. Futures 1h: `v7_um_1h.parquet`. SOLUSDT and XRPUSDT miss 120 hours (2022-02-26 onward, 5 days); filled from `v2_<SYM>_1h.parquet`, which is identical to v7 on every overlapping bar. No futures hour is missing after the fill.
3. Spot 1h: Binance public spot monthly archive (data.binance.vision, no key), stored under `data/raw_spot/<SYM>/`. 2025+ files use microsecond timestamps; converted. Exchange-maintenance gaps remain (19-31 hours per coin) and are NOT filled.
4. Coin window: from the first hour where funding, futures and spot data all exist (BTC/ETH 2020-01-01, XRP 2020-01-06 08:00, BNB 2020-02-10 08:00, DOGE 2020-07-10 09:00, SOL 2020-09-14 07:00) to 2026-09-30 23:00 UTC. Earlier real funding prints are allowed as history for the first signal.

## Signal
5. "last 9 prints" = the last 9 realized prints including the print at the settlement being judged. Settlements = the actual print timestamps.
6. SOLUSDT has 99 prints on a 2h (and 2 on a 4h) funding interval. Raw prints are used as-is for both the signal and accrual (no rescaling to 8h). Rescaling would inflate those prints 4x and make entries easier; raw is the conservative reading.

## Position and fills
7. Legs are equal notional at entry (spot X, short notional X, X = 0.75 C, margin X/3), as the spec says, not equal quantity.
8. Slots: each coin is an independent 1/6 sub-account that compounds on its own (C = slot equity at entry). No cross-slot rebalancing. A slot is cash (0 return) before its coin window starts and when flat.
9. Entry: at the open of the 1h bar that starts at the settlement time, both legs. No entry if either leg has no bar at that hour (wait for the next settlement).
10. Funding: credited/debited at each settlement while the short is held, on q_short x futures open of the settlement hour. The entry settlement print is not received. The print at an exit settlement IS applied (the short is open at that instant): conservative because the exit print is usually low or negative.
11. Signal exit: both legs at the open of the settlement bar. If either leg has no bar then, both legs stay on and close together at the first hour where both have a bar (stays hedged; counted as a deferred exit).
12. Liquidation price = entry x 1.31 (spec value; the isolated-margin formula gives about +32.7%, so 1.31 is the conservative one). Funding received is not added to margin. If the 1h futures high >= liquidation price, it is a liquidation (counted as an SL failure, as the spec says) even if the +20% SL would have filled first; the futures leg loses the whole margin X/3.
13. SL (+20%) fill = max(SL price, bar open) x (1 + 0.10%), plus the normal futures taker 0.05% and slippage 0.02% (the extra 0.10% is read as additional). TP (-20%) fill = exactly the TP price (no gap improvement), plus taker 0.05% and slippage 0.02%. A bar touching both SL and TP is an SL.
14. R4: after an SL/TP/liquidation the spot leg is sold at the same 1h bar close (spot taker 0.10% + 0.02%). If that spot bar is missing, spot is sold at the open of the first available spot bar and every hour-close in between counts as a one-leg interval.
15. Re-entry after SL/TP/liquidation: next settlement strictly after the exit bar, entry rules unchanged, new SL/TP from the new price.
16. R1/R3 modeled as an explicit per-coin order set: {SL, TP} for the full quantity right after entry (SL < liquidation asserted); every trade end cancels all orders and checks 0 orders and 0 legs (violations counted). R2 (breakeven SL after partial TP) is not active: the rule has no partial TP (TP is the full quantity).
17. Positions still open at 2026-09-30 23:00 are marked at that close and charged their exit fees (no free exit).

## Costs
18. Per side: spot 0.10% + 0.02% slippage, futures 0.05% + 0.02% slippage, on the notional at the fill price (round trip ~0.38% of X). 2x cost: every fee and slippage doubled, including the extra SL slippage. Trade path is identical at 1x and 2x (signals do not depend on cost); only cost lines and compounding differ.
19. Basis: real spot and futures 1h prices are used for every fill and mark, so basis changes are in the P&L.

## Measurement
20. Daily wallet return = UTC-day close equity / previous day close equity - 1 for every calendar day 2020-01-01 .. 2026-09-30 (including flat days); day 1 is against the starting wallet 1.0. All 6 slots summed.
21. Halt (-25%): hourly worst mark = futures 1h HIGH for the short and spot 1h LOW for the spot leg in the same hour, for all coins at once (short loss capped at its margin); compared with the running peak of hourly close equity up to the previous hour, which starts at 1.0 (covers from start or any later peak). The halt is measured, not acted on.
22. Expectancy: mean of daily returns at 1x and at 2x cost.
23. Bootstrap: moving-block, block 7 days, 10,000 resamples, numpy default_rng(102), block starts uniform on [0, n-7], ceil(n/7) blocks truncated to n days; lower bound = the 0.0625% quantile (one-sided 99.9375%, N = 80) of resampled means of the 1x daily returns.
24. Halves: daily series split by day count (first floor(n/2) days vs the rest), 1x cost.
25. One-leg interval = an hour close at which exactly one leg is held.
