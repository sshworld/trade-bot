# H98 screen result (1m intrabar; frame fe2) -- 2026-10-29 14:53 KST

Runner: branch h48-screen @ b91fd39a44; runtime 804 s (whole session), peak RSS 1656 MB; locks: prereg-lock-h93-h98-v1_2.md c2945d535a11, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h93_early_v1_1.md 1f575ac39bd7; rule v1.1 hypotheses_h93_early.md e225f7ccee5c; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Spec notes: Batch 3 common frame (lock c2945d535a11 over QR v1.1 1f575ac39bd7): intrabar entry at the trigger 1m close, entry instant = close of the trigger minute; the 0.15% round trip (fees + slippage, lock costs line) is the only cost term, no separate entry-slippage add-on; stop 2 x A4 (Wilder ATR14 of the last closed 4h bar) fixed; a stop touched in the first held minute fills at min(open, stop) (short: max); exit at the next 1m open after the first 4h close below the prior 20-bar low (short: above the prior 20-bar high), counting 4h bars that close after the entry instant; no time cap, no target; BTC SMA200 regime of the last completed UTC day before the trigger minute (long 1, short 0, unknown skipped). Closed-bar values use bars that end at or before the trigger minute start; 15m bars are built from the stored 1m rows and rolling windows count existing bars (as the 4h bars). Signal-state rules (cooldown, one per range, re-arm, first-in-4h) run on the signal stream before the entry filters; filter order: window, next minute present, busy, regime, stop width (skip_stop_low < 0.60%, skip_stop_high > 8.0%; per coin in generator_counts_per_coin csv). Counters cooldown / range_used / not_first / not_rearmed / funding_not_neutral count candidate MINUTES. H98: re-arm needs a 15m bar after the signal whose 16-bar window range is > 1.0 x A4 at that bar close; funding = last settled rate with timestamp <= trigger minute start, |rate| <= 0.0001 inclusive.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H98 / six (primary), seed 101, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 1431, months 69, win rate 0.275, mean R 0.2167 (0.30% cost 0.1782), PF 1.367, MDD 0.866, final wallet x1.594

Candidate list (unlimited, R units): trades 1431
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1431 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.2167 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.1228 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.1782 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.2457, 0.1877, 715, 716) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.8665, 'top5_removed_mean': -0.3175, 'removed': 72} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.4541, '2024') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.0371, 99.8% -0.0807, lock bound index 6

Candidate list: 1431 trades, average hold 136.31 h, annual n 252 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 844, months 68, win rate 0.278, mean R 0.3161 (0.30% cost 0.2781), PF 1.542, MDD 0.721, final wallet x6.959

Limits book: trades 844
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (844 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.3161 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.1715 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.2781 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.1935, 0.4386, 422, 422) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.7211, 'top5_removed_mean': -0.305, 'removed': 43} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.5588, '2024') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.0599, 99.8% -0.1169, lock bound index 6
end_of_data trades: 3

Lock aux numbers: trades 844 (>= 100: True), mean R 0.3161 (> 0: True), mean R at 2x cost 0.2781 (> 0: True)

- U1: coins with >= 10 trades 6, positive 5, share 0.833 (need >= 0.667; meets)
- U2: best coin XRPUSDT share 0.403 of total R 266.78 (need <= 0.35; does not meet)
- U3: mean R without XRPUSDT: 0.2202, n 723 (meets)
- U4: in H16 universe: trades 832, coins 6, mean R 0.3180; not in H16: trades 12, coins 3, mean R 0.1801 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| XRPUSDT | 121 | 0.8892 | 107.59 |
| BNBUSDT | 143 | 0.5289 | 75.63 |
| ETHUSDT | 179 | 0.2731 | 48.88 |
| DOGEUSDT | 113 | 0.3297 | 37.25 |
| SOLUSDT | 110 | 0.0214 | 2.35 |
| BTCUSDT | 178 | -0.0277 | -4.93 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 5.

