# Batch 3 clause numbers: H93 H94 H95 H96 H98 (numbers only, no verdict)

Source: results/<H>/<H>_screen_result.md and .json from the single --final session (runner h48-screen @ b91fd39; lock prereg-lock-h93-h98-v1_2.md c2945d535a11; QR hypotheses_h93_early_v1_1.md 1f575ac39bd7). Every number below is copied from those output files; nothing recalculated. Judgment is TA's.
S1-0 tiers: >= 1000 pass; 300-999 conditional; < 300 undecidable. "mechanical, verdict is TA's" tags and threshold words removed.

# H93
result md sha256 be6f46051abd4231eb19b2c1f7ad5109a23a13a069608e5d30ab22a7f221bb65; runtime_s 804
## H93 / six (primary), seed 97, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)
Summary line: trades 1667, months 69, win rate 0.292, mean R 0.2937 (0.30% cost 0.2545), PF 1.477, MDD 0.926, final wallet x5.667
Candidate list (unlimited, R units):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1667 trades)
  - S1-1 mean R > 0: 0.2937
  - S1-2 date-block bootstrap lower bound > 0: -0.0855
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.2545
  - S1-4 both halves > 0 (first, second mean, n, n): (0.3764, 0.2111, 833, 834)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.9261, 'top5_removed_mean': -0.302, 'removed': 84}
  - S1-6 best-year share of total R <= 60% (share, year): (0.4309, '2021')
  - date-block bounds: 99% 0.0109, 99.8% -0.0467, lock bound index 6
Summary line: trades 915, months 68, win rate 0.297, mean R 0.3324 (0.30% cost 0.2926), PF 1.549, MDD 0.719, final wallet x13.129
Old-frame limits book (report only; this is what summary_numbers/json carry):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (915 trades)
  - S1-1 mean R > 0: 0.3324
  - S1-2 date-block bootstrap lower bound > 0: -0.1297
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.2926
  - S1-4 both halves > 0 (first, second mean, n, n): (0.3185, 0.3462, 457, 458)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.7188, 'top5_removed_mean': -0.2781, 'removed': 46}
  - S1-6 best-year share of total R <= 60% (share, year): (0.2855, '2021')
  - date-block bounds: 99% -0.0139, 99.8% -0.0675, lock bound index 6
H7-T entry overlap (limits book): same week any coin 0.401, same week same coin 0.154; same day any coin 0.095, same day same coin 0.033 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)
H7-T open-trade overlap (candidate list, n 1667): entered while an H7-T trade on the same coin was open 0.025 (same side 0.025); an H7-T trade on the same coin entered while this trade was open 0.150; either 0.175 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)
Long / short (candidate list): long 870, short 797, long share 0.522
Signals skipped by the live limits: 752 of 1667 raw signals (mean unsized R of the skipped, descriptive only):
  - max_concurrent: 725 (mean R 0.2551)
  - daily_loss_cap: 27 (mean R 0.0188)
Stop-width skips (generator counters, filter order window, next minute, busy, regime, stop width): skip_stop_low (<0.60%) 0, skip_stop_high (>8.0%) 485; entries 1667, signals 22555
FE sizing: Candidates 1667; sized 1667; variants run: A, B, C.
|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Entered | 445 | 545 | 342 | 455 | 377 | 509 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.3966 | 0.0413 | 0.2331 | 0.0703 | 0.5441 | 0.0916 |
| Final wallet | 848.12 | 105.03 | 252.95 | 136.66 | 1312.38 | 143.20 |
| FE-Z1 real-order MDD | 75.25% | 81.69% | 83.64% | 81.04% | 78.12% | 76.90% |
| FE-Z2 share reaching -25% (seed 88) | 95.62% | 95.96% | 98.09% | 97.19% | 95.19% | 96.03% |
| FE-Z3 worst trade loss/wallet | 10.07% | 8.73% | 14.10% | 8.73% | 9.99% | 8.73% |
| Liquidated | 1 | 1 | 1 | 1 | 1 | 1 |
| Skips by reason | below_min_notional 1, max_positions 6, open_loss_cap 1049, stop_vs_liq 166 | below_min_notional 22, max_positions 8, open_loss_cap 836, qty_zero 91, stop_vs_liq 165 | below_min_notional 1, open_loss_cap 1157, qty_zero 1, stop_vs_liq 166 | below_min_notional 4, open_loss_cap 1013, qty_zero 30, stop_vs_liq 165 | below_min_notional 1, open_loss_cap 1123, stop_vs_liq 166 | below_min_notional 5, open_loss_cap 978, qty_zero 10, stop_vs_liq 165 |

