# H70 screen result (1m intrabar; frame fe2) -- 2026-10-29 13:34 KST

Runner: branch h48-screen @ b540344b9c; runtime 633 s (whole session), peak RSS 1513 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H70 / six (primary), seed 98, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 1181, months 69, win rate 0.285, mean R -0.0666 (0.30% cost -0.1403), PF 0.904, MDD 0.963, final wallet x0.072

Candidate list (unlimited, R units): trades 1181
- S1-0 trades / months: trades 1181 >= 300 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0666 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2445 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1403 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.062, -0.0713, 590, 591) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9629 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3294, 60) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1933, 99.8% -0.2245, lock bound index 6

Candidate list: 1181 trades, average hold 32.23 h, annual n 206 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 1027, months 69, win rate 0.287, mean R -0.0554 (0.30% cost -0.1301), PF 0.920, MDD 0.917, final wallet x0.140

Limits book: trades 1027
- S1-0 trades / months: trades 1027 >= 300 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0554 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.242 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1301 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0411, -0.0696, 513, 514) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9168 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3201, 52) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1903, 99.8% -0.2196, lock bound index 6
end_of_data trades: 1

Lock aux numbers: trades 1027 (>= 100: True), mean R -0.0554 (> 0: False), mean R at 2x cost -0.1301 (> 0: False)

- U1: coins with >= 10 trades 6, positive 2, share 0.333 (need >= 0.667; does not meet)
- U2: best coin ETHUSDT share nan of total R -56.86 (need <= 0.35; does not meet)
- U3: mean R without ETHUSDT: -0.0794, n 791 (does not meet)
- U4: in H16 universe: trades 997, coins 6, mean R -0.0553; not in H16: trades 30, coins 2, mean R -0.0571 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| ETHUSDT | 236 | 0.0252 | 5.95 |
| DOGEUSDT | 104 | 0.0464 | 4.83 |
| XRPUSDT | 102 | -0.0289 | -2.95 |
| BTCUSDT | 193 | -0.0642 | -12.39 |
| BNBUSDT | 185 | -0.0777 | -14.38 |
| SOLUSDT | 207 | -0.1832 | -37.92 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 2.

Annual n (limits book): 178.61 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 205.39 per year.
By year (KST entry year): 2021: n 234 mean -0.154, 2022: n 161 mean 0.015, 2023: n 165 mean 0.120, 2024: n 207 mean -0.092, 2025: n 162 mean -0.103, 2026: n 98 mean -0.076

Average hold 32.16 h (median 18.02); realized cost 0.0748 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00045 (return units); exit reasons {'end_of_data': 1, 'stop': 724, 'target': 230, 'time': 72}

Trades per month: 2021-01 18, 2021-02 32, 2021-03 18, 2021-04 29, 2021-05 13, 2021-06 9, 2021-07 16, 2021-08 31, 2021-09 10, 2021-10 33, 2021-11 12, 2021-12 13, 2022-01 3, 2022-02 15, 2022-03 30, 2022-04 6, 2022-05 4, 2022-06 9, 2022-07 19, 2022-08 16, 2022-09 25, 2022-10 13, 2022-11 14, 2022-12 7, 2023-01 25, 2023-02 6, 2023-03 11, 2023-04 16, 2023-05 8, 2023-06 12, 2023-07 15, 2023-08 5, 2023-09 8, 2023-10 16, 2023-11 21, 2023-12 22, 2024-01 9, 2024-02 26, 2024-03 31, 2024-04 10, 2024-05 19, 2024-06 6, 2024-07 19, 2024-08 10, 2024-09 18, 2024-10 20, 2024-11 27, 2024-12 12, 2025-01 17, 2025-02 3, 2025-03 7, 2025-04 16, 2025-05 17, 2025-06 9, 2025-07 31, 2025-08 17, 2025-09 13, 2025-10 21, 2025-11 2, 2025-12 10, 2026-01 14, 2026-02 3, 2026-03 9, 2026-04 13, 2026-05 6, 2026-06 2, 2026-07 20, 2026-08 17, 2026-09 13

H7-T entry overlap (limits book): same week any coin 0.558, same week same coin 0.302; same day any coin 0.233, same day same coin 0.101 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 154 of 1181 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 114 (mean R -0.0998)
- daily_loss_cap: 40 (mean R -0.2609)

