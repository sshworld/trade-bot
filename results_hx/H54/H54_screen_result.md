# H54 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h53-h54.md b6f45ee172bf, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h53_h54.md be82b3a12320; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

## H54 / six (primary), seed 80, N 57, bound 99.912% (q 0.000877), min trades 100

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 1852, months 69, win rate 0.435, mean R -0.1306 (0.30% cost -0.2573), PF 0.739, MDD 0.997, final wallet x0.004

Limits book: trades 1852
- S1-0 trades / months: trades 1852 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1306 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2263 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2573 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.1222, -0.1391, 926, 926) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9967 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2615, 93) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1993, 99.8% -0.2160, lock bound index 8
end_of_data trades: 0

Lock aux numbers: trades 1852 (>= 100: True), mean R -0.1306 (> 0: False), mean R at 2x cost -0.2573 (> 0: False)

- U1: coins with >= 10 trades 6, positive 1, share 0.167 (need >= 0.667; does not meet)
- U2: best coin SOLUSDT share nan of total R -241.94 (need <= 0.35; does not meet)
- U3: mean R without SOLUSDT: -0.1461, n 1666 (does not meet)
- U4: in H16 universe: trades 1803, coins 6, mean R -0.1281; not in H16: trades 49, coins 3, mean R -0.2235 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| SOLUSDT | 186 | 0.0082 | 1.53 |
| BNBUSDT | 231 | -0.1062 | -24.53 |
| DOGEUSDT | 371 | -0.1219 | -45.23 |
| XRPUSDT | 360 | -0.1342 | -48.32 |
| BTCUSDT | 329 | -0.1699 | -55.90 |
| ETHUSDT | 375 | -0.1853 | -69.50 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 1.

Annual n (limits book): 322.09 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 437.22 per year.
By year (KST entry year): 2021: n 279 mean -0.129, 2022: n 326 mean -0.182, 2023: n 581 mean -0.046, 2024: n 287 mean -0.138, 2025: n 204 mean -0.200, 2026: n 175 mean -0.225

Average hold 1.46 h (median 0.63); realized cost 0.1266 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00001 (return units); exit reasons {'stop': 904, 'target': 547, 'time': 401}

Trades per month: 2021-01 32, 2021-02 34, 2021-03 24, 2021-04 13, 2021-05 36, 2021-06 19, 2021-07 18, 2021-08 13, 2021-09 18, 2021-10 28, 2021-11 20, 2021-12 24, 2022-01 21, 2022-02 9, 2022-03 16, 2022-04 21, 2022-05 23, 2022-06 26, 2022-07 15, 2022-08 16, 2022-09 23, 2022-10 45, 2022-11 43, 2022-12 68, 2023-01 56, 2023-02 43, 2023-03 40, 2023-04 40, 2023-05 53, 2023-06 52, 2023-07 53, 2023-08 62, 2023-09 56, 2023-10 63, 2023-11 34, 2023-12 32, 2024-01 35, 2024-02 21, 2024-03 28, 2024-04 24, 2024-05 20, 2024-06 36, 2024-07 36, 2024-08 24, 2024-09 16, 2024-10 16, 2024-11 11, 2024-12 17, 2025-01 23, 2025-02 21, 2025-03 17, 2025-04 20, 2025-05 11, 2025-06 15, 2025-07 6, 2025-08 14, 2025-09 16, 2025-10 29, 2025-11 8, 2025-12 25, 2026-01 26, 2026-02 14, 2026-03 18, 2026-04 10, 2026-05 21, 2026-06 18, 2026-07 10, 2026-08 28, 2026-09 29

H7-T entry overlap (limits book): same week any coin 0.440, same week same coin 0.179; same day any coin 0.119, same day same coin 0.042 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 662 of 2514 raw signals (mean unsized R of the skipped, descriptive only):
- daily_loss_cap: 422 (mean R 0.0843)
- max_concurrent: 240 (mean R 0.0490)

Same-4h-bar signal overlap across coins: 1261 of 2514 (0.502), max coins in one bar 6

- min-order skips at $100: 84 of 2514
- min-order skips at $300: 8 of 2514

Generator counters (summed over coins): above_F 151, cancelled 1236, entries 2514, expired 329, flushes 8173, signals 6608, skip_busy 2650, skip_no_minute 0, skip_other 0, skip_stop_range 317, skip_window 976

Trades open across a data hole window: 0

