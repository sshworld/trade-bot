# H66 screen result (1m intrabar; frame fe2) -- 2026-10-29 12:24 KST

Runner: branch h48-screen @ 714a1e3488; runtime 665 s (whole session), peak RSS 1433 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H66 / six (primary), seed 94, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 190, months 53, win rate 0.268, mean R -0.2111 (0.30% cost -0.3460), PF 0.702, MDD 0.646, final wallet x0.418

Candidate list (unlimited, R units): trades 190
- S1-0 trades / months: trades 190 >= 300 and months 53 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: -0.2111 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.5113 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.346 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.2346, -0.1877, 95, 95) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.6463 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4092, 10) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.4342, 99.8% -0.4811, lock bound index 6

Candidate list: 190 trades, average hold 13.17 h, annual n 38 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 189, months 53, win rate 0.270, mean R -0.2072 (0.30% cost -0.3417), PF 0.707, MDD 0.639, final wallet x0.426

Limits book: trades 189
- S1-0 trades / months: trades 189 >= 300 and months 53 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: -0.2072 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.5089 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.3417 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.2268, -0.1877, 94, 95) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.6394 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4061, 10) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.4297, 99.8% -0.4777, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 189 (>= 100: True), mean R -0.2072 (> 0: False), mean R at 2x cost -0.3417 (> 0: False)

- U1: coins with >= 10 trades 6, positive 2, share 0.333 (need >= 0.667; does not meet)
- U2: best coin XRPUSDT share nan of total R -39.15 (need <= 0.35; does not meet)
- U3: mean R without XRPUSDT: -0.3025, n 168 (does not meet)
- U4: in H16 universe: trades 189, coins 6, mean R -0.2072; not in H16: trades 0, coins 0, mean R nan (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| XRPUSDT | 21 | 0.5558 | 11.67 |
| SOLUSDT | 15 | 0.0649 | 0.97 |
| DOGEUSDT | 20 | -0.2015 | -4.03 |
| ETHUSDT | 35 | -0.1882 | -6.59 |
| BTCUSDT | 46 | -0.3215 | -14.79 |
| BNBUSDT | 52 | -0.5076 | -26.39 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 2.

Annual n (limits book): 32.87 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 33.04 per year.
By year (KST entry year): 2021: n 8 mean -0.178, 2022: n 28 mean -0.123, 2023: n 35 mean -0.217, 2024: n 44 mean -0.226, 2025: n 37 mean -0.286, 2026: n 37 mean -0.167

Average hold 13.21 h (median 8.28); realized cost 0.1346 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00008 (return units); exit reasons {'stop': 136, 'target': 40, 'time': 13}

Trades per month: 2021-08 2, 2021-09 2, 2021-10 3, 2021-12 1, 2022-01 1, 2022-02 1, 2022-03 10, 2022-04 2, 2022-05 1, 2022-07 1, 2022-08 2, 2022-10 6, 2022-11 1, 2022-12 3, 2023-01 3, 2023-02 2, 2023-03 2, 2023-04 2, 2023-06 1, 2023-07 2, 2023-08 1, 2023-09 11, 2023-10 3, 2023-11 8, 2024-01 1, 2024-02 8, 2024-04 5, 2024-05 1, 2024-06 4, 2024-07 6, 2024-08 2, 2024-09 7, 2024-10 5, 2024-11 1, 2024-12 5, 2025-01 2, 2025-03 2, 2025-04 4, 2025-05 8, 2025-06 2, 2025-07 6, 2025-08 4, 2025-09 5, 2025-10 1, 2025-12 2, 2026-01 5, 2026-02 2, 2026-03 3, 2026-04 9, 2026-05 7, 2026-06 2, 2026-07 6, 2026-08 3

H7-T entry overlap (limits book): same week any coin 0.439, same week same coin 0.217; same day any coin 0.228, same day same coin 0.111 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 1 of 190 raw signals (mean unsized R of the skipped, descriptive only):
- daily_loss_cap: 1 (mean R -0.9620)

Same-4h-bar signal overlap across coins: 14 of 190 (0.074), max coins in one bar 2

- min-order skips at $100: 11 of 190
- min-order skips at $300: 0 of 190

Generator counters (summed over coins): attempts 847, entries 190, ranges 360, signals 360, skip_busy 3, skip_no_minute 0, skip_other 0, skip_rr 21, skip_stop_range 114, skip_wide 0, skip_window 32

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 190; sized 190; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 190, mean R -0.2111; seed 94, N 74, q 0.000676): S1-1 pass=False value=-0.21114097298404452; S1-2 pass=False value=-0.5112892568198567; S1-3 pass=False value=-0.37275840948566696; S1-4 pass=False value=(-0.2345536952842934, -0.1877282506837956); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=34.26% top5-removed mean R=-0.4092), B: reference only (S1-5 pass=False MDD=73.18% top5-removed mean R=-0.4092), C: reference only (S1-5 pass=False MDD=66.04% top5-removed mean R=-0.4092)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 190 | 190 | 190 | 190 | 190 | 190 |
| Entered | 178 | 178 | 171 | 177 | 187 | 188 |
| Annual n (nearest int) | 35 | 35 | 34 | 35 | 37 | 37 |
| S1-0 tier | undecidable | undecidable | undecidable | undecidable | undecidable | undecidable |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.1956 | -0.1956 | -0.2343 | -0.2401 | -0.2146 | -0.2071 |
| Average hold (min) | 794.60 | 794.60 | 801.82 | 776.99 | 792.16 | 789.79 |
| Closed by replacement | 0 | 0 | 0 | 3 | 0 | 2 |
| Mean R of replaced | n/a | n/a | n/a | -0.3213 | n/a | -0.3350 |
| Replace attempts failed | none | none | none | no_loser 10, still_blocked 1 | none | no_loser 2 |
| Final wallet | 86.97 | 86.97 | 39.16 | 37.92 | 51.59 | 51.91 |
| Max concurrent | 3 | 3 | 2 | 2 | 3 | 3 |
| Max open loss (fraction of wallet) | 4.26% | 4.26% | 5.92% | 5.98% | 5.93% | 5.93% |
| FE-Z1 real-order MDD | 34.26% | 34.26% | 73.18% | 73.95% | 66.04% | 65.81% |
| FE-Z2 share reaching -25% (seed 88) | 0.45% | 0.45% | 63.10% | 63.87% | 43.42% | 42.30% |
| FE-Z2 n (annual) | 35 | 35 | 34 | 35 | 37 | 37 |
| FE-Z3 worst trade loss/wallet | 2.24% | 2.24% | 4.94% | 4.91% | 4.86% | 4.82% |
| First -25% touch vs initial (report only) | 2024-09-25 01:40:00 | 2024-09-25 01:40:00 | 2022-12-06 04:06:00 | 2022-12-06 04:06:00 | 2024-04-11 02:46:00 | 2024-04-11 02:46:00 |
| First -25% touch vs peak (report only) | 2024-04-12 05:52:00 | 2024-04-12 05:52:00 | 2022-05-05 10:25:00 | 2022-05-05 10:25:00 | 2023-11-05 12:51:00 | 2023-11-05 12:51:00 |
| Sized by margin cap / by loss | 178 / 0 | 178 / 0 | 165 / 6 | 171 / 6 | 162 / 25 | 163 / 25 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | qty_zero 12 | qty_zero 12 | open_loss_cap 16, qty_zero 3 | open_loss_cap 11, qty_zero 2 | open_loss_cap 3 | open_loss_cap 2 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H66 / new (aux), seed 94, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 396, months 51, win rate 0.293, mean R -0.1469 (0.30% cost -0.2757), PF 0.788, MDD 0.838, final wallet x0.253

