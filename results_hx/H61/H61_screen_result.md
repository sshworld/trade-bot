# H61 screen result (1m intrabar; frame fe2) -- 2026-10-29 11:46 KST

Runner: branch h48-screen @ 714a1e3488; runtime 709 s (whole session), peak RSS 1460 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H61 / six (primary), seed 89, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 779, months 69, win rate 0.381, mean R -0.0893 (0.30% cost -0.1990), PF 0.838, MDD 0.829, final wallet x0.187

Candidate list (unlimited, R units): trades 779
- S1-0 trades / months: trades 779 >= 300 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0893 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2566 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.199 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0519, -0.1267, 389, 390) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.8288 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2259, 39) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2014, 99.8% -0.2262, lock bound index 6

Candidate list: 779 trades, average hold 6.59 h, annual n 136 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 747, months 69, win rate 0.384, mean R -0.0786 (0.30% cost -0.1891), PF 0.856, MDD 0.783, final wallet x0.237

Limits book: trades 747
- S1-0 trades / months: trades 747 >= 300 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0786 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2439 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1891 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0443, -0.1128, 373, 374) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.7834 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.217, 38) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1905, 99.8% -0.2132, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 747 (>= 100: True), mean R -0.0786 (> 0: False), mean R at 2x cost -0.1891 (> 0: False)

- U1: coins with >= 10 trades 6, positive 1, share 0.167 (need >= 0.667; does not meet)
- U2: best coin BTCUSDT share nan of total R -58.70 (need <= 0.35; does not meet)
- U3: mean R without BTCUSDT: -0.0919, n 655 (does not meet)
- U4: in H16 universe: trades 718, coins 6, mean R -0.0887; not in H16: trades 29, coins 2, mean R 0.1724 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| BTCUSDT | 92 | 0.0162 | 1.49 |
| XRPUSDT | 144 | -0.0278 | -4.01 |
| BNBUSDT | 105 | -0.0693 | -7.28 |
| SOLUSDT | 151 | -0.0691 | -10.44 |
| ETHUSDT | 119 | -0.1585 | -18.86 |
| DOGEUSDT | 136 | -0.1441 | -19.60 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 1.

Annual n (limits book): 129.91 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 135.48 per year.
By year (KST entry year): 2021: n 189 mean -0.194, 2022: n 129 mean 0.087, 2023: n 115 mean 0.142, 2024: n 117 mean -0.176, 2025: n 132 mean -0.037, 2026: n 65 mean -0.373

Average hold 6.63 h (median 4.92); realized cost 0.1105 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00009 (return units); exit reasons {'stop': 398, 'target': 182, 'time': 167}

Trades per month: 2021-01 11, 2021-02 13, 2021-03 22, 2021-04 16, 2021-05 20, 2021-06 12, 2021-07 16, 2021-08 16, 2021-09 24, 2021-10 21, 2021-11 7, 2021-12 11, 2022-01 11, 2022-02 6, 2022-03 7, 2022-04 12, 2022-05 12, 2022-06 11, 2022-07 10, 2022-08 18, 2022-09 17, 2022-10 12, 2022-11 10, 2022-12 3, 2023-01 12, 2023-02 9, 2023-03 14, 2023-04 10, 2023-05 5, 2023-06 15, 2023-07 11, 2023-08 4, 2023-09 2, 2023-10 3, 2023-11 20, 2023-12 10, 2024-01 11, 2024-02 6, 2024-03 7, 2024-04 3, 2024-05 11, 2024-06 13, 2024-07 13, 2024-08 15, 2024-09 12, 2024-10 9, 2024-11 5, 2024-12 12, 2025-01 16, 2025-02 11, 2025-03 11, 2025-04 12, 2025-05 12, 2025-06 6, 2025-07 7, 2025-08 14, 2025-09 5, 2025-10 17, 2025-11 15, 2025-12 6, 2026-01 4, 2026-02 14, 2026-03 13, 2026-04 8, 2026-05 7, 2026-06 4, 2026-07 3, 2026-08 7, 2026-09 5

H7-T entry overlap (limits book): same week any coin 0.415, same week same coin 0.175; same day any coin 0.092, same day same coin 0.011 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 32 of 779 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 31 (mean R -0.3199)
- daily_loss_cap: 1 (mean R -0.9779)

