# H48 screen result (1m intrabar; frame old) -- 2026-10-29 10:59 KST

Runner: branch h48-screen @ 00db36fc63; runtime 711 s (whole session), peak RSS 1468 MB; locks: prereg-lock-h48.md 09580f1d71b9, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h48.md a3d09fac3cc1; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

## H48 / six (primary), seed 69, N 48, bound 99.896% (q 0.001042), min trades 100

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 93, months 35, win rate 0.269, mean R 1.2909 (0.30% cost 1.2756), PF 3.216, MDD 0.228, final wallet x4.341

Limits book: trades 93
- S1-0 trades / months: trades 93 >= 100 and months 35 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: 1.2909 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.4018 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: 1.2756 (threshold meets; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (1.272, 1.3093, 46, 47) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.2285 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.1149, 5) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (0.5716, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2429, 99.8% -0.3670, lock bound index 10
end_of_data trades: 3

Lock aux numbers: trades 93 (>= 100: False), mean R 1.2909 (> 0: True), mean R at 2x cost 1.2756 (> 0: True)

- U1: coins with >= 10 trades 6, positive 4, share 0.667 (need >= 0.667; meets)
- U2: best coin DOGEUSDT share 0.546 of total R 120.05 (need <= 0.35; does not meet)
- U3: mean R without DOGEUSDT: 0.6644, n 82 (meets)
- U4: in H16 universe: trades 89, coins 6, mean R 0.7204; not in H16: trades 4, coins 1, mean R 13.9845 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| DOGEUSDT | 11 | 5.9607 | 65.57 |
| SOLUSDT | 16 | 2.9899 | 47.84 |
| BTCUSDT | 18 | 0.9690 | 17.44 |
| ETHUSDT | 15 | 0.4828 | 7.24 |
| XRPUSDT | 14 | -0.4928 | -6.90 |
| BNBUSDT | 19 | -0.5864 | -11.14 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 4.

Annual n (limits book): 16.17 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 27.48 per year.
By year (KST entry year): 2021: n 13 mean 5.278, 2022: n 17 mean -0.636, 2023: n 23 mean 2.657, 2024: n 13 mean 0.575, 2025: n 14 mean -0.065, 2026: n 13 mean -0.417

Average hold 970.89 h (median 426.15); realized cost 0.0153 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.01669 (return units); exit reasons {'end_of_data': 3, 'signal': 46, 'stop': 44}

Trades per month: 2021-01 6, 2021-05 1, 2021-08 3, 2021-09 2, 2021-12 1, 2022-04 6, 2022-08 1, 2022-09 6, 2022-10 1, 2022-11 3, 2023-01 2, 2023-02 3, 2023-03 2, 2023-05 2, 2023-06 2, 2023-07 2, 2023-08 2, 2023-09 3, 2023-10 2, 2023-11 3, 2024-06 1, 2024-07 4, 2024-08 1, 2024-09 2, 2024-10 4, 2024-11 1, 2025-02 1, 2025-03 2, 2025-05 4, 2025-06 5, 2025-10 2, 2026-05 6, 2026-06 2, 2026-07 1, 2026-08 4

H7-T entry overlap (limits book): same week any coin 0.484, same week same coin 0.215; same day any coin 0.161, same day same coin 0.011 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 65 of 158 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 65 (mean R 1.5667)

Same-4h-bar signal overlap across coins: 111 of 158 (0.703), max coins in one bar 5

- min-order skips at $100: 33 of 158
- min-order skips at $300: 20 of 158

Generator counters (summed over coins): entries 158, signals 286, skip_busy 0, skip_no_minute 0, skip_other 0, skip_stop_range 0, skip_window 128

Trades open across a data hole window: 0

## H48 / new (aux), seed 70, N 48, bound 99.896% (q 0.001042), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)

trades 158, months 56, win rate 0.266, mean R 0.1314 (0.30% cost 0.1240), PF 1.214, MDD 0.439, final wallet x1.190

Limits book: trades 158
- S1-0 trades / months: trades 158 >= 100 and months 56 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: 0.1314 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.4257 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: 0.124 (threshold meets; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.1925, 0.0703, 79, 79) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.439 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4028, 8) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (1.2368, '2023') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.3180, 99.8% -0.3999, lock bound index 10
end_of_data trades: 2

