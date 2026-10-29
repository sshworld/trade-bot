# H64 screen result (1m intrabar; frame fe2) -- 2026-10-29 12:52 KST

Runner: branch h48-screen @ 70bf69a551; runtime 691 s (whole session), peak RSS 1402 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H64 / six (primary), seed 92, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 367, months 64, win rate 0.234, mean R -0.0857 (0.30% cost -0.1897), PF 0.884, MDD 0.703, final wallet x0.370

Candidate list (unlimited, R units): trades 367
- S1-0 trades / months: trades 367 >= 300 and months 64 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0857 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.4185 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1897 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0495, -0.1216, 183, 184) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.7035 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3896, 19) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.3343, 99.8% -0.3818, lock bound index 6

Candidate list: 367 trades, average hold 19.23 h, annual n 66 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 346, months 64, win rate 0.231, mean R -0.0881 (0.30% cost -0.1932), PF 0.881, MDD 0.701, final wallet x0.389

Limits book: trades 346
- S1-0 trades / months: trades 346 >= 300 and months 64 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0881 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.4059 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.1932 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0607, -0.1154, 173, 173) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.7006 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3996, 18) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.3410, 99.8% -0.3780, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 346 (>= 100: True), mean R -0.0881 (> 0: False), mean R at 2x cost -0.1932 (> 0: False)

- U1: coins with >= 10 trades 6, positive 3, share 0.500 (need >= 0.667; does not meet)
- U2: best coin ETHUSDT share nan of total R -30.47 (need <= 0.35; does not meet)
- U3: mean R without ETHUSDT: -0.1676, n 284 (does not meet)
- U4: in H16 universe: trades 339, coins 6, mean R -0.0783; not in H16: trades 7, coins 3, mean R -0.5586 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| ETHUSDT | 62 | 0.2763 | 17.13 |
| BTCUSDT | 42 | 0.1981 | 8.32 |
| DOGEUSDT | 72 | 0.0382 | 2.75 |
| BNBUSDT | 40 | -0.1484 | -5.93 |
| SOLUSDT | 68 | -0.3579 | -24.34 |
| XRPUSDT | 62 | -0.4580 | -28.40 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 3.

Annual n (limits book): 60.17 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 63.83 per year.
By year (KST entry year): 2021: n 44 mean -0.446, 2022: n 93 mean 0.122, 2023: n 53 mean -0.151, 2024: n 48 mean -0.063, 2025: n 65 mean -0.295, 2026: n 43 mean 0.188

Average hold 18.97 h (median 8.38); realized cost 0.1051 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00006 (return units); exit reasons {'stop': 259, 'target': 64, 'time': 23}

Trades per month: 2021-01 1, 2021-03 2, 2021-04 1, 2021-05 3, 2021-06 12, 2021-07 6, 2021-08 1, 2021-09 2, 2021-10 1, 2021-11 4, 2021-12 11, 2022-01 7, 2022-02 4, 2022-03 14, 2022-04 6, 2022-05 8, 2022-06 6, 2022-07 12, 2022-08 7, 2022-09 6, 2022-10 5, 2022-11 8, 2022-12 10, 2023-01 3, 2023-02 5, 2023-03 10, 2023-05 7, 2023-06 6, 2023-07 2, 2023-08 7, 2023-09 9, 2023-10 3, 2023-12 1, 2024-01 4, 2024-02 2, 2024-04 5, 2024-05 3, 2024-06 4, 2024-07 8, 2024-08 9, 2024-09 8, 2024-10 2, 2024-11 1, 2024-12 4, 2025-01 4, 2025-02 5, 2025-03 13, 2025-04 12, 2025-05 4, 2025-06 5, 2025-07 1, 2025-08 4, 2025-09 2, 2025-10 5, 2025-11 5, 2025-12 4, 2026-01 7, 2026-02 7, 2026-03 12, 2026-04 6, 2026-05 2, 2026-06 2, 2026-07 5, 2026-08 1

H7-T entry overlap (limits book): same week any coin 0.289, same week same coin 0.136; same day any coin 0.101, same day same coin 0.035 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 21 of 367 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 9 (mean R 0.5637)
- daily_loss_cap: 12 (mean R -0.5036)

