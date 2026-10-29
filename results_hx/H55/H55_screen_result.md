# H55 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h55.md 17da062a1189, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h55.md dacde151306d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

## H55 / six (primary), seed 81, N 58, bound 99.914% (q 0.000862), min trades 100

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 303, months 45, win rate 0.383, mean R -0.0742 (0.30% cost -0.1088), PF 0.865, MDD 0.684, final wallet x0.555

Limits book: trades 303
- S1-0 trades / months: trades 303 >= 100 and months 45 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0742 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3139 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1088 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.1163, -0.2636, 151, 152) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.6841 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2034, 16) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2497, 99.8% -0.2892, lock bound index 8
end_of_data trades: 1

Lock aux numbers: trades 303 (>= 100: True), mean R -0.0742 (> 0: False), mean R at 2x cost -0.1088 (> 0: False)

- U1: coins with >= 10 trades 6, positive 2, share 0.333 (need >= 0.667; does not meet)
- U2: best coin DOGEUSDT share nan of total R -22.50 (need <= 0.35; does not meet)
- U3: mean R without DOGEUSDT: -0.1068, n 255 (does not meet)
- U4: in H16 universe: trades 296, coins 6, mean R -0.0747; not in H16: trades 7, coins 2, mean R -0.0569 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| DOGEUSDT | 48 | 0.0987 | 4.74 |
| SOLUSDT | 48 | 0.0434 | 2.08 |
| XRPUSDT | 47 | -0.0091 | -0.43 |
| BTCUSDT | 52 | -0.1018 | -5.29 |
| BNBUSDT | 51 | -0.1450 | -7.40 |
| ETHUSDT | 57 | -0.2842 | -16.20 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 2.

Annual n (limits book): 52.70 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 57.39 per year.
By year (KST entry year): 2021: n 75 mean 0.245, 2023: n 78 mean -0.026, 2024: n 78 mean -0.311, 2025: n 64 mean -0.144, 2026: n 8 mean -0.670

Average hold 63.88 h (median 56.98); realized cost 0.0345 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00148 (return units); exit reasons {'end_of_data': 1, 'stop': 159, 'target': 47, 'time': 96}

Trades per month: 2021-01 14, 2021-02 4, 2021-03 5, 2021-04 6, 2021-05 9, 2021-08 9, 2021-09 4, 2021-10 10, 2021-11 9, 2021-12 5, 2023-01 8, 2023-02 5, 2023-03 8, 2023-04 7, 2023-05 7, 2023-06 5, 2023-07 9, 2023-08 4, 2023-10 1, 2023-11 13, 2023-12 11, 2024-01 3, 2024-02 9, 2024-03 8, 2024-04 10, 2024-05 7, 2024-06 3, 2024-07 6, 2024-08 5, 2024-09 5, 2024-10 9, 2024-11 5, 2024-12 8, 2025-01 7, 2025-02 6, 2025-03 7, 2025-04 1, 2025-05 9, 2025-06 6, 2025-07 9, 2025-08 6, 2025-09 4, 2025-10 9, 2026-08 2, 2026-09 6

H7-T entry overlap (limits book): same week any coin 0.772, same week same coin 0.449; same day any coin 0.188, same day same coin 0.083 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 27 of 330 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 27 (mean R 0.2561)

Same-4h-bar signal overlap across coins: 0 of 330 (0.000), max coins in one bar 1

- min-order skips at $100: 62 of 330
- min-order skips at $300: 9 of 330

Generator counters (summed over coins): entries 330, expired_unfilled 243, fills 330, legs 573, orders_formed 573, signals 0, skip_busy 2368, skip_no_minute 0, skip_other 0, skip_stop_range 0, skip_window 397

Trades open across a data hole window: 0

