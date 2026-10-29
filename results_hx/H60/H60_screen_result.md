# H60 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h59-h60.md 85afd19cbaed, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h59_h60.md 17ee5db4e2f1; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Spec notes: H60: the lock condition 'Hi2 earlier than Lo2' is an always-true (vacuous) condition because Hi2 is taken from the 40 bars before the 40 bars that contain Lo2; implemented literally (always true). Orders persist until their 6-closed-4h-bar expiry or the next valid order; a bar without a valid cluster does not cancel.

## H60 / six (primary), seed 86, N 63, bound 99.921% (q 0.000794), min trades 60

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 41, months 21, win rate 0.293, mean R 0.1666 (0.30% cost 0.0750), PF 1.247, MDD 0.148, final wallet x1.104

Limits book: trades 41
- S1-0 trades / months: trades 41 >= 60 and months 21 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: 0.1666 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.7111 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: 0.075 (threshold meets; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.4061, -0.0615, 20, 21) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.1478 (threshold meets; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2197, 3) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (2.0536, '2022') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.4832, 99.8% -0.6237, lock bound index 7
end_of_data trades: 0

Lock aux numbers: trades 41 (>= 100: False), mean R 0.1666 (> 0: True), mean R at 2x cost 0.0750 (> 0: True)

- U1: coins with >= 10 trades 1, positive 1, share 1.000 (need >= 0.667; meets)
- U2: best coin BNBUSDT share 0.510 of total R 6.83 (need <= 0.35; does not meet)
- U3: mean R without BNBUSDT: 0.0904, n 37 (meets)
- U4: in H16 universe: trades 41, coins 6, mean R 0.1666; not in H16: trades 0, coins 0, mean R nan (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| BNBUSDT | 4 | 0.8711 | 3.48 |
| BTCUSDT | 6 | 0.4243 | 2.55 |
| SOLUSDT | 11 | 0.1464 | 1.61 |
| DOGEUSDT | 7 | 0.2227 | 1.56 |
| ETHUSDT | 7 | -0.0343 | -0.24 |
| XRPUSDT | 6 | -0.3548 | -2.13 |

Coins with trades 6; with >= 10 trades 1; mean R > 0 among those 1.

Annual n (limits book): 7.13 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 7.13 per year.
By year (KST entry year): 2021: n 4 mean -0.992, 2022: n 14 mean 1.002, 2023: n 6 mean -0.168, 2024: n 6 mean 0.374, 2025: n 1 mean -0.990, 2026: n 10 mean -0.348

Average hold 28.09 h (median 10.13); realized cost 0.0915 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00005 (return units); exit reasons {'stop': 28, 'target': 4, 'time': 9}

Trades per month: 2021-06 3, 2021-08 1, 2022-02 2, 2022-03 1, 2022-04 2, 2022-07 2, 2022-09 1, 2022-10 3, 2022-11 3, 2023-01 1, 2023-09 1, 2023-10 4, 2024-07 1, 2024-08 4, 2024-10 1, 2025-03 1, 2026-01 2, 2026-04 3, 2026-05 3, 2026-07 1, 2026-08 1

H7-T entry overlap (limits book): same week any coin 0.049, same week same coin 0.000; same day any coin 0.000, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 0 of 41 raw signals (mean unsized R of the skipped, descriptive only):

Same-4h-bar signal overlap across coins: 0 of 41 (0.000), max coins in one bar 1

- min-order skips at $100: 3 of 41
- min-order skips at $300: 0 of 41

Generator counters (summed over coins): entries 41, fills 41, orders 1281, signals 0, skip_busy 0, skip_no_minute 0, skip_other 0, skip_stop_range 4, skip_window 0, unfilled 1236

Trades open across a data hole window: 0

