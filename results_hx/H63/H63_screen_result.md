# H63 screen result (1m intrabar; frame fe2) -- 2026-10-29 12:45 KST

Runner: branch h48-screen @ 70bf69a551; runtime 691 s (whole session), peak RSS 1402 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H63 / six (primary), seed 91, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 382, months 59, win rate 0.241, mean R -0.1362 (0.30% cost -0.2322), PF 0.816, MDD 0.779, final wallet x0.268

Candidate list (unlimited, R units): trades 382
- S1-0 trades / months: trades 382 >= 300 and months 59 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1362 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.433 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2322 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.022, -0.2503, 191, 191) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.7788 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4242, 20) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.3528, 99.8% -0.3978, lock bound index 6

Candidate list: 382 trades, average hold 19.45 h, annual n 67 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 371, months 59, win rate 0.237, mean R -0.1427 (0.30% cost -0.2390), PF 0.808, MDD 0.781, final wallet x0.266

Limits book: trades 371
- S1-0 trades / months: trades 371 >= 300 and months 59 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1427 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.4439 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.239 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0059, -0.2788, 185, 186) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.781 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4292, 19) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.3606, 99.8% -0.4156, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 371 (>= 100: True), mean R -0.1427 (> 0: False), mean R at 2x cost -0.2390 (> 0: False)

- U1: coins with >= 10 trades 6, positive 2, share 0.333 (need >= 0.667; does not meet)
- U2: best coin XRPUSDT share nan of total R -52.95 (need <= 0.35; does not meet)
- U3: mean R without XRPUSDT: -0.1829, n 308 (does not meet)
- U4: in H16 universe: trades 357, coins 6, mean R -0.1730; not in H16: trades 14, coins 3, mean R 0.6300 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| XRPUSDT | 63 | 0.0537 | 3.38 |
| ETHUSDT | 60 | 0.0461 | 2.76 |
| SOLUSDT | 76 | -0.1054 | -8.01 |
| DOGEUSDT | 54 | -0.2326 | -12.56 |
| BTCUSDT | 51 | -0.3644 | -18.58 |
| BNBUSDT | 67 | -0.2975 | -19.94 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 2.

Annual n (limits book): 64.52 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 66.43 per year.
By year (KST entry year): 2021: n 85 mean -0.026, 2022: n 34 mean -0.287, 2023: n 65 mean 0.142, 2024: n 87 mean -0.105, 2025: n 62 mean -0.281, 2026: n 38 mean -0.622

Average hold 19.21 h (median 8.50); realized cost 0.0963 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00050 (return units); exit reasons {'stop': 276, 'target': 66, 'time': 29}

Trades per month: 2021-01 8, 2021-02 6, 2021-03 10, 2021-04 9, 2021-05 7, 2021-06 2, 2021-07 1, 2021-08 14, 2021-09 4, 2021-10 9, 2021-11 11, 2021-12 4, 2022-03 6, 2022-04 2, 2022-07 1, 2022-08 12, 2022-09 3, 2022-10 3, 2022-11 5, 2022-12 2, 2023-01 7, 2023-02 11, 2023-03 3, 2023-04 6, 2023-05 3, 2023-06 5, 2023-07 7, 2023-08 5, 2023-10 3, 2023-11 11, 2023-12 4, 2024-01 6, 2024-02 5, 2024-03 8, 2024-04 10, 2024-05 8, 2024-06 4, 2024-07 9, 2024-08 2, 2024-09 1, 2024-10 11, 2024-11 11, 2024-12 12, 2025-01 4, 2025-02 3, 2025-04 1, 2025-05 7, 2025-06 8, 2025-07 16, 2025-08 12, 2025-09 7, 2025-10 4, 2026-01 8, 2026-03 2, 2026-04 2, 2026-05 6, 2026-07 2, 2026-08 4, 2026-09 14

H7-T entry overlap (limits book): same week any coin 0.569, same week same coin 0.237; same day any coin 0.108, same day same coin 0.008 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 11 of 382 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 5 (mean R -0.4288)
- daily_loss_cap: 6 (mean R 0.5124)