Same-4h-bar signal overlap across coins: 419 of 1181 (0.355), max coins in one bar 5

- min-order skips at $100: 129 of 1181
- min-order skips at $300: 8 of 1181

Generator counters (summed over coins): channel_breaks 1821, entries 1181, signals 1816, skip_busy 169, skip_no_minute 0, skip_other 0, skip_rr 179, skip_stop_range 57, skip_wide 17, skip_window 213

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 1181; sized 1181; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 1181, mean R -0.0666; seed 98, N 74, q 0.000676): S1-1 pass=False value=-0.0666188184430439; S1-2 pass=False value=-0.24451511579638596; S1-3 pass=False value=-0.14928500009367973; S1-4 pass=False value=(-0.0619777295281524, -0.07125205441560906); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=89.31% top5-removed mean R=-0.3294), B: reference only (S1-5 pass=False MDD=96.38% top5-removed mean R=-0.3294), C: reference only (S1-5 pass=False MDD=89.24% top5-removed mean R=-0.3294)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 1181 | 1181 | 1181 | 1181 | 1181 | 1181 |
| Entered | 766 | 852 | 535 | 659 | 726 | 819 |
| Annual n (nearest int) | 133 | 148 | 93 | 115 | 126 | 143 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0914 | -0.0578 | -0.0801 | -0.0156 | -0.0768 | -0.0490 |
| Average hold (min) | 1745.14 | 1660.93 | 1745.29 | 1498.96 | 1727.22 | 1576.87 |
| Closed by replacement | 0 | 50 | 0 | 98 | 0 | 74 |
| Mean R of replaced | n/a | -0.3309 | n/a | -0.3174 | n/a | -0.3349 |
| Replace attempts failed | none | no_loser 188, still_blocked 10 | none | no_loser 456, still_blocked 7 | none | no_loser 291, still_blocked 7 |
| Final wallet | 19.51 | 36.51 | 6.97 | 25.10 | 17.31 | 25.04 |
| Max concurrent | 3 | 3 | 2 | 2 | 3 | 3 |
| Max open loss (fraction of wallet) | 5.99% | 6.00% | 5.99% | 5.96% | 5.99% | 6.00% |
| FE-Z1 real-order MDD | 89.31% | 80.43% | 96.38% | 86.98% | 89.24% | 86.54% |
| FE-Z2 share reaching -25% (seed 88) | 94.07% | 92.52% | 99.63% | 99.63% | 96.91% | 97.34% |
| FE-Z2 n (annual) | 133 | 148 | 93 | 115 | 126 | 143 |
| FE-Z3 worst trade loss/wallet | 8.41% | 8.42% | 8.42% | 8.40% | 8.39% | 8.40% |
| First -25% touch vs initial (report only) | 2021-04-30 18:52:00 | 2021-03-09 20:37:00 | 2021-03-08 19:15:00 | 2021-02-16 12:30:00 | 2021-04-12 01:30:00 | 2021-02-18 18:38:00 |
| First -25% touch vs peak (report only) | 2021-02-12 11:08:00 | 2021-02-10 08:05:00 | 2021-02-09 08:06:00 | 2021-02-09 08:06:00 | 2021-02-12 11:08:00 | 2021-02-10 08:05:00 |
| Sized by margin cap / by loss | 736 / 30 | 821 / 31 | 257 / 278 | 329 / 330 | 602 / 124 | 657 / 162 |
| Liquidated | 1 | 1 | 1 | 1 | 1 | 1 |
| Skips by reason | below_min_notional 58, max_positions 23, open_loss_cap 207, qty_zero 92, stop_vs_liq 35 | below_min_notional 13, max_positions 24, open_loss_cap 174, qty_zero 81, stop_vs_liq 37 | below_min_notional 38, open_loss_cap 501, qty_zero 72, stop_vs_liq 35 | below_min_notional 3, open_loss_cap 463, qty_zero 19, stop_vs_liq 37 | below_min_notional 34, max_positions 14, open_loss_cap 336, qty_zero 36, stop_vs_liq 35 | below_min_notional 8, max_positions 14, open_loss_cap 284, qty_zero 20, stop_vs_liq 36 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H70 / new (aux), seed 98, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 5955, months 69, win rate 0.283, mean R -0.0437 (0.30% cost -0.1000), PF 0.938, MDD 1.000, final wallet x0.000

