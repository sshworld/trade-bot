# H94 screen result (1m intrabar; frame fe2) -- 2026-10-29 14:41 KST

Runner: branch h48-screen @ b91fd39a44; runtime 804 s (whole session), peak RSS 1656 MB; locks: prereg-lock-h93-h98-v1_2.md c2945d535a11, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h93_early_v1_1.md 1f575ac39bd7; rule v1.1 hypotheses_h93_early.md e225f7ccee5c; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Spec notes: Batch 3 common frame (lock c2945d535a11 over QR v1.1 1f575ac39bd7): intrabar entry at the trigger 1m close, entry instant = close of the trigger minute; the 0.15% round trip (fees + slippage, lock costs line) is the only cost term, no separate entry-slippage add-on; stop 2 x A4 (Wilder ATR14 of the last closed 4h bar) fixed; a stop touched in the first held minute fills at min(open, stop) (short: max); exit at the next 1m open after the first 4h close below the prior 20-bar low (short: above the prior 20-bar high), counting 4h bars that close after the entry instant; no time cap, no target; BTC SMA200 regime of the last completed UTC day before the trigger minute (long 1, short 0, unknown skipped). Closed-bar values use bars that end at or before the trigger minute start; 15m bars are built from the stored 1m rows and rolling windows count existing bars (as the 4h bars). Signal-state rules (cooldown, one per range, re-arm, first-in-4h) run on the signal stream before the entry filters; filter order: window, next minute present, busy, regime, stop width (skip_stop_low < 0.60%, skip_stop_high > 8.0%; per coin in generator_counts_per_coin csv). Counters cooldown / range_used / not_first / not_rearmed / funding_not_neutral count candidate MINUTES. H94: the opening range needs all 60 1m bars (else counted or_incomplete); the width test is a session-level test at S0+60m with A4 of the last closed 4h bar then (width_rule_at_trigger_differs counts sessions where A4 at the break minute would flip it); the stop uses A4 at the trigger; first close beyond ORH/ORL only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H94 / six (primary), seed 98, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 1921, months 69, win rate 0.274, mean R 0.2480 (0.30% cost 0.2098), PF 1.426, MDD 0.947, final wallet x2.282

Candidate list (unlimited, R units): trades 1921
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1921 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.248 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.0891 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.2098 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.4023, 0.0939, 960, 961) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.947, 'top5_removed_mean': -0.3169, 'removed': 97} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.4942, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.0039, 99.8% -0.0562, lock bound index 6

Candidate list: 1921 trades, average hold 127.01 h, annual n 334 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 1029, months 69, win rate 0.283, mean R 0.3719 (0.30% cost 0.3338), PF 1.660, MDD 0.658, final wallet x17.676

Limits book: trades 1029
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1029 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.3719 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.0879 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.3338 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.5708, 0.1735, 514, 515) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.6582, 'top5_removed_mean': -0.2934, 'removed': 52} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.538, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% 0.0043, 99.8% -0.0561, lock bound index 6
end_of_data trades: 3

Lock aux numbers: trades 1029 (>= 100: True), mean R 0.3719 (> 0: True), mean R at 2x cost 0.3338 (> 0: True)

- U1: coins with >= 10 trades 6, positive 5, share 0.833 (need >= 0.667; meets)
- U2: best coin XRPUSDT share 0.370 of total R 382.71 (need <= 0.35; does not meet)
- U3: mean R without XRPUSDT: 0.2742, n 879 (meets)
- U4: in H16 universe: trades 1008, coins 6, mean R 0.2830; not in H16: trades 21, coins 3, mean R 4.6426 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| XRPUSDT | 150 | 0.9446 | 141.70 |
| DOGEUSDT | 128 | 1.0152 | 129.95 |
| BNBUSDT | 213 | 0.3472 | 73.96 |
| SOLUSDT | 166 | 0.1643 | 27.28 |
| ETHUSDT | 179 | 0.0869 | 15.55 |
| BTCUSDT | 193 | -0.0296 | -5.72 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 5.