## H93 / new (aux), seed 97, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)
Summary line: trades 8510, months 70, win rate 0.257, mean R -0.0244 (0.30% cost -0.0526), PF 0.963, MDD 1.000, final wallet x0.000
Candidate list (unlimited, R units):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (8510 trades)
  - S1-1 mean R > 0: -0.0244
  - S1-2 date-block bootstrap lower bound > 0: -0.1866
  - S1-3 mean R at 2x cost (0.30%) > 0: -0.0526
  - S1-4 both halves > 0 (first, second mean, n, n): (0.0197, -0.0684, 4255, 4255)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 1.0, 'top5_removed_mean': -0.4115, 'removed': 426}
  - S1-6 best-year share of total R <= 60% (share, year): (nan, '2022')
  - date-block bounds: 99% -0.1470, 99.8% -0.1759, lock bound index 6
Summary line: trades 988, months 69, win rate 0.284, mean R 0.0563 (0.30% cost 0.0286), PF 1.094, MDD 0.880, final wallet x0.770
Old-frame limits book (report only; this is what summary_numbers/json carry):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (988 trades)
  - S1-1 mean R > 0: 0.0563
  - S1-2 date-block bootstrap lower bound > 0: -0.1637
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.0286
  - S1-4 both halves > 0 (first, second mean, n, n): (0.099, 0.0136, 494, 494)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.8796, 'top5_removed_mean': -0.3251, 'removed': 50}
  - S1-6 best-year share of total R <= 60% (share, year): (0.8628, '2022')
  - date-block bounds: 99% -0.1065, 99.8% -0.1512, lock bound index 6
H7-T entry overlap (limits book): same week any coin 0.421, same week same coin 0.000; same day any coin 0.093, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)
H7-T open-trade overlap (candidate list, n 8510): entered while an H7-T trade on the same coin was open 0.000 (same side 0.000); an H7-T trade on the same coin entered while this trade was open 0.000; either 0.000 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)
Long / short (candidate list): long 4553, short 3957, long share 0.535
Signals skipped by the live limits: 7522 of 8510 raw signals (mean unsized R of the skipped, descriptive only):
  - max_concurrent: 7321 (mean R -0.0266)
  - daily_loss_cap: 201 (mean R -0.3386)
Stop-width skips (generator counters, filter order window, next minute, busy, regime, stop width): skip_stop_low (<0.60%) 0, skip_stop_high (>8.0%) 7477; entries 8510, signals 274793
FE sizing: Candidates 8510; sized 8081; variants run: A, B.
Variant C not run on this group (per-coin f defined for the six only).
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 429 trades in 10 coins (AUDIOUSDT 4, EOSUSDT 149, FRONTUSDT 3, HNTUSDT 10, LUNAUSDT 13, MATICUSDT 150, RNDRUSDT 17, SRMUSDT 20, SXPUSDT 41, TOMOUSDT 22).
|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Entered | 378 | 665 | 348 | 621 |
| S1-0 tier | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.1098 | 0.0324 | 0.0852 | 0.0456 |
| Final wallet | 118.23 | 70.59 | 72.36 | 73.02 |
| FE-Z1 real-order MDD | 84.54% | 86.20% | 88.22% | 85.33% |
| FE-Z2 share reaching -25% (seed 88) | 97.41% | 99.05% | 98.70% | 99.24% |
| FE-Z3 worst trade loss/wallet | 5.88% | 8.79% | 5.88% | 8.80% |
| Liquidated | 0 | 2 | 0 | 2 |
| Skips by reason | bracket 46, open_loss_cap 4600, qty_zero 7, stop_vs_liq 3050 | bracket 46, open_loss_cap 4312, qty_zero 13, stop_vs_liq 3045 | bracket 46, open_loss_cap 4630, qty_zero 8, stop_vs_liq 3049 | bracket 46, open_loss_cap 4356, qty_zero 15, stop_vs_liq 3043 |