Candidate list (unlimited, R units): trades 5955
- S1-0 trades / months: trades 5955 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0437 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.1607 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0712, -0.0163, 2977, 2978) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 1.0 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3127, 298) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1306, 99.8% -0.1479, lock bound index 6

Candidate list: 5955 trades, average hold 27.75 h, annual n 1037 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 2351, months 69, win rate 0.274, mean R -0.0244 (0.30% cost -0.0854), PF 0.966, MDD 0.975, final wallet x0.032

Limits book: trades 2351
- S1-0 trades / months: trades 2351 >= 100 and months 69 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0244 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.1569 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.0854 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0333, -0.0155, 1175, 1176) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9747 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3209, 118) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2024') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1187, 99.8% -0.1426, lock bound index 6
end_of_data trades: 3

Lock aux numbers: trades 2351 (>= 100: True), mean R -0.0244 (> 0: False), mean R at 2x cost -0.0854 (> 0: False)

- U1: coins with >= 10 trades 70, positive 25, share 0.357 (need >= 0.667; does not meet)
- U2: best coin LITUSDT share nan of total R -57.37 (need <= 0.35; does not meet)
- U3: mean R without LITUSDT: -0.0370, n 2338 (does not meet)
- U4: in H16 universe: trades 852, coins 79, mean R 0.0607; not in H16: trades 1499, coins 150, mean R -0.0727 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| LITUSDT | 13 | 2.2434 | 29.16 |
| ADAUSDT | 68 | 0.4265 | 29.00 |
| 1000SHIBUSDT | 25 | 0.9201 | 23.00 |
| OPUSDT | 31 | 0.7132 | 22.11 |
| FILUSDT | 42 | 0.3978 | 16.71 |
| STXUSDT | 8 | 1.7213 | 13.77 |
| ALGOUSDT | 16 | 0.8481 | 13.57 |
| APEUSDT | 9 | 1.1638 | 10.47 |
| THETAUSDT | 19 | 0.5463 | 10.38 |
| LINKUSDT | 120 | 0.0856 | 10.27 |
| 1000FLOKIUSDT | 10 | 0.9413 | 9.41 |
| TRXUSDT | 60 | 0.1446 | 8.68 |
| ATOMUSDT | 50 | 0.1635 | 8.18 |
| AKEUSDT | 1 | 6.6627 | 6.66 |
| SRMUSDT | 2 | 3.1030 | 6.21 |

Coins with trades 156; with >= 10 trades 70; mean R > 0 among those 25.

Annual n (limits book): 408.87 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 1035.65 per year.
By year (KST entry year): 2021: n 424 mean -0.087, 2022: n 337 mean 0.025, 2023: n 477 mean -0.055, 2024: n 437 mean 0.094, 2025: n 350 mean 0.000, 2026: n 326 mean -0.134

Average hold 25.29 h (median 12.78); realized cost 0.0610 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00033 (return units); exit reasons {'end_of_data': 3, 'stop': 1694, 'target': 562, 'time': 92}

Trades per month: 2021-01 16, 2021-02 29, 2021-03 34, 2021-04 50, 2021-05 19, 2021-06 19, 2021-07 32, 2021-08 62, 2021-09 33, 2021-10 52, 2021-11 37, 2021-12 41, 2022-01 22, 2022-02 19, 2022-03 54, 2022-04 24, 2022-05 7, 2022-06 23, 2022-07 45, 2022-08 29, 2022-09 30, 2022-10 37, 2022-11 32, 2022-12 17, 2023-01 50, 2023-02 27, 2023-03 23, 2023-04 33, 2023-05 27, 2023-06 28, 2023-07 42, 2023-08 26, 2023-09 49, 2023-10 53, 2023-11 54, 2023-12 63, 2024-01 28, 2024-02 62, 2024-03 43, 2024-04 16, 2024-05 37, 2024-06 23, 2024-07 33, 2024-08 39, 2024-09 49, 2024-10 32, 2024-11 45, 2024-12 30, 2025-01 34, 2025-02 16, 2025-03 36, 2025-04 45, 2025-05 26, 2025-06 20, 2025-07 47, 2025-08 25, 2025-09 29, 2025-10 25, 2025-11 19, 2025-12 28, 2026-01 28, 2026-02 17, 2026-03 26, 2026-04 38, 2026-05 41, 2026-06 24, 2026-07 48, 2026-08 41, 2026-09 63

