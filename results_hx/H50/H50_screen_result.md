# H50 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h50-h52.md 4f4bd7b20475, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h50_h52.md 50291d79d243; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

## H50 / six (primary), seed 73, N 55, bound 99.909% (q 0.000909), min trades 60

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 30, months 16, win rate 0.667, mean R 0.2574 (0.30% cost 0.2446), PF 2.269, MDD 0.039, final wallet x1.156

Limits book: trades 30
- S1-0 trades / months: trades 30 >= 60 and months 16 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: 0.2574 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3332 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: 0.2446 (threshold meets; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0017, 0.5165, 15, 15) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.0395 (threshold meets; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (0.1381, 2) (threshold meets; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (1.0104, '2024') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1881, 99.8% -0.2714, lock bound index 9
end_of_data trades: 0

Lock aux numbers: trades 30 (>= 100: False), mean R 0.2574 (> 0: True), mean R at 2x cost 0.2446 (> 0: True)

- U1: coins with >= 10 trades 0, positive 0, share nan (need >= 0.667; does not meet)
- U2: best coin BNBUSDT share 0.452 of total R 7.72 (need <= 0.35; does not meet)
- U3: mean R without BNBUSDT: 0.1567, n 27 (meets)
- U4: in H16 universe: trades 30, coins 6, mean R 0.2574; not in H16: trades 0, coins 0, mean R nan (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| BNBUSDT | 3 | 1.1639 | 3.49 |
| ETHUSDT | 6 | 0.4114 | 2.47 |
| SOLUSDT | 6 | 0.2220 | 1.33 |
| XRPUSDT | 7 | 0.0757 | 0.53 |
| DOGEUSDT | 3 | 0.1753 | 0.53 |
| BTCUSDT | 5 | -0.1252 | -0.63 |

Coins with trades 6; with >= 10 trades 0; mean R > 0 among those 0.

Annual n (limits book): 5.22 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 5.74 per year.
By year (KST entry year): 2021: n 6 mean -0.044, 2022: n 3 mean 0.289, 2023: n 3 mean -0.101, 2024: n 9 mean 0.867, 2025: n 7 mean 0.230, 2026: n 2 mean -0.997

Average hold 209.50 h (median 240.00); realized cost 0.0128 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00008 (return units); exit reasons {'stop': 5, 'target': 3, 'time': 22}

Trades per month: 2021-05 2, 2021-06 1, 2021-12 3, 2022-06 2, 2022-11 1, 2023-06 1, 2023-08 2, 2024-04 1, 2024-06 2, 2024-07 3, 2024-08 3, 2025-01 1, 2025-10 3, 2025-11 3, 2026-02 1, 2026-06 1

H7-T entry overlap (limits book): same week any coin 0.233, same week same coin 0.000; same day any coin 0.033, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 3 of 33 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 3 (mean R 0.9888)

Same-4h-bar signal overlap across coins: 24 of 33 (0.727), max coins in one bar 6

- min-order skips at $100: 8 of 33
- min-order skips at $300: 6 of 33

Generator counters (summed over coins): entries 33, signals 35, skip_busy 0, skip_no_minute 0, skip_other 0, skip_stop_range 0, skip_window 2

Trades open across a data hole window: 0

## H50 / new (aux), seed 76, N 55, bound 99.909% (q 0.000909), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 73, months 33, win rate 0.548, mean R 0.0270 (0.30% cost 0.0156), PF 1.081, MDD 0.187, final wallet x1.019

Limits book: trades 73
- S1-0 trades / months: trades 73 >= 100 and months 33 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: 0.027 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3817 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: 0.0156 (threshold meets; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.1031, -0.0471, 36, 37) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.1872 (threshold meets; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.081, 4) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (1.8486, '2021') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2892, 99.8% -0.3624, lock bound index 9
end_of_data trades: 0

Lock aux numbers: trades 73 (>= 100: False), mean R 0.0270 (> 0: True), mean R at 2x cost 0.0156 (> 0: True)

- U1: coins with >= 10 trades 0, positive 0, share nan (need >= 0.667; does not meet)
- U2: best coin LTCUSDT share 2.597 of total R 1.97 (need <= 0.35; does not meet)
- U3: mean R without LTCUSDT: -0.0463, n 68 (does not meet)
- U4: in H16 universe: trades 18, coins 17, mean R -0.0799; not in H16: trades 55, coins 32, mean R 0.0620 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| LTCUSDT | 5 | 1.0235 | 5.12 |
| ETCUSDT | 6 | 0.7023 | 4.21 |
| ADAUSDT | 3 | 0.9451 | 2.84 |
| RUNEUSDT | 1 | 1.9871 | 1.99 |
| FILUSDT | 2 | 0.6513 | 1.30 |
| ONDOUSDT | 1 | 1.2548 | 1.25 |
| ZECUSDT | 1 | 1.1412 | 1.14 |
| ALICEUSDT | 1 | 1.1377 | 1.14 |
| ATOMUSDT | 2 | 0.3832 | 0.77 |
| NEARUSDT | 3 | 0.2523 | 0.76 |
| EOSUSDT | 1 | 0.3884 | 0.39 |
| MATICUSDT | 1 | 0.2951 | 0.30 |
| XLMUSDT | 5 | 0.0327 | 0.16 |
| 1000SHIBUSDT | 3 | 0.0433 | 0.13 |
| UNFIUSDT | 1 | 0.1029 | 0.10 |

Coins with trades 39; with >= 10 trades 0; mean R > 0 among those 0.

Annual n (limits book): 12.70 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 30.09 per year.
By year (KST entry year): 2021: n 9 mean 0.405, 2022: n 12 mean 0.104, 2023: n 8 mean 0.353, 2024: n 17 mean 0.173, 2025: n 20 mean -0.252, 2026: n 7 mean -0.519

Average hold 203.92 h (median 240.00); realized cost 0.0114 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00007 (return units); exit reasons {'stop': 20, 'target': 2, 'time': 51}

Trades per month: 2021-06 3, 2021-07 1, 2021-09 1, 2021-10 1, 2021-12 3, 2022-01 3, 2022-02 2, 2022-05 1, 2022-06 3, 2022-10 3, 2023-05 1, 2023-06 3, 2023-08 3, 2023-12 1, 2024-01 1, 2024-04 2, 2024-06 6, 2024-07 4, 2024-08 3, 2024-12 1, 2025-01 3, 2025-02 3, 2025-03 2, 2025-04 1, 2025-06 2, 2025-09 2, 2025-10 3, 2025-11 4, 2026-01 1, 2026-02 3, 2026-03 1, 2026-05 1, 2026-06 1

H7-T entry overlap (limits book): same week any coin 0.288, same week same coin 0.000; same day any coin 0.055, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 100 of 173 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 100 (mean R 0.2337)

Same-4h-bar signal overlap across coins: 155 of 173 (0.896), max coins in one bar 27

- min-order skips at $100: 40 of 173
- min-order skips at $300: 1 of 173

Generator counters (summed over coins): entries 173, signals 541, skip_busy 0, skip_no_minute 115, skip_other 1, skip_stop_range 0, skip_window 252

Trades open across a data hole window: 0