Annual n (limits book): 146.78 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 248.87 per year.
By year (KST entry year): 2021: n 109 mean 0.681, 2022: n 151 mean 0.185, 2023: n 154 mean -0.094, 2024: n 152 mean 0.981, 2025: n 158 mean 0.004, 2026: n 120 mean 0.244

Average hold 137.31 h (median 93.97); realized cost 0.0380 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00108 (return units); exit reasons {'channel': 486, 'end_of_data': 3, 'stop': 355}

Trades per month: 2021-01 3, 2021-03 10, 2021-04 2, 2021-05 3, 2021-06 10, 2021-07 18, 2021-08 15, 2021-09 10, 2021-10 6, 2021-11 15, 2021-12 17, 2022-01 8, 2022-02 14, 2022-03 23, 2022-04 8, 2022-05 10, 2022-06 7, 2022-07 22, 2022-08 15, 2022-09 14, 2022-10 14, 2022-11 9, 2022-12 8, 2023-01 18, 2023-02 14, 2023-03 15, 2023-04 11, 2023-05 16, 2023-06 14, 2023-07 9, 2023-08 14, 2023-09 16, 2023-10 10, 2023-11 10, 2023-12 6, 2024-01 14, 2024-02 1, 2024-03 3, 2024-04 12, 2024-05 14, 2024-06 15, 2024-07 14, 2024-08 22, 2024-09 16, 2024-10 18, 2024-11 9, 2024-12 14, 2025-01 11, 2025-02 14, 2025-03 18, 2025-04 12, 2025-05 10, 2025-06 12, 2025-07 9, 2025-08 14, 2025-09 8, 2025-10 23, 2025-11 16, 2025-12 11, 2026-01 17, 2026-02 8, 2026-03 15, 2026-04 21, 2026-05 15, 2026-06 8, 2026-07 15, 2026-08 9, 2026-09 12

H7-T entry overlap (limits book): same week any coin 0.374, same week same coin 0.148; same day any coin 0.100, same day same coin 0.024 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

H7-T open-trade overlap (candidate list, n 1431): entered while an H7-T trade on the same coin was open 0.036 (same side 0.035); an H7-T trade on the same coin entered while this trade was open 0.137; either 0.172 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)

Long / short (candidate list): long 722, short 709, long share 0.505

Signals skipped by the live limits: 587 of 1431 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 569 (mean R 0.0769)
- daily_loss_cap: 18 (mean R -0.0258)

Same-4h-bar signal overlap across coins: 175 of 1431 (0.122), max coins in one bar 6

- min-order skips at $100: 262 of 1431
- min-order skips at $300: 52 of 1431

Generator counters (summed over coins): entries 1431, funding_not_neutral 20262, long_entries 722, not_rearmed 65711, short_entries 709, signals 11825, skip_busy 7114, skip_no_minute 0, skip_other 0, skip_regime 1528, skip_stop_high 353, skip_stop_low 0, skip_window 1399