Annual n (limits book): 178.96 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 334.09 per year.
By year (KST entry year): 2021: n 158 mean 1.303, 2022: n 174 mean 0.226, 2023: n 166 mean 0.123, 2024: n 195 mean 0.510, 2025: n 182 mean -0.036, 2026: n 154 mean 0.156

Average hold 125.89 h (median 71.78); realized cost 0.0381 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00153 (return units); exit reasons {'channel': 614, 'end_of_data': 3, 'stop': 412}

Trades per month: 2021-01 14, 2021-02 1, 2021-03 11, 2021-04 6, 2021-05 3, 2021-06 13, 2021-07 25, 2021-08 21, 2021-09 17, 2021-10 14, 2021-11 12, 2021-12 21, 2022-01 11, 2022-02 14, 2022-03 23, 2022-04 11, 2022-05 12, 2022-06 8, 2022-07 26, 2022-08 18, 2022-09 14, 2022-10 16, 2022-11 13, 2022-12 8, 2023-01 21, 2023-02 16, 2023-03 16, 2023-04 12, 2023-05 19, 2023-06 13, 2023-07 12, 2023-08 23, 2023-09 13, 2023-10 7, 2023-11 9, 2023-12 5, 2024-01 12, 2024-02 3, 2024-03 8, 2024-04 20, 2024-05 16, 2024-06 21, 2024-07 18, 2024-08 23, 2024-09 21, 2024-10 19, 2024-11 13, 2024-12 21, 2025-01 19, 2025-02 20, 2025-03 18, 2025-04 16, 2025-05 14, 2025-06 15, 2025-07 10, 2025-08 13, 2025-09 11, 2025-10 26, 2025-11 11, 2025-12 9, 2026-01 21, 2026-02 7, 2026-03 17, 2026-04 24, 2026-05 23, 2026-06 13, 2026-07 18, 2026-08 18, 2026-09 13

H7-T entry overlap (limits book): same week any coin 0.392, same week same coin 0.149; same day any coin 0.083, same day same coin 0.025 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

H7-T open-trade overlap (candidate list, n 1921): entered while an H7-T trade on the same coin was open 0.023 (same side 0.023); an H7-T trade on the same coin entered while this trade was open 0.129; either 0.153 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)

Long / short (candidate list): long 1015, short 906, long share 0.528

Signals skipped by the live limits: 892 of 1921 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 774 (mean R 0.1583)
- daily_loss_cap: 118 (mean R -0.2449)

Same-4h-bar signal overlap across coins: 371 of 1921 (0.193), max coins in one bar 5

- min-order skips at $100: 354 of 1921
- min-order skips at $300: 75 of 1921

