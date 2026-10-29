# H62 screen result (1m intrabar; frame fe2) -- 2026-10-29 12:10 KST

Runner: branch h48-screen @ 714a1e3488; runtime 709 s (whole session), peak RSS 1460 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H62 / six (primary), seed 90, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 761, months 69, win rate 0.348, mean R -0.1287 (0.30% cost -0.2408), PF 0.780, MDD 0.905, final wallet x0.101

Candidate list (unlimited, R units): trades 761
- S1-0 trades / months: trades 761 >= 300 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1287 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3016 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2408 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.1805, -0.0772, 380, 381) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9049 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3097, 39) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2545, 99.8% -0.2828, lock bound index 6

Candidate list: 761 trades, average hold 6.17 h, annual n 133 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 738, months 69, win rate 0.350, mean R -0.1261 (0.30% cost -0.2389), PF 0.784, MDD 0.892, final wallet x0.114

Limits book: trades 738
- S1-0 trades / months: trades 738 >= 300 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1261 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2903 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2389 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.1814, -0.0709, 369, 369) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.8923 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.302, 37) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2506, 99.8% -0.2740, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 738 (>= 100: True), mean R -0.1261 (> 0: False), mean R at 2x cost -0.2389 (> 0: False)

- U1: coins with >= 10 trades 6, positive 0, share 0.000 (need >= 0.667; does not meet)
- U2: best coin SOLUSDT share nan of total R -93.09 (need <= 0.35; does not meet)
- U3: mean R without SOLUSDT: -0.1430, n 598 (does not meet)
- U4: in H16 universe: trades 719, coins 6, mean R -0.1308; not in H16: trades 19, coins 3, mean R 0.0519 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| SOLUSDT | 140 | -0.0542 | -7.59 |
| ETHUSDT | 129 | -0.0653 | -8.42 |
| DOGEUSDT | 121 | -0.0736 | -8.91 |
| BTCUSDT | 103 | -0.1625 | -16.74 |
| BNBUSDT | 124 | -0.1692 | -20.98 |
| XRPUSDT | 121 | -0.2517 | -30.45 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 0.

Annual n (limits book): 128.35 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 132.35 per year.
By year (KST entry year): 2021: n 192 mean -0.173, 2022: n 147 mean -0.287, 2023: n 93 mean 0.092, 2024: n 114 mean -0.058, 2025: n 123 mean -0.001, 2026: n 69 mean -0.284

Average hold 6.16 h (median 4.86); realized cost 0.1128 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00007 (return units); exit reasons {'stop': 416, 'target': 175, 'time': 147}

Trades per month: 2021-01 16, 2021-02 16, 2021-03 15, 2021-04 17, 2021-05 14, 2021-06 22, 2021-07 19, 2021-08 17, 2021-09 10, 2021-10 17, 2021-11 20, 2021-12 9, 2022-01 8, 2022-02 8, 2022-03 5, 2022-04 9, 2022-05 16, 2022-06 15, 2022-07 26, 2022-08 8, 2022-09 16, 2022-10 11, 2022-11 10, 2022-12 15, 2023-01 10, 2023-02 9, 2023-03 6, 2023-04 5, 2023-05 14, 2023-06 6, 2023-07 6, 2023-08 9, 2023-09 5, 2023-10 5, 2023-11 8, 2023-12 10, 2024-01 11, 2024-02 14, 2024-03 8, 2024-04 11, 2024-05 8, 2024-06 2, 2024-07 12, 2024-08 11, 2024-09 7, 2024-10 10, 2024-11 9, 2024-12 11, 2025-01 11, 2025-02 7, 2025-03 11, 2025-04 15, 2025-05 9, 2025-06 12, 2025-07 10, 2025-08 17, 2025-09 6, 2025-10 6, 2025-11 18, 2025-12 1, 2026-01 9, 2026-02 12, 2026-03 4, 2026-04 12, 2026-05 8, 2026-06 6, 2026-07 9, 2026-08 2, 2026-09 7

H7-T entry overlap (limits book): same week any coin 0.400, same week same coin 0.187; same day any coin 0.140, same day same coin 0.030 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 23 of 761 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 22 (mean R -0.3288)
- daily_loss_cap: 1 (mean R 2.3437)