Trades open across a data hole window: 1

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 1431; sized 1431; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Sizing-ledger RP-gate inputs on the unlimited candidate list (sizing-ledger R = unit / (stop_dist + 0.0017), n 1431, mean R 0.2167; seed 101, N 79, q 0.000633; a different R definition from the clause lines above, so these are not the clause S1-3 etc. and feed only the RP gate): gate mean R pass=True value=0.2166760167276453; gate date-block lower bound pass=False value=-0.12279965991084649; gate 2x-cost mean (R - 0.0015/stop_dist) pass=True value=0.1760918399284888; gate halves pass=True value=(0.2457285947239286, 0.18766401495761387); gate best-year share pass=True value=0.45408313297770875

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=70.71% top5-removed mean R=-0.3175), B: reference only (S1-5 pass=False MDD=66.38% top5-removed mean R=-0.3175), C: reference only (S1-5 pass=False MDD=63.76% top5-removed mean R=-0.3175)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 1431 | 1431 | 1431 | 1431 | 1431 | 1431 |
| Entered | 387 | 495 | 308 | 429 | 359 | 467 |
| Annual n (nearest int) | 68 | 87 | 54 | 76 | 63 | 82 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.6386 | 0.4947 | 0.6752 | 0.4977 | 0.6030 | 0.4582 |
| Average hold (min) | 7962.45 | 6217.81 | 7932.65 | 5725.18 | 7853.48 | 5980.73 |
| Closed by replacement | 0 | 130 | 0 | 138 | 0 | 127 |
| Mean R of replaced | n/a | -0.2100 | n/a | -0.2071 | n/a | -0.2117 |
| Replace attempts failed | none | no_loser 772, still_blocked 18 | none | no_loser 856 | none | no_loser 798, still_blocked 20 |
| Final wallet | 2811.06 | 2431.94 | 2464.73 | 2949.62 | 1342.72 | 1242.05 |
| Max concurrent | 3 | 3 | 1 | 1 | 2 | 2 |
| Max open loss (fraction of wallet) | 6.00% | 5.99% | 5.00% | 5.00% | 5.99% | 5.99% |
| FE-Z1 real-order MDD | 70.71% | 70.46% | 66.38% | 62.67% | 63.76% | 68.84% |
| FE-Z2 share reaching -25% (seed 88) | 88.84% | 90.28% | 97.06% | 97.29% | 93.74% | 94.47% |
| FE-Z2 n (annual) | 68 | 87 | 54 | 76 | 63 | 82 |
| FE-Z3 worst trade loss/wallet | 10.06% | 9.99% | 14.08% | 14.08% | 10.05% | 9.99% |
| First -25% touch vs initial (report only) | n/a | n/a | n/a | n/a | n/a | n/a |
| First -25% touch vs peak (report only) | 2021-08-12 14:57:00 | 2021-08-10 13:00:00 | 2021-08-12 14:57:00 | 2021-08-10 13:00:00 | 2021-08-12 14:57:00 | 2021-08-10 13:00:00 |
| Sized by margin cap / by loss | 289 / 98 | 371 / 124 | 10 / 298 | 15 / 414 | 200 / 159 | 271 / 196 |
| Liquidated | 1 | 1 | 1 | 1 | 1 | 1 |
| Skips by reason | max_positions 1, open_loss_cap 897, stop_vs_liq 146 | max_positions 1, open_loss_cap 789, stop_vs_liq 146 | open_loss_cap 977, stop_vs_liq 146 | open_loss_cap 856, stop_vs_liq 146 | open_loss_cap 926, stop_vs_liq 146 | open_loss_cap 818, stop_vs_liq 146 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H98 / new (aux), seed 101, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 7016, months 67, win rate 0.258, mean R -0.0322 (0.30% cost -0.0600), PF 0.947, MDD 1.000, final wallet x0.000

Candidate list (unlimited, R units): trades 7016
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (7016 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: -0.0322 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.1791 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: -0.06 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.0642, -0.1287, 3508, 3508) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 1.0, 'top5_removed_mean': -0.3917, 'removed': 351} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1466, 99.8% -0.1688, lock bound index 6

Candidate list: 7016 trades, average hold 125.17 h, annual n 1221 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 1002, months 67, win rate 0.283, mean R 0.0917 (0.30% cost 0.0647), PF 1.160, MDD 0.942, final wallet x0.722

Limits book: trades 1002
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1002 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.0917 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.1971 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.0647 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.1818, 0.0017, 501, 501) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.9422, 'top5_removed_mean': -0.3408, 'removed': 51} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.9152, '2021') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1360, 99.8% -0.1686, lock bound index 6
end_of_data trades: 3

Lock aux numbers: trades 1002 (>= 100: True), mean R 0.0917 (> 0: True), mean R at 2x cost 0.0647 (> 0: True)