Generator counters (summed over coins): entries 1921, long_entries 1015, no_break 2251, or_incomplete 0, or_width_invalid 10277, sessions 42854, short_entries 906, signals 30326, skip_busy 20860, skip_no_minute 0, skip_other 0, skip_regime 2751, skip_stop_high 999, skip_stop_low 0, skip_window 3795, width_rule_at_trigger_differs 9

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 1921; sized 1921; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Sizing-ledger RP-gate inputs on the unlimited candidate list (sizing-ledger R = unit / (stop_dist + 0.0017), n 1921, mean R 0.2480; seed 98, N 79, q 0.000633; a different R definition from the clause lines above, so these are not the clause S1-3 etc. and feed only the RP gate): gate mean R pass=True value=0.24797525411798305; gate date-block lower bound pass=False value=-0.08912973443575341; gate 2x-cost mean (R - 0.0015/stop_dist) pass=True value=0.20775647227676328; gate halves pass=True value=(0.40225649446369205, 0.09385455616597405); gate best-year share pass=True value=0.4941974909675186

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=72.57% top5-removed mean R=-0.3169), B: reference only (S1-5 pass=False MDD=83.50% top5-removed mean R=-0.3169), C: reference only (S1-5 pass=False MDD=77.77% top5-removed mean R=-0.3169)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 1921 | 1921 | 1921 | 1921 | 1921 | 1921 |
| Entered | 484 | 677 | 370 | 538 | 414 | 581 |
| Annual n (nearest int) | 84 | 118 | 64 | 94 | 72 | 101 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.2592 | 0.2126 | 0.0648 | 0.0704 | 0.2862 | 0.1248 |
| Average hold (min) | 6877.06 | 5456.60 | 7110.58 | 4980.61 | 7001.94 | 5357.95 |
| Closed by replacement | 0 | 170 | 0 | 185 | 0 | 179 |
| Mean R of replaced | n/a | -0.1991 | n/a | -0.1984 | n/a | -0.1915 |
| Replace attempts failed | none | no_loser 950, still_blocked 47 | none | no_loser 1137 | none | no_loser 1065, still_blocked 28 |
| Final wallet | 372.75 | 266.53 | 78.96 | 119.44 | 219.15 | 137.94 |
| Max concurrent | 3 | 3 | 1 | 1 | 3 | 2 |
| Max open loss (fraction of wallet) | 5.99% | 5.99% | 5.00% | 5.00% | 5.99% | 5.99% |
| FE-Z1 real-order MDD | 72.57% | 74.99% | 83.50% | 84.82% | 77.77% | 76.74% |
| FE-Z2 share reaching -25% (seed 88) | 94.54% | 95.70% | 97.93% | 98.81% | 96.08% | 95.82% |
| FE-Z2 n (annual) | 84 | 118 | 64 | 94 | 72 | 101 |
| FE-Z3 worst trade loss/wallet | 6.24% | 5.72% | 6.24% | 5.72% | 6.24% | 5.72% |
| First -25% touch vs initial (report only) | 2023-08-29 14:20:00 | 2023-06-14 20:05:00 | 2023-08-16 12:17:00 | 2022-04-03 22:43:00 | 2023-06-28 19:30:00 | 2022-03-30 15:16:00 |
| First -25% touch vs peak (report only) | 2021-08-10 13:11:00 | 2021-08-11 01:18:00 | 2021-08-10 13:11:00 | 2021-08-10 08:28:00 | 2021-08-10 13:11:00 | 2021-08-10 08:28:00 |
| Sized by margin cap / by loss | 368 / 116 | 521 / 156 | 18 / 352 | 27 / 511 | 224 / 190 | 331 / 250 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | max_positions 10, open_loss_cap 1181, stop_vs_liq 246 | below_min_notional 1, max_positions 14, open_loss_cap 983, stop_vs_liq 246 | open_loss_cap 1282, qty_zero 23, stop_vs_liq 246 | open_loss_cap 1137, stop_vs_liq 246 | open_loss_cap 1259, qty_zero 2, stop_vs_liq 246 | open_loss_cap 1093, qty_zero 1, stop_vs_liq 246 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H94 / new (aux), seed 98, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 10339, months 70, win rate 0.240, mean R -0.0604 (0.30% cost -0.0877), PF 0.900, MDD 1.000, final wallet x-0.000

Candidate list (unlimited, R units): trades 10339
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (10339 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: -0.0604 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.2004 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: -0.0877 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.0015, -0.1222, 5169, 5170) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 1.0, 'top5_removed_mean': -0.406, 'removed': 517} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1661, 99.8% -0.1894, lock bound index 6

Candidate list: 10339 trades, average hold 114.13 h, annual n 1799 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 1143, months 68, win rate 0.255, mean R -0.0841 (0.30% cost -0.1120), PF 0.853, MDD 0.988, final wallet x0.053

Limits book: trades 1143
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1143 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: -0.0841 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.2547 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: -0.112 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (-0.0382, -0.1299, 571, 572) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.9882, 'top5_removed_mean': -0.367, 'removed': 58} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2155, 99.8% -0.2397, lock bound index 6
end_of_data trades: 3

Lock aux numbers: trades 1143 (>= 100: True), mean R -0.0841 (> 0: False), mean R at 2x cost -0.1120 (> 0: False)

