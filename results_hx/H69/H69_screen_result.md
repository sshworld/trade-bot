# H69 screen result (1m intrabar; frame fe2) -- 2026-10-29 13:15 KST

Runner: branch h48-screen @ b540344b9c; runtime 633 s (whole session), peak RSS 1513 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H69 / six (primary), seed 97, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 871, months 68, win rate 0.326, mean R -0.0531 (0.30% cost -0.1180), PF 0.919, MDD 0.900, final wallet x0.163

Candidate list (unlimited, R units): trades 871
- S1-0 trades / months: trades 871 >= 300 and months 68 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0531 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2988 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.118 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.0082, -0.1143, 435, 436) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.8999 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2829, 44) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2262, 99.8% -0.2619, lock bound index 6

Candidate list: 871 trades, average hold 40.09 h, annual n 153 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 695, months 68, win rate 0.308, mean R -0.1066 (0.30% cost -0.1742), PF 0.842, MDD 0.910, final wallet x0.133

Limits book: trades 695
- S1-0 trades / months: trades 695 >= 300 and months 68 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1066 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3308 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1742 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0347, -0.1783, 347, 348) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9099 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3233, 35) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2715, 99.8% -0.3100, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 695 (>= 100: True), mean R -0.1066 (> 0: False), mean R at 2x cost -0.1742 (> 0: False)

- U1: coins with >= 10 trades 6, positive 1, share 0.167 (need >= 0.667; does not meet)
- U2: best coin BNBUSDT share nan of total R -74.08 (need <= 0.35; does not meet)
- U3: mean R without BNBUSDT: -0.1338, n 580 (does not meet)
- U4: in H16 universe: trades 684, coins 6, mean R -0.1076; not in H16: trades 11, coins 2, mean R -0.0460 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| BNBUSDT | 115 | 0.0308 | 3.54 |
| SOLUSDT | 104 | -0.0418 | -4.34 |
| DOGEUSDT | 113 | -0.0578 | -6.53 |
| BTCUSDT | 146 | -0.0971 | -14.17 |
| XRPUSDT | 106 | -0.1539 | -16.31 |
| ETHUSDT | 111 | -0.3267 | -36.26 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 1.

Annual n (limits book): 120.87 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 151.48 per year.
By year (KST entry year): 2021: n 86 mean -0.181, 2022: n 153 mean -0.028, 2023: n 104 mean 0.085, 2024: n 104 mean -0.058, 2025: n 134 mean -0.181, 2026: n 114 mean -0.287

Average hold 38.28 h (median 22.75); realized cost 0.0676 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00015 (return units); exit reasons {'stop': 467, 'target': 154, 'time': 74}

Trades per month: 2021-01 3, 2021-02 3, 2021-03 9, 2021-04 2, 2021-05 2, 2021-06 10, 2021-07 17, 2021-08 3, 2021-09 10, 2021-10 3, 2021-11 14, 2021-12 10, 2022-01 16, 2022-02 12, 2022-03 6, 2022-04 9, 2022-05 24, 2022-06 25, 2022-07 9, 2022-08 15, 2022-09 14, 2022-10 6, 2022-11 5, 2022-12 12, 2023-02 13, 2023-03 10, 2023-04 12, 2023-05 16, 2023-06 9, 2023-07 6, 2023-08 14, 2023-09 12, 2023-10 9, 2023-11 1, 2023-12 2, 2024-01 11, 2024-02 4, 2024-03 6, 2024-04 15, 2024-05 7, 2024-06 14, 2024-07 8, 2024-08 16, 2024-09 6, 2024-10 7, 2024-11 4, 2024-12 6, 2025-01 7, 2025-02 17, 2025-03 15, 2025-04 6, 2025-05 8, 2025-06 10, 2025-07 4, 2025-08 19, 2025-09 9, 2025-10 2, 2025-11 23, 2025-12 14, 2026-01 11, 2026-02 18, 2026-03 12, 2026-04 3, 2026-05 18, 2026-06 19, 2026-07 12, 2026-08 8, 2026-09 13

H7-T entry overlap (limits book): same week any coin 0.266, same week same coin 0.049; same day any coin 0.024, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 176 of 871 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 93 (mean R 0.0764)
- daily_loss_cap: 83 (mean R 0.2495)