Same-4h-bar signal overlap across coins: 71 of 367 (0.193), max coins in one bar 3

- min-order skips at $100: 18 of 367
- min-order skips at $300: 0 of 367

Generator counters (summed over coins): entries 367, signals 650, skip_busy 0, skip_no_minute 0, skip_other 0, skip_rr 99, skip_stop_range 108, skip_wide 2, skip_window 74, weeks 2035

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 367; sized 367; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 367, mean R -0.0857; seed 92, N 74, q 0.000676): S1-1 pass=False value=-0.0856639489727125; S1-2 pass=False value=-0.4185030609593723; S1-3 pass=False value=-0.2066879040677684; S1-4 pass=False value=(-0.04951951068795548, -0.12161195009287842); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=62.95% top5-removed mean R=-0.3896), B: reference only (S1-5 pass=False MDD=84.12% top5-removed mean R=-0.3896), C: reference only (S1-5 pass=False MDD=64.41% top5-removed mean R=-0.3896)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 367 | 367 | 367 | 367 | 367 | 367 |
| Entered | 329 | 329 | 273 | 287 | 324 | 326 |
| Annual n (nearest int) | 59 | 59 | 49 | 52 | 58 | 59 |
| S1-0 tier | conditional | conditional | undecidable | undecidable | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.1047 | -0.1081 | -0.1014 | -0.0826 | -0.1080 | -0.0971 |
| Average hold (min) | 1105.09 | 1105.94 | 1132.28 | 1077.74 | 1119.34 | 1123.48 |
| Closed by replacement | 0 | 3 | 0 | 15 | 0 | 5 |
| Mean R of replaced | n/a | -0.1941 | n/a | -0.3087 | n/a | -0.2911 |
| Replace attempts failed | none | no_loser 19 | none | no_loser 66 | none | no_loser 38, still_blocked 2 |
| Final wallet | 49.30 | 47.35 | 24.64 | 24.41 | 49.62 | 58.06 |
| Max concurrent | 3 | 3 | 2 | 2 | 3 | 3 |
| Max open loss (fraction of wallet) | 5.93% | 5.91% | 5.98% | 6.00% | 5.93% | 5.91% |
| FE-Z1 real-order MDD | 62.95% | 64.54% | 84.12% | 85.45% | 64.41% | 59.00% |
| FE-Z2 share reaching -25% (seed 88) | 52.13% | 53.75% | 91.87% | 92.68% | 63.78% | 61.95% |
| FE-Z2 n (annual) | 59 | 59 | 49 | 52 | 58 | 59 |
| FE-Z3 worst trade loss/wallet | 4.94% | 4.93% | 5.00% | 5.00% | 4.93% | 4.94% |
| First -25% touch vs initial (report only) | 2021-12-21 12:34:00 | 2021-12-21 03:34:00 | 2021-07-30 01:38:00 | 2021-07-30 01:38:00 | 2022-01-12 13:30:00 | 2022-01-12 13:30:00 |
| First -25% touch vs peak (report only) | 2021-12-21 12:34:00 | 2021-12-21 03:34:00 | 2021-07-30 01:38:00 | 2021-07-30 01:38:00 | 2022-01-12 13:30:00 | 2022-01-12 13:30:00 |
| Sized by margin cap / by loss | 328 / 1 | 328 / 1 | 214 / 59 | 225 / 62 | 301 / 23 | 305 / 21 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | below_min_notional 2, max_positions 4, open_loss_cap 18, qty_zero 13, stop_vs_liq 1 | below_min_notional 4, max_positions 4, open_loss_cap 15, qty_zero 14, stop_vs_liq 1 | open_loss_cap 82, qty_zero 11, stop_vs_liq 1 | open_loss_cap 66, qty_zero 13, stop_vs_liq 1 | max_positions 1, open_loss_cap 41, stop_vs_liq 1 | max_positions 1, open_loss_cap 39, stop_vs_liq 1 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H64 / new (aux), seed 92, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 2914, months 67, win rate 0.217, mean R -0.1531 (0.30% cost -0.2444), PF 0.799, MDD 1.000, final wallet x0.000