Same-4h-bar signal overlap across coins: 217 of 779 (0.279), max coins in one bar 5

- min-order skips at $100: 31 of 779
- min-order skips at $300: 0 of 779

Generator counters (summed over coins): days 14277, entries 779, no_profile 0, signals 1660, skip_busy 0, skip_no_minute 0, skip_other 0, skip_rr 429, skip_stop_range 275, skip_wide 3, skip_window 174

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 779; sized 779; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 779, mean R -0.0893; seed 89, N 74, q 0.000676): S1-1 pass=False value=-0.08933283690509414; S1-2 pass=False value=-0.2565684623364924; S1-3 pass=False value=-0.21765614942625033; S1-4 pass=False value=(-0.05186631214953808, -0.12670329364845642); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=68.20% top5-removed mean R=-0.2259), B: reference only (S1-5 pass=False MDD=87.71% top5-removed mean R=-0.2259), C: reference only (S1-5 pass=False MDD=68.90% top5-removed mean R=-0.2259)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 779 | 779 | 779 | 779 | 779 | 779 |
| Entered | 675 | 678 | 557 | 575 | 685 | 690 |
| Annual n (nearest int) | 118 | 118 | 97 | 100 | 119 | 120 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.1079 | -0.1079 | -0.0989 | -0.0927 | -0.1024 | -0.1117 |
| Average hold (min) | 389.28 | 387.67 | 383.90 | 371.64 | 385.69 | 381.13 |
| Closed by replacement | 0 | 3 | 0 | 19 | 0 | 6 |
| Mean R of replaced | n/a | -0.1004 | n/a | -0.2322 | n/a | -0.1762 |
| Replace attempts failed | none | no_loser 46 | none | no_loser 178, still_blocked 1 | none | no_loser 84, still_blocked 2 |
| Final wallet | 41.95 | 42.04 | 17.32 | 17.46 | 40.30 | 39.56 |
| Max concurrent | 3 | 3 | 2 | 2 | 3 | 3 |
| Max open loss (fraction of wallet) | 5.95% | 5.95% | 5.99% | 5.98% | 5.98% | 5.98% |
| FE-Z1 real-order MDD | 68.20% | 68.13% | 87.71% | 86.71% | 68.90% | 69.47% |
| FE-Z2 share reaching -25% (seed 88) | 55.96% | 53.27% | 92.21% | 92.19% | 68.94% | 69.86% |
| FE-Z2 n (annual) | 118 | 118 | 97 | 100 | 119 | 120 |
| FE-Z3 worst trade loss/wallet | 5.00% | 5.00% | 5.17% | 5.08% | 5.04% | 5.01% |
| First -25% touch vs initial (report only) | 2021-07-27 16:22:00 | 2021-07-27 16:22:00 | 2021-07-11 13:17:00 | 2021-07-09 12:08:00 | 2021-06-22 06:43:00 | 2021-06-22 06:43:00 |
| First -25% touch vs peak (report only) | 2021-07-09 12:08:00 | 2021-07-09 12:08:00 | 2021-06-22 06:43:00 | 2021-06-20 09:06:00 | 2021-05-09 03:34:00 | 2021-05-11 12:24:00 |
| Sized by margin cap / by loss | 669 / 6 | 672 / 6 | 456 / 101 | 471 / 104 | 615 / 70 | 619 / 71 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | below_min_notional 27, max_positions 16, open_loss_cap 33, qty_zero 26, stop_vs_liq 2 | below_min_notional 27, max_positions 14, open_loss_cap 32, qty_zero 26, stop_vs_liq 2 | below_min_notional 2, open_loss_cap 196, qty_zero 22, stop_vs_liq 2 | below_min_notional 2, open_loss_cap 179, qty_zero 21, stop_vs_liq 2 | max_positions 18, open_loss_cap 73, qty_zero 1, stop_vs_liq 2 | max_positions 18, open_loss_cap 68, qty_zero 1, stop_vs_liq 2 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H61 / new (aux), seed 89, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 5396, months 69, win rate 0.361, mean R -0.1060 (0.30% cost -0.1992), PF 0.820, MDD 1.000, final wallet x0.000