Same-4h-bar signal overlap across coins: 517 of 871 (0.594), max coins in one bar 6

- min-order skips at $100: 116 of 871
- min-order skips at $300: 17 of 871

Generator counters (summed over coins): channel_breaks 1367, entries 871, signals 1361, skip_busy 129, skip_no_minute 0, skip_other 0, skip_rr 180, skip_stop_range 15, skip_wide 35, skip_window 131

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 871; sized 871; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 871, mean R -0.0531; seed 97, N 74, q 0.000676): S1-1 pass=False value=-0.05312843092032084; S1-2 pass=False value=-0.2987532238941177; S1-3 pass=False value=-0.1251149022188857; S1-4 pass=False value=(0.008163657476802377, -0.114279941133047); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=81.89% top5-removed mean R=-0.2829), B: reference only (S1-5 pass=False MDD=93.51% top5-removed mean R=-0.2829), C: reference only (S1-5 pass=False MDD=89.73% top5-removed mean R=-0.2829)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 871 | 871 | 871 | 871 | 871 | 871 |
| Entered | 543 | 569 | 382 | 421 | 499 | 543 |
| Annual n (nearest int) | 95 | 100 | 67 | 74 | 88 | 95 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0987 | -0.0843 | -0.0797 | -0.0932 | -0.1168 | -0.1063 |
| Average hold (min) | 2084.87 | 1983.89 | 2073.13 | 1823.34 | 2073.06 | 1881.93 |
| Closed by replacement | 0 | 33 | 0 | 45 | 0 | 42 |
| Mean R of replaced | n/a | -0.2793 | n/a | -0.2824 | n/a | -0.2848 |
| Replace attempts failed | none | no_loser 180, still_blocked 2 | none | no_loser 321 | none | no_loser 230, still_blocked 4 |
| Final wallet | 27.60 | 30.86 | 13.77 | 8.62 | 17.52 | 17.92 |
| Max concurrent | 3 | 3 | 2 | 2 | 3 | 3 |
| Max open loss (fraction of wallet) | 6.00% | 5.99% | 5.97% | 5.81% | 5.96% | 6.00% |
| FE-Z1 real-order MDD | 81.89% | 81.15% | 93.51% | 94.94% | 89.73% | 89.31% |
| FE-Z2 share reaching -25% (seed 88) | 87.77% | 88.11% | 98.56% | 98.92% | 94.04% | 94.60% |
| FE-Z2 n (annual) | 95 | 100 | 67 | 74 | 88 | 95 |
| FE-Z3 worst trade loss/wallet | 10.07% | 10.07% | 25.19% | 25.19% | 10.07% | 10.07% |
| First -25% touch vs initial (report only) | 2022-01-10 14:04:00 | 2022-05-27 12:01:00 | 2021-07-16 10:12:00 | 2021-07-16 11:41:00 | 2021-07-20 01:06:00 | 2021-07-19 12:31:00 |
| First -25% touch vs peak (report only) | 2021-07-17 01:56:00 | 2021-07-17 01:56:00 | 2021-07-08 13:29:00 | 2021-07-08 13:29:00 | 2021-07-08 20:55:00 | 2021-07-08 20:55:00 |
| Sized by margin cap / by loss | 518 / 25 | 544 / 25 | 168 / 214 | 180 / 241 | 404 / 95 | 434 / 109 |
| Liquidated | 1 | 1 | 1 | 1 | 1 | 1 |
| Skips by reason | below_min_notional 2, max_positions 22, open_loss_cap 187, qty_zero 64, stop_vs_liq 53 | below_min_notional 4, max_positions 16, open_loss_cap 166, qty_zero 64, stop_vs_liq 52 | below_min_notional 7, open_loss_cap 388, qty_zero 42, stop_vs_liq 52 | below_min_notional 15, open_loss_cap 321, qty_zero 62, stop_vs_liq 52 | below_min_notional 12, max_positions 4, open_loss_cap 284, qty_zero 20, stop_vs_liq 52 | below_min_notional 16, max_positions 5, open_loss_cap 229, qty_zero 26, stop_vs_liq 52 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H69 / new (aux), seed 97, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 6054, months 69, win rate 0.275, mean R -0.0473 (0.30% cost -0.1011), PF 0.933, MDD 1.000, final wallet x0.000