- U1: coins with >= 10 trades 30, positive 9, share 0.300 (need >= 0.667; does not meet)
- U2: best coin INJUSDT share nan of total R -96.08 (need <= 0.35; does not meet)
- U3: mean R without INJUSDT: -0.1069, n 1135 (does not meet)
- U4: in H16 universe: trades 390, coins 66, mean R -0.0681; not in H16: trades 753, coins 137, mean R -0.0923 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| INJUSDT | 8 | 3.1595 | 25.28 |
| BCHUSDT | 84 | 0.1496 | 12.57 |
| 1000FLOKIUSDT | 5 | 2.4641 | 12.32 |
| TRXUSDT | 56 | 0.1554 | 8.70 |
| ADAUSDT | 37 | 0.1934 | 7.15 |
| FLMUSDT | 2 | 3.5014 | 7.00 |
| AVAXUSDT | 23 | 0.2808 | 6.46 |
| APEUSDT | 8 | 0.8026 | 6.42 |
| AXSUSDT | 11 | 0.5396 | 5.94 |
| TRBUSDT | 6 | 0.9842 | 5.91 |
| MANAUSDT | 2 | 2.6865 | 5.37 |
| SANDUSDT | 10 | 0.5235 | 5.24 |
| DASHUSDT | 8 | 0.5940 | 4.75 |
| JUPUSDT | 1 | 4.2983 | 4.30 |
| LRCUSDT | 1 | 3.9104 | 3.91 |

Coins with trades 144; with >= 10 trades 30; mean R > 0 among those 9.

Annual n (limits book): 198.78 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 1798.09 per year.
By year (KST entry year): 2021: n 165 mean 0.019, 2022: n 180 mean 0.159, 2023: n 199 mean -0.238, 2024: n 259 mean -0.270, 2025: n 196 mean -0.147, 2026: n 144 mean 0.126

Average hold 117.28 h (median 66.88); realized cost 0.0280 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00170 (return units); exit reasons {'channel': 710, 'end_of_data': 3, 'stop': 430}

Trades per month: 2021-01 10, 2021-03 9, 2021-04 3, 2021-05 2, 2021-06 16, 2021-07 27, 2021-08 22, 2021-09 17, 2021-10 22, 2021-11 19, 2021-12 18, 2022-01 9, 2022-02 20, 2022-03 26, 2022-04 6, 2022-05 17, 2022-06 12, 2022-07 26, 2022-08 13, 2022-09 11, 2022-10 20, 2022-11 15, 2022-12 5, 2023-01 29, 2023-02 11, 2023-03 18, 2023-04 15, 2023-05 26, 2023-06 16, 2023-07 12, 2023-08 19, 2023-09 15, 2023-10 13, 2023-11 14, 2023-12 11, 2024-01 27, 2024-02 6, 2024-03 7, 2024-04 20, 2024-05 23, 2024-06 27, 2024-07 23, 2024-08 35, 2024-09 30, 2024-10 23, 2024-11 17, 2024-12 21, 2025-01 15, 2025-02 18, 2025-03 20, 2025-04 18, 2025-05 23, 2025-06 13, 2025-07 9, 2025-08 17, 2025-09 13, 2025-10 26, 2025-11 14, 2025-12 10, 2026-01 22, 2026-02 6, 2026-03 11, 2026-04 20, 2026-05 19, 2026-06 18, 2026-07 17, 2026-08 17, 2026-09 14

H7-T entry overlap (limits book): same week any coin 0.424, same week same coin 0.000; same day any coin 0.097, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

H7-T open-trade overlap (candidate list, n 10339): entered while an H7-T trade on the same coin was open 0.000 (same side 0.000); an H7-T trade on the same coin entered while this trade was open 0.000; either 0.000 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)

Long / short (candidate list): long 5679, short 4660, long share 0.549

Signals skipped by the live limits: 9196 of 10339 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 8615 (mean R -0.0299)
- daily_loss_cap: 581 (mean R -0.4659)

