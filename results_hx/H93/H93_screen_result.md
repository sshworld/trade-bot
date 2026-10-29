# H93 screen result (1m intrabar; frame fe2) -- 2026-10-29 14:29 KST

Runner: branch h48-screen @ b91fd39a44; runtime 804 s (whole session), peak RSS 1656 MB; locks: prereg-lock-h93-h98-v1_2.md c2945d535a11, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h93_early_v1_1.md 1f575ac39bd7; rule v1.1 hypotheses_h93_early.md e225f7ccee5c; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Spec notes: Batch 3 common frame (lock c2945d535a11 over QR v1.1 1f575ac39bd7): intrabar entry at the trigger 1m close, entry instant = close of the trigger minute; the 0.15% round trip (fees + slippage, lock costs line) is the only cost term, no separate entry-slippage add-on; stop 2 x A4 (Wilder ATR14 of the last closed 4h bar) fixed; a stop touched in the first held minute fills at min(open, stop) (short: max); exit at the next 1m open after the first 4h close below the prior 20-bar low (short: above the prior 20-bar high), counting 4h bars that close after the entry instant; no time cap, no target; BTC SMA200 regime of the last completed UTC day before the trigger minute (long 1, short 0, unknown skipped). Closed-bar values use bars that end at or before the trigger minute start; 15m bars are built from the stored 1m rows and rolling windows count existing bars (as the 4h bars). Signal-state rules (cooldown, one per range, re-arm, first-in-4h) run on the signal stream before the entry filters; filter order: window, next minute present, busy, regime, stop width (skip_stop_low < 0.60%, skip_stop_high > 8.0%; per coin in generator_counts_per_coin csv). Counters cooldown / range_used / not_first / not_rearmed / funding_not_neutral count candidate MINUTES. H93: one signal per Hi6/Lo6 VALUE per direction (literal QR v1 wording); V15 = volume of the 15 1m rows in [t-14m, t]; median over the previous 672 closed 15m bars.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H93 / six (primary), seed 97, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 1667, months 69, win rate 0.292, mean R 0.2937 (0.30% cost 0.2545), PF 1.477, MDD 0.926, final wallet x5.667

Candidate list (unlimited, R units): trades 1667
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (1667 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.2937 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.0855 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.2545 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.3764, 0.2111, 833, 834) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.9261, 'top5_removed_mean': -0.302, 'removed': 84} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.4309, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% 0.0109, 99.8% -0.0467, lock bound index 6

Candidate list: 1667 trades, average hold 136.03 h, annual n 290 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 915, months 68, win rate 0.297, mean R 0.3324 (0.30% cost 0.2926), PF 1.549, MDD 0.719, final wallet x13.129

Limits book: trades 915
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (915 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.3324 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.1297 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.2926 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.3185, 0.3462, 457, 458) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.7188, 'top5_removed_mean': -0.2781, 'removed': 46} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.2855, '2021') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.0139, 99.8% -0.0675, lock bound index 6
end_of_data trades: 3

Lock aux numbers: trades 915 (>= 100: True), mean R 0.3324 (> 0: True), mean R at 2x cost 0.2926 (> 0: True)

- U1: coins with >= 10 trades 6, positive 6, share 1.000 (need >= 0.667; meets)
- U2: best coin XRPUSDT share 0.424 of total R 304.10 (need <= 0.35; does not meet)
- U3: mean R without XRPUSDT: 0.2168, n 808 (meets)
- U4: in H16 universe: trades 902, coins 6, mean R 0.3299; not in H16: trades 13, coins 3, mean R 0.5050 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| XRPUSDT | 107 | 1.2052 | 128.96 |
| BNBUSDT | 164 | 0.4973 | 81.55 |
| SOLUSDT | 112 | 0.5694 | 63.77 |
| DOGEUSDT | 107 | 0.1306 | 13.97 |
| BTCUSDT | 229 | 0.0450 | 10.29 |
| ETHUSDT | 196 | 0.0284 | 5.56 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 6.