# H94
result md sha256 c5a1b1c93353f802825a5a9915e5b0cd395ef236dc13f35f2f81753ef9bbf846; runtime_s 804
## H94 / six (primary), seed 98, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)
Summary line: trades 1921, months 69, win rate 0.274, mean R 0.2480 (0.30% cost 0.2098), PF 1.426, MDD 0.947, final wallet x2.282
Candidate list (unlimited, R units):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1921 trades)
  - S1-1 mean R > 0: 0.248
  - S1-2 date-block bootstrap lower bound > 0: -0.0891
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.2098
  - S1-4 both halves > 0 (first, second mean, n, n): (0.4023, 0.0939, 960, 961)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.947, 'top5_removed_mean': -0.3169, 'removed': 97}
  - S1-6 best-year share of total R <= 60% (share, year): (0.4942, '2021')
  - date-block bounds: 99% -0.0039, 99.8% -0.0562, lock bound index 6
Summary line: trades 1029, months 69, win rate 0.283, mean R 0.3719 (0.30% cost 0.3338), PF 1.660, MDD 0.658, final wallet x17.676
Old-frame limits book (report only; this is what summary_numbers/json carry):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1029 trades)
  - S1-1 mean R > 0: 0.3719
  - S1-2 date-block bootstrap lower bound > 0: -0.0879
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.3338
  - S1-4 both halves > 0 (first, second mean, n, n): (0.5708, 0.1735, 514, 515)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.6582, 'top5_removed_mean': -0.2934, 'removed': 52}
  - S1-6 best-year share of total R <= 60% (share, year): (0.538, '2021')
  - date-block bounds: 99% 0.0043, 99.8% -0.0561, lock bound index 6
H7-T entry overlap (limits book): same week any coin 0.392, same week same coin 0.149; same day any coin 0.083, same day same coin 0.025 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)
H7-T open-trade overlap (candidate list, n 1921): entered while an H7-T trade on the same coin was open 0.023 (same side 0.023); an H7-T trade on the same coin entered while this trade was open 0.129; either 0.153 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)
Long / short (candidate list): long 1015, short 906, long share 0.528
Signals skipped by the live limits: 892 of 1921 raw signals (mean unsized R of the skipped, descriptive only):
  - max_concurrent: 774 (mean R 0.1583)
  - daily_loss_cap: 118 (mean R -0.2449)
Stop-width skips (generator counters, filter order window, next minute, busy, regime, stop width): skip_stop_low (<0.60%) 0, skip_stop_high (>8.0%) 999; entries 1921, signals 30326
FE sizing: Candidates 1921; sized 1921; variants run: A, B, C.
|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Entered | 484 | 677 | 370 | 538 | 414 | 581 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.2592 | 0.2126 | 0.0648 | 0.0704 | 0.2862 | 0.1248 |
| Final wallet | 372.75 | 266.53 | 78.96 | 119.44 | 219.15 | 137.94 |
| FE-Z1 real-order MDD | 72.57% | 74.99% | 83.50% | 84.82% | 77.77% | 76.74% |
| FE-Z2 share reaching -25% (seed 88) | 94.54% | 95.70% | 97.93% | 98.81% | 96.08% | 95.82% |
| FE-Z3 worst trade loss/wallet | 6.24% | 5.72% | 6.24% | 5.72% | 6.24% | 5.72% |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | max_positions 10, open_loss_cap 1181, stop_vs_liq 246 | below_min_notional 1, max_positions 14, open_loss_cap 983, stop_vs_liq 246 | open_loss_cap 1282, qty_zero 23, stop_vs_liq 246 | open_loss_cap 1137, stop_vs_liq 246 | open_loss_cap 1259, qty_zero 2, stop_vs_liq 246 | open_loss_cap 1093, qty_zero 1, stop_vs_liq 246 |