- U1: coins with >= 10 trades 28, positive 15, share 0.536 (need >= 0.667; does not meet)
- U2: best coin ETCUSDT share 1.044 of total R 91.93 (need <= 0.35; does not meet)
- U3: mean R without ETCUSDT: -0.0042, n 975 (does not meet)
- U4: in H16 universe: trades 335, coins 62, mean R 0.2460; not in H16: trades 667, coins 139, mean R 0.0143 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| ETCUSDT | 27 | 3.5545 | 95.97 |
| APTUSDT | 10 | 2.0132 | 20.13 |
| SUIUSDT | 18 | 1.0593 | 19.07 |
| ZECUSDT | 13 | 1.3006 | 16.91 |
| RUNEUSDT | 9 | 1.7272 | 15.54 |
| WLDUSDT | 12 | 1.2316 | 14.78 |
| CRVUSDT | 15 | 0.9469 | 14.20 |
| DOTUSDT | 24 | 0.4859 | 11.66 |
| LTCUSDT | 51 | 0.1942 | 9.91 |
| CFXUSDT | 4 | 2.2597 | 9.04 |
| EGLDUSDT | 4 | 2.1839 | 8.74 |
| UNIUSDT | 29 | 0.2908 | 8.43 |
| FILUSDT | 29 | 0.2174 | 6.30 |
| TRUMPUSDT | 5 | 0.9934 | 4.97 |
| SUSHIUSDT | 3 | 1.5359 | 4.61 |

Coins with trades 148; with >= 10 trades 28; mean R > 0 among those 15.

Annual n (limits book): 174.26 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 1220.17 per year.
By year (KST entry year): 2021: n 132 mean 0.637, 2022: n 166 mean 0.284, 2023: n 190 mean -0.164, 2024: n 195 mean -0.136, 2025: n 192 mean -0.157, 2026: n 127 mean 0.381

Average hold 126.38 h (median 82.06); realized cost 0.0270 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00117 (return units); exit reasons {'channel': 594, 'end_of_data': 3, 'stop': 405}

Trades per month: 2021-01 1, 2021-03 8, 2021-04 1, 2021-05 1, 2021-06 11, 2021-07 18, 2021-08 28, 2021-09 10, 2021-10 19, 2021-11 15, 2021-12 20, 2022-01 16, 2022-02 17, 2022-03 26, 2022-04 9, 2022-05 7, 2022-06 10, 2022-07 21, 2022-08 10, 2022-09 15, 2022-10 15, 2022-11 10, 2022-12 10, 2023-01 27, 2023-02 11, 2023-03 21, 2023-04 15, 2023-05 23, 2023-06 12, 2023-07 13, 2023-08 17, 2023-09 20, 2023-10 11, 2023-11 13, 2023-12 7, 2024-01 16, 2024-02 5, 2024-03 5, 2024-04 13, 2024-05 19, 2024-06 18, 2024-07 25, 2024-08 27, 2024-09 16, 2024-10 20, 2024-11 17, 2024-12 14, 2025-01 17, 2025-02 13, 2025-03 25, 2025-04 20, 2025-05 17, 2025-06 11, 2025-07 14, 2025-08 18, 2025-09 13, 2025-10 23, 2025-11 12, 2025-12 9, 2026-01 12, 2026-02 15, 2026-03 14, 2026-04 21, 2026-05 11, 2026-06 16, 2026-07 16, 2026-08 11, 2026-09 11

H7-T entry overlap (limits book): same week any coin 0.418, same week same coin 0.000; same day any coin 0.097, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

H7-T open-trade overlap (candidate list, n 7016): entered while an H7-T trade on the same coin was open 0.000 (same side 0.000); an H7-T trade on the same coin entered while this trade was open 0.000; either 0.000 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)

Long / short (candidate list): long 3833, short 3183, long share 0.546

Signals skipped by the live limits: 6014 of 7016 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 5902 (mean R -0.0441)
- daily_loss_cap: 112 (mean R -0.5157)

