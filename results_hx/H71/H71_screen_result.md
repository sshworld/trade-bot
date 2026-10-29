# H71 screen result (1m intrabar; frame fe2) -- 2026-10-29 13:36 KST

Runner: branch h48-screen @ b540344b9c; runtime 633 s (whole session), peak RSS 1513 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H71 / six (primary), seed 99, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 75, months 41, win rate 0.240, mean R -0.1355 (0.30% cost -0.1817), PF 0.746, MDD 0.363, final wallet x0.785

Candidate list (unlimited, R units): trades 75
- S1-0 trades / months: trades 75 >= 300 and months 41 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: -0.1355 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.5837 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1817 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0766, -0.1929, 37, 38) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.3632 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4446, 4) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.4955, 99.8% -0.5447, lock bound index 6

Candidate list: 75 trades, average hold 39.91 h, annual n 13 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 74, months 41, win rate 0.243, mean R -0.1238 (0.30% cost -0.1702), PF 0.765, MDD 0.351, final wallet x0.800

Limits book: trades 74
- S1-0 trades / months: trades 74 >= 300 and months 41 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: -0.1238 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.5783 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1702 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.064, -0.1837, 37, 37) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.3507 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4366, 4) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.4875, 99.8% -0.5385, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 74 (>= 100: False), mean R -0.1238 (> 0: False), mean R at 2x cost -0.1702 (> 0: False)

- U1: coins with >= 10 trades 4, positive 2, share 0.500 (need >= 0.667; does not meet)
- U2: best coin BNBUSDT share nan of total R -9.16 (need <= 0.35; does not meet)
- U3: mean R without BNBUSDT: -0.2398, n 55 (does not meet)
- U4: in H16 universe: trades 73, coins 6, mean R -0.1339; not in H16: trades 1, coins 1, mean R 0.6115 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| BNBUSDT | 19 | 0.2119 | 4.03 |
| BTCUSDT | 11 | 0.0011 | 0.01 |
| DOGEUSDT | 8 | -0.1400 | -1.12 |
| SOLUSDT | 9 | -0.3137 | -2.82 |
| ETHUSDT | 16 | -0.2858 | -4.57 |
| XRPUSDT | 11 | -0.4258 | -4.68 |

Coins with trades 6; with >= 10 trades 4; mean R > 0 among those 2.

Annual n (limits book): 12.87 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 13.04 per year.
By year (KST entry year): 2021: n 18 mean 0.480, 2022: n 2 mean -0.668, 2023: n 18 mean -0.569, 2024: n 21 mean 0.063, 2025: n 13 mean -0.502, 2026: n 2 mean -0.511

Average hold 40.09 h (median 30.47); realized cost 0.0464 R per trade; mean slippage on stops -0.9108 R (all trades -0.6031); mean funding paid per trade -0.00129 (return units); exit reasons {'bb_mid': 25, 'stop': 49}

Trades per month: 2021-01 2, 2021-02 3, 2021-03 2, 2021-04 1, 2021-05 1, 2021-08 2, 2021-09 2, 2021-10 2, 2021-11 2, 2021-12 1, 2022-08 1, 2022-12 1, 2023-01 3, 2023-04 4, 2023-05 2, 2023-06 1, 2023-07 3, 2023-08 3, 2023-10 1, 2023-12 1, 2024-01 5, 2024-02 1, 2024-03 2, 2024-04 2, 2024-05 1, 2024-06 2, 2024-07 1, 2024-08 1, 2024-10 1, 2024-11 3, 2024-12 2, 2025-01 1, 2025-02 1, 2025-03 1, 2025-05 1, 2025-06 3, 2025-08 2, 2025-09 3, 2025-10 1, 2026-01 1, 2026-09 1

H7-T entry overlap (limits book): same week any coin 0.770, same week same coin 0.338; same day any coin 0.432, same day same coin 0.203 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 1 of 75 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 1 (mean R -1.0021)

Same-4h-bar signal overlap across coins: 12 of 75 (0.160), max coins in one bar 2

- min-order skips at $100: 8 of 75
- min-order skips at $300: 2 of 75