## H94 / new (aux), seed 98, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)
Summary line: trades 10339, months 70, win rate 0.240, mean R -0.0604 (0.30% cost -0.0877), PF 0.900, MDD 1.000, final wallet x-0.000
Candidate list (unlimited, R units):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (10339 trades)
  - S1-1 mean R > 0: -0.0604
  - S1-2 date-block bootstrap lower bound > 0: -0.2004
  - S1-3 mean R at 2x cost (0.30%) > 0: -0.0877
  - S1-4 both halves > 0 (first, second mean, n, n): (0.0015, -0.1222, 5169, 5170)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 1.0, 'top5_removed_mean': -0.406, 'removed': 517}
  - S1-6 best-year share of total R <= 60% (share, year): (nan, '2022')
  - date-block bounds: 99% -0.1661, 99.8% -0.1894, lock bound index 6
Summary line: trades 1143, months 68, win rate 0.255, mean R -0.0841 (0.30% cost -0.1120), PF 0.853, MDD 0.988, final wallet x0.053
Old-frame limits book (report only; this is what summary_numbers/json carry):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1143 trades)
  - S1-1 mean R > 0: -0.0841
  - S1-2 date-block bootstrap lower bound > 0: -0.2547
  - S1-3 mean R at 2x cost (0.30%) > 0: -0.112
  - S1-4 both halves > 0 (first, second mean, n, n): (-0.0382, -0.1299, 571, 572)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.9882, 'top5_removed_mean': -0.367, 'removed': 58}
  - S1-6 best-year share of total R <= 60% (share, year): (nan, '2022')
  - date-block bounds: 99% -0.2155, 99.8% -0.2397, lock bound index 6
H7-T entry overlap (limits book): same week any coin 0.424, same week same coin 0.000; same day any coin 0.097, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)
H7-T open-trade overlap (candidate list, n 10339): entered while an H7-T trade on the same coin was open 0.000 (same side 0.000); an H7-T trade on the same coin entered while this trade was open 0.000; either 0.000 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)
Long / short (candidate list): long 5679, short 4660, long share 0.549
Signals skipped by the live limits: 9196 of 10339 raw signals (mean unsized R of the skipped, descriptive only):
  - max_concurrent: 8615 (mean R -0.0299)
  - daily_loss_cap: 581 (mean R -0.4659)
Stop-width skips (generator counters, filter order window, next minute, busy, regime, stop width): skip_stop_low (<0.60%) 0, skip_stop_high (>8.0%) 14103; entries 10339, signals 445395
FE sizing: Candidates 10339; sized 9806; variants run: A, B.
Variant C not run on this group (per-coin f defined for the six only).
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 533 trades in 10 coins (AUDIOUSDT 6, EOSUSDT 184, FRONTUSDT 4, HNTUSDT 13, LUNAUSDT 21, MATICUSDT 169, RNDRUSDT 24, SRMUSDT 24, SXPUSDT 60, TOMOUSDT 28).
|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Entered | 412 | 753 | 372 | 618 |
| S1-0 tier | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0627 | -0.0248 | -0.0298 | -0.0948 |
| Final wallet | 12.44 | 9.17 | 16.90 | 2.46 |
| FE-Z1 real-order MDD | 94.52% | 95.55% | 91.11% | 98.19% |
| FE-Z2 share reaching -25% (seed 88) | 98.82% | 99.46% | 99.19% | 99.81% |
| FE-Z3 worst trade loss/wallet | 8.25% | 9.97% | 8.25% | 9.13% |
| Liquidated | 1 | 7 | 1 | 5 |
| Skips by reason | below_min_notional 492, bracket 55, open_loss_cap 4545, qty_zero 299, stop_vs_liq 4003 | below_min_notional 1315, bracket 55, open_loss_cap 3750, qty_zero 472, stop_vs_liq 3461 | below_min_notional 156, bracket 55, open_loss_cap 4975, qty_zero 172, stop_vs_liq 4076 | below_min_notional 3287, bracket 53, open_loss_cap 2786, qty_zero 603, stop_vs_liq 2459 |

# H95
result md sha256 17b24ca72a200ed68f8369e9af5d7633b58a869a36bf9673fd2df1c67794977d; runtime_s 804
## H95 / six (primary), seed 99, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)
Summary line: trades 870, months 68, win rate 0.266, mean R 0.2243 (0.30% cost 0.1844), PF 1.342, MDD 0.730, final wallet x2.006
Candidate list (unlimited, R units):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (870 trades)
  - S1-1 mean R > 0: 0.2243
  - S1-2 date-block bootstrap lower bound > 0: -0.1786
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.1844
  - S1-4 both halves > 0 (first, second mean, n, n): (0.1833, 0.2652, 435, 435)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.7301, 'top5_removed_mean': -0.3417, 'removed': 44}
  - S1-6 best-year share of total R <= 60% (share, year): (0.5823, '2024')
  - date-block bounds: 99% -0.0907, 99.8% -0.1377, lock bound index 6
