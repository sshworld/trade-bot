# H53 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h53-h54.md b6f45ee172bf, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h53_h54.md be82b3a12320; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

## H53 / six (primary), seed 79, N 57, bound 99.912% (q 0.000877), min trades 200

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 3596, months 46, win rate 0.383, mean R -0.0126 (0.30% cost -0.1154), PF 0.979, MDD 0.997, final wallet x0.072

Limits book: trades 3596
- S1-0 trades / months: trades 3596 >= 200 and months 46 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0126 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.0996 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1154 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.0128, -0.0379, 1798, 1798) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9967 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.1115, 180) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.0733, 99.8% -0.0906, lock bound index 8
end_of_data trades: 1

Lock aux numbers: trades 3596 (>= 100: True), mean R -0.0126 (> 0: False), mean R at 2x cost -0.1154 (> 0: False)

- U1: coins with >= 10 trades 6, positive 3, share 0.500 (need >= 0.667; does not meet)
- U2: best coin SOLUSDT share nan of total R -45.14 (need <= 0.35; does not meet)
- U3: mean R without SOLUSDT: -0.0332, n 2997 (does not meet)
- U4: in H16 universe: trades 3486, coins 6, mean R -0.0270; not in H16: trades 110, coins 2, mean R 0.4453 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| SOLUSDT | 599 | 0.0907 | 54.33 |
| DOGEUSDT | 541 | 0.0367 | 19.83 |
| XRPUSDT | 536 | 0.0360 | 19.31 |
| BNBUSDT | 614 | -0.0236 | -14.49 |
| ETHUSDT | 630 | -0.0397 | -25.01 |
| BTCUSDT | 676 | -0.1466 | -99.11 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 3.

Annual n (limits book): 625.39 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 832.00 per year.
By year (KST entry year): 2021: n 869 mean 0.115, 2023: n 924 mean -0.092, 2024: n 894 mean -0.060, 2025: n 767 mean -0.053, 2026: n 142 mean 0.241

Average hold 7.17 h (median 4.55); realized cost 0.1029 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00017 (return units); exit reasons {'end_of_data': 1, 'stop': 2118, 'target': 1215, 'time': 262}

Trades per month: 2021-01 105, 2021-02 106, 2021-03 114, 2021-04 115, 2021-05 56, 2021-08 69, 2021-09 50, 2021-10 107, 2021-11 91, 2021-12 56, 2023-01 59, 2023-02 78, 2023-03 92, 2023-04 82, 2023-05 90, 2023-06 89, 2023-07 104, 2023-08 49, 2023-10 61, 2023-11 106, 2023-12 114, 2024-01 84, 2024-02 109, 2024-03 112, 2024-04 67, 2024-05 90, 2024-06 76, 2024-07 67, 2024-08 9, 2024-09 16, 2024-10 59, 2024-11 112, 2024-12 93, 2025-01 104, 2025-02 51, 2025-03 46, 2025-04 21, 2025-05 89, 2025-06 81, 2025-07 108, 2025-08 84, 2025-09 95, 2025-10 83, 2025-11 5, 2026-08 46, 2026-09 96

H7-T entry overlap (limits book): same week any coin 0.764, same week same coin 0.357; same day any coin 0.311, same day same coin 0.116 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 1188 of 4784 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 997 (mean R -0.1062)
- daily_loss_cap: 191 (mean R -0.0854)

Same-4h-bar signal overlap across coins: 422 of 4784 (0.088), max coins in one bar 4

- min-order skips at $100: 209 of 4784
- min-order skips at $300: 0 of 4784

Generator counters (summed over coins): busy_minutes 240556, cooldown_minutes 51755, entries 4784, gate_fail 24208, signals 4784, skip_busy 0, skip_no_minute 0, skip_other 0, skip_stop_range 0, skip_window 0

Trades open across a data hole window: 0

