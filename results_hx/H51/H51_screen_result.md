# H51 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h50-h52.md 4f4bd7b20475, prereg-lock-h49-h51-v2-addendum.md e5181fe6a1b2, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h49_h51_v2_intrabar.md 4c12a5ae7d04; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Spec notes: H51 v2 fills the standing buy AT L literally (conservative for the buyer). The generator counter fill_above_open counts fills whose 1m bar opened below L (the lock says report it; no change of the fill rule).

## H51 / six (primary), seed 74, N 55, bound 99.909% (q 0.000909), min trades 60

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 577, months 41, win rate 0.205, mean R -0.5412 (0.30% cost -0.5596), PF 0.301, MDD 0.999, final wallet x0.002

Limits book: trades 577
- S1-0 trades / months: trades 577 >= 60 and months 41 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.5412 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.6608 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.5596 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.542, -0.5403, 288, 289) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9986 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.6384, 29) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2026') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.6311, 99.8% -0.6543, lock bound index 9
end_of_data trades: 3

Lock aux numbers: trades 577 (>= 100: True), mean R -0.5412 (> 0: False), mean R at 2x cost -0.5596 (> 0: False)

- U1: coins with >= 10 trades 6, positive 0, share 0.000 (need >= 0.667; does not meet)
- U2: best coin DOGEUSDT share nan of total R -312.24 (need <= 0.35; does not meet)
- U3: mean R without DOGEUSDT: -0.5655, n 513 (does not meet)
- U4: in H16 universe: trades 551, coins 6, mean R -0.5534; not in H16: trades 26, coins 2, mean R -0.2822 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| DOGEUSDT | 64 | -0.3461 | -22.15 |
| BNBUSDT | 104 | -0.3640 | -37.85 |
| SOLUSDT | 87 | -0.5219 | -45.41 |
| ETHUSDT | 94 | -0.5560 | -52.26 |
| BTCUSDT | 122 | -0.6056 | -73.88 |
| XRPUSDT | 106 | -0.7613 | -80.69 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 0.

Annual n (limits book): 100.35 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 138.61 per year.
By year (KST entry year): 2021: n 146 mean -0.441, 2023: n 162 mean -0.641, 2024: n 138 mean -0.510, 2025: n 114 mean -0.629, 2026: n 17 mean -0.109

Average hold 82.83 h (median 24.13); realized cost 0.0184 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00151 (return units); exit reasons {'end_of_data': 3, 'stop': 437, 'target': 102, 'time': 35}

Trades per month: 2021-01 33, 2021-02 29, 2021-03 7, 2021-04 20, 2021-05 12, 2021-08 2, 2021-09 11, 2021-10 7, 2021-11 19, 2021-12 6, 2023-01 4, 2023-02 13, 2023-03 25, 2023-04 18, 2023-05 14, 2023-06 5, 2023-07 20, 2023-08 26, 2023-11 13, 2023-12 24, 2024-01 33, 2024-02 8, 2024-03 15, 2024-04 20, 2024-05 7, 2024-06 18, 2024-07 2, 2024-08 2, 2024-09 1, 2024-10 5, 2024-11 10, 2024-12 17, 2025-01 13, 2025-02 12, 2025-03 1, 2025-05 3, 2025-06 18, 2025-07 12, 2025-08 21, 2025-09 26, 2025-10 8, 2026-08 3, 2026-09 14

H7-T entry overlap (limits book): same week any coin 0.674, same week same coin 0.248; same day any coin 0.159, same day same coin 0.021 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 220 of 797 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 204 (mean R -0.5701)
- daily_loss_cap: 16 (mean R 0.1134)

Same-4h-bar signal overlap across coins: 549 of 797 (0.689), max coins in one bar 5

- min-order skips at $100: 172 of 797
- min-order skips at $300: 102 of 797

Generator counters (summed over coins): entries 797, fill_above_open 552, orders 2602, signals 4975, skip_busy 2367, skip_no_minute 6, skip_other 0, skip_stop_range 0, skip_window 0, unfilled 1805

Trades open across a data hole window: 0

## H51 / new (aux), seed 77, N 55, bound 99.909% (q 0.000909), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 952, months 45, win rate 0.162, mean R -0.6360 (0.30% cost -0.6493), PF 0.226, MDD 1.000, final wallet x0.000