Summary line: trades 585, months 68, win rate 0.294, mean R 0.2649 (0.30% cost 0.2261), PF 1.430, MDD 0.538, final wallet x5.068
Old-frame limits book (report only; this is what summary_numbers/json carry):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (585 trades)
  - S1-1 mean R > 0: 0.2649
  - S1-2 date-block bootstrap lower bound > 0: -0.123
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.2261
  - S1-4 both halves > 0 (first, second mean, n, n): (0.3495, 0.1806, 292, 293)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.5384, 'top5_removed_mean': -0.2281, 'removed': 30}
  - S1-6 best-year share of total R <= 60% (share, year): (0.3134, '2022')
  - date-block bounds: 99% -0.0378, 99.8% -0.0914, lock bound index 6
H7-T entry overlap (limits book): same week any coin 0.470, same week same coin 0.231; same day any coin 0.191, same day same coin 0.103 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)
H7-T open-trade overlap (candidate list, n 870): entered while an H7-T trade on the same coin was open 0.099 (same side 0.099); an H7-T trade on the same coin entered while this trade was open 0.190; either 0.287 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)
Long / short (candidate list): long 551, short 319, long share 0.633
Signals skipped by the live limits: 285 of 870 raw signals (mean unsized R of the skipped, descriptive only):
  - max_concurrent: 284 (mean R 0.1449)
  - daily_loss_cap: 1 (mean R -0.9969)
Stop-width skips (generator counters, filter order window, next minute, busy, regime, stop width): skip_stop_low (<0.60%) 0, skip_stop_high (>8.0%) 161; entries 870, signals 4968
FE sizing: Candidates 870; sized 870; variants run: A, B, C.
|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Entered | 296 | 336 | 243 | 293 | 263 | 324 |
| S1-0 tier | undecidable | conditional | undecidable | undecidable | undecidable | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.2211 | 0.1829 | 0.2199 | 0.1623 | 0.2383 | 0.2021 |
| Final wallet | 354.68 | 219.78 | 387.44 | 241.12 | 355.96 | 233.33 |
| FE-Z1 real-order MDD | 60.31% | 71.98% | 64.14% | 68.35% | 60.57% | 72.12% |
| FE-Z2 share reaching -25% (seed 88) | 82.90% | 86.07% | 91.06% | 91.73% | 82.59% | 85.80% |
| FE-Z3 worst trade loss/wallet | 5.11% | 5.14% | 6.41% | 6.41% | 6.41% | 6.41% |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | below_min_notional 21, max_positions 3, open_loss_cap 486, stop_vs_liq 64 | below_min_notional 50, max_positions 1, open_loss_cap 407, qty_zero 12, stop_vs_liq 64 | below_min_notional 8, open_loss_cap 555, stop_vs_liq 64 | below_min_notional 9, open_loss_cap 504, stop_vs_liq 64 | below_min_notional 8, open_loss_cap 535, stop_vs_liq 64 | below_min_notional 10, open_loss_cap 472, stop_vs_liq 64 |

## H95 / new (aux), seed 99, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)
Summary line: trades 0, months 0, win rate nan, mean R nan (0.30% cost nan), PF nan, MDD nan, final wallet x1.000
Candidate list (unlimited, R units):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): undecidable (0 trades)
Summary line: trades 0, months 0, win rate nan, mean R nan (0.30% cost nan), PF nan, MDD nan, final wallet x1.000
Old-frame limits book (report only; this is what summary_numbers/json carry):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): undecidable (0 trades)
Long / short (candidate list): long 0, short 0, long share nan
Signals skipped by the live limits: 0 of 0 raw signals (mean unsized R of the skipped, descriptive only):
Stop-width skips (generator counters, filter order window, next minute, busy, regime, stop width): skip_stop_low (<0.60%) 0, skip_stop_high (>8.0%) 0; entries 0, signals 0