Candidate list (unlimited, R units): trades 5396
- S1-0 trades / months: trades 5396 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.106 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2052 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1992 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.1037, -0.1084, 2698, 2698) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 1.0 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2703, 270) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2026') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1800, 99.8% -0.1973, lock bound index 6

Candidate list: 5396 trades, average hold 5.92 h, annual n 939 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 3138, months 69, win rate 0.371, mean R -0.0921 (0.30% cost -0.1900), PF 0.842, MDD 1.000, final wallet x0.001

Limits book: trades 3138
- S1-0 trades / months: trades 3138 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0921 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.1814 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.19 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0927, -0.0914, 1569, 1569) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9997 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2554, 157) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1564, 99.8% -0.1737, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 3138 (>= 100: True), mean R -0.0921 (> 0: False), mean R at 2x cost -0.1900 (> 0: False)

- U1: coins with >= 10 trades 87, positive 25, share 0.287 (need >= 0.667; does not meet)
- U2: best coin EOSUSDT share nan of total R -288.95 (need <= 0.35; does not meet)
- U3: mean R without EOSUSDT: -0.1001, n 3082 (does not meet)
- U4: in H16 universe: trades 1087, coins 114, mean R -0.1149; not in H16: trades 2051, coins 182, mean R -0.0800 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| EOSUSDT | 56 | 0.3475 | 19.46 |
| FTMUSDT | 73 | 0.2552 | 18.63 |
| 1000PEPEUSDT | 37 | 0.2463 | 9.11 |
| ZECUSDT | 33 | 0.2519 | 8.31 |
| ENAUSDT | 22 | 0.3470 | 7.63 |
| GMTUSDT | 21 | 0.3155 | 6.62 |
| LDOUSDT | 16 | 0.3741 | 5.99 |
| XTZUSDT | 30 | 0.1896 | 5.69 |
| GALAUSDT | 34 | 0.1616 | 5.49 |
| TOMOUSDT | 12 | 0.4383 | 5.26 |
| LPTUSDT | 4 | 1.2229 | 4.89 |
| VELVETUSDT | 6 | 0.7909 | 4.75 |
| OGNUSDT | 9 | 0.5231 | 4.71 |
| KSMUSDT | 4 | 1.1585 | 4.63 |
| PUMPUSDT | 12 | 0.3847 | 4.62 |

Coins with trades 193; with >= 10 trades 87; mean R > 0 among those 25.

Annual n (limits book): 545.74 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 938.43 per year.
By year (KST entry year): 2021: n 491 mean -0.054, 2022: n 588 mean -0.106, 2023: n 558 mean -0.066, 2024: n 580 mean -0.142, 2025: n 484 mean -0.069, 2026: n 437 mean -0.108

Average hold 5.68 h (median 4.00); realized cost 0.0979 R per trade; mean slippage on stops 0.0001 R (all trades 0.0001); mean funding paid per trade -0.00005 (return units); exit reasons {'stop': 1799, 'target': 784, 'time': 555}

Trades per month: 2021-01 14, 2021-02 15, 2021-03 34, 2021-04 49, 2021-05 47, 2021-06 37, 2021-07 44, 2021-08 56, 2021-09 56, 2021-10 52, 2021-11 35, 2021-12 52, 2022-01 44, 2022-02 41, 2022-03 67, 2022-04 68, 2022-05 32, 2022-06 40, 2022-07 39, 2022-08 57, 2022-09 59, 2022-10 65, 2022-11 42, 2022-12 34, 2023-01 48, 2023-02 48, 2023-03 62, 2023-04 46, 2023-05 48, 2023-06 54, 2023-07 54, 2023-08 38, 2023-09 30, 2023-10 45, 2023-11 45, 2023-12 40, 2024-01 55, 2024-02 35, 2024-03 57, 2024-04 22, 2024-05 50, 2024-06 67, 2024-07 53, 2024-08 40, 2024-09 50, 2024-10 50, 2024-11 50, 2024-12 51, 2025-01 27, 2025-02 48, 2025-03 37, 2025-04 64, 2025-05 46, 2025-06 24, 2025-07 43, 2025-08 40, 2025-09 25, 2025-10 43, 2025-11 41, 2025-12 46, 2026-01 47, 2026-02 47, 2026-03 46, 2026-04 49, 2026-05 59, 2026-06 48, 2026-07 43, 2026-08 48, 2026-09 50