Same-4h-bar signal overlap across coins: 192 of 761 (0.252), max coins in one bar 5

- min-order skips at $100: 23 of 761
- min-order skips at $300: 0 of 761

Generator counters (summed over coins): days 14277, entries 761, no_profile 0, signals 1798, skip_busy 0, skip_no_minute 1, skip_other 0, skip_rr 457, skip_stop_range 295, skip_wide 2, skip_window 282

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 761; sized 761; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 761, mean R -0.1287; seed 90, N 74, q 0.000676): S1-1 pass=False value=-0.1287492256096436; S1-2 pass=False value=-0.3016223283807858; S1-3 pass=False value=-0.2603477299468191; S1-4 pass=False value=(-0.18045797977972186, -0.0771761899544475); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=77.12% top5-removed mean R=-0.3097), B: reference only (S1-5 pass=False MDD=95.88% top5-removed mean R=-0.3097), C: reference only (S1-5 pass=False MDD=87.72% top5-removed mean R=-0.3097)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 761 | 761 | 761 | 761 | 761 | 761 |
| Entered | 658 | 661 | 562 | 587 | 663 | 671 |
| Annual n (nearest int) | 115 | 115 | 98 | 103 | 116 | 117 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.1250 | -0.1197 | -0.1534 | -0.1201 | -0.1526 | -0.1407 |
| Average hold (min) | 365.32 | 363.71 | 356.94 | 352.51 | 362.10 | 360.97 |
| Closed by replacement | 0 | 3 | 0 | 15 | 0 | 6 |
| Mean R of replaced | n/a | -0.3283 | n/a | -0.3120 | n/a | -0.3068 |
| Replace attempts failed | none | no_loser 25 | none | no_loser 115 | none | no_loser 42 |
| Final wallet | 29.48 | 30.16 | 6.22 | 10.07 | 15.81 | 14.93 |
| Max concurrent | 3 | 3 | 2 | 2 | 3 | 3 |
| Max open loss (fraction of wallet) | 5.94% | 5.94% | 5.97% | 5.97% | 5.98% | 5.97% |
| FE-Z1 real-order MDD | 77.12% | 76.59% | 95.88% | 93.33% | 87.72% | 88.41% |
| FE-Z2 share reaching -25% (seed 88) | 67.58% | 67.88% | 97.37% | 96.28% | 86.21% | 87.24% |
| FE-Z2 n (annual) | 115 | 115 | 98 | 103 | 116 | 117 |
| FE-Z3 worst trade loss/wallet | 5.35% | 5.35% | 5.44% | 5.45% | 5.35% | 5.35% |
| First -25% touch vs initial (report only) | 2021-05-01 17:02:00 | 2021-05-01 17:02:00 | 2021-03-07 07:30:00 | 2021-03-07 07:30:00 | 2021-02-20 11:59:00 | 2021-02-20 11:59:00 |
| First -25% touch vs peak (report only) | 2021-03-09 22:31:00 | 2021-03-09 22:31:00 | 2021-02-20 11:59:00 | 2021-02-20 11:59:00 | 2021-02-19 06:29:00 | 2021-02-19 06:29:00 |
| Sized by margin cap / by loss | 650 / 8 | 653 / 8 | 433 / 129 | 455 / 132 | 604 / 59 | 610 / 61 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | below_min_notional 38, max_positions 14, open_loss_cap 14, qty_zero 33, stop_vs_liq 4 | below_min_notional 38, max_positions 12, open_loss_cap 13, qty_zero 33, stop_vs_liq 4 | below_min_notional 36, open_loss_cap 126, qty_zero 33, stop_vs_liq 4 | below_min_notional 23, open_loss_cap 115, qty_zero 32, stop_vs_liq 4 | below_min_notional 36, max_positions 10, open_loss_cap 37, qty_zero 11, stop_vs_liq 4 | below_min_notional 34, max_positions 8, open_loss_cap 34, qty_zero 10, stop_vs_liq 4 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H62 / new (aux), seed 90, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 4994, months 69, win rate 0.387, mean R -0.0508 (0.30% cost -0.1453), PF 0.909, MDD 1.000, final wallet x0.000