Candidate list (unlimited, R units): trades 6054
- S1-0 trades / months: trades 6054 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0473 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2306 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1011 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0281, -0.0665, 3027, 3027) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 1.0 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3382, 303) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1811, 99.8% -0.2085, lock bound index 6

Candidate list: 6054 trades, average hold 35.70 h, annual n 1059 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 1921, months 69, win rate 0.221, mean R -0.1345 (0.30% cost -0.2003), PF 0.824, MDD 1.000, final wallet x0.001

Limits book: trades 1921
- S1-0 trades / months: trades 1921 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1345 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3067 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2003 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.1223, -0.1467, 960, 961) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9997 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4827, 97) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2603, 99.8% -0.2930, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 1921 (>= 100: True), mean R -0.1345 (> 0: False), mean R at 2x cost -0.2003 (> 0: False)

- U1: coins with >= 10 trades 62, positive 18, share 0.290 (need >= 0.667; does not meet)
- U2: best coin ENJUSDT share nan of total R -258.43 (need <= 0.35; does not meet)
- U3: mean R without ENJUSDT: -0.1460, n 1914 (does not meet)
- U4: in H16 universe: trades 704, coins 105, mean R -0.1380; not in H16: trades 1217, coins 165, mean R -0.1325 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| ENJUSDT | 7 | 3.0062 | 21.04 |
| 1000BONKUSDT | 12 | 1.5846 | 19.01 |
| LDOUSDT | 16 | 0.9521 | 15.23 |
| OMUSDT | 4 | 3.7959 | 15.18 |
| FILUSDT | 29 | 0.5062 | 14.68 |
| OPUSDT | 24 | 0.5633 | 13.52 |
| XLMUSDT | 31 | 0.4086 | 12.67 |
| 1000SHIBUSDT | 36 | 0.3387 | 12.19 |
| DASHUSDT | 17 | 0.6301 | 10.71 |
| ALICEUSDT | 5 | 2.1353 | 10.68 |
| CFXUSDT | 3 | 3.3404 | 10.02 |
| AXSUSDT | 23 | 0.4248 | 9.77 |
| TRXUSDT | 30 | 0.2756 | 8.27 |
| TNSRUSDT | 7 | 1.1285 | 7.90 |
| KAVAUSDT | 8 | 0.9031 | 7.22 |

Coins with trades 176; with >= 10 trades 62; mean R > 0 among those 18.

Annual n (limits book): 334.09 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 1052.87 per year.
By year (KST entry year): 2021: n 180 mean 0.123, 2022: n 380 mean -0.320, 2023: n 312 mean -0.046, 2024: n 313 mean -0.200, 2025: n 374 mean -0.106, 2026: n 362 mean -0.117

Average hold 29.73 h (median 13.83); realized cost 0.0658 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00004 (return units); exit reasons {'stop': 1478, 'target': 335, 'time': 108}

Trades per month: 2021-01 7, 2021-02 1, 2021-03 16, 2021-04 4, 2021-05 11, 2021-06 22, 2021-07 27, 2021-08 16, 2021-09 15, 2021-10 18, 2021-11 23, 2021-12 20, 2022-01 34, 2022-02 30, 2022-03 22, 2022-04 42, 2022-05 40, 2022-06 43, 2022-07 21, 2022-08 29, 2022-09 27, 2022-10 22, 2022-11 26, 2022-12 44, 2023-01 7, 2023-02 21, 2023-03 38, 2023-04 20, 2023-05 38, 2023-06 24, 2023-07 23, 2023-08 27, 2023-09 37, 2023-10 36, 2023-11 19, 2023-12 22, 2024-01 22, 2024-02 21, 2024-03 12, 2024-04 34, 2024-05 24, 2024-06 41, 2024-07 27, 2024-08 30, 2024-09 20, 2024-10 33, 2024-11 23, 2024-12 26, 2025-01 29, 2025-02 30, 2025-03 35, 2025-04 18, 2025-05 36, 2025-06 26, 2025-07 22, 2025-08 35, 2025-09 33, 2025-10 18, 2025-11 44, 2025-12 48, 2026-01 45, 2026-02 34, 2026-03 51, 2026-04 31, 2026-05 42, 2026-06 52, 2026-07 46, 2026-08 29, 2026-09 32