Annual n (limits book): 159.13 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 289.91 per year.
By year (KST entry year): 2021: n 129 mean 0.673, 2022: n 163 mean 0.247, 2023: n 164 mean 0.119, 2024: n 176 mean 0.491, 2025: n 167 mean 0.024, 2026: n 116 mean 0.579

Average hold 137.54 h (median 88.75); realized cost 0.0397 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00150 (return units); exit reasons {'channel': 456, 'end_of_data': 3, 'stop': 456}

Trades per month: 2021-01 13, 2021-03 13, 2021-04 6, 2021-05 3, 2021-06 8, 2021-07 18, 2021-08 17, 2021-09 13, 2021-10 10, 2021-11 13, 2021-12 15, 2022-01 11, 2022-02 14, 2022-03 22, 2022-04 10, 2022-05 12, 2022-06 6, 2022-07 24, 2022-08 16, 2022-09 18, 2022-10 14, 2022-11 9, 2022-12 7, 2023-01 27, 2023-02 12, 2023-03 13, 2023-04 15, 2023-05 18, 2023-06 14, 2023-07 6, 2023-08 19, 2023-09 11, 2023-10 8, 2023-11 9, 2023-12 12, 2024-01 14, 2024-02 3, 2024-03 10, 2024-04 19, 2024-05 11, 2024-06 21, 2024-07 15, 2024-08 19, 2024-09 21, 2024-10 18, 2024-11 10, 2024-12 15, 2025-01 15, 2025-02 15, 2025-03 16, 2025-04 19, 2025-05 11, 2025-06 16, 2025-07 8, 2025-08 20, 2025-09 7, 2025-10 16, 2025-11 13, 2025-12 11, 2026-01 16, 2026-02 7, 2026-03 17, 2026-04 20, 2026-05 11, 2026-06 9, 2026-07 15, 2026-08 9, 2026-09 12

H7-T entry overlap (limits book): same week any coin 0.401, same week same coin 0.154; same day any coin 0.095, same day same coin 0.033 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

H7-T open-trade overlap (candidate list, n 1667): entered while an H7-T trade on the same coin was open 0.025 (same side 0.025); an H7-T trade on the same coin entered while this trade was open 0.150; either 0.175 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)

Long / short (candidate list): long 870, short 797, long share 0.522

Signals skipped by the live limits: 752 of 1667 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 725 (mean R 0.2551)
- daily_loss_cap: 27 (mean R 0.0188)

Same-4h-bar signal overlap across coins: 192 of 1667 (0.115), max coins in one bar 3

- min-order skips at $100: 308 of 1667
- min-order skips at $300: 68 of 1667

Generator counters (summed over coins): cooldown 307440, entries 1667, long_entries 870, range_used 5158, short_entries 797, signals 22555, skip_busy 14851, skip_no_minute 0, skip_other 0, skip_regime 2659, skip_stop_high 485, skip_stop_low 0, skip_window 2893

