# H96 screen result (1m intrabar; frame fe2) -- 2026-10-29 14:42 KST

Runner: branch h48-screen @ b91fd39a44; runtime 804 s (whole session), peak RSS 1656 MB; locks: prereg-lock-h93-h98-v1_2.md c2945d535a11, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h93_early_v1_1.md 1f575ac39bd7; rule v1.1 hypotheses_h93_early.md e225f7ccee5c; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Spec notes: Batch 3 common frame (lock c2945d535a11 over QR v1.1 1f575ac39bd7): intrabar entry at the trigger 1m close, entry instant = close of the trigger minute; the 0.15% round trip (fees + slippage, lock costs line) is the only cost term, no separate entry-slippage add-on; stop 2 x A4 (Wilder ATR14 of the last closed 4h bar) fixed; a stop touched in the first held minute fills at min(open, stop) (short: max); exit at the next 1m open after the first 4h close below the prior 20-bar low (short: above the prior 20-bar high), counting 4h bars that close after the entry instant; no time cap, no target; BTC SMA200 regime of the last completed UTC day before the trigger minute (long 1, short 0, unknown skipped). Closed-bar values use bars that end at or before the trigger minute start; 15m bars are built from the stored 1m rows and rolling windows count existing bars (as the 4h bars). Signal-state rules (cooldown, one per range, re-arm, first-in-4h) run on the signal stream before the entry filters; filter order: window, next minute present, busy, regime, stop width (skip_stop_low < 0.60%, skip_stop_high > 8.0%; per coin in generator_counts_per_coin csv). Counters cooldown / range_used / not_first / not_rearmed / funding_not_neutral count candidate MINUTES. H96: common 1m grid from 2020-12-31 00:00 UTC; R4 = close / close of the 1m bar 240 min earlier - 1, a coin missing either minute is out of that minute ranking; the rank-1 coin must pass its own R4 floor and 24h-high test (no fall-back to rank 2); a signal at t blocks all six for [t, t + 4h). Six-coin rule: no new-coin book.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H96 / six (primary), seed 100, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 639, months 46, win rate 0.247, mean R 0.7450 (0.30% cost 0.7065), PF 2.060, MDD 0.807, final wallet x36.051

Candidate list (unlimited, R units): trades 639
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (639 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.745 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.0378 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.7065 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.9462, 0.5444, 319, 320) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.8073, 'top5_removed_mean': -0.2923, 'removed': 32} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.5506, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% 0.1154, 99.8% 0.0078, lock bound index 6

Candidate list: 639 trades, average hold 136.78 h, annual n 111 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 416, months 46, win rate 0.274, mean R 0.9705 (0.30% cost 0.9348), PF 2.439, MDD 0.698, final wallet x65.655

Limits book: trades 416
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (416 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.9705 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.0773 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.9348 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (1.2755, 0.6654, 208, 208) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.6982, 'top5_removed_mean': -0.1941, 'removed': 21} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.4688, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% 0.1291, 99.8% 0.0021, lock bound index 6
end_of_data trades: 3

Lock aux numbers: trades 416 (>= 100: True), mean R 0.9705 (> 0: True), mean R at 2x cost 0.9348 (> 0: True)

- U1: coins with >= 10 trades 6, positive 5, share 0.833 (need >= 0.667; meets)
- U2: best coin DOGEUSDT share 0.424 of total R 403.71 (need <= 0.35; does not meet)
- U3: mean R without DOGEUSDT: 0.6862, n 339 (meets)
- U4: in H16 universe: trades 411, coins 6, mean R 0.7279; not in H16: trades 5, coins 2, mean R 20.9080 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| DOGEUSDT | 77 | 2.2221 | 171.10 |
| XRPUSDT | 80 | 1.6338 | 130.70 |
| SOLUSDT | 85 | 1.0730 | 91.20 |
| BNBUSDT | 69 | 0.1785 | 12.32 |
| BTCUSDT | 43 | 0.0764 | 3.28 |
| ETHUSDT | 62 | -0.0790 | -4.90 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 5.

Annual n (limits book): 72.35 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 111.13 per year.
By year (KST entry year): 2021: n 77 mean 2.458, 2023: n 116 mean 0.331, 2024: n 105 mean 1.360, 2025: n 102 mean 0.186, 2026: n 16 mean 0.889

Average hold 142.94 h (median 88.00); realized cost 0.0357 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00279 (return units); exit reasons {'channel': 165, 'end_of_data': 3, 'stop': 248}

Trades per month: 2021-01 11, 2021-02 2, 2021-03 11, 2021-04 3, 2021-05 2, 2021-08 8, 2021-09 5, 2021-10 9, 2021-11 14, 2021-12 12, 2023-01 11, 2023-02 13, 2023-03 12, 2023-04 17, 2023-05 14, 2023-06 10, 2023-07 9, 2023-08 8, 2023-10 3, 2023-11 9, 2023-12 10, 2024-01 13, 2024-02 2, 2024-03 5, 2024-04 11, 2024-05 12, 2024-06 18, 2024-07 6, 2024-08 3, 2024-09 4, 2024-10 8, 2024-11 9, 2024-12 14, 2025-01 13, 2025-02 11, 2025-03 12, 2025-04 4, 2025-05 8, 2025-06 13, 2025-07 9, 2025-08 13, 2025-09 9, 2025-10 8, 2025-11 2, 2026-08 4, 2026-09 12