Candidate list (unlimited, R units): trades 396
- S1-0 trades / months: trades 396 >= 100 and months 51 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1469 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3969 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2757 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0264, -0.2674, 198, 198) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.8385 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3264, 20) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.3314, 99.8% -0.3706, lock bound index 6

Candidate list: 396 trades, average hold 8.48 h, annual n 81 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 349, months 51, win rate 0.309, mean R -0.1010 (0.30% cost -0.2293), PF 0.850, MDD 0.780, final wallet x0.417

Limits book: trades 349
- S1-0 trades / months: trades 349 >= 100 and months 51 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.101 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3481 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2293 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.0249, -0.2262, 174, 175) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.78 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2836, 18) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2888, 99.8% -0.3366, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 349 (>= 100: True), mean R -0.1010 (> 0: False), mean R at 2x cost -0.2293 (> 0: False)

- U1: coins with >= 10 trades 11, positive 4, share 0.364 (need >= 0.667; does not meet)
- U2: best coin CRVUSDT share nan of total R -35.25 (need <= 0.35; does not meet)
- U3: mean R without CRVUSDT: -0.1166, n 343 (does not meet)
- U4: in H16 universe: trades 91, coins 30, mean R -0.0185; not in H16: trades 258, coins 67, mean R -0.1301 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| CRVUSDT | 6 | 0.7937 | 4.76 |
| DOTUSDT | 20 | 0.1988 | 3.98 |
| LDOUSDT | 1 | 3.7703 | 3.77 |
| TAOUSDT | 3 | 1.1149 | 3.34 |
| XMRUSDT | 2 | 1.4607 | 2.92 |
| 1000PEPEUSDT | 2 | 1.3805 | 2.76 |
| SNXUSDT | 2 | 1.2245 | 2.45 |
| 1000BONKUSDT | 1 | 2.4304 | 2.43 |
| ETCUSDT | 19 | 0.1158 | 2.20 |
| STMXUSDT | 1 | 1.8815 | 1.88 |
| WIFUSDT | 1 | 1.5904 | 1.59 |
| EOSUSDT | 5 | 0.3159 | 1.58 |
| SXPUSDT | 1 | 1.4309 | 1.43 |
| LUNA2USDT | 1 | 1.4058 | 1.41 |
| ENSUSDT | 2 | 0.6652 | 1.33 |