# H96
result md sha256 11807f124eaf2f699c6b4e4feb821b256056a02774c85e4c6d566d5efd63636c; runtime_s 804
## H96 / six (primary), seed 100, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)
Summary line: trades 639, months 46, win rate 0.247, mean R 0.7450 (0.30% cost 0.7065), PF 2.060, MDD 0.807, final wallet x36.051
Candidate list (unlimited, R units):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (639 trades)
  - S1-1 mean R > 0: 0.745
  - S1-2 date-block bootstrap lower bound > 0: -0.0378
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.7065
  - S1-4 both halves > 0 (first, second mean, n, n): (0.9462, 0.5444, 319, 320)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.8073, 'top5_removed_mean': -0.2923, 'removed': 32}
  - S1-6 best-year share of total R <= 60% (share, year): (0.5506, '2021')
  - date-block bounds: 99% 0.1154, 99.8% 0.0078, lock bound index 6
Summary line: trades 416, months 46, win rate 0.274, mean R 0.9705 (0.30% cost 0.9348), PF 2.439, MDD 0.698, final wallet x65.655
Old-frame limits book (report only; this is what summary_numbers/json carry):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (416 trades)
  - S1-1 mean R > 0: 0.9705
  - S1-2 date-block bootstrap lower bound > 0: -0.0773
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.9348
  - S1-4 both halves > 0 (first, second mean, n, n): (1.2755, 0.6654, 208, 208)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.6982, 'top5_removed_mean': -0.1941, 'removed': 21}
  - S1-6 best-year share of total R <= 60% (share, year): (0.4688, '2021')
  - date-block bounds: 99% 0.1291, 99.8% 0.0021, lock bound index 6
H7-T entry overlap (limits book): same week any coin 0.740, same week same coin 0.382; same day any coin 0.245, same day same coin 0.139 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)
H7-T open-trade overlap (candidate list, n 639): entered while an H7-T trade on the same coin was open 0.152 (same side 0.152); an H7-T trade on the same coin entered while this trade was open 0.302; either 0.454 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)
Long / short (candidate list): long 639, short 0, long share 1.000
Signals skipped by the live limits: 223 of 639 raw signals (mean unsized R of the skipped, descriptive only):
  - max_concurrent: 221 (mean R 0.3322)
  - daily_loss_cap: 2 (mean R -0.5429)
Stop-width skips (generator counters, filter order window, next minute, busy, regime, stop width): skip_stop_low (<0.60%) 0, skip_stop_high (>8.0%) 218; entries 639, signals 4021
FE sizing: Candidates 639; sized 639; variants run: A, B, C.
|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Entered | 173 | 231 | 143 | 201 | 154 | 208 |
| S1-0 tier | undecidable | undecidable | undecidable | undecidable | undecidable | undecidable |
| Mean R (sizing, R = net / loss at stop incl. fee) | 1.2738 | 0.8769 | 1.4703 | 1.0725 | 1.4504 | 1.0448 |
| Final wallet | 4258.69 | 2622.05 | 6900.39 | 5794.96 | 5335.60 | 3865.87 |
| FE-Z1 real-order MDD | 62.65% | 70.46% | 68.09% | 71.83% | 64.19% | 69.15% |
| FE-Z2 share reaching -25% (seed 88) | 55.42% | 72.32% | 68.21% | 78.53% | 52.92% | 68.00% |
| FE-Z3 worst trade loss/wallet | 5.32% | 8.05% | 6.28% | 8.05% | 5.38% | 8.04% |
| Liquidated | 0 | 1 | 0 | 1 | 0 | 1 |
| Skips by reason | below_min_notional 2, max_positions 1, open_loss_cap 392, stop_vs_liq 71 | below_min_notional 2, max_positions 1, open_loss_cap 334, stop_vs_liq 71 | below_min_notional 2, open_loss_cap 423, stop_vs_liq 71 | below_min_notional 2, open_loss_cap 365, stop_vs_liq 71 | below_min_notional 2, open_loss_cap 412, stop_vs_liq 71 | below_min_notional 2, open_loss_cap 358, stop_vs_liq 71 |