H7-T entry overlap (limits book): same week any coin 0.397, same week same coin 0.000; same day any coin 0.097, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 2258 of 5396 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 1995 (mean R -0.1327)
- daily_loss_cap: 263 (mean R -0.0703)

Same-4h-bar signal overlap across coins: 3379 of 5396 (0.626), max coins in one bar 15

- min-order skips at $100: 14 of 5396
- min-order skips at $300: 0 of 5396

Generator counters (summed over coins): days 197770, entries 5396, no_profile 0, signals 25544, skip_busy 0, skip_no_minute 15, skip_other 0, skip_rr 2822, skip_stop_range 527, skip_wide 10, skip_window 16774

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 5396; sized 5121; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 275 trades in 10 coins (AUDIOUSDT 4, EOSUSDT 91, FRONTUSDT 2, HNTUSDT 13, LUNAUSDT 10, MATICUSDT 89, RNDRUSDT 8, SRMUSDT 13, SXPUSDT 33, TOMOUSDT 12).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 5396, mean R -0.1060; seed 89, N 74, q 0.000676): S1-1 pass=False value=-0.10602729192220552; S1-2 pass=False value=-0.2051846122416326; S1-3 pass=False value=-0.21287963072737523; S1-4 pass=False value=(-0.10370130784050266, -0.1083532760039084); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=97.81% top5-removed mean R=-0.2703), B: reference only (S1-5 pass=False MDD=99.04% top5-removed mean R=-0.2703)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 5121 | 5121 | 5121 | 5121 |
| Entered | 1950 | 2004 | 1040 | 780 |
| Annual n (nearest int) | 492 | 529 | 311 | 349 |
| S1-0 tier | ok | ok | ok | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.1090 | -0.1122 | -0.1013 | -0.1477 |
| Average hold (min) | 325.28 | 295.53 | 317.52 | 268.87 |
| Closed by replacement | 0 | 178 | 0 | 83 |
| Mean R of replaced | n/a | -0.3059 | n/a | -0.3284 |
| Replace attempts failed | none | no_loser 1016, still_blocked 38 | none | no_loser 1130, still_blocked 12 |
| Final wallet | 4.88 | 4.97 | 1.97 | 1.95 |
| Max concurrent | 3 | 3 | 3 | 2 |
| Max open loss (fraction of wallet) | 5.98% | 6.00% | 6.00% | 6.00% |
| FE-Z1 real-order MDD | 97.81% | 97.50% | 99.04% | 99.02% |
| FE-Z2 share reaching -25% (seed 88) | 99.68% | 99.78% | 100.00% | 100.00% |
| FE-Z2 n (annual) | 492 | 529 | 311 | 349 |
| FE-Z3 worst trade loss/wallet | 4.98% | 4.85% | 5.21% | 5.21% |
| First -25% touch vs initial (report only) | 2021-11-14 00:00:00 | 2021-10-19 08:01:00 | 2021-10-06 20:33:00 | 2021-09-07 06:57:00 |
| First -25% touch vs peak (report only) | 2021-05-28 04:42:00 | 2021-05-17 15:36:00 | 2021-05-16 14:35:00 | 2021-05-11 12:32:00 |
| Sized by margin cap / by loss | 1937 / 13 | 1993 / 11 | 761 / 279 | 546 / 234 |
| Liquidated | 0 | 0 | 0 | 0 |
| Skips by reason | below_min_notional 1586, bracket 25, max_positions 820, open_loss_cap 526, qty_zero 179, stop_vs_liq 35 | below_min_notional 1756, bracket 25, max_positions 675, open_loss_cap 379, qty_zero 247, stop_vs_liq 35 | below_min_notional 2125, bracket 30, max_positions 2, open_loss_cap 1612, qty_zero 282, stop_vs_liq 30 | below_min_notional 2802, bracket 2, open_loss_cap 1142, qty_zero 369, stop_vs_liq 26 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