Trades open across a data hole window: 1

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 1667; sized 1667; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Sizing-ledger RP-gate inputs on the unlimited candidate list (sizing-ledger R = unit / (stop_dist + 0.0017), n 1667, mean R 0.2937; seed 97, N 79, q 0.000633; a different R definition from the clause lines above, so these are not the clause S1-3 etc. and feed only the RP gate): gate mean R pass=True value=0.2936931221466907; gate date-block lower bound pass=False value=-0.08545430972639285; gate 2x-cost mean (R - 0.0015/stop_dist) pass=True value=0.2523158997247079; gate halves pass=True value=(0.3764206873576359, 0.21106475065902006); gate best-year share pass=True value=0.4309032955446368

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=75.25% top5-removed mean R=-0.3020), B: reference only (S1-5 pass=False MDD=83.64% top5-removed mean R=-0.3020), C: reference only (S1-5 pass=False MDD=78.12% top5-removed mean R=-0.3020)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 1667 | 1667 | 1667 | 1667 | 1667 | 1667 |
| Entered | 445 | 545 | 342 | 455 | 377 | 509 |
| Annual n (nearest int) | 77 | 95 | 60 | 79 | 66 | 89 |
| S1-0 tier | conditional | conditional | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.3966 | 0.0413 | 0.2331 | 0.0703 | 0.5441 | 0.0916 |
| Average hold (min) | 7441.34 | 5936.62 | 7515.75 | 5632.72 | 7759.02 | 5802.72 |
| Closed by replacement | 0 | 136 | 0 | 149 | 0 | 148 |
| Mean R of replaced | n/a | -0.2063 | n/a | -0.1920 | n/a | -0.1985 |
| Replace attempts failed | none | no_loser 812, no_price 2, still_blocked 30 | none | no_loser 1011, no_price 2 | none | no_loser 960, no_price 2, still_blocked 16 |
| Final wallet | 848.12 | 105.03 | 252.95 | 136.66 | 1312.38 | 143.20 |
| Max concurrent | 3 | 3 | 1 | 1 | 2 | 2 |
| Max open loss (fraction of wallet) | 6.00% | 6.00% | 5.00% | 5.00% | 6.00% | 5.98% |
| FE-Z1 real-order MDD | 75.25% | 81.69% | 83.64% | 81.04% | 78.12% | 76.90% |
| FE-Z2 share reaching -25% (seed 88) | 95.62% | 95.96% | 98.09% | 97.19% | 95.19% | 96.03% |
| FE-Z2 n (annual) | 77 | 95 | 60 | 79 | 66 | 89 |
| FE-Z3 worst trade loss/wallet | 10.07% | 8.73% | 14.10% | 8.73% | 9.99% | 8.73% |
| First -25% touch vs initial (report only) | n/a | 2022-03-24 16:00:00 | 2023-08-29 14:20:00 | 2021-12-22 04:00:00 | n/a | 2021-12-21 05:18:00 |
| First -25% touch vs peak (report only) | 2021-06-13 20:04:00 | 2021-06-13 20:04:00 | 2021-05-12 22:08:00 | 2021-05-12 22:08:00 | 2021-05-12 22:08:00 | 2021-05-12 22:08:00 |
| Sized by margin cap / by loss | 343 / 102 | 400 / 145 | 17 / 325 | 10 / 445 | 195 / 182 | 279 / 230 |
| Liquidated | 1 | 1 | 1 | 1 | 1 | 1 |
| Skips by reason | below_min_notional 1, max_positions 6, open_loss_cap 1049, stop_vs_liq 166 | below_min_notional 22, max_positions 8, open_loss_cap 836, qty_zero 91, stop_vs_liq 165 | below_min_notional 1, open_loss_cap 1157, qty_zero 1, stop_vs_liq 166 | below_min_notional 4, open_loss_cap 1013, qty_zero 30, stop_vs_liq 165 | below_min_notional 1, open_loss_cap 1123, stop_vs_liq 166 | below_min_notional 5, open_loss_cap 978, qty_zero 10, stop_vs_liq 165 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H93 / new (aux), seed 97, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 8510, months 70, win rate 0.257, mean R -0.0244 (0.30% cost -0.0526), PF 0.963, MDD 1.000, final wallet x0.000

Candidate list (unlimited, R units): trades 8510
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): pass (8510 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: -0.0244 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.1866 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: -0.0526 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.0197, -0.0684, 4255, 4255) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 1.0, 'top5_removed_mean': -0.4115, 'removed': 426} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1470, 99.8% -0.1759, lock bound index 6

Candidate list: 8510 trades, average hold 121.99 h, annual n 1481 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 988, months 69, win rate 0.284, mean R 0.0563 (0.30% cost 0.0286), PF 1.094, MDD 0.880, final wallet x0.770

