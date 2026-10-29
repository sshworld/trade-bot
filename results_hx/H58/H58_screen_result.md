# H58 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h56-h58.md ae8a63a92973, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h56_h58.md 059963626773; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

## H58 / six (primary), seed 84, N 61, bound 99.918% (q 0.000820), min trades 60

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 228, months 37, win rate 0.504, mean R 0.0475 (0.30% cost 0.0200), PF 1.119, MDD 0.344, final wallet x1.151

Limits book: trades 228
- S1-0 trades / months: trades 228 >= 60 and months 37 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: 0.0475 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.1835 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: 0.02 (threshold meets; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.1541, -0.0591, 114, 114) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.3441 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.0333, 12) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (1.1793, '2022') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1276, 99.8% -0.1660, lock bound index 8
end_of_data trades: 0

Lock aux numbers: trades 228 (>= 100: True), mean R 0.0475 (> 0: True), mean R at 2x cost 0.0200 (> 0: True)

- U1: coins with >= 10 trades 6, positive 3, share 0.500 (need >= 0.667; does not meet)
- U2: best coin ETHUSDT share 1.167 of total R 10.83 (need <= 0.35; does not meet)
- U3: mean R without ETHUSDT: -0.0090, n 201 (does not meet)
- U4: in H16 universe: trades 224, coins 6, mean R 0.0424; not in H16: trades 4, coins 2, mean R 0.3346 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| ETHUSDT | 27 | 0.4682 | 12.64 |
| DOGEUSDT | 46 | 0.2031 | 9.34 |
| SOLUSDT | 34 | 0.0480 | 1.63 |
| BNBUSDT | 47 | -0.0274 | -1.29 |
| XRPUSDT | 38 | -0.1369 | -5.20 |
| BTCUSDT | 36 | -0.1748 | -6.29 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 3.

Annual n (limits book): 39.65 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 49.57 per year.
By year (KST entry year): 2021: n 22 mean 0.312, 2022: n 88 mean 0.145, 2023: n 18 mean -0.203, 2024: n 15 mean -0.139, 2025: n 30 mean 0.071, 2026: n 55 mean -0.094

Average hold 78.79 h (median 98.80); realized cost 0.0276 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00007 (return units); exit reasons {'stop': 82, 'target': 54, 'time': 92}

Trades per month: 2021-05 2, 2021-06 7, 2021-07 9, 2021-09 3, 2021-12 1, 2022-01 6, 2022-02 6, 2022-03 4, 2022-04 7, 2022-05 12, 2022-06 6, 2022-07 9, 2022-08 5, 2022-09 7, 2022-10 9, 2022-11 7, 2022-12 10, 2023-01 2, 2023-08 2, 2023-09 10, 2023-10 4, 2024-07 3, 2024-08 4, 2024-09 6, 2024-10 2, 2025-03 4, 2025-04 8, 2025-11 10, 2025-12 8, 2026-01 7, 2026-02 9, 2026-03 9, 2026-04 3, 2026-05 9, 2026-06 3, 2026-07 12, 2026-08 3

H7-T entry overlap (limits book): same week any coin 0.013, same week same coin 0.004; same day any coin 0.000, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 57 of 285 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 57 (mean R 0.0282)

Same-4h-bar signal overlap across coins: 39 of 285 (0.137), max coins in one bar 3

- min-order skips at $100: 55 of 285
- min-order skips at $300: 21 of 285

Generator counters (summed over coins): entries 285, expired_unfilled 128, fills 285, legs 413, orders_formed 413, signals 0, skip_busy 1251, skip_no_minute 0, skip_other 0, skip_stop_range 0, skip_window 50

Trades open across a data hole window: 0