Candidate list (unlimited, R units): trades 2914
- S1-0 trades / months: trades 2914 >= 100 and months 67 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1531 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3151 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2444 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.1955, -0.1107, 1457, 1457) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 1.0 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.448, 146) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2793, 99.8% -0.3023, lock bound index 6

Candidate list: 2914 trades, average hold 16.83 h, annual n 510 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 1559, months 67, win rate 0.218, mean R -0.1220 (0.30% cost -0.2190), PF 0.839, MDD 0.997, final wallet x0.005

Limits book: trades 1559
- S1-0 trades / months: trades 1559 >= 100 and months 67 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.122 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.2961 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.219 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.1193, -0.1246, 779, 780) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.9971 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4404, 78) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2026') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2502, 99.8% -0.2767, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 1559 (>= 100: True), mean R -0.1220 (> 0: False), mean R at 2x cost -0.2190 (> 0: False)

- U1: coins with >= 10 trades 51, positive 19, share 0.373 (need >= 0.667; does not meet)
- U2: best coin BNXUSDT share nan of total R -190.17 (need <= 0.35; does not meet)
- U3: mean R without BNXUSDT: -0.1355, n 1554 (does not meet)
- U4: in H16 universe: trades 475, coins 90, mean R -0.1081; not in H16: trades 1084, coins 164, mean R -0.1281 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| BNXUSDT | 5 | 4.0693 | 20.35 |
| MATICUSDT | 21 | 0.8768 | 18.41 |
| AVAXUSDT | 42 | 0.3524 | 14.80 |
| ENAUSDT | 15 | 0.8966 | 13.45 |
| FETUSDT | 14 | 0.8124 | 11.37 |
| FILUSDT | 48 | 0.2059 | 9.88 |
| SANDUSDT | 21 | 0.4319 | 9.07 |
| WIFUSDT | 19 | 0.3521 | 6.69 |
| HNTUSDT | 4 | 1.5581 | 6.23 |
| 1000SATSUSDT | 3 | 2.0609 | 6.18 |
| TNSRUSDT | 3 | 2.0332 | 6.10 |
| JUPUSDT | 3 | 1.8652 | 5.60 |
| ZECUSDT | 16 | 0.3417 | 5.47 |
| NEIROUSDT | 1 | 5.3476 | 5.35 |
| GALAUSDT | 15 | 0.3514 | 5.27 |

Coins with trades 172; with >= 10 trades 51; mean R > 0 among those 19.

Annual n (limits book): 271.13 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 506.78 per year.
By year (KST entry year): 2021: n 173 mean -0.344, 2022: n 325 mean -0.084, 2023: n 247 mean 0.010, 2024: n 254 mean -0.164, 2025: n 297 mean -0.249, 2026: n 263 mean 0.037

Average hold 15.36 h (median 5.78); realized cost 0.0970 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00004 (return units); exit reasons {'stop': 1191, 'target': 254, 'time': 114}

Trades per month: 2021-01 3, 2021-03 3, 2021-05 9, 2021-06 16, 2021-07 39, 2021-08 8, 2021-09 18, 2021-10 32, 2021-11 25, 2021-12 20, 2022-01 31, 2022-02 29, 2022-03 32, 2022-04 24, 2022-05 21, 2022-06 25, 2022-07 34, 2022-08 24, 2022-09 22, 2022-10 22, 2022-11 33, 2022-12 28, 2023-01 18, 2023-02 4, 2023-03 31, 2023-04 27, 2023-05 27, 2023-06 23, 2023-07 28, 2023-08 30, 2023-09 37, 2023-10 14, 2023-11 1, 2023-12 7, 2024-01 28, 2024-02 13, 2024-03 8, 2024-04 24, 2024-05 28, 2024-06 26, 2024-07 33, 2024-08 31, 2024-09 26, 2024-10 11, 2024-11 13, 2024-12 15, 2025-01 28, 2025-02 21, 2025-03 43, 2025-04 35, 2025-05 24, 2025-06 17, 2025-07 14, 2025-08 14, 2025-09 18, 2025-10 15, 2025-11 33, 2025-12 33, 2026-01 37, 2026-02 30, 2026-03 33, 2026-04 30, 2026-05 23, 2026-06 22, 2026-07 43, 2026-08 28, 2026-09 17