Limits book: trades 952
- S1-0 trades / months: trades 952 >= 100 and months 45 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.636 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.7232 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.6493 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.5976, -0.6744, 476, 476) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 1.0 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.7393, 48) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2026') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.7028, 99.8% -0.7190, lock bound index 9
end_of_data trades: 3

Lock aux numbers: trades 952 (>= 100: True), mean R -0.6360 (> 0: False), mean R at 2x cost -0.6493 (> 0: False)

- U1: coins with >= 10 trades 26, positive 1, share 0.038 (need >= 0.667; does not meet)
- U2: best coin CFXUSDT share nan of total R -605.45 (need <= 0.35; does not meet)
- U3: mean R without CFXUSDT: -0.6412, n 947 (does not meet)
- U4: in H16 universe: trades 548, coins 65, mean R -0.6725; not in H16: trades 404, coins 87, mean R -0.5864 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| CFXUSDT | 5 | 0.3603 | 1.80 |
| OGNUSDT | 1 | 1.2953 | 1.30 |
| COMPUSDT | 1 | 1.2889 | 1.29 |
| KNCUSDT | 1 | 1.2748 | 1.27 |
| BANDUSDT | 1 | 1.2712 | 1.27 |
| TIAUSDT | 1 | 1.2682 | 1.27 |
| ASTERUSDT | 1 | 1.2599 | 1.26 |
| OPUSDT | 1 | 1.2561 | 1.26 |
| LPTUSDT | 6 | 0.1908 | 1.14 |
| FTMUSDT | 9 | 0.1101 | 0.99 |
| UNFIUSDT | 4 | 0.1499 | 0.60 |
| INJUSDT | 10 | 0.0446 | 0.45 |
| LUNAUSDT | 2 | 0.1593 | 0.32 |
| ETHFIUSDT | 2 | 0.1545 | 0.31 |
| SYNUSDT | 2 | 0.1519 | 0.30 |

Coins with trades 106; with >= 10 trades 26; mean R > 0 among those 1.

Annual n (limits book): 165.57 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 704.70 per year.
By year (KST entry year): 2021: n 218 mean -0.513, 2023: n 283 mean -0.627, 2024: n 253 mean -0.741, 2025: n 152 mean -0.694, 2026: n 46 mean -0.507

Average hold 61.80 h (median 1.81); realized cost 0.0133 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00145 (return units); exit reasons {'end_of_data': 3, 'stop': 771, 'target': 131, 'time': 47}

Trades per month: 2021-01 33, 2021-02 24, 2021-03 8, 2021-04 22, 2021-05 15, 2021-08 7, 2021-09 24, 2021-10 15, 2021-11 35, 2021-12 35, 2023-01 8, 2023-02 17, 2023-03 32, 2023-04 31, 2023-05 33, 2023-06 58, 2023-07 27, 2023-08 20, 2023-10 13, 2023-11 19, 2023-12 25, 2024-01 38, 2024-02 12, 2024-03 14, 2024-04 49, 2024-05 14, 2024-06 28, 2024-07 9, 2024-08 1, 2024-09 2, 2024-10 9, 2024-11 30, 2024-12 47, 2025-01 14, 2025-02 10, 2025-04 1, 2025-05 10, 2025-06 42, 2025-07 14, 2025-08 20, 2025-09 29, 2025-10 11, 2025-11 1, 2026-08 14, 2026-09 32

H7-T entry overlap (limits book): same week any coin 0.672, same week same coin 0.000; same day any coin 0.184, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 3100 of 4052 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 2990 (mean R -0.6535)
- daily_loss_cap: 110 (mean R -0.2503)

Same-4h-bar signal overlap across coins: 3862 of 4052 (0.953), max coins in one bar 27

- min-order skips at $100: 630 of 4052
- min-order skips at $300: 87 of 4052

Generator counters (summed over coins): entries 4052, fill_above_open 3087, orders 33597, signals 54314, skip_busy 9017, skip_no_minute 11700, skip_other 0, skip_stop_range 0, skip_window 0, unfilled 29545

Trades open across a data hole window: 0