Lock aux numbers: trades 158 (>= 100: True), mean R 0.1314 (> 0: True), mean R at 2x cost 0.1240 (> 0: True)

- U1: coins with >= 10 trades 0, positive 0, share nan (need >= 0.667; does not meet)
- U2: best coin ADAUSDT share 0.976 of total R 20.77 (need <= 0.35; does not meet)
- U3: mean R without ADAUSDT: 0.0033, n 153 (meets)
- U4: in H16 universe: trades 85, coins 51, mean R 0.1745; not in H16: trades 73, coins 49, mean R 0.0813 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| ADAUSDT | 5 | 4.0533 | 20.27 |
| PIPPINUSDT | 1 | 11.0687 | 11.07 |
| FETUSDT | 2 | 4.6046 | 9.21 |
| STORJUSDT | 1 | 8.4098 | 8.41 |
| MKRUSDT | 2 | 3.8177 | 7.64 |
| OCEANUSDT | 1 | 6.7720 | 6.77 |
| TRXUSDT | 4 | 1.3161 | 5.26 |
| ENAUSDT | 2 | 2.0092 | 4.02 |
| AAVEUSDT | 5 | 0.7769 | 3.88 |
| DUSKUSDT | 1 | 2.4182 | 2.42 |
| LINAUSDT | 1 | 2.3529 | 2.35 |
| WIFUSDT | 1 | 1.6323 | 1.63 |
| TRBUSDT | 5 | 0.3217 | 1.61 |
| NEARUSDT | 1 | 1.5851 | 1.59 |
| XLMUSDT | 1 | 1.4746 | 1.47 |

Coins with trades 80; with >= 10 trades 0; mean R > 0 among those 0.

Annual n (limits book): 27.48 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 175.83 per year.
By year (KST entry year): 2021: n 22 mean 0.470, 2022: n 38 mean -0.393, 2023: n 20 mean 1.284, 2024: n 23 mean 0.433, 2025: n 27 mean -0.124, 2026: n 28 mean -0.248

Average hold 810.11 h (median 447.39); realized cost 0.0074 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00778 (return units); exit reasons {'delist': 1, 'end_of_data': 2, 'signal': 74, 'stop': 81}

Trades per month: 2021-01 4, 2021-05 2, 2021-07 4, 2021-08 5, 2021-09 3, 2021-11 1, 2021-12 3, 2022-01 4, 2022-02 2, 2022-03 2, 2022-04 3, 2022-05 5, 2022-06 3, 2022-07 3, 2022-08 4, 2022-09 1, 2022-10 3, 2022-11 6, 2022-12 2, 2023-01 1, 2023-03 2, 2023-04 1, 2023-05 4, 2023-06 3, 2023-07 3, 2023-08 3, 2023-09 2, 2023-10 1, 2024-01 1, 2024-02 1, 2024-03 2, 2024-04 1, 2024-06 6, 2024-07 4, 2024-08 2, 2024-09 3, 2024-10 3, 2025-01 2, 2025-02 1, 2025-04 3, 2025-05 4, 2025-06 4, 2025-08 2, 2025-09 1, 2025-10 5, 2025-11 2, 2025-12 3, 2026-01 3, 2026-02 4, 2026-03 3, 2026-04 4, 2026-05 3, 2026-06 4, 2026-07 1, 2026-08 5, 2026-09 1

H7-T entry overlap (limits book): same week any coin 0.291, same week same coin 0.000; same day any coin 0.101, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 853 of 1011 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 853 (mean R -0.1191)

Same-4h-bar signal overlap across coins: 952 of 1011 (0.942), max coins in one bar 24

- min-order skips at $100: 191 of 1011
- min-order skips at $300: 16 of 1011

Generator counters (summed over coins): entries 1011, signals 10472, skip_busy 0, skip_no_minute 3054, skip_other 70, skip_stop_range 0, skip_window 6337

Trades open across a data hole window: 0

