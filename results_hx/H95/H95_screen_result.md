# H95 screen result (1m intrabar; frame fe2) -- 2026-10-29 14:41 KST

Runner: branch h48-screen @ b91fd39a44; runtime 804 s (whole session), peak RSS 1656 MB; locks: prereg-lock-h93-h98-v1_2.md c2945d535a11, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h93_early_v1_1.md 1f575ac39bd7; rule v1.1 hypotheses_h93_early.md e225f7ccee5c; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Spec notes: Batch 3 common frame (lock c2945d535a11 over QR v1.1 1f575ac39bd7): intrabar entry at the trigger 1m close, entry instant = close of the trigger minute; the 0.15% round trip (fees + slippage, lock costs line) is the only cost term, no separate entry-slippage add-on; stop 2 x A4 (Wilder ATR14 of the last closed 4h bar) fixed; a stop touched in the first held minute fills at min(open, stop) (short: max); exit at the next 1m open after the first 4h close below the prior 20-bar low (short: above the prior 20-bar high), counting 4h bars that close after the entry instant; no time cap, no target; BTC SMA200 regime of the last completed UTC day before the trigger minute (long 1, short 0, unknown skipped). Closed-bar values use bars that end at or before the trigger minute start; 15m bars are built from the stored 1m rows and rolling windows count existing bars (as the 4h bars). Signal-state rules (cooldown, one per range, re-arm, first-in-4h) run on the signal stream before the entry filters; filter order: window, next minute present, busy, regime, stop width (skip_stop_low < 0.60%, skip_stop_high > 8.0%; per coin in generator_counts_per_coin csv). Counters cooldown / range_used / not_first / not_rearmed / funding_not_neutral count candidate MINUTES. H95: OI points with timestamp <= trigger minute start; fresh = latest point >= t - 10 min (stale counted once per direction and level, it does not use up the level or the cooldown); dOI >= +1.5% inclusive; entries from the first complete OI month (BTC 2020-09 -> window start 2021-01; ETH SOL BNB XRP DOGE 2021-12). OI exists for the six only: new coins give 0 trades (no_oi_data).

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H95 / six (primary), seed 99, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 870, months 68, win rate 0.266, mean R 0.2243 (0.30% cost 0.1844), PF 1.342, MDD 0.730, final wallet x2.006

Candidate list (unlimited, R units): trades 870
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (870 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.2243 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.1786 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.1844 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.1833, 0.2652, 435, 435) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.7301, 'top5_removed_mean': -0.3417, 'removed': 44} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.5823, '2024') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.0907, 99.8% -0.1377, lock bound index 6

Candidate list: 870 trades, average hold 134.22 h, annual n 151 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 585, months 68, win rate 0.294, mean R 0.2649 (0.30% cost 0.2261), PF 1.430, MDD 0.538, final wallet x5.068