# H98
result md sha256 48c089a4094894df47ef8e62fac861dba368bee6662a9fad67c8b5e547484654; runtime_s 804
## H98 / six (primary), seed 101, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)
Summary line: trades 1431, months 69, win rate 0.275, mean R 0.2167 (0.30% cost 0.1782), PF 1.367, MDD 0.866, final wallet x1.594
Candidate list (unlimited, R units):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1431 trades)
  - S1-1 mean R > 0: 0.2167
  - S1-2 date-block bootstrap lower bound > 0: -0.1228
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.1782
  - S1-4 both halves > 0 (first, second mean, n, n): (0.2457, 0.1877, 715, 716)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.8665, 'top5_removed_mean': -0.3175, 'removed': 72}
  - S1-6 best-year share of total R <= 60% (share, year): (0.4541, '2024')
  - date-block bounds: 99% -0.0371, 99.8% -0.0807, lock bound index 6
Summary line: trades 844, months 68, win rate 0.278, mean R 0.3161 (0.30% cost 0.2781), PF 1.542, MDD 0.721, final wallet x6.959
Old-frame limits book (report only; this is what summary_numbers/json carry):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (844 trades)
  - S1-1 mean R > 0: 0.3161
  - S1-2 date-block bootstrap lower bound > 0: -0.1715
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.2781
  - S1-4 both halves > 0 (first, second mean, n, n): (0.1935, 0.4386, 422, 422)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.7211, 'top5_removed_mean': -0.305, 'removed': 43}
  - S1-6 best-year share of total R <= 60% (share, year): (0.5588, '2024')
  - date-block bounds: 99% -0.0599, 99.8% -0.1169, lock bound index 6
H7-T entry overlap (limits book): same week any coin 0.374, same week same coin 0.148; same day any coin 0.100, same day same coin 0.024 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)
H7-T open-trade overlap (candidate list, n 1431): entered while an H7-T trade on the same coin was open 0.036 (same side 0.035); an H7-T trade on the same coin entered while this trade was open 0.137; either 0.172 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)
Long / short (candidate list): long 722, short 709, long share 0.505
Signals skipped by the live limits: 587 of 1431 raw signals (mean unsized R of the skipped, descriptive only):
  - max_concurrent: 569 (mean R 0.0769)
  - daily_loss_cap: 18 (mean R -0.0258)
Stop-width skips (generator counters, filter order window, next minute, busy, regime, stop width): skip_stop_low (<0.60%) 0, skip_stop_high (>8.0%) 353; entries 1431, signals 11825
FE sizing: Candidates 1431; sized 1431; variants run: A, B, C.
|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Entered | 387 | 495 | 308 | 429 | 359 | 467 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.6386 | 0.4947 | 0.6752 | 0.4977 | 0.6030 | 0.4582 |
| Final wallet | 2811.06 | 2431.94 | 2464.73 | 2949.62 | 1342.72 | 1242.05 |
| FE-Z1 real-order MDD | 70.71% | 70.46% | 66.38% | 62.67% | 63.76% | 68.84% |
| FE-Z2 share reaching -25% (seed 88) | 88.84% | 90.28% | 97.06% | 97.29% | 93.74% | 94.47% |
| FE-Z3 worst trade loss/wallet | 10.06% | 9.99% | 14.08% | 14.08% | 10.05% | 9.99% |
| Liquidated | 1 | 1 | 1 | 1 | 1 | 1 |
| Skips by reason | max_positions 1, open_loss_cap 897, stop_vs_liq 146 | max_positions 1, open_loss_cap 789, stop_vs_liq 146 | open_loss_cap 977, stop_vs_liq 146 | open_loss_cap 856, stop_vs_liq 146 | open_loss_cap 926, stop_vs_liq 146 | open_loss_cap 818, stop_vs_liq 146 |

## H98 / new (aux), seed 101, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)
Summary line: trades 7016, months 67, win rate 0.258, mean R -0.0322 (0.30% cost -0.0600), PF 0.947, MDD 1.000, final wallet x0.000
Candidate list (unlimited, R units):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (7016 trades)
  - S1-1 mean R > 0: -0.0322
  - S1-2 date-block bootstrap lower bound > 0: -0.1791
  - S1-3 mean R at 2x cost (0.30%) > 0: -0.06
  - S1-4 both halves > 0 (first, second mean, n, n): (0.0642, -0.1287, 3508, 3508)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 1.0, 'top5_removed_mean': -0.3917, 'removed': 351}
  - S1-6 best-year share of total R <= 60% (share, year): (nan, '2022')
  - date-block bounds: 99% -0.1466, 99.8% -0.1688, lock bound index 6