Same-4h-bar signal overlap across coins: 3978 of 10339 (0.385), max coins in one bar 26

- min-order skips at $100: 140 of 10339
- min-order skips at $300: 22 of 10339

Generator counters (summed over coins): entries 10339, long_entries 5679, no_break 30025, or_incomplete 6, or_width_invalid 151396, sessions 626822, short_entries 4660, signals 445395, skip_busy 105542, skip_no_minute 0, skip_other 0, skip_regime 24044, skip_stop_high 14103, skip_stop_low 0, skip_window 291367, width_rule_at_trigger_differs 111

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 10339; sized 9806; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 533 trades in 10 coins (AUDIOUSDT 6, EOSUSDT 184, FRONTUSDT 4, HNTUSDT 13, LUNAUSDT 21, MATICUSDT 169, RNDRUSDT 24, SRMUSDT 24, SXPUSDT 60, TOMOUSDT 28).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Sizing-ledger RP-gate inputs on the unlimited candidate list (sizing-ledger R = unit / (stop_dist + 0.0017), n 10339, mean R -0.0604; seed 98, N 79, q 0.000633; a different R definition from the clause lines above, so these are not the clause S1-3 etc. and feed only the RP gate): gate mean R pass=False value=-0.060382544562619864; gate date-block lower bound pass=False value=-0.20041920175661518; gate 2x-cost mean (R - 0.0015/stop_dist) pass=False value=-0.08875834762609718; gate halves pass=False value=(0.001465915598726891, -0.1222190417722913); gate best-year share pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=94.52% top5-removed mean R=-0.4060), B: reference only (S1-5 pass=False MDD=91.11% top5-removed mean R=-0.4060)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 9806 | 9806 | 9806 | 9806 |
| Entered | 412 | 753 | 372 | 618 |
| Annual n (nearest int) | 74 | 136 | 67 | 113 |
| S1-0 tier | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0627 | -0.0248 | -0.0298 | -0.0948 |
| Average hold (min) | 6804.23 | 3911.61 | 6965.94 | 3814.49 |
| Closed by replacement | 0 | 374 | 0 | 296 |
| Mean R of replaced | n/a | -0.1703 | n/a | -0.1591 |
| Replace attempts failed | none | no_loser 3629, still_blocked 121 | none | no_loser 2785, still_blocked 1 |
| Final wallet | 12.44 | 9.17 | 16.90 | 2.46 |
| Max concurrent | 2 | 2 | 1 | 1 |
| Max open loss (fraction of wallet) | 6.00% | 6.00% | 5.00% | 5.00% |
| FE-Z1 real-order MDD | 94.52% | 95.55% | 91.11% | 98.19% |
| FE-Z2 share reaching -25% (seed 88) | 98.82% | 99.46% | 99.19% | 99.81% |
| FE-Z2 n (annual) | 74 | 136 | 67 | 113 |
| FE-Z3 worst trade loss/wallet | 8.25% | 9.97% | 8.25% | 9.13% |
| First -25% touch vs initial (report only) | 2021-08-31 00:00:00 | 2021-07-26 19:22:00 | 2021-08-26 16:00:00 | 2021-07-26 19:22:00 |
| First -25% touch vs peak (report only) | 2021-08-01 03:37:00 | 2021-07-25 18:24:00 | 2021-08-01 03:37:00 | 2021-07-25 18:24:00 |
| Sized by margin cap / by loss | 188 / 224 | 355 / 398 | 9 / 363 | 34 / 584 |
| Liquidated | 1 | 7 | 1 | 5 |
| Skips by reason | below_min_notional 492, bracket 55, open_loss_cap 4545, qty_zero 299, stop_vs_liq 4003 | below_min_notional 1315, bracket 55, open_loss_cap 3750, qty_zero 472, stop_vs_liq 3461 | below_min_notional 156, bracket 55, open_loss_cap 4975, qty_zero 172, stop_vs_liq 4076 | below_min_notional 3287, bracket 53, open_loss_cap 2786, qty_zero 603, stop_vs_liq 2459 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