Candidate list (unlimited, R units): trades 4994
- S1-0 trades / months: trades 4994 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0508 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.1532 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1453 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0104, -0.0912, 2497, 2497) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 1.0 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2162, 250) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1245, 99.8% -0.1403, lock bound index 6

Candidate list: 4994 trades, average hold 6.03 h, annual n 871 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 3333, months 69, win rate 0.381, mean R -0.0559 (0.30% cost -0.1532), PF 0.902, MDD 0.996, final wallet x0.005

Limits book: trades 3333
- S1-0 trades / months: trades 3333 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0559 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.1484 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1532 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0194, -0.0924, 1666, 1667) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9961 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2212, 167) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1207, 99.8% -0.1376, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 3333 (>= 100: True), mean R -0.0559 (> 0: False), mean R at 2x cost -0.1532 (> 0: False)

- U1: coins with >= 10 trades 88, positive 34, share 0.386 (need >= 0.667; does not meet)
- U2: best coin TIAUSDT share nan of total R -186.47 (need <= 0.35; does not meet)
- U3: mean R without TIAUSDT: -0.0610, n 3314 (does not meet)
- U4: in H16 universe: trades 1185, coins 110, mean R -0.0727; not in H16: trades 2148, coins 181, mean R -0.0467 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| TIAUSDT | 19 | 0.8234 | 15.64 |
| FILUSDT | 110 | 0.1259 | 13.85 |
| GMTUSDT | 11 | 1.2318 | 13.55 |
| NEARUSDT | 68 | 0.1429 | 9.72 |
| ZILUSDT | 11 | 0.8798 | 9.68 |
| UNIUSDT | 62 | 0.1383 | 8.58 |
| MATICUSDT | 64 | 0.1287 | 8.24 |
| ONEUSDT | 5 | 1.5971 | 7.99 |
| APEUSDT | 16 | 0.4932 | 7.89 |
| PEOPLEUSDT | 22 | 0.3580 | 7.88 |
| LINAUSDT | 10 | 0.7581 | 7.58 |
| WAVESUSDT | 29 | 0.2464 | 7.15 |
| IOSTUSDT | 8 | 0.8211 | 6.57 |
| ETCUSDT | 68 | 0.0915 | 6.22 |
| ANKRUSDT | 5 | 1.1933 | 5.97 |

Coins with trades 189; with >= 10 trades 88; mean R > 0 among those 34.

Annual n (limits book): 579.65 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 868.52 per year.
By year (KST entry year): 2021: n 570 mean -0.055, 2022: n 614 mean -0.076, 2023: n 597 mean 0.070, 2024: n 587 mean -0.079, 2025: n 552 mean -0.069, 2026: n 413 mean -0.160

Average hold 5.84 h (median 4.08); realized cost 0.0973 R per trade; mean slippage on stops 0.0001 R (all trades 0.0000); mean funding paid per trade 0.00005 (return units); exit reasons {'stop': 1856, 'target': 885, 'time': 592}

Trades per month: 2021-01 19, 2021-02 25, 2021-03 38, 2021-04 54, 2021-05 52, 2021-06 53, 2021-07 44, 2021-08 55, 2021-09 50, 2021-10 56, 2021-11 74, 2021-12 50, 2022-01 55, 2022-02 39, 2022-03 47, 2022-04 50, 2022-05 63, 2022-06 45, 2022-07 69, 2022-08 43, 2022-09 55, 2022-10 51, 2022-11 52, 2022-12 45, 2023-01 46, 2023-02 45, 2023-03 41, 2023-04 44, 2023-05 38, 2023-06 38, 2023-07 56, 2023-08 50, 2023-09 50, 2023-10 55, 2023-11 72, 2023-12 62, 2024-01 59, 2024-02 64, 2024-03 60, 2024-04 37, 2024-05 46, 2024-06 24, 2024-07 44, 2024-08 53, 2024-09 44, 2024-10 55, 2024-11 50, 2024-12 51, 2025-01 51, 2025-02 48, 2025-03 53, 2025-04 46, 2025-05 56, 2025-06 49, 2025-07 48, 2025-08 43, 2025-09 40, 2025-10 45, 2025-11 34, 2025-12 39, 2026-01 42, 2026-02 40, 2026-03 37, 2026-04 45, 2026-05 48, 2026-06 40, 2026-07 59, 2026-08 51, 2026-09 51