Limits book: trades 988
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (988 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.0563 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.1637 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.0286 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.099, 0.0136, 494, 494) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.8796, 'top5_removed_mean': -0.3251, 'removed': 50} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.8628, '2022') (threshold does not meet; mechanical, verdict is TA's)
- date-block bounds: 99% -0.1065, 99.8% -0.1512, lock bound index 6
end_of_data trades: 3

Lock aux numbers: trades 988 (>= 100: True), mean R 0.0563 (> 0: True), mean R at 2x cost 0.0286 (> 0: True)

- U1: coins with >= 10 trades 28, positive 13, share 0.464 (need >= 0.667; does not meet)
- U2: best coin TRXUSDT share 0.525 of total R 55.61 (need <= 0.35; does not meet)
- U3: mean R without TRXUSDT: 0.0276, n 957 (meets)
- U4: in H16 universe: trades 308, coins 60, mean R -0.0183; not in H16: trades 680, coins 137, mean R 0.0900 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| TRXUSDT | 31 | 0.9420 | 29.20 |
| RUNEUSDT | 11 | 2.4256 | 26.68 |
| 1000BONKUSDT | 4 | 5.6031 | 22.41 |
| NEARUSDT | 22 | 0.8734 | 19.21 |
| OMUSDT | 1 | 16.4205 | 16.42 |
| STORJUSDT | 2 | 6.4674 | 12.93 |
| DOTUSDT | 26 | 0.4489 | 11.67 |
| AAVEUSDT | 21 | 0.5374 | 11.28 |
| BCHUSDT | 54 | 0.1828 | 9.87 |
| SUSHIUSDT | 9 | 1.0168 | 9.15 |
| STRKUSDT | 2 | 4.4769 | 8.95 |
| INJUSDT | 10 | 0.8287 | 8.29 |
| WIFUSDT | 2 | 3.0812 | 6.16 |
| DASHUSDT | 6 | 0.9559 | 5.74 |
| GALAUSDT | 9 | 0.6146 | 5.53 |

Coins with trades 147; with >= 10 trades 28; mean R > 0 among those 13.

Annual n (limits book): 171.83 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 1480.00 per year.
By year (KST entry year): 2021: n 132 mean 0.137, 2022: n 170 mean 0.282, 2023: n 192 mean -0.089, 2024: n 192 mean -0.093, 2025: n 172 mean 0.072, 2026: n 130 mean 0.093

Average hold 134.27 h (median 88.37); realized cost 0.0277 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00190 (return units); exit reasons {'channel': 527, 'end_of_data': 3, 'stop': 458}

Trades per month: 2021-01 9, 2021-02 2, 2021-03 10, 2021-04 3, 2021-05 1, 2021-06 10, 2021-07 16, 2021-08 24, 2021-09 9, 2021-10 13, 2021-11 13, 2021-12 22, 2022-01 10, 2022-02 22, 2022-03 26, 2022-04 8, 2022-05 12, 2022-06 9, 2022-07 19, 2022-08 20, 2022-09 7, 2022-10 19, 2022-11 11, 2022-12 7, 2023-01 29, 2023-02 14, 2023-03 21, 2023-04 10, 2023-05 22, 2023-06 16, 2023-07 7, 2023-08 30, 2023-09 16, 2023-10 12, 2023-11 11, 2023-12 4, 2024-01 13, 2024-02 10, 2024-03 10, 2024-04 19, 2024-05 16, 2024-06 19, 2024-07 15, 2024-08 23, 2024-09 22, 2024-10 25, 2024-11 10, 2024-12 10, 2025-01 16, 2025-02 20, 2025-03 13, 2025-04 17, 2025-05 20, 2025-06 11, 2025-07 8, 2025-08 17, 2025-09 11, 2025-10 16, 2025-11 13, 2025-12 10, 2026-01 8, 2026-02 11, 2026-03 17, 2026-04 20, 2026-05 16, 2026-06 12, 2026-07 23, 2026-08 10, 2026-09 13

H7-T entry overlap (limits book): same week any coin 0.421, same week same coin 0.000; same day any coin 0.093, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

H7-T open-trade overlap (candidate list, n 8510): entered while an H7-T trade on the same coin was open 0.000 (same side 0.000); an H7-T trade on the same coin entered while this trade was open 0.000; either 0.000 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)

Long / short (candidate list): long 4553, short 3957, long share 0.535