Same-4h-bar signal overlap across coins: 104 of 382 (0.272), max coins in one bar 5

- min-order skips at $100: 19 of 382
- min-order skips at $300: 1 of 382

Generator counters (summed over coins): entries 382, signals 643, skip_busy 0, skip_no_minute 0, skip_other 0, skip_rr 81, skip_stop_range 76, skip_wide 9, skip_window 95, weeks 2035

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 382; sized 382; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 382, mean R -0.1362; seed 91, N 74, q 0.000676): S1-1 pass=False value=-0.13617390773504517; S1-2 pass=False value=-0.4330306452236132; S1-3 pass=False value=-0.24697558027508523; S1-4 pass=False value=(-0.022012532979756645, -0.25033528249033365); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=65.71% top5-removed mean R=-0.4242), B: reference only (S1-5 pass=False MDD=82.61% top5-removed mean R=-0.4242), C: reference only (S1-5 pass=False MDD=78.97% top5-removed mean R=-0.4242)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 382 | 382 | 382 | 382 | 382 | 382 |
| Entered | 330 | 341 | 271 | 287 | 338 | 343 |
| Annual n (nearest int) | 58 | 60 | 48 | 51 | 60 | 60 |
| S1-0 tier | conditional | conditional | undecidable | undecidable | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.1484 | -0.1167 | -0.1342 | -0.0797 | -0.1876 | -0.1416 |
| Average hold (min) | 1093.22 | 1089.47 | 1116.48 | 1057.86 | 1083.13 | 1040.74 |
| Closed by replacement | 0 | 4 | 0 | 9 | 0 | 8 |
| Mean R of replaced | n/a | -0.1611 | n/a | -0.2675 | n/a | -0.2960 |
| Replace attempts failed | none | no_loser 17 | none | no_loser 88 | none | no_loser 31, still_blocked 1 |
| Final wallet | 43.75 | 52.80 | 21.99 | 36.38 | 26.86 | 30.83 |
| Max concurrent | 3 | 3 | 2 | 2 | 3 | 3 |
| Max open loss (fraction of wallet) | 5.84% | 5.89% | 5.97% | 5.72% | 5.87% | 5.79% |
| FE-Z1 real-order MDD | 65.71% | 61.40% | 82.61% | 79.36% | 78.97% | 75.98% |
| FE-Z2 share reaching -25% (seed 88) | 63.28% | 60.47% | 93.13% | 92.45% | 78.50% | 77.42% |
| FE-Z2 n (annual) | 58 | 60 | 48 | 51 | 60 | 60 |
| FE-Z3 worst trade loss/wallet | 7.37% | 6.40% | 7.36% | 6.40% | 7.36% | 6.40% |
| First -25% touch vs initial (report only) | 2021-03-05 00:25:00 | 2022-08-19 00:21:00 | 2021-02-20 22:39:00 | 2022-09-07 00:19:00 | 2021-02-23 08:08:00 | 2021-05-06 18:33:00 |
| First -25% touch vs peak (report only) | 2021-03-05 00:25:00 | 2022-04-06 13:49:00 | 2021-02-20 22:39:00 | 2021-04-28 00:05:00 | 2021-02-23 08:08:00 | 2021-05-06 18:33:00 |
| Sized by margin cap / by loss | 318 / 12 | 329 / 12 | 185 / 86 | 202 / 85 | 297 / 41 | 300 / 43 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | below_min_notional 8, max_positions 4, open_loss_cap 16, qty_zero 18, stop_vs_liq 6 | below_min_notional 1, max_positions 5, open_loss_cap 12, qty_zero 17, stop_vs_liq 6 | below_min_notional 1, open_loss_cap 87, qty_zero 17, stop_vs_liq 6 | below_min_notional 1, open_loss_cap 88, stop_vs_liq 6 | below_min_notional 1, max_positions 3, open_loss_cap 33, qty_zero 1, stop_vs_liq 6 | below_min_notional 1, max_positions 3, open_loss_cap 29, stop_vs_liq 6 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H63 / new (aux), seed 91, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 1825, months 69, win rate 0.208, mean R -0.1915 (0.30% cost -0.2718), PF 0.754, MDD 1.000, final wallet x0.000