H7-T entry overlap (limits book): same week any coin 0.437, same week same coin 0.000; same day any coin 0.136, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 1661 of 4994 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 1493 (mean R -0.0360)
- daily_loss_cap: 168 (mean R -0.0805)

Same-4h-bar signal overlap across coins: 2791 of 4994 (0.559), max coins in one bar 19

- min-order skips at $100: 11 of 4994
- min-order skips at $300: 0 of 4994

Generator counters (summed over coins): days 197770, entries 4994, no_profile 0, signals 25143, skip_busy 0, skip_no_minute 10, skip_other 0, skip_rr 3124, skip_stop_range 673, skip_wide 6, skip_window 16336

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 4994; sized 4725; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 269 trades in 10 coins (AUDIOUSDT 1, EOSUSDT 102, FRONTUSDT 2, HNTUSDT 12, LUNAUSDT 16, MATICUSDT 87, RNDRUSDT 9, SRMUSDT 9, SXPUSDT 21, TOMOUSDT 10).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 4994, mean R -0.0508; seed 90, N 74, q 0.000676): S1-1 pass=False value=-0.05081928009276484; S1-2 pass=False value=-0.15316192485993035; S1-3 pass=False value=-0.15948832604206994; S1-4 pass=False value=(-0.010398266570186353, -0.09124029361534333); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=95.74% top5-removed mean R=-0.2162), B: reference only (S1-5 pass=False MDD=98.47% top5-removed mean R=-0.2162)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 4725 | 4725 | 4725 | 4725 |
| Entered | 2225 | 2453 | 1422 | 1583 |
| Annual n (nearest int) | 511 | 552 | 337 | 373 |
| S1-0 tier | ok | ok | ok | ok |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0432 | -0.0397 | -0.0512 | -0.0386 |
| Average hold (min) | 339.49 | 316.95 | 332.42 | 292.26 |
| Closed by replacement | 0 | 157 | 0 | 148 |
| Mean R of replaced | n/a | -0.3185 | n/a | -0.3132 |
| Replace attempts failed | none | no_loser 949, still_blocked 16 | none | no_loser 1463, still_blocked 8 |
| Final wallet | 5.00 | 4.86 | 1.92 | 1.97 |
| Max concurrent | 3 | 3 | 3 | 3 |
| Max open loss (fraction of wallet) | 5.98% | 6.00% | 6.00% | 6.00% |
| FE-Z1 real-order MDD | 95.74% | 96.28% | 98.47% | 98.42% |
| FE-Z2 share reaching -25% (seed 88) | 99.62% | 99.74% | 100.00% | 100.00% |
| FE-Z2 n (annual) | 511 | 552 | 337 | 373 |
| FE-Z3 worst trade loss/wallet | 4.99% | 4.99% | 5.15% | 5.14% |
| First -25% touch vs initial (report only) | 2021-03-02 08:25:00 | 2021-03-02 08:25:00 | 2021-03-01 09:07:00 | 2021-03-01 09:10:00 |
| First -25% touch vs peak (report only) | 2021-03-02 08:25:00 | 2021-03-02 08:25:00 | 2021-02-27 11:25:00 | 2021-02-27 11:25:00 |
| Sized by margin cap / by loss | 2194 / 31 | 2422 / 31 | 993 / 429 | 1115 / 468 |
| Liquidated | 0 | 0 | 0 | 0 |
| Skips by reason | below_min_notional 1157, bracket 29, max_positions 659, open_loss_cap 449, qty_zero 162, stop_vs_liq 44 | below_min_notional 1079, bracket 29, max_positions 603, open_loss_cap 362, qty_zero 156, stop_vs_liq 43 | below_min_notional 1357, bracket 34, max_positions 1, open_loss_cap 1693, qty_zero 183, stop_vs_liq 35 | below_min_notional 1409, bracket 33, max_positions 8, open_loss_cap 1463, qty_zero 199, stop_vs_liq 30 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

