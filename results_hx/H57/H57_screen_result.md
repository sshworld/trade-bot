# H57 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h56-h58.md ae8a63a92973, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h56_h58.md 059963626773; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

## H57 / six (primary), seed 83, N 61, bound 99.918% (q 0.000820), min trades 60

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 189, months 36, win rate 0.455, mean R -0.0224 (0.30% cost -0.0588), PF 0.956, MDD 0.440, final wallet x0.845

Limits book: trades 189
- S1-0 trades / months: trades 189 >= 60 and months 36 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0224 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3222 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.0588 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.0363, -0.0804, 94, 95) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.4402 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.1481, 10) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2498, 99.8% -0.2884, lock bound index 8
end_of_data trades: 0

Lock aux numbers: trades 189 (>= 100: True), mean R -0.0224 (> 0: False), mean R at 2x cost -0.0588 (> 0: False)

- U1: coins with >= 10 trades 6, positive 3, share 0.500 (need >= 0.667; does not meet)
- U2: best coin DOGEUSDT share nan of total R -4.22 (need <= 0.35; does not meet)
- U3: mean R without DOGEUSDT: -0.0761, n 154 (does not meet)
- U4: in H16 universe: trades 184, coins 6, mean R -0.0260; not in H16: trades 5, coins 2, mean R 0.1110 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| DOGEUSDT | 35 | 0.2140 | 7.49 |
| ETHUSDT | 27 | 0.0770 | 2.08 |
| XRPUSDT | 31 | 0.0327 | 1.01 |
| BNBUSDT | 34 | -0.1021 | -3.47 |
| BTCUSDT | 30 | -0.1335 | -4.01 |
| SOLUSDT | 32 | -0.2291 | -7.33 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 3.

Annual n (limits book): 32.87 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 37.39 per year.
By year (KST entry year): 2021: n 16 mean 0.326, 2022: n 75 mean 0.001, 2023: n 15 mean -0.587, 2024: n 16 mean 0.116, 2025: n 20 mean 0.009, 2026: n 47 mean -0.058

Average hold 68.49 h (median 66.85); realized cost 0.0365 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00006 (return units); exit reasons {'stop': 95, 'target': 27, 'time': 67}

Trades per month: 2021-05 1, 2021-06 6, 2021-07 5, 2021-09 4, 2022-01 3, 2022-02 4, 2022-03 4, 2022-04 8, 2022-05 8, 2022-06 7, 2022-07 11, 2022-08 2, 2022-09 8, 2022-10 7, 2022-11 6, 2022-12 7, 2023-01 3, 2023-08 2, 2023-09 8, 2023-10 2, 2024-07 3, 2024-08 5, 2024-09 6, 2024-10 2, 2025-03 3, 2025-04 6, 2025-11 4, 2025-12 7, 2026-01 6, 2026-02 6, 2026-03 8, 2026-04 3, 2026-05 8, 2026-06 1, 2026-07 11, 2026-08 4

H7-T entry overlap (limits book): same week any coin 0.021, same week same coin 0.005; same day any coin 0.005, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 26 of 215 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 26 (mean R 0.1323)

Same-4h-bar signal overlap across coins: 27 of 215 (0.126), max coins in one bar 3

- min-order skips at $100: 35 of 215
- min-order skips at $300: 7 of 215

Generator counters (summed over coins): entries 215, expired_unfilled 188, fills 215, legs 403, orders_formed 403, signals 0, skip_busy 1261, skip_no_minute 0, skip_other 0, skip_stop_range 0, skip_window 50

Trades open across a data hole window: 0