Signals skipped by the live limits: 7522 of 8510 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 7321 (mean R -0.0266)
- daily_loss_cap: 201 (mean R -0.3386)

Same-4h-bar signal overlap across coins: 2160 of 8510 (0.254), max coins in one bar 14

- min-order skips at $100: 107 of 8510
- min-order skips at $300: 20 of 8510

Generator counters (summed over coins): cooldown 3426388, entries 8510, long_entries 4553, range_used 143883, short_entries 3957, signals 274793, skip_busy 60682, skip_no_minute 0, skip_other 0, skip_regime 20006, skip_stop_high 7477, skip_stop_low 0, skip_window 178118

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 8510; sized 8081; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 429 trades in 10 coins (AUDIOUSDT 4, EOSUSDT 149, FRONTUSDT 3, HNTUSDT 10, LUNAUSDT 13, MATICUSDT 150, RNDRUSDT 17, SRMUSDT 20, SXPUSDT 41, TOMOUSDT 22).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Sizing-ledger RP-gate inputs on the unlimited candidate list (sizing-ledger R = unit / (stop_dist + 0.0017), n 8510, mean R -0.0244; seed 97, N 79, q 0.000633; a different R definition from the clause lines above, so these are not the clause S1-3 etc. and feed only the RP gate): gate mean R pass=False value=-0.02435528953529456; gate date-block lower bound pass=False value=-0.18660305262379612; gate 2x-cost mean (R - 0.0015/stop_dist) pass=False value=-0.053688245103889656; gate halves pass=False value=(0.01967056102146981, -0.06838114009205891); gate best-year share pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=84.54% top5-removed mean R=-0.4115), B: reference only (S1-5 pass=False MDD=88.22% top5-removed mean R=-0.4115)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 8081 | 8081 | 8081 | 8081 |
| Entered | 378 | 665 | 348 | 621 |
| Annual n (nearest int) | 67 | 118 | 62 | 110 |
| S1-0 tier | conditional | conditional | conditional | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.1098 | 0.0324 | 0.0852 | 0.0456 |
| Average hold (min) | 7365.82 | 4324.29 | 7417.32 | 4216.09 |
| Closed by replacement | 0 | 340 | 0 | 334 |
| Mean R of replaced | n/a | -0.1941 | n/a | -0.1920 |
| Replace attempts failed | none | no_loser 4245, still_blocked 67 | none | no_loser 4356 |
| Final wallet | 118.23 | 70.59 | 72.36 | 73.02 |
| Max concurrent | 2 | 2 | 2 | 1 |
| Max open loss (fraction of wallet) | 6.00% | 6.00% | 5.93% | 5.00% |
| FE-Z1 real-order MDD | 84.54% | 86.20% | 88.22% | 85.33% |
| FE-Z2 share reaching -25% (seed 88) | 97.41% | 99.05% | 98.70% | 99.24% |
| FE-Z2 n (annual) | 67 | 118 | 62 | 110 |
| FE-Z3 worst trade loss/wallet | 5.88% | 8.79% | 5.88% | 8.80% |
| First -25% touch vs initial (report only) | 2022-11-05 00:01:00 | 2023-05-25 13:57:00 | 2022-10-30 07:14:00 | 2023-05-25 01:26:00 |
| First -25% touch vs peak (report only) | 2021-08-06 17:57:00 | 2021-08-05 20:00:00 | 2021-08-06 17:57:00 | 2021-08-05 20:00:00 |
| Sized by margin cap / by loss | 178 / 200 | 317 / 348 | 6 / 342 | 8 / 613 |
| Liquidated | 0 | 2 | 0 | 2 |
| Skips by reason | bracket 46, open_loss_cap 4600, qty_zero 7, stop_vs_liq 3050 | bracket 46, open_loss_cap 4312, qty_zero 13, stop_vs_liq 3045 | bracket 46, open_loss_cap 4630, qty_zero 8, stop_vs_liq 3049 | bracket 46, open_loss_cap 4356, qty_zero 15, stop_vs_liq 3043 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