Candidate list (unlimited, R units): trades 1825
- S1-0 trades / months: trades 1825 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1915 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.4015 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2718 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.0092, -0.3921, 912, 913) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 1.0 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4919, 92) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.3416, 99.8% -0.3825, lock bound index 6

Candidate list: 1825 trades, average hold 15.90 h, annual n 321 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 1123, months 69, win rate 0.190, mean R -0.2710 (0.30% cost -0.3562), PF 0.658, MDD 0.999, final wallet x0.001

Limits book: trades 1123
- S1-0 trades / months: trades 1123 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.271 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.4705 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.3562 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0758, -0.4659, 561, 562) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9992 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.5764, 57) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.4130, 99.8% -0.4506, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 1123 (>= 100: True), mean R -0.2710 (> 0: False), mean R at 2x cost -0.3562 (> 0: False)

- U1: coins with >= 10 trades 35, positive 5, share 0.143 (need >= 0.667; does not meet)
- U2: best coin STORJUSDT share nan of total R -304.36 (need <= 0.35; does not meet)
- U3: mean R without STORJUSDT: -0.2834, n 1117 (does not meet)
- U4: in H16 universe: trades 486, coins 90, mean R -0.2089; not in H16: trades 637, coins 134, mean R -0.3184 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| STORJUSDT | 6 | 2.0295 | 12.18 |
| XMRUSDT | 8 | 1.4375 | 11.50 |
| FTMUSDT | 21 | 0.4942 | 10.38 |
| STMXUSDT | 5 | 1.9076 | 9.54 |
| ETCUSDT | 20 | 0.3986 | 7.97 |
| BLZUSDT | 5 | 1.4164 | 7.08 |
| CHZUSDT | 4 | 1.6913 | 6.77 |
| MATICUSDT | 25 | 0.2329 | 5.82 |
| JASMYUSDT | 3 | 1.8330 | 5.50 |
| QTUMUSDT | 3 | 1.8041 | 5.41 |
| GRTUSDT | 2 | 2.3781 | 4.76 |
| 1INCHUSDT | 2 | 2.2606 | 4.52 |
| PENDLEUSDT | 6 | 0.7524 | 4.51 |
| ARBUSDT | 7 | 0.6148 | 4.30 |
| THETAUSDT | 7 | 0.6110 | 4.28 |

Coins with trades 151; with >= 10 trades 35; mean R > 0 among those 5.

Annual n (limits book): 195.30 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 317.39 per year.
By year (KST entry year): 2021: n 182 mean -0.114, 2022: n 133 mean -0.375, 2023: n 238 mean 0.121, 2024: n 256 mean -0.502, 2025: n 158 mean -0.433, 2026: n 156 mean -0.421

Average hold 14.30 h (median 5.62); realized cost 0.0852 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00003 (return units); exit reasons {'stop': 896, 'target': 155, 'time': 72}

Trades per month: 2021-01 5, 2021-02 1, 2021-03 24, 2021-04 16, 2021-05 18, 2021-06 3, 2021-07 5, 2021-08 22, 2021-09 20, 2021-10 27, 2021-11 28, 2021-12 13, 2022-01 14, 2022-02 5, 2022-03 8, 2022-04 13, 2022-05 2, 2022-06 1, 2022-07 11, 2022-08 35, 2022-09 13, 2022-10 7, 2022-11 13, 2022-12 11, 2023-01 21, 2023-02 35, 2023-03 17, 2023-04 16, 2023-05 6, 2023-06 8, 2023-07 23, 2023-08 17, 2023-09 7, 2023-10 32, 2023-11 29, 2023-12 28, 2024-01 26, 2024-02 16, 2024-03 34, 2024-04 28, 2024-05 18, 2024-06 10, 2024-07 17, 2024-08 6, 2024-09 14, 2024-10 34, 2024-11 29, 2024-12 23, 2025-01 13, 2025-02 3, 2025-03 3, 2025-04 11, 2025-05 26, 2025-06 10, 2025-07 25, 2025-08 28, 2025-09 12, 2025-10 14, 2025-11 9, 2025-12 4, 2026-01 20, 2026-02 3, 2026-03 8, 2026-04 16, 2026-05 21, 2026-06 19, 2026-07 14, 2026-08 20, 2026-09 35