H7-T entry overlap (limits book): same week any coin 0.316, same week same coin 0.000; same day any coin 0.057, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 4133 of 6054 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 2671 (mean R 0.0447)
- daily_loss_cap: 1462 (mean R -0.1006)

Same-4h-bar signal overlap across coins: 5139 of 6054 (0.849), max coins in one bar 28

- min-order skips at $100: 29 of 6054
- min-order skips at $300: 2 of 6054

Generator counters (summed over coins): channel_breaks 32139, entries 6054, signals 31667, skip_busy 1009, skip_no_minute 8429, skip_other 0, skip_rr 751, skip_stop_range 64, skip_wide 319, skip_window 15041

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 6054; sized 5790; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 264 trades in 10 coins (AUDIOUSDT 2, EOSUSDT 82, FRONTUSDT 4, HNTUSDT 18, LUNAUSDT 10, MATICUSDT 88, RNDRUSDT 11, SRMUSDT 13, SXPUSDT 30, TOMOUSDT 6).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 6054, mean R -0.0473; seed 97, N 74, q 0.000676): S1-1 pass=False value=-0.04726870650209592; S1-2 pass=False value=-0.23058646684617018; S1-3 pass=False value=-0.10606159026041667; S1-4 pass=False value=(-0.030582113315364673, -0.06395529968882718); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=97.74% top5-removed mean R=-0.3382), B: reference only (S1-5 pass=False MDD=99.17% top5-removed mean R=-0.3382)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 5790 | 5790 | 5790 | 5790 |
| Entered | 638 | 576 | 475 | 537 |
| Annual n (nearest int) | 225 | 248 | 117 | 148 |
| S1-0 tier | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.1356 | -0.1832 | -0.0847 | -0.0968 |
| Average hold (min) | 1560.05 | 1265.32 | 1507.74 | 1296.63 |
| Closed by replacement | 0 | 71 | 0 | 78 |
| Mean R of replaced | n/a | -0.3462 | n/a | -0.3277 |
| Replace attempts failed | none | no_loser 1126, still_blocked 32 | none | no_loser 1617, still_blocked 6 |
| Final wallet | 4.91 | 4.98 | 1.92 | 1.95 |
| Max concurrent | 3 | 3 | 2 | 2 |
| Max open loss (fraction of wallet) | 6.00% | 5.99% | 5.99% | 5.98% |
| FE-Z1 real-order MDD | 97.74% | 98.19% | 99.17% | 99.29% |
| FE-Z2 share reaching -25% (seed 88) | 100.00% | 100.00% | 100.00% | 100.00% |
| FE-Z2 n (annual) | 225 | 248 | 117 | 148 |
| FE-Z3 worst trade loss/wallet | 10.07% | 10.07% | 20.73% | 20.74% |
| First -25% touch vs initial (report only) | 2022-04-11 09:48:00 | 2022-04-30 22:00:00 | 2022-04-06 23:06:00 | 2022-05-07 21:13:00 |
| First -25% touch vs peak (report only) | 2021-07-11 04:06:00 | 2021-07-11 04:06:00 | 2021-07-09 11:25:00 | 2021-07-09 11:25:00 |
| Sized by margin cap / by loss | 616 / 22 | 554 / 22 | 199 / 276 | 235 / 302 |
| Liquidated | 1 | 2 | 2 | 1 |
| Skips by reason | below_min_notional 3090, bracket 17, max_positions 415, open_loss_cap 1014, qty_zero 382, stop_vs_liq 234 | below_min_notional 3445, bracket 3, max_positions 301, open_loss_cap 857, qty_zero 384, stop_vs_liq 224 | below_min_notional 2829, bracket 18, open_loss_cap 1779, qty_zero 466, stop_vs_liq 223 | below_min_notional 2916, bracket 16, open_loss_cap 1623, qty_zero 480, stop_vs_liq 218 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

