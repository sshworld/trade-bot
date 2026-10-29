# H52 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h50-h52.md 4f4bd7b20475, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h50_h52.md 50291d79d243; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

## H52 / six (primary), seed 75, N 55, bound 99.909% (q 0.000909), min trades 60

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 94, months 42, win rate 0.383, mean R 0.3051 (0.30% cost 0.2915), PF 2.287, MDD 0.189, final wallet x1.680

Limits book: trades 94
- S1-0 trades / months: trades 94 >= 60 and months 42 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: 0.3051 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.0972 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: 0.2915 (threshold meets; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.5837, 0.0265, 47, 47) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.1891 (threshold meets; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (0.0021, 5) (threshold meets; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (0.555, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.0251, 99.8% -0.0758, lock bound index 9
end_of_data trades: 2

Lock aux numbers: trades 94 (>= 100: False), mean R 0.3051 (> 0: True), mean R at 2x cost 0.2915 (> 0: True)

- U1: coins with >= 10 trades 2, positive 2, share 1.000 (need >= 0.667; meets)
- U2: best coin BNBUSDT share 0.692 of total R 28.68 (need <= 0.35; does not meet)
- U3: mean R without BNBUSDT: 0.2265, n 39 (meets)
- U4: in H16 universe: trades 87, coins 6, mean R 0.2944; not in H16: trades 7, coins 2, mean R 0.4376 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| BNBUSDT | 55 | 0.3608 | 19.85 |
| SOLUSDT | 18 | 0.3279 | 5.90 |
| BTCUSDT | 3 | 1.1152 | 3.35 |
| DOGEUSDT | 8 | 0.2052 | 1.64 |
| ETHUSDT | 1 | -0.2601 | -0.26 |
| XRPUSDT | 9 | -0.1998 | -1.80 |

Coins with trades 6; with >= 10 trades 2; mean R > 0 among those 2.

Annual n (limits book): 16.35 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 17.04 per year.
By year (KST entry year): 2021: n 24 mean 0.438, 2023: n 22 mean 0.723, 2024: n 20 mean -0.176, 2025: n 25 mean 0.135, 2026: n 3 mean 0.796

Average hold 202.00 h (median 90.42); realized cost 0.0136 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00159 (return units); exit reasons {'end_of_data': 2, 'signal': 81, 'stop': 11}

Trades per month: 2021-01 6, 2021-02 3, 2021-03 2, 2021-04 1, 2021-05 3, 2021-09 3, 2021-10 3, 2021-11 1, 2021-12 2, 2023-01 3, 2023-02 6, 2023-03 1, 2023-04 2, 2023-05 2, 2023-06 3, 2023-07 1, 2023-08 1, 2023-10 2, 2023-12 1, 2024-02 1, 2024-03 1, 2024-04 4, 2024-05 3, 2024-06 3, 2024-07 2, 2024-08 2, 2024-09 1, 2024-10 1, 2024-12 2, 2025-01 3, 2025-02 3, 2025-03 4, 2025-04 3, 2025-05 1, 2025-06 2, 2025-07 2, 2025-08 1, 2025-09 3, 2025-10 2, 2025-11 1, 2026-08 1, 2026-09 2

H7-T entry overlap (limits book): same week any coin 0.681, same week same coin 0.362; same day any coin 0.277, same day same coin 0.064 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 4 of 98 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 4 (mean R 1.1602)

Same-4h-bar signal overlap across coins: 16 of 98 (0.163), max coins in one bar 2

- min-order skips at $100: 12 of 98
- min-order skips at $300: 3 of 98

Generator counters (summed over coins): entries 98, signals 568, skip_busy 392, skip_no_minute 0, skip_other 0, skip_stop_range 0, skip_window 78

Trades open across a data hole window: 0

## H52 / new (aux), seed 78, N 55, bound 99.909% (q 0.000909), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 205, months 41, win rate 0.273, mean R 0.0325 (0.30% cost 0.0223), PF 1.100, MDD 0.219, final wallet x1.079

Limits book: trades 205
- S1-0 trades / months: trades 205 >= 100 and months 41 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: 0.0325 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.1937 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: 0.0223 (threshold meets; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0245, 0.0889, 102, 103) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.2192 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.1713, 11) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (1.1264, '2026') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1469, 99.8% -0.1794, lock bound index 9
end_of_data trades: 2

Lock aux numbers: trades 205 (>= 100: True), mean R 0.0325 (> 0: True), mean R at 2x cost 0.0223 (> 0: True)

- U1: coins with >= 10 trades 2, positive 2, share 1.000 (need >= 0.667; meets)
- U2: best coin INJUSDT share 1.269 of total R 6.67 (need <= 0.35; does not meet)
- U3: mean R without INJUSDT: -0.0088, n 204 (does not meet)
- U4: in H16 universe: trades 67, coins 37, mean R -0.0863; not in H16: trades 138, coins 60, mean R 0.0902 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| INJUSDT | 1 | 8.4568 | 8.46 |
| TRXUSDT | 20 | 0.2104 | 4.21 |
| BCHUSDT | 27 | 0.1318 | 3.56 |
| ENAUSDT | 1 | 3.1199 | 3.12 |
| WLDUSDT | 2 | 1.4187 | 2.84 |
| AXSUSDT | 4 | 0.6990 | 2.80 |
| RUNEUSDT | 3 | 0.7778 | 2.33 |
| SUIUSDT | 3 | 0.7548 | 2.26 |
| UNIUSDT | 2 | 1.0844 | 2.17 |
| HBARUSDT | 5 | 0.3447 | 1.72 |
| OMGUSDT | 2 | 0.7527 | 1.51 |
| ZECUSDT | 1 | 1.3732 | 1.37 |
| HYPEUSDT | 1 | 1.3361 | 1.34 |
| LINAUSDT | 3 | 0.4337 | 1.30 |
| KNCUSDT | 1 | 1.2961 | 1.30 |

Coins with trades 82; with >= 10 trades 2; mean R > 0 among those 2.

Annual n (limits book): 35.65 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 61.91 per year.
By year (KST entry year): 2021: n 28 mean -0.208, 2023: n 65 mean 0.096, 2024: n 39 mean -0.055, 2025: n 63 mean 0.015, 2026: n 10 mean 0.751

Average hold 169.93 h (median 96.00); realized cost 0.0102 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00554 (return units); exit reasons {'end_of_data': 2, 'signal': 171, 'stop': 32}

Trades per month: 2021-02 1, 2021-05 5, 2021-09 5, 2021-10 5, 2021-11 7, 2021-12 5, 2023-01 5, 2023-02 8, 2023-03 11, 2023-04 9, 2023-05 4, 2023-06 8, 2023-07 3, 2023-08 4, 2023-10 4, 2023-11 5, 2023-12 4, 2024-01 4, 2024-03 1, 2024-04 5, 2024-05 5, 2024-06 1, 2024-07 3, 2024-08 4, 2024-09 3, 2024-10 6, 2024-11 3, 2024-12 4, 2025-01 5, 2025-02 4, 2025-03 8, 2025-04 3, 2025-05 5, 2025-06 7, 2025-07 9, 2025-08 12, 2025-09 2, 2025-10 6, 2025-11 2, 2026-08 6, 2026-09 4

H7-T entry overlap (limits book): same week any coin 0.678, same week same coin 0.000; same day any coin 0.317, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 151 of 356 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 151 (mean R 0.1461)

Same-4h-bar signal overlap across coins: 184 of 356 (0.517), max coins in one bar 7

- min-order skips at $100: 62 of 356
- min-order skips at $300: 10 of 356

Generator counters (summed over coins): entries 356, signals 6440, skip_busy 1206, skip_no_minute 1442, skip_other 2, skip_stop_range 0, skip_window 3434

Trades open across a data hole window: 0