H7-T entry overlap (limits book): same week any coin 0.359, same week same coin 0.000; same day any coin 0.132, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 1355 of 2914 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 789 (mean R -0.1225)
- daily_loss_cap: 566 (mean R -0.2816)

Same-4h-bar signal overlap across coins: 1438 of 2914 (0.493), max coins in one bar 21

- min-order skips at $100: 7 of 2914
- min-order skips at $300: 0 of 2914

Generator counters (summed over coins): entries 2914, signals 16276, skip_busy 0, skip_no_minute 4667, skip_other 0, skip_rr 605, skip_stop_range 422, skip_wide 8, skip_window 7660, weeks 40430

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 2914; sized 2776; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 138 trades in 10 coins (AUDIOUSDT 1, EOSUSDT 53, FRONTUSDT 2, HNTUSDT 6, LUNAUSDT 2, MATICUSDT 39, RNDRUSDT 5, SRMUSDT 8, SXPUSDT 18, TOMOUSDT 4).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 2914, mean R -0.1531; seed 92, N 74, q 0.000676): S1-1 pass=False value=-0.15313551800752376; S1-2 pass=False value=-0.31511886267213646; S1-3 pass=False value=-0.2578865537198128; S1-4 pass=False value=(-0.1955260931961373, -0.11074494281891023); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=96.37% top5-removed mean R=-0.4480), B: reference only (S1-5 pass=False MDD=98.76% top5-removed mean R=-0.4480)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 2776 | 2776 | 2776 | 2776 |
| Entered | 841 | 567 | 265 | 325 |
| Annual n (nearest int) | 238 | 258 | 152 | 172 |
| S1-0 tier | conditional | conditional | undecidable | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.2012 | -0.3299 | -0.3442 | -0.2788 |
| Average hold (min) | 819.59 | 691.42 | 622.41 | 597.83 |
| Closed by replacement | 0 | 49 | 0 | 41 |
| Mean R of replaced | n/a | -0.3743 | n/a | -0.3948 |
| Replace attempts failed | none | no_loser 357, still_blocked 14 | none | no_loser 374, still_blocked 1 |
| Final wallet | 4.95 | 4.84 | 1.95 | 1.96 |
| Max concurrent | 3 | 3 | 3 | 3 |
| Max open loss (fraction of wallet) | 5.94% | 5.98% | 5.95% | 5.97% |
| FE-Z1 real-order MDD | 96.37% | 96.45% | 98.76% | 98.75% |
| FE-Z2 share reaching -25% (seed 88) | 99.89% | 100.00% | 100.00% | 100.00% |
| FE-Z2 n (annual) | 238 | 258 | 152 | 172 |
| FE-Z3 worst trade loss/wallet | 4.98% | 4.97% | 5.75% | 5.16% |
| First -25% touch vs initial (report only) | 2021-07-24 16:18:00 | 2021-07-24 14:34:00 | 2021-07-23 01:01:00 | 2021-07-22 20:01:00 |
| First -25% touch vs peak (report only) | 2021-07-23 00:53:00 | 2021-07-22 09:31:00 | 2021-07-06 07:28:00 | 2021-07-06 07:28:00 |
| Sized by margin cap / by loss | 831 / 10 | 559 / 8 | 167 / 98 | 212 / 113 |
| Liquidated | 0 | 0 | 0 | 0 |
| Skips by reason | below_min_notional 1196, bracket 16, max_positions 397, open_loss_cap 151, qty_zero 149, stop_vs_liq 26 | below_min_notional 1632, bracket 1, max_positions 253, open_loss_cap 118, qty_zero 179, stop_vs_liq 26 | below_min_notional 1868, max_positions 12, open_loss_cap 368, qty_zero 248, stop_vs_liq 15 | below_min_notional 1816, max_positions 12, open_loss_cap 363, qty_zero 245, stop_vs_liq 15 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