Coins with trades 72; with >= 10 trades 11; mean R > 0 among those 4.

Annual n (limits book): 60.70 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 68.87 per year.
By year (KST entry year): 2021: n 3 mean -0.985, 2022: n 36 mean 0.376, 2023: n 115 mean 0.000, 2024: n 66 mean -0.316, 2025: n 67 mean -0.426, 2026: n 62 mean 0.058

Average hold 8.98 h (median 4.53); realized cost 0.1283 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00006 (return units); exit reasons {'stop': 241, 'target': 99, 'time': 9}

Trades per month: 2021-10 2, 2021-11 1, 2022-01 1, 2022-03 2, 2022-07 5, 2022-08 2, 2022-09 2, 2022-10 10, 2022-11 1, 2022-12 13, 2023-01 13, 2023-02 3, 2023-03 1, 2023-04 16, 2023-05 6, 2023-06 12, 2023-07 5, 2023-08 8, 2023-09 28, 2023-10 9, 2023-11 6, 2023-12 8, 2024-01 5, 2024-02 17, 2024-04 3, 2024-05 9, 2024-06 7, 2024-07 8, 2024-08 6, 2024-09 4, 2024-10 6, 2024-11 1, 2025-01 2, 2025-02 2, 2025-03 11, 2025-04 3, 2025-05 3, 2025-06 3, 2025-07 7, 2025-08 6, 2025-09 17, 2025-10 6, 2025-11 4, 2025-12 3, 2026-01 5, 2026-02 5, 2026-03 3, 2026-04 19, 2026-05 6, 2026-07 13, 2026-08 9, 2026-09 2

H7-T entry overlap (limits book): same week any coin 0.479, same week same coin 0.000; same day any coin 0.255, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 47 of 396 raw signals (mean unsized R of the skipped, descriptive only):
- daily_loss_cap: 40 (mean R -0.4574)
- max_concurrent: 7 (mean R -0.6612)

Same-4h-bar signal overlap across coins: 78 of 396 (0.197), max coins in one bar 4

- min-order skips at $100: 0 of 396
- min-order skips at $300: 0 of 396

Generator counters (summed over coins): attempts 7051, entries 396, ranges 3277, signals 3277, skip_busy 16, skip_no_minute 921, skip_other 0, skip_rr 17, skip_stop_range 222, skip_wide 0, skip_window 1705

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 396; sized 371; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 25 trades in 4 coins (EOSUSDT 6, HNTUSDT 1, MATICUSDT 17, SXPUSDT 1).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 396, mean R -0.1469; seed 94, N 74, q 0.000676): S1-1 pass=False value=-0.14689264655397485; S1-2 pass=False value=-0.3969226422158238; S1-3 pass=False value=-0.30024153442087886; S1-4 pass=False value=(-0.026362520829220228, -0.26742277227872946); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=59.27% top5-removed mean R=-0.3264), B: reference only (S1-5 pass=False MDD=87.14% top5-removed mean R=-0.3264)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 371 | 371 | 371 | 371 |
| Entered | 357 | 359 | 303 | 316 |
| Annual n (nearest int) | 73 | 73 | 62 | 65 |
| S1-0 tier | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.1190 | -0.1146 | -0.1454 | -0.1675 |
| Average hold (min) | 520.38 | 516.41 | 513.82 | 497.33 |
| Closed by replacement | 0 | 4 | 0 | 15 |
| Mean R of replaced | n/a | -0.3697 | n/a | -0.3252 |
| Replace attempts failed | none | no_loser 7 | none | no_loser 49, still_blocked 1 |
| Final wallet | 84.38 | 85.90 | 35.86 | 27.26 |
| Max concurrent | 3 | 3 | 2 | 2 |
| Max open loss (fraction of wallet) | 4.88% | 4.87% | 5.97% | 5.96% |
| FE-Z1 real-order MDD | 59.27% | 59.42% | 87.14% | 87.09% |
| FE-Z2 share reaching -25% (seed 88) | 15.13% | 14.31% | 83.28% | 87.06% |
| FE-Z2 n (annual) | 73 | 73 | 62 | 65 |
| FE-Z3 worst trade loss/wallet | 2.67% | 2.67% | 5.02% | 5.02% |
| First -25% touch vs initial (report only) | 2025-08-08 17:40:00 | 2025-08-11 14:02:00 | 2024-09-24 06:19:00 | 2024-02-10 02:46:00 |
| First -25% touch vs peak (report only) | 2024-02-12 22:40:00 | 2024-02-12 22:40:00 | 2023-04-11 17:18:00 | 2023-01-09 07:31:00 |
| Sized by margin cap / by loss | 357 / 0 | 359 / 0 | 277 / 26 | 290 / 26 |
| Liquidated | 0 | 0 | 0 | 0 |
| Skips by reason | bracket 5, max_positions 9 | bracket 5, max_positions 7 | bracket 5, open_loss_cap 63 | bracket 5, open_loss_cap 50 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