Generator counters (summed over coins): entries 75, events 178, signals 178, skip_busy 68, skip_no_minute 0, skip_other 0, skip_rr 0, skip_stop_range 0, skip_wide 2, skip_window 33

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 75; sized 75; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 75, mean R -0.1355; seed 99, N 74, q 0.000676): S1-1 pass=False value=-0.1355431919877658; S1-2 pass=False value=-0.5837014455081567; S1-3 pass=False value=-0.18510138680750657; S1-4 pass=False value=(-0.07662364020062812, -0.19291222925418935); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=42.68% top5-removed mean R=-0.4446), B: reference only (S1-5 pass=False MDD=51.40% top5-removed mean R=-0.4446), C: reference only (S1-5 pass=False MDD=45.24% top5-removed mean R=-0.4446)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 75 | 75 | 75 | 75 | 75 | 75 |
| Entered | 58 | 59 | 54 | 55 | 56 | 57 |
| Annual n (nearest int) | 10 | 10 | 10 | 10 | 10 | 10 |
| S1-0 tier | undecidable | undecidable | undecidable | undecidable | undecidable | undecidable |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0876 | -0.0839 | -0.0669 | -0.0656 | -0.0913 | -0.0874 |
| Average hold (min) | 2404.47 | 2385.20 | 2387.78 | 2344.38 | 2348.45 | 2329.49 |
| Closed by replacement | 0 | 1 | 0 | 1 | 0 | 1 |
| Mean R of replaced | n/a | -0.1957 | n/a | -0.1504 | n/a | -0.1957 |
| Replace attempts failed | none | no_loser 6 | none | no_loser 11 | none | no_loser 9 |
| Final wallet | 98.81 | 98.13 | 84.71 | 84.77 | 94.39 | 95.96 |
| Max concurrent | 2 | 2 | 1 | 1 | 2 | 2 |
| Max open loss (fraction of wallet) | 5.55% | 5.55% | 5.00% | 5.00% | 5.78% | 5.78% |
| FE-Z1 real-order MDD | 42.68% | 43.08% | 51.40% | 51.37% | 45.24% | 44.33% |
| FE-Z2 share reaching -25% (seed 88) | 0.38% | 0.40% | 19.27% | 17.62% | 2.71% | 1.87% |
| FE-Z2 n (annual) | 10 | 10 | 10 | 10 | 10 | 10 |
| FE-Z3 worst trade loss/wallet | 4.77% | 4.77% | 4.99% | 4.99% | 4.88% | 4.88% |
| First -25% touch vs initial (report only) | n/a | n/a | 2024-05-27 20:00:00 | 2024-05-27 20:00:00 | n/a | n/a |
| First -25% touch vs peak (report only) | 2023-08-13 16:00:00 | 2023-08-13 16:00:00 | 2023-07-10 21:57:00 | 2023-07-10 21:57:00 | 2023-10-31 08:00:00 | 2023-10-31 08:00:00 |
| Sized by margin cap / by loss | 49 / 9 | 50 / 9 | 9 / 45 | 9 / 46 | 38 / 18 | 39 / 18 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | open_loss_cap 7, qty_zero 1, stop_vs_liq 9 | open_loss_cap 6, qty_zero 1, stop_vs_liq 9 | open_loss_cap 12, stop_vs_liq 9 | open_loss_cap 11, stop_vs_liq 9 | open_loss_cap 10, stop_vs_liq 9 | open_loss_cap 9, stop_vs_liq 9 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H71 / new (aux), seed 99, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 288, months 53, win rate 0.264, mean R 0.0758 (0.30% cost 0.0482), PF 1.164, MDD 0.652, final wallet x1.142

Candidate list (unlimited, R units): trades 288
- S1-0 trades / months: trades 288 >= 100 and months 53 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: 0.0758 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2971 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: 0.0482 (threshold meets; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0569, 0.2085, 144, 144) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.6524 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3093, 15) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (0.9111, '2021') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2247, 99.8% -0.2662, lock bound index 6

Candidate list: 288 trades, average hold 41.58 h, annual n 51 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 238, months 52, win rate 0.273, mean R 0.0055 (0.30% cost -0.0221), PF 1.012, MDD 0.564, final wallet x0.891

Limits book: trades 238
- S1-0 trades / months: trades 238 >= 100 and months 52 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: 0.0055 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2956 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.0221 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.2467, 0.2577, 119, 119) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.5638 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2907, 12) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (12.6693, '2024') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2259, 99.8% -0.2681, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 238 (>= 100: True), mean R 0.0055 (> 0: True), mean R at 2x cost -0.0221 (> 0: False)

- U1: coins with >= 10 trades 2, positive 0, share 0.000 (need >= 0.667; does not meet)
- U2: best coin STXUSDT share 10.725 of total R 1.31 (need <= 0.35; does not meet)
- U3: mean R without STXUSDT: -0.0544, n 235 (does not meet)
- U4: in H16 universe: trades 120, coins 51, mean R -0.0404; not in H16: trades 118, coins 66, mean R 0.0522 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| STXUSDT | 3 | 4.6961 | 14.09 |
| CRVUSDT | 6 | 1.6077 | 9.65 |
| ENAUSDT | 2 | 3.9890 | 7.98 |
| VVVUSDT | 1 | 7.8693 | 7.87 |
| TRXUSDT | 9 | 0.5797 | 5.22 |
| TRBUSDT | 2 | 1.5633 | 3.13 |
| ARCUSDT | 2 | 1.5024 | 3.00 |
| AVAXUSDT | 5 | 0.4440 | 2.22 |
| WLDUSDT | 1 | 2.0989 | 2.10 |
| DOTUSDT | 3 | 0.6592 | 1.98 |
| 1000FLOKIUSDT | 4 | 0.4178 | 1.67 |
| DASHUSDT | 2 | 0.8103 | 1.62 |
| PENGUUSDT | 1 | 1.5207 | 1.52 |
| CFXUSDT | 2 | 0.6407 | 1.28 |
| LPTUSDT | 2 | 0.5685 | 1.14 |

Coins with trades 91; with >= 10 trades 2; mean R > 0 among those 0.