H7-T entry overlap (limits book): same week any coin 0.495, same week same coin 0.000; same day any coin 0.182, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 3604 of 5955 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 2468 (mean R -0.0503)
- daily_loss_cap: 1136 (mean R -0.0695)

Same-4h-bar signal overlap across coins: 4156 of 5955 (0.698), max coins in one bar 19

- min-order skips at $100: 61 of 5955
- min-order skips at $300: 9 of 5955

Generator counters (summed over coins): channel_breaks 34956, entries 5955, signals 34461, skip_busy 976, skip_no_minute 9438, skip_other 0, skip_rr 1288, skip_stop_range 100, skip_wide 150, skip_window 16554

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 5955; sized 5631; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 324 trades in 10 coins (AUDIOUSDT 1, EOSUSDT 120, FRONTUSDT 2, HNTUSDT 8, LUNAUSDT 15, MATICUSDT 119, RNDRUSDT 9, SRMUSDT 3, SXPUSDT 30, TOMOUSDT 17).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 5955, mean R -0.0437; seed 98, N 74, q 0.000676): S1-1 pass=False value=-0.04374368732276675; S1-2 pass=False value=-0.1607100280937384; S1-3 pass=False value=-0.10551724609260352; S1-4 pass=False value=(-0.07113797733341484, -0.01635859620063799); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=93.53% top5-removed mean R=-0.3127), B: reference only (S1-5 pass=False MDD=98.31% top5-removed mean R=-0.3127)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 5631 | 5631 | 5631 | 5631 |
| Entered | 1665 | 1849 | 777 | 834 |
| Annual n (nearest int) | 290 | 326 | 172 | 208 |
| S1-0 tier | ok | ok | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0212 | -0.0329 | -0.0747 | -0.0590 |
| Average hold (min) | 1241.55 | 1104.25 | 1217.95 | 1069.96 |
| Closed by replacement | 0 | 256 | 0 | 168 |
| Mean R of replaced | n/a | -0.3387 | n/a | -0.3405 |
| Replace attempts failed | none | no_loser 2361, still_blocked 107 | none | no_loser 1835, still_blocked 8 |
| Final wallet | 8.57 | 4.85 | 1.98 | 2.00 |
| Max concurrent | 3 | 3 | 2 | 2 |
| Max open loss (fraction of wallet) | 6.00% | 5.99% | 5.98% | 5.97% |
| FE-Z1 real-order MDD | 93.53% | 95.87% | 98.31% | 98.30% |
| FE-Z2 share reaching -25% (seed 88) | 99.97% | 99.98% | 100.00% | 100.00% |
| FE-Z2 n (annual) | 290 | 326 | 172 | 208 |
| FE-Z3 worst trade loss/wallet | 10.07% | 10.05% | 15.12% | 15.19% |
| First -25% touch vs initial (report only) | 2021-01-25 00:23:00 | 2021-01-25 00:23:00 | 2021-01-17 22:12:00 | 2021-01-17 22:12:00 |
| First -25% touch vs peak (report only) | 2021-01-25 00:23:00 | 2021-01-25 00:23:00 | 2021-01-17 22:12:00 | 2021-01-17 22:12:00 |
| Sized by margin cap / by loss | 1564 / 101 | 1738 / 111 | 322 / 455 | 323 / 511 |
| Liquidated | 4 | 6 | 3 | 3 |
| Skips by reason | below_min_notional 467, bracket 20, max_positions 796, open_loss_cap 1943, qty_zero 306, stop_vs_liq 434 | below_min_notional 587, bracket 19, max_positions 801, open_loss_cap 1667, qty_zero 331, stop_vs_liq 377 | below_min_notional 2133, bracket 22, open_loss_cap 1998, qty_zero 555, stop_vs_liq 146 | below_min_notional 2199, bracket 21, open_loss_cap 1843, qty_zero 502, stop_vs_liq 232 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

