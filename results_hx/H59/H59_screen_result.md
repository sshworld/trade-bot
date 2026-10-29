# H59 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h59-h60.md 85afd19cbaed, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h59_h60.md 17ee5db4e2f1; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Spec notes: H59: the lock condition 'Lo earlier than Hi' is an always-true (vacuous) condition because Lo is taken from the 40 bars before the 40 bars that contain Hi; implemented literally (always true). Orders persist until their 6-closed-4h-bar expiry or the next valid order; a bar without a valid cluster does not cancel.

## H59 / six (primary), seed 85, N 63, bound 99.921% (q 0.000794), min trades 100

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 67, months 31, win rate 0.224, mean R -0.2943 (0.30% cost -0.3947), PF 0.620, MDD 0.347, final wallet x0.656

Limits book: trades 67
- S1-0 trades / months: trades 67 >= 100 and months 31 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: -0.2943 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.8188 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.3947 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.2815, -0.3067, 33, 34) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.3475 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.529, 4) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.6850, 99.8% -0.7815, lock bound index 7
end_of_data trades: 0

Lock aux numbers: trades 67 (>= 100: False), mean R -0.2943 (> 0: False), mean R at 2x cost -0.3947 (> 0: False)

- U1: coins with >= 10 trades 4, positive 1, share 0.250 (need >= 0.667; does not meet)
- U2: best coin BNBUSDT share nan of total R -19.72 (need <= 0.35; does not meet)
- U3: mean R without BNBUSDT: -0.4732, n 52 (does not meet)
- U4: in H16 universe: trades 67, coins 6, mean R -0.2943; not in H16: trades 0, coins 0, mean R nan (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| BNBUSDT | 15 | 0.3261 | 4.89 |
| DOGEUSDT | 9 | 0.4813 | 4.33 |
| SOLUSDT | 4 | -1.0043 | -4.02 |
| BTCUSDT | 11 | -0.4442 | -4.89 |
| ETHUSDT | 10 | -0.5417 | -5.42 |
| XRPUSDT | 18 | -0.8122 | -14.62 |

Coins with trades 6; with >= 10 trades 4; mean R > 0 among those 1.

Annual n (limits book): 11.65 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 11.65 per year.
By year (KST entry year): 2021: n 8 mean -0.687, 2023: n 21 mean 0.016, 2024: n 21 mean -0.335, 2025: n 17 mean -0.441

Average hold 23.45 h (median 11.37); realized cost 0.1005 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00034 (return units); exit reasons {'stop': 52, 'target': 8, 'time': 7}

Trades per month: 2021-03 1, 2021-05 1, 2021-10 4, 2021-11 1, 2021-12 1, 2023-02 3, 2023-03 2, 2023-04 1, 2023-05 5, 2023-06 3, 2023-07 2, 2023-08 2, 2023-12 3, 2024-01 3, 2024-02 1, 2024-04 2, 2024-05 3, 2024-06 3, 2024-07 5, 2024-08 2, 2024-11 1, 2024-12 1, 2025-01 2, 2025-02 1, 2025-03 2, 2025-04 2, 2025-05 1, 2025-06 3, 2025-07 2, 2025-09 1, 2025-10 3

H7-T entry overlap (limits book): same week any coin 0.687, same week same coin 0.328; same day any coin 0.164, same day same coin 0.030 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 0 of 67 raw signals (mean unsized R of the skipped, descriptive only):

Same-4h-bar signal overlap across coins: 4 of 67 (0.060), max coins in one bar 2

- min-order skips at $100: 2 of 67
- min-order skips at $300: 0 of 67

Generator counters (summed over coins): entries 67, fills 67, orders 1907, signals 0, skip_busy 0, skip_no_minute 0, skip_other 0, skip_stop_range 0, skip_window 0, unfilled 1840

Trades open across a data hole window: 0