H7-T entry overlap (limits book): same week any coin 0.524, same week same coin 0.000; same day any coin 0.119, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 702 of 1825 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 359 (mean R -0.1742)
- daily_loss_cap: 343 (mean R 0.0506)

Same-4h-bar signal overlap across coins: 945 of 1825 (0.518), max coins in one bar 17

- min-order skips at $100: 15 of 1825
- min-order skips at $300: 1 of 1825

Generator counters (summed over coins): entries 1825, signals 9528, skip_busy 0, skip_no_minute 2520, skip_other 0, skip_rr 472, skip_stop_range 117, skip_wide 27, skip_window 4567, weeks 40430

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 1825; sized 1735; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 90 trades in 8 coins (AUDIOUSDT 1, EOSUSDT 31, LUNAUSDT 7, MATICUSDT 29, RNDRUSDT 3, SRMUSDT 4, SXPUSDT 6, TOMOUSDT 9).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 1825, mean R -0.1915; seed 91, N 74, q 0.000676): S1-1 pass=False value=-0.19152398919085123; S1-2 pass=False value=-0.40154258026574013; S1-3 pass=False value=-0.2824039706226019; S1-4 pass=False value=(0.012001716335510046, -0.394826774995935); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=95.88% top5-removed mean R=-0.4919), B: reference only (S1-5 pass=False MDD=98.33% top5-removed mean R=-0.4919)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 1735 | 1735 | 1735 | 1735 |
| Entered | 819 | 868 | 556 | 591 |
| Annual n (nearest int) | 183 | 192 | 126 | 135 |
| S1-0 tier | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.2002 | -0.1965 | -0.1408 | -0.1353 |
| Average hold (min) | 805.91 | 756.47 | 757.51 | 708.86 |
| Closed by replacement | 0 | 37 | 0 | 42 |
| Mean R of replaced | n/a | -0.3253 | n/a | -0.3000 |
| Replace attempts failed | none | no_loser 370, still_blocked 11 | none | no_loser 572, still_blocked 2 |
| Final wallet | 4.88 | 5.00 | 1.96 | 1.97 |
| Max concurrent | 3 | 3 | 2 | 2 |
| Max open loss (fraction of wallet) | 5.99% | 6.00% | 5.98% | 6.00% |
| FE-Z1 real-order MDD | 95.88% | 95.79% | 98.33% | 98.33% |
| FE-Z2 share reaching -25% (seed 88) | 99.63% | 99.71% | 100.00% | 99.99% |
| FE-Z2 n (annual) | 183 | 192 | 126 | 135 |
| FE-Z3 worst trade loss/wallet | 5.27% | 10.07% | 5.43% | 10.36% |
| First -25% touch vs initial (report only) | 2021-03-23 20:58:00 | 2021-03-23 20:58:00 | 2021-03-12 13:02:00 | 2021-03-12 13:02:00 |
| First -25% touch vs peak (report only) | 2021-03-23 20:58:00 | 2021-03-23 20:58:00 | 2021-03-12 13:02:00 | 2021-03-12 13:02:00 |
| Sized by margin cap / by loss | 797 / 22 | 846 / 22 | 346 / 210 | 371 / 220 |
| Liquidated | 0 | 1 | 0 | 1 |
| Skips by reason | below_min_notional 407, bracket 10, max_positions 208, open_loss_cap 179, qty_zero 70, stop_vs_liq 42 | below_min_notional 360, bracket 11, max_positions 215, open_loss_cap 166, qty_zero 74, stop_vs_liq 41 | below_min_notional 440, bracket 12, open_loss_cap 612, qty_zero 72, stop_vs_liq 43 | below_min_notional 444, bracket 12, open_loss_cap 574, qty_zero 70, stop_vs_liq 44 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