Same-4h-bar signal overlap across coins: 1812 of 7016 (0.258), max coins in one bar 10

- min-order skips at $100: 70 of 7016
- min-order skips at $300: 13 of 7016

Generator counters (summed over coins): entries 7016, funding_not_neutral 268084, long_entries 3833, not_rearmed 818472, short_entries 3183, signals 153124, skip_busy 28780, skip_no_minute 0, skip_other 0, skip_regime 11498, skip_stop_high 5393, skip_stop_low 0, skip_window 100437

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 7016; sized 6644; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 372 trades in 10 coins (AUDIOUSDT 6, EOSUSDT 136, FRONTUSDT 3, HNTUSDT 9, LUNAUSDT 10, MATICUSDT 124, RNDRUSDT 15, SRMUSDT 12, SXPUSDT 39, TOMOUSDT 18).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Sizing-ledger RP-gate inputs on the unlimited candidate list (sizing-ledger R = unit / (stop_dist + 0.0017), n 7016, mean R -0.0322; seed 101, N 79, q 0.000633; a different R definition from the clause lines above, so these are not the clause S1-3 etc. and feed only the RP gate): gate mean R pass=False value=-0.032247576387098964; gate date-block lower bound pass=False value=-0.17906778845867577; gate 2x-cost mean (R - 0.0015/stop_dist) pass=False value=-0.06099229595434199; gate halves pass=False value=(0.06417650582953344, -0.12867165860373136); gate best-year share pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=94.57% top5-removed mean R=-0.3917), B: reference only (S1-5 pass=False MDD=95.82% top5-removed mean R=-0.3917)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 6644 | 6644 | 6644 | 6644 |
| Entered | 356 | 642 | 335 | 591 |
| Annual n (nearest int) | 67 | 121 | 63 | 111 |
| S1-0 tier | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0684 | -0.0405 | -0.0658 | -0.0325 |
| Average hold (min) | 7098.33 | 3969.26 | 6999.87 | 4008.21 |
| Closed by replacement | 0 | 305 | 0 | 289 |
| Mean R of replaced | n/a | -0.1739 | n/a | -0.1752 |
| Replace attempts failed | none | no_loser 2946, still_blocked 60 | none | no_loser 2888 |
| Final wallet | 19.17 | 14.94 | 12.53 | 15.10 |
| Max concurrent | 2 | 2 | 1 | 1 |
| Max open loss (fraction of wallet) | 5.97% | 6.00% | 5.00% | 5.00% |
| FE-Z1 real-order MDD | 94.57% | 96.06% | 95.82% | 97.03% |
| FE-Z2 share reaching -25% (seed 88) | 98.69% | 99.50% | 99.56% | 99.42% |
| FE-Z2 n (annual) | 67 | 121 | 63 | 111 |
| FE-Z3 worst trade loss/wallet | 6.62% | 6.62% | 9.39% | 8.61% |
| First -25% touch vs initial (report only) | 2021-08-26 07:04:00 | 2021-12-13 16:00:00 | 2021-08-26 07:04:00 | 2021-12-13 16:00:00 |
| First -25% touch vs peak (report only) | 2021-08-17 20:28:00 | 2021-10-11 00:00:00 | 2021-08-17 20:28:00 | 2021-10-11 00:00:00 |
| Sized by margin cap / by loss | 155 / 201 | 284 / 358 | 2 / 333 | 3 / 588 |
| Liquidated | 0 | 0 | 1 | 1 |
| Skips by reason | below_min_notional 211, bracket 39, open_loss_cap 3299, qty_zero 123, stop_vs_liq 2616 | below_min_notional 232, bracket 39, open_loss_cap 3006, qty_zero 141, stop_vs_liq 2584 | below_min_notional 267, bracket 39, open_loss_cap 3309, qty_zero 148, stop_vs_liq 2546 | below_min_notional 542, bracket 39, open_loss_cap 2888, qty_zero 217, stop_vs_liq 2367 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