H7-T entry overlap (limits book): same week any coin 0.740, same week same coin 0.382; same day any coin 0.245, same day same coin 0.139 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

H7-T open-trade overlap (candidate list, n 639): entered while an H7-T trade on the same coin was open 0.152 (same side 0.152); an H7-T trade on the same coin entered while this trade was open 0.302; either 0.454 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)

Long / short (candidate list): long 639, short 0, long share 1.000

Signals skipped by the live limits: 223 of 639 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 221 (mean R 0.3322)
- daily_loss_cap: 2 (mean R -0.5429)

Same-4h-bar signal overlap across coins: 0 of 639 (0.000), max coins in one bar 1

- min-order skips at $100: 87 of 639
- min-order skips at $300: 13 of 639

Generator counters (summed over coins): entries 639, long_entries 639, not_first 181475, short_entries 0, signals 4021, skip_busy 1643, skip_no_minute 0, skip_other 0, skip_regime 1487, skip_stop_high 218, skip_stop_low 0, skip_window 34

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 639; sized 639; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Sizing-ledger RP-gate inputs on the unlimited candidate list (sizing-ledger R = unit / (stop_dist + 0.0017), n 639, mean R 0.7450; seed 100, N 79, q 0.000633; a different R definition from the clause lines above, so these are not the clause S1-3 etc. and feed only the RP gate): gate mean R pass=True value=0.7449646170688168; gate date-block lower bound pass=False value=-0.03780636471057183; gate 2x-cost mean (R - 0.0015/stop_dist) pass=True value=0.704443059645009; gate halves pass=True value=(0.9461549036264638, 0.5444030501566622); gate best-year share pass=True value=0.5506034464700809

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=62.65% top5-removed mean R=-0.2923), B: reference only (S1-5 pass=False MDD=68.09% top5-removed mean R=-0.2923), C: reference only (S1-5 pass=False MDD=64.19% top5-removed mean R=-0.2923)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 639 | 639 | 639 | 639 | 639 | 639 |
| Entered | 173 | 231 | 143 | 201 | 154 | 208 |
| Annual n (nearest int) | 30 | 40 | 25 | 35 | 27 | 36 |
| S1-0 tier | undecidable | undecidable | undecidable | undecidable | undecidable | undecidable |
| Mean R (sizing, R = net / loss at stop incl. fee) | 1.2738 | 0.8769 | 1.4703 | 1.0725 | 1.4504 | 1.0448 |
| Average hold (min) | 8700.83 | 6569.15 | 9066.38 | 6431.58 | 9120.22 | 6537.89 |
| Closed by replacement | 0 | 54 | 0 | 58 | 0 | 57 |
| Mean R of replaced | n/a | -0.2391 | n/a | -0.2263 | n/a | -0.2305 |
| Replace attempts failed | none | no_loser 328, still_blocked 7 | none | no_loser 365 | none | no_loser 355, still_blocked 3 |
| Final wallet | 4258.69 | 2622.05 | 6900.39 | 5794.96 | 5335.60 | 3865.87 |
| Max concurrent | 3 | 3 | 1 | 1 | 2 | 2 |
| Max open loss (fraction of wallet) | 5.92% | 6.00% | 5.00% | 5.00% | 5.79% | 5.86% |
| FE-Z1 real-order MDD | 62.65% | 70.46% | 68.09% | 71.83% | 64.19% | 69.15% |
| FE-Z2 share reaching -25% (seed 88) | 55.42% | 72.32% | 68.21% | 78.53% | 52.92% | 68.00% |
| FE-Z2 n (annual) | 30 | 40 | 25 | 35 | 27 | 36 |
| FE-Z3 worst trade loss/wallet | 5.32% | 8.05% | 6.28% | 8.05% | 5.38% | 8.04% |
| First -25% touch vs initial (report only) | n/a | n/a | n/a | n/a | n/a | n/a |
| First -25% touch vs peak (report only) | 2021-12-03 19:31:00 | 2021-10-22 19:23:00 | 2021-12-03 19:31:00 | 2021-10-22 19:23:00 | 2021-12-03 19:31:00 | 2021-10-22 19:23:00 |
| Sized by margin cap / by loss | 121 / 52 | 169 / 62 | 1 / 142 | 5 / 196 | 86 / 68 | 116 / 92 |
| Liquidated | 0 | 1 | 0 | 1 | 0 | 1 |
| Skips by reason | below_min_notional 2, max_positions 1, open_loss_cap 392, stop_vs_liq 71 | below_min_notional 2, max_positions 1, open_loss_cap 334, stop_vs_liq 71 | below_min_notional 2, open_loss_cap 423, stop_vs_liq 71 | below_min_notional 2, open_loss_cap 365, stop_vs_liq 71 | below_min_notional 2, open_loss_cap 412, stop_vs_liq 71 | below_min_notional 2, open_loss_cap 358, stop_vs_liq 71 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