Annual n (limits book): 41.39 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 50.09 per year.
By year (KST entry year): 2021: n 55 mean -0.151, 2022: n 13 mean -0.560, 2023: n 68 mean -0.247, 2024: n 60 mean 0.277, 2025: n 20 mean 0.436, 2026: n 22 mean 0.378

Average hold 40.98 h (median 30.10); realized cost 0.0277 R per trade; mean slippage on stops -1.1693 R (all trades -0.5994); mean funding paid per trade -0.00139 (return units); exit reasons {'bb_mid': 116, 'stop': 122}

Trades per month: 2021-02 6, 2021-03 6, 2021-04 9, 2021-07 1, 2021-08 10, 2021-09 4, 2021-10 13, 2021-11 6, 2022-01 1, 2022-03 2, 2022-08 6, 2022-09 2, 2022-12 2, 2023-01 3, 2023-02 7, 2023-03 2, 2023-04 14, 2023-06 3, 2023-07 6, 2023-08 9, 2023-09 4, 2023-10 5, 2023-11 4, 2023-12 11, 2024-01 9, 2024-02 9, 2024-03 9, 2024-04 3, 2024-05 6, 2024-06 3, 2024-07 5, 2024-09 2, 2024-10 5, 2024-11 3, 2024-12 7, 2025-01 2, 2025-02 1, 2025-03 1, 2025-04 1, 2025-05 4, 2025-06 1, 2025-07 1, 2025-08 3, 2025-09 4, 2025-12 1, 2026-01 1, 2026-03 1, 2026-04 3, 2026-05 3, 2026-06 3, 2026-07 3, 2026-08 4, 2026-09 4

H7-T entry overlap (limits book): same week any coin 0.660, same week same coin 0.000; same day any coin 0.261, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 50 of 288 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 50 (mean R 0.4103)

Same-4h-bar signal overlap across coins: 78 of 288 (0.271), max coins in one bar 4

- min-order skips at $100: 6 of 288
- min-order skips at $300: 2 of 288

Generator counters (summed over coins): entries 288, events 2030, signals 2030, skip_busy 269, skip_no_minute 460, skip_other 0, skip_rr 0, skip_stop_range 0, skip_wide 40, skip_window 973

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 288; sized 268; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 20 trades in 5 coins (EOSUSDT 7, MATICUSDT 6, RNDRUSDT 2, SXPUSDT 1, TOMOUSDT 4).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 288, mean R 0.0758; seed 99, N 74, q 0.000676): S1-1 pass=True value=0.07580186966179775; S1-2 pass=False value=-0.29709258337244315; S1-3 pass=True value=0.04713548374110088; S1-4 pass=False value=(-0.056885100293440245, 0.20848883961703576); S1-6 pass=False value=0.9111125071659866

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=63.99% top5-removed mean R=-0.3093), B: reference only (S1-5 pass=False MDD=66.54% top5-removed mean R=-0.3093)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 268 | 268 | 268 | 268 |
| Entered | 87 | 98 | 86 | 97 |
| Annual n (nearest int) | 16 | 18 | 16 | 18 |
| S1-0 tier | undecidable | undecidable | undecidable | undecidable |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.1349 | -0.0968 | -0.1312 | -0.0949 |
| Average hold (min) | 2301.38 | 2091.97 | 2307.01 | 2076.95 |
| Closed by replacement | 0 | 9 | 0 | 10 |
| Mean R of replaced | n/a | -0.2350 | n/a | -0.2210 |
| Replace attempts failed | none | no_loser 49, still_blocked 1 | none | no_loser 51 |
| Final wallet | 64.04 | 71.68 | 60.16 | 65.26 |
| Max concurrent | 2 | 2 | 1 | 1 |
| Max open loss (fraction of wallet) | 5.48% | 5.96% | 5.00% | 5.00% |
| FE-Z1 real-order MDD | 63.99% | 58.01% | 66.54% | 62.01% |
| FE-Z2 share reaching -25% (seed 88) | 23.99% | 23.05% | 34.00% | 33.57% |
| FE-Z2 n (annual) | 16 | 18 | 16 | 18 |
| FE-Z3 worst trade loss/wallet | 8.14% | 8.13% | 8.13% | 8.13% |
| First -25% touch vs initial (report only) | 2023-09-01 08:00:00 | 2023-12-10 09:59:00 | 2023-08-15 04:00:00 | 2023-11-26 16:27:00 |
| First -25% touch vs peak (report only) | 2022-03-28 23:53:00 | 2022-08-08 16:00:00 | 2021-11-16 00:04:00 | 2021-11-16 00:04:00 |
| Sized by margin cap / by loss | 45 / 42 | 51 / 47 | 2 / 84 | 2 / 95 |
| Liquidated | 1 | 1 | 1 | 1 |
| Skips by reason | bracket 2, open_loss_cap 60, qty_zero 2, stop_vs_liq 117 | bracket 2, open_loss_cap 50, qty_zero 1, stop_vs_liq 117 | bracket 2, open_loss_cap 61, qty_zero 2, stop_vs_liq 117 | bracket 2, open_loss_cap 51, qty_zero 1, stop_vs_liq 117 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

