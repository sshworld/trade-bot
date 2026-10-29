# H56 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h56-h58.md ae8a63a92973, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h56_h58.md 059963626773; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

## H56 / six (primary), seed 82, N 61, bound 99.918% (q 0.000820), min trades 100

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 355, months 45, win rate 0.408, mean R -0.0664 (0.30% cost -0.0915), PF 0.854, MDD 0.623, final wallet x0.561

Limits book: trades 355
- S1-0 trades / months: trades 355 >= 100 and months 45 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0664 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2409 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.0915 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.0479, -0.18, 177, 178) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.6233 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.1501, 18) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1939, 99.8% -0.2241, lock bound index 8
end_of_data trades: 1

Lock aux numbers: trades 355 (>= 100: True), mean R -0.0664 (> 0: False), mean R at 2x cost -0.0915 (> 0: False)

- U1: coins with >= 10 trades 6, positive 3, share 0.500 (need >= 0.667; does not meet)
- U2: best coin XRPUSDT share nan of total R -23.57 (need <= 0.35; does not meet)
- U3: mean R without XRPUSDT: -0.1038, n 292 (does not meet)
- U4: in H16 universe: trades 341, coins 6, mean R -0.0832; not in H16: trades 14, coins 2, mean R 0.3440 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| XRPUSDT | 63 | 0.1068 | 6.73 |
| SOLUSDT | 60 | 0.0986 | 5.92 |
| DOGEUSDT | 61 | 0.0562 | 3.43 |
| BTCUSDT | 57 | -0.1178 | -6.71 |
| BNBUSDT | 52 | -0.2854 | -14.84 |
| ETHUSDT | 62 | -0.2918 | -18.09 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 3.

Annual n (limits book): 61.74 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 73.91 per year.
By year (KST entry year): 2021: n 99 mean 0.121, 2023: n 89 mean -0.026, 2024: n 84 mean -0.192, 2025: n 69 mean -0.219, 2026: n 14 mean -0.146

Average hold 74.41 h (median 78.72); realized cost 0.0251 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00196 (return units); exit reasons {'end_of_data': 1, 'stop': 141, 'target': 73, 'time': 140}

Trades per month: 2021-01 15, 2021-02 11, 2021-03 8, 2021-04 12, 2021-05 9, 2021-08 9, 2021-09 6, 2021-10 15, 2021-11 9, 2021-12 5, 2023-01 8, 2023-02 6, 2023-03 8, 2023-04 8, 2023-05 9, 2023-06 7, 2023-07 9, 2023-08 4, 2023-10 5, 2023-11 11, 2023-12 14, 2024-01 4, 2024-02 13, 2024-03 7, 2024-04 9, 2024-05 6, 2024-06 3, 2024-07 6, 2024-08 5, 2024-09 6, 2024-10 8, 2024-11 8, 2024-12 9, 2025-01 8, 2025-02 6, 2025-03 7, 2025-04 2, 2025-05 9, 2025-06 6, 2025-07 11, 2025-08 7, 2025-09 5, 2025-10 8, 2026-08 5, 2026-09 9

H7-T entry overlap (limits book): same week any coin 0.780, same week same coin 0.473; same day any coin 0.245, same day same coin 0.135 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 70 of 425 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 70 (mean R 0.1450)

Same-4h-bar signal overlap across coins: 2 of 425 (0.005), max coins in one bar 2

- min-order skips at $100: 87 of 425
- min-order skips at $300: 32 of 425

Generator counters (summed over coins): entries 425, expired_unfilled 161, fills 425, legs 586, orders_formed 586, signals 0, skip_busy 2355, skip_no_minute 0, skip_other 0, skip_stop_range 0, skip_window 397

Trades open across a data hole window: 0