Summary line: trades 1002, months 67, win rate 0.283, mean R 0.0917 (0.30% cost 0.0647), PF 1.160, MDD 0.942, final wallet x0.722
Old-frame limits book (report only; this is what summary_numbers/json carry):
  - S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1002 trades)
  - S1-1 mean R > 0: 0.0917
  - S1-2 date-block bootstrap lower bound > 0: -0.1971
  - S1-3 mean R at 2x cost (0.30%) > 0: 0.0647
  - S1-4 both halves > 0 (first, second mean, n, n): (0.1818, 0.0017, 501, 501)
  - S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.9422, 'top5_removed_mean': -0.3408, 'removed': 51}
  - S1-6 best-year share of total R <= 60% (share, year): (0.9152, '2021')
  - date-block bounds: 99% -0.1360, 99.8% -0.1686, lock bound index 6
H7-T entry overlap (limits book): same week any coin 0.418, same week same coin 0.000; same day any coin 0.097, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)
H7-T open-trade overlap (candidate list, n 7016): entered while an H7-T trade on the same coin was open 0.000 (same side 0.000); an H7-T trade on the same coin entered while this trade was open 0.000; either 0.000 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)
Long / short (candidate list): long 3833, short 3183, long share 0.546
Signals skipped by the live limits: 6014 of 7016 raw signals (mean unsized R of the skipped, descriptive only):
  - max_concurrent: 5902 (mean R -0.0441)
  - daily_loss_cap: 112 (mean R -0.5157)
Stop-width skips (generator counters, filter order window, next minute, busy, regime, stop width): skip_stop_low (<0.60%) 0, skip_stop_high (>8.0%) 5393; entries 7016, signals 153124
FE sizing: Candidates 7016; sized 6644; variants run: A, B.
Variant C not run on this group (per-coin f defined for the six only).
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 372 trades in 10 coins (AUDIOUSDT 6, EOSUSDT 136, FRONTUSDT 3, HNTUSDT 9, LUNAUSDT 10, MATICUSDT 124, RNDRUSDT 15, SRMUSDT 12, SXPUSDT 39, TOMOUSDT 18).
|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Entered | 356 | 642 | 335 | 591 |
| S1-0 tier | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0684 | -0.0405 | -0.0658 | -0.0325 |
| Final wallet | 19.17 | 14.94 | 12.53 | 15.10 |
| FE-Z1 real-order MDD | 94.57% | 96.06% | 95.82% | 97.03% |
| FE-Z2 share reaching -25% (seed 88) | 98.69% | 99.50% | 99.56% | 99.42% |
| FE-Z3 worst trade loss/wallet | 6.62% | 6.62% | 9.39% | 8.61% |
| Liquidated | 0 | 0 | 1 | 1 |
| Skips by reason | below_min_notional 211, bracket 39, open_loss_cap 3299, qty_zero 123, stop_vs_liq 2616 | below_min_notional 232, bracket 39, open_loss_cap 3006, qty_zero 141, stop_vs_liq 2584 | below_min_notional 267, bracket 39, open_loss_cap 3309, qty_zero 148, stop_vs_liq 2546 | below_min_notional 542, bracket 39, open_loss_cap 2888, qty_zero 217, stop_vs_liq 2367 |

# Notes (from the output files and the lock text, no judgment)
- H95 / new: 0 trades, 0 signals in both books (H95_screen_result.md new section). Lock line 22: "A coin with no OI gives 0 trades on H95."
- H96: the output has the six (primary) group only; no new-coin section was written.
- New-coin groups: variant C not run (per-coin f defined for the six only); candidates without exchange filters/brackets in the snapshot were dropped before sizing (counts listed per group).
- Two books per group: the candidate list (unlimited, R units) carries the clause lines; the old-frame limits book is report only in the .md, but it is what summary_numbers.md and the .json S1 block carry.
- H7-T overlap: two measures as printed: entry overlap on the limits book (same week / same day) and open-trade overlap on the candidate list.