Limits book: trades 585
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): conditional (585 trades; mechanical, verdict is TA's)
- S1-1 mean R > 0: 0.2649 (threshold meets; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound > 0: -0.123 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 2x cost (0.30%) > 0: 0.2261 (threshold meets; mechanical, verdict is TA's)
- S1-4 both halves > 0 (first, second mean, n, n): (0.3495, 0.1806, 292, 293) (threshold meets; mechanical, verdict is TA's)
- S1-5 MDD <= 20% and top-5%-removed mean > 0: {'max_dd': 0.5384, 'top5_removed_mean': -0.2281, 'removed': 30} (threshold does not meet; mechanical, verdict is TA's)
- S1-6 best-year share of total R <= 60% (share, year): (0.3134, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.0378, 99.8% -0.0914, lock bound index 6
end_of_data trades: 2

Lock aux numbers: trades 585 (>= 100: True), mean R 0.2649 (> 0: True), mean R at 2x cost 0.2261 (> 0: True)

- U1: coins with >= 10 trades 6, positive 5, share 0.833 (need >= 0.667; meets)
- U2: best coin SOLUSDT share 0.412 of total R 154.96 (need <= 0.35; does not meet)
- U3: mean R without SOLUSDT: 0.1890, n 482 (meets)
- U4: in H16 universe: trades 581, coins 6, mean R 0.2722; not in H16: trades 4, coins 2, mean R -0.7964 (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| SOLUSDT | 103 | 0.6199 | 63.85 |
| BTCUSDT | 134 | 0.2081 | 27.89 |
| DOGEUSDT | 100 | 0.2657 | 26.57 |
| ETHUSDT | 100 | 0.2428 | 24.28 |
| BNBUSDT | 72 | 0.3122 | 22.48 |
| XRPUSDT | 76 | -0.1330 | -10.11 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 5.

Annual n (limits book): 101.74 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 151.30 per year.
By year (KST entry year): 2021: n 48 mean -0.389, 2022: n 92 mean 0.528, 2023: n 130 mean 0.255, 2024: n 127 mean 0.347, 2025: n 119 mean 0.180, 2026: n 69 mean 0.381

Average hold 144.91 h (median 95.92); realized cost 0.0388 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00167 (return units); exit reasons {'channel': 271, 'end_of_data': 2, 'stop': 312}

Trades per month: 2021-01 5, 2021-03 4, 2021-04 2, 2021-05 1, 2021-06 4, 2021-07 2, 2021-08 3, 2021-09 5, 2021-10 3, 2021-11 4, 2021-12 15, 2022-01 8, 2022-02 6, 2022-03 8, 2022-04 8, 2022-05 6, 2022-06 7, 2022-07 11, 2022-08 9, 2022-09 9, 2022-10 7, 2022-11 7, 2022-12 6, 2023-01 12, 2023-02 11, 2023-03 13, 2023-04 13, 2023-05 13, 2023-06 12, 2023-07 8, 2023-08 16, 2023-09 6, 2023-10 8, 2023-11 9, 2023-12 9, 2024-01 14, 2024-02 8, 2024-03 7, 2024-04 13, 2024-05 10, 2024-06 16, 2024-07 10, 2024-08 13, 2024-09 5, 2024-10 13, 2024-11 7, 2024-12 11, 2025-01 12, 2025-02 10, 2025-03 17, 2025-04 13, 2025-05 7, 2025-06 12, 2025-07 4, 2025-08 11, 2025-09 8, 2025-10 11, 2025-11 9, 2025-12 7, 2026-01 8, 2026-02 7, 2026-03 9, 2026-04 7, 2026-05 5, 2026-06 4, 2026-07 7, 2026-08 8, 2026-09 12

H7-T entry overlap (limits book): same week any coin 0.470, same week same coin 0.231; same day any coin 0.191, same day same coin 0.103 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

H7-T open-trade overlap (candidate list, n 870): entered while an H7-T trade on the same coin was open 0.099 (same side 0.099); an H7-T trade on the same coin entered while this trade was open 0.190; either 0.287 (same coin; H7-T entry <= entry < H7-T exit counts as H7-T first; H7-T entry strictly inside this trade counts as this trade first)

Long / short (candidate list): long 551, short 319, long share 0.633

Signals skipped by the live limits: 285 of 870 raw signals (mean unsized R of the skipped, descriptive only):
- max_concurrent: 284 (mean R 0.1449)
- daily_loss_cap: 1 (mean R -0.9969)

Same-4h-bar signal overlap across coins: 14 of 870 (0.016), max coins in one bar 2

- min-order skips at $100: 170 of 870
- min-order skips at $300: 40 of 870

Generator counters (summed over coins): cooldown 237522, entries 870, long_entries 551, no_oi_data 0, no_oi_recent 23, range_used 10799, short_entries 319, signals 4968, skip_busy 2338, skip_no_minute 0, skip_other 0, skip_regime 1461, skip_stop_high 161, skip_stop_low 0, skip_window 138

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 870; sized 870; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Sizing-ledger RP-gate inputs on the unlimited candidate list (sizing-ledger R = unit / (stop_dist + 0.0017), n 870, mean R 0.2243; seed 99, N 79, q 0.000633; a different R definition from the clause lines above, so these are not the clause S1-3 etc. and feed only the RP gate): gate mean R pass=True value=0.22427100853249418; gate date-block lower bound pass=False value=-0.17864753817955836; gate 2x-cost mean (R - 0.0015/stop_dist) pass=True value=0.18217458041262596; gate halves pass=True value=(0.18330661644692497, 0.26523540061806333); gate best-year share pass=True value=0.5822753817118017

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=60.31% top5-removed mean R=-0.3417), B: reference only (S1-5 pass=False MDD=64.14% top5-removed mean R=-0.3417), C: reference only (S1-5 pass=False MDD=60.57% top5-removed mean R=-0.3417)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 870 | 870 | 870 | 870 | 870 | 870 |
| Entered | 296 | 336 | 243 | 293 | 263 | 324 |
| Annual n (nearest int) | 52 | 58 | 42 | 51 | 46 | 56 |
| S1-0 tier | undecidable | conditional | undecidable | undecidable | undecidable | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | 0.2211 | 0.1829 | 0.2199 | 0.1623 | 0.2383 | 0.2021 |
| Average hold (min) | 8245.07 | 7252.22 | 8227.16 | 7113.08 | 8280.47 | 7260.93 |
| Closed by replacement | 0 | 63 | 0 | 67 | 0 | 70 |
| Mean R of replaced | n/a | -0.2410 | n/a | -0.2278 | n/a | -0.2298 |
| Replace attempts failed | none | no_loser 404, still_blocked 4 | none | no_loser 504 | none | no_loser 468, still_blocked 4 |
| Final wallet | 354.68 | 219.78 | 387.44 | 241.12 | 355.96 | 233.33 |
| Max concurrent | 3 | 3 | 1 | 1 | 3 | 3 |
| Max open loss (fraction of wallet) | 5.97% | 6.00% | 5.00% | 5.00% | 5.97% | 6.00% |
| FE-Z1 real-order MDD | 60.31% | 71.98% | 64.14% | 68.35% | 60.57% | 72.12% |
| FE-Z2 share reaching -25% (seed 88) | 82.90% | 86.07% | 91.06% | 91.73% | 82.59% | 85.80% |
| FE-Z2 n (annual) | 52 | 58 | 42 | 51 | 46 | 56 |
| FE-Z3 worst trade loss/wallet | 5.11% | 5.14% | 6.41% | 6.41% | 6.41% | 6.41% |
| First -25% touch vs initial (report only) | 2021-10-26 21:44:00 | 2021-10-26 21:44:00 | 2021-09-20 03:02:00 | 2021-09-20 03:02:00 | 2021-09-20 03:02:00 | 2021-09-20 03:02:00 |
| First -25% touch vs peak (report only) | 2021-10-26 21:44:00 | 2021-10-26 21:44:00 | 2021-09-20 03:02:00 | 2021-09-20 03:02:00 | 2021-09-20 03:02:00 | 2021-09-20 03:02:00 |
| Sized by margin cap / by loss | 229 / 67 | 249 / 87 | 7 / 236 | 7 / 286 | 154 / 109 | 189 / 135 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | below_min_notional 21, max_positions 3, open_loss_cap 486, stop_vs_liq 64 | below_min_notional 50, max_positions 1, open_loss_cap 407, qty_zero 12, stop_vs_liq 64 | below_min_notional 8, open_loss_cap 555, stop_vs_liq 64 | below_min_notional 9, open_loss_cap 504, stop_vs_liq 64 | below_min_notional 8, open_loss_cap 535, stop_vs_liq 64 | below_min_notional 10, open_loss_cap 472, stop_vs_liq 64 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H95 / new (aux), seed 99, N 79, bound 99.937% (q 0.000633), S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable)

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 0, months 0, win rate nan, mean R nan (0.30% cost nan), PF nan, MDD nan, final wallet x1.000

Candidate list (unlimited, R units): trades 0
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): undecidable (0 trades; mechanical, verdict is TA's)

Candidate list: 0 trades, average hold n/a h, annual n 0 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 0, months 0, win rate nan, mean R nan (0.30% cost nan), PF nan, MDD nan, final wallet x1.000

Limits book: trades 0
- S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): undecidable (0 trades; mechanical, verdict is TA's)
end_of_data trades: 0

Lock aux numbers: trades 0 (>= 100: False), mean R nan (> 0: False), mean R at 2x cost nan (> 0: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|

Coins with trades 0; with >= 10 trades 0; mean R > 0 among those 0.

Annual n (limits book): 0.00 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 0.00 per year.
By year (KST entry year): 

Long / short (candidate list): long 0, short 0, long share nan

Signals skipped by the live limits: 0 of 0 raw signals (mean unsized R of the skipped, descriptive only):

Same-4h-bar signal overlap across coins: 0 of 0 (nan), max coins in one bar 0

- min-order skips at $100: 0 of 0
- min-order skips at $300: 0 of 0

Generator counters (summed over coins): cooldown 0, entries 0, long_entries 0, no_oi_data 197, no_oi_recent 0, range_used 0, short_entries 0, signals 0, skip_busy 0, skip_no_minute 0, skip_other 0, skip_regime 0, skip_stop_high 0, skip_stop_low 0, skip_window 0

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

no candidate trades: nothing to size

