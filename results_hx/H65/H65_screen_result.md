# H65 screen result (1m intrabar; frame fe2) -- 2026-10-29 12:22 KST

Runner: branch h48-screen @ 714a1e3488; runtime 665 s (whole session), peak RSS 1433 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H65 / six (primary), seed 93, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 173, months 55, win rate 0.272, mean R -0.3194 (0.30% cost -0.4410), PF 0.549, MDD 0.697, final wallet x0.314

Candidate list (unlimited, R units): trades 173
- S1-0 trades / months: trades 173 >= 300 and months 55 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: -0.3194 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.6031 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.441 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.1856, -0.4516, 86, 87) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.6975 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4816, 9) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2024') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.5277, 99.8% -0.5722, lock bound index 6

Candidate list: 173 trades, average hold 13.03 h, annual n 32 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 173, months 55, win rate 0.272, mean R -0.3194 (0.30% cost -0.4410), PF 0.549, MDD 0.697, final wallet x0.314

Limits book: trades 173
- S1-0 trades / months: trades 173 >= 300 and months 55 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: -0.3194 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.6031 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.441 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.1856, -0.4516, 86, 87) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.6975 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.4816, 9) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2024') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.5277, 99.8% -0.5722, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 173 (>= 100: True), mean R -0.3194 (> 0: False), mean R at 2x cost -0.4410 (> 0: False)

- U1: coins with >= 10 trades 6, positive 0, share 0.000 (need >= 0.667; does not meet)
- U2: best coin SOLUSDT share nan of total R -55.25 (need <= 0.35; does not meet)
- U3: mean R without SOLUSDT: -0.3301, n 161 (does not meet)
- U4: in H16 universe: trades 173, coins 6, mean R -0.3194; not in H16: trades 0, coins 0, mean R nan (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| SOLUSDT | 12 | -0.1755 | -2.11 |
| ETHUSDT | 26 | -0.1427 | -3.71 |
| BNBUSDT | 45 | -0.1449 | -6.52 |
| DOGEUSDT | 11 | -0.6077 | -6.69 |
| BTCUSDT | 45 | -0.2990 | -13.46 |
| XRPUSDT | 34 | -0.6698 | -22.77 |

Coins with trades 6; with >= 10 trades 6; mean R > 0 among those 0.

Annual n (limits book): 30.09 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 30.09 per year.
By year (KST entry year): 2021: n 5 mean -0.023, 2022: n 25 mean -0.364, 2023: n 32 mean -0.324, 2024: n 42 mean 0.028, 2025: n 37 mean -0.578, 2026: n 32 mean -0.484

Average hold 13.03 h (median 6.77); realized cost 0.1216 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00006 (return units); exit reasons {'stop': 124, 'target': 34, 'time': 15}

Trades per month: 2021-04 1, 2021-07 1, 2021-09 1, 2021-12 2, 2022-01 4, 2022-02 2, 2022-04 1, 2022-05 1, 2022-08 2, 2022-09 2, 2022-10 9, 2022-11 1, 2022-12 3, 2023-01 1, 2023-02 7, 2023-03 2, 2023-04 2, 2023-05 6, 2023-06 1, 2023-07 1, 2023-08 3, 2023-09 2, 2023-10 3, 2023-11 2, 2023-12 2, 2024-01 7, 2024-02 2, 2024-04 2, 2024-05 5, 2024-06 4, 2024-07 4, 2024-08 4, 2024-09 3, 2024-10 5, 2024-11 5, 2024-12 1, 2025-01 4, 2025-02 2, 2025-03 2, 2025-04 1, 2025-05 5, 2025-06 3, 2025-08 5, 2025-09 4, 2025-10 6, 2025-12 5, 2026-01 6, 2026-02 3, 2026-03 3, 2026-04 5, 2026-05 3, 2026-06 3, 2026-07 5, 2026-08 1, 2026-09 3

H7-T entry overlap (limits book): same week any coin 0.451, same week same coin 0.110; same day any coin 0.046, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 0 of 173 raw signals (mean unsized R of the skipped, descriptive only):

Same-4h-bar signal overlap across coins: 10 of 173 (0.058), max coins in one bar 2

- min-order skips at $100: 10 of 173
- min-order skips at $300: 0 of 173

Generator counters (summed over coins): attempts 573, entries 173, ranges 277, signals 277, skip_busy 0, skip_no_minute 0, skip_other 0, skip_rr 20, skip_stop_range 70, skip_wide 0, skip_window 14

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 173; sized 173; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 173, mean R -0.3194; seed 93, N 74, q 0.000676): S1-1 pass=False value=-0.3193667538594927; S1-2 pass=False value=-0.6031251210895064; S1-3 pass=False value=-0.46226645726005205; S1-4 pass=False value=(-0.18563448419706702, -0.4515618709970629); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=47.99% top5-removed mean R=-0.4816), B: reference only (S1-5 pass=False MDD=82.41% top5-removed mean R=-0.4816), C: reference only (S1-5 pass=False MDD=70.53% top5-removed mean R=-0.4816)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 173 | 173 | 173 | 173 | 173 | 173 |
| Entered | 159 | 159 | 155 | 156 | 171 | 171 |
| Annual n (nearest int) | 29 | 29 | 29 | 29 | 32 | 32 |
| S1-0 tier | undecidable | undecidable | undecidable | undecidable | undecidable | undecidable |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.3044 | -0.3044 | -0.3199 | -0.3180 | -0.3317 | -0.3317 |
| Average hold (min) | 768.39 | 768.39 | 749.70 | 751.13 | 766.85 | 766.85 |
| Closed by replacement | 0 | 0 | 0 | 2 | 0 | 0 |
| Mean R of replaced | n/a | n/a | n/a | -0.5144 | n/a | n/a |
| Replace attempts failed | none | none | none | no_loser 5 | none | no_loser 2 |
| Final wallet | 64.77 | 64.77 | 24.11 | 23.83 | 37.32 | 37.32 |
| Max concurrent | 3 | 3 | 2 | 2 | 2 | 2 |
| Max open loss (fraction of wallet) | 4.20% | 4.20% | 5.45% | 5.56% | 5.70% | 5.70% |
| FE-Z1 real-order MDD | 47.99% | 47.99% | 82.41% | 82.61% | 70.53% | 70.53% |
| FE-Z2 share reaching -25% (seed 88) | 0.86% | 0.86% | 73.54% | 73.48% | 48.10% | 48.10% |
| FE-Z2 n (annual) | 29 | 29 | 29 | 29 | 32 | 32 |
| FE-Z3 worst trade loss/wallet | 2.07% | 2.07% | 4.98% | 4.92% | 4.95% | 4.95% |
| First -25% touch vs initial (report only) | 2024-01-31 14:05:00 | 2024-01-31 14:05:00 | 2022-08-10 02:33:00 | 2022-08-10 02:33:00 | 2023-05-11 17:18:00 | 2023-05-11 17:18:00 |
| First -25% touch vs peak (report only) | 2023-09-25 00:22:00 | 2023-09-25 00:22:00 | 2022-04-11 02:46:00 | 2022-04-11 02:46:00 | 2022-12-07 07:13:00 | 2022-12-07 07:13:00 |
| Sized by margin cap / by loss | 159 / 0 | 159 / 0 | 148 / 7 | 149 / 7 | 137 / 34 | 137 / 34 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | qty_zero 14 | qty_zero 14 | open_loss_cap 7, qty_zero 11 | open_loss_cap 5, qty_zero 12 | open_loss_cap 2 | open_loss_cap 2 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H65 / new (aux), seed 93, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 384, months 52, win rate 0.318, mean R -0.0782 (0.30% cost -0.2002), PF 0.881, MDD 0.618, final wallet x0.431

Candidate list (unlimited, R units): trades 384
- S1-0 trades / months: trades 384 >= 100 and months 52 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.0782 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3696 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2002 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.0768, -0.0796, 192, 192) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.6178 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.2578, 20) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2023') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.2866, 99.8% -0.3317, lock bound index 6

Candidate list: 384 trades, average hold 12.59 h, annual n 70 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 349, months 52, win rate 0.301, mean R -0.1375 (0.30% cost -0.2596), PF 0.796, MDD 0.722, final wallet x0.320

Limits book: trades 349
- S1-0 trades / months: trades 349 >= 100 and months 52 >= 12 (threshold meets; mechanical, verdict is TA's)
- S1-1 mean R: -0.1375 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.3934 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.2596 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (-0.16, -0.1151, 174, 175) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.7216 (threshold does not meet; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.3144, 18) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2024') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.3291, 99.8% -0.3688, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 349 (>= 100: True), mean R -0.1375 (> 0: False), mean R at 2x cost -0.2596 (> 0: False)

- U1: coins with >= 10 trades 9, positive 2, share 0.222 (need >= 0.667; does not meet)
- U2: best coin LTCUSDT share nan of total R -47.99 (need <= 0.35; does not meet)
- U3: mean R without LTCUSDT: -0.1927, n 322 (does not meet)
- U4: in H16 universe: trades 90, coins 20, mean R -0.1930; not in H16: trades 259, coins 66, mean R -0.1182 (not-H16 trades >= 100: True)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| LTCUSDT | 27 | 0.5211 | 14.07 |
| FTMUSDT | 4 | 1.9899 | 7.96 |
| 1000BONKUSDT | 3 | 2.3913 | 7.17 |
| MASKUSDT | 4 | 1.7561 | 7.02 |
| AVAXUSDT | 9 | 0.6796 | 6.12 |
| NEARUSDT | 7 | 0.8444 | 5.91 |
| MANAUSDT | 6 | 0.6510 | 3.91 |
| ARBUSDT | 2 | 1.7725 | 3.54 |
| HBARUSDT | 1 | 3.2036 | 3.20 |
| AXSUSDT | 3 | 1.0367 | 3.11 |
| WIFUSDT | 1 | 2.2256 | 2.23 |
| OCEANUSDT | 1 | 2.0989 | 2.10 |
| EGLDUSDT | 1 | 1.9915 | 1.99 |
| BELUSDT | 1 | 1.9208 | 1.92 |
| KAVAUSDT | 2 | 0.7063 | 1.41 |

Coins with trades 69; with >= 10 trades 9; mean R > 0 among those 2.

Annual n (limits book): 60.70 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 66.78 per year.
By year (KST entry year): 2021: n 8 mean -0.995, 2022: n 53 mean -0.348, 2023: n 103 mean -0.086, 2024: n 62 mean 0.129, 2025: n 55 mean -0.464, 2026: n 68 mean 0.071

Average hold 12.55 h (median 6.92); realized cost 0.1221 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade -0.00003 (return units); exit reasons {'stop': 238, 'target': 90, 'time': 21}

Trades per month: 2021-03 1, 2021-07 2, 2021-09 1, 2021-10 2, 2021-12 2, 2022-01 4, 2022-06 1, 2022-07 1, 2022-08 3, 2022-09 6, 2022-10 13, 2022-11 5, 2022-12 20, 2023-01 1, 2023-02 4, 2023-03 5, 2023-04 10, 2023-05 19, 2023-06 7, 2023-07 11, 2023-08 19, 2023-09 10, 2023-10 5, 2023-11 7, 2023-12 6, 2024-01 6, 2024-02 9, 2024-04 2, 2024-05 11, 2024-06 10, 2024-07 4, 2024-08 4, 2024-09 5, 2024-10 10, 2025-02 1, 2025-03 2, 2025-04 1, 2025-05 5, 2025-06 6, 2025-07 4, 2025-09 12, 2025-10 9, 2025-11 7, 2025-12 10, 2026-01 8, 2026-02 3, 2026-03 5, 2026-04 14, 2026-05 2, 2026-06 6, 2026-07 8, 2026-08 14, 2026-09 6

H7-T entry overlap (limits book): same week any coin 0.424, same week same coin 0.000; same day any coin 0.069, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 35 of 384 raw signals (mean unsized R of the skipped, descriptive only):
- daily_loss_cap: 26 (mean R 0.4582)
- max_concurrent: 9 (mean R 0.6739)

Same-4h-bar signal overlap across coins: 85 of 384 (0.221), max coins in one bar 5

- min-order skips at $100: 0 of 384
- min-order skips at $300: 0 of 384

Generator counters (summed over coins): attempts 5195, entries 384, ranges 2409, signals 2409, skip_busy 4, skip_no_minute 562, skip_other 0, skip_rr 23, skip_stop_range 125, skip_wide 0, skip_window 1311

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 384; sized 361; variants run: A, B.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.
variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.
Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: 23 trades in 4 coins (EOSUSDT 10, HNTUSDT 1, MATICUSDT 11, RNDRUSDT 1).

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 384, mean R -0.0782; seed 93, N 74, q 0.000676): S1-1 pass=False value=-0.07816278126481248; S1-2 pass=False value=-0.36956278628402217; S1-3 pass=False value=-0.2218809471477541; S1-4 pass=False value=(-0.07675382703445731, -0.07957173549516765); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=38.77% top5-removed mean R=-0.2578), B: reference only (S1-5 pass=False MDD=82.00% top5-removed mean R=-0.2578)

|  | A_off | A_on | B_off | B_on |
|---|---|---|---|---|
| Signals sized | 361 | 361 | 361 | 361 |
| Entered | 349 | 350 | 295 | 302 |
| Annual n (nearest int) | 64 | 64 | 54 | 55 |
| S1-0 tier | conditional | conditional | undecidable | conditional |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.0953 | -0.0875 | -0.1415 | -0.1341 |
| Average hold (min) | 745.93 | 742.01 | 707.09 | 704.75 |
| Closed by replacement | 0 | 1 | 0 | 6 |
| Mean R of replaced | n/a | -0.3999 | n/a | -0.4330 |
| Replace attempts failed | none | no_loser 9 | none | no_loser 55, still_blocked 2 |
| Final wallet | 73.65 | 75.65 | 22.03 | 23.66 |
| Max concurrent | 3 | 3 | 2 | 2 |
| Max open loss (fraction of wallet) | 5.45% | 5.45% | 5.99% | 6.00% |
| FE-Z1 real-order MDD | 38.77% | 37.22% | 82.00% | 80.62% |
| FE-Z2 share reaching -25% (seed 88) | 17.06% | 16.29% | 84.95% | 84.29% |
| FE-Z2 n (annual) | 64 | 64 | 54 | 55 |
| FE-Z3 worst trade loss/wallet | 10.07% | 10.07% | 25.19% | 25.19% |
| First -25% touch vs initial (report only) | 2022-12-30 07:24:00 | 2022-12-30 07:24:00 | 2022-10-21 08:35:00 | 2022-10-21 08:35:00 |
| First -25% touch vs peak (report only) | 2022-12-30 07:24:00 | 2022-12-30 07:24:00 | 2022-10-21 08:35:00 | 2022-10-21 08:35:00 |
| Sized by margin cap / by loss | 349 / 0 | 350 / 0 | 279 / 16 | 286 / 16 |
| Liquidated | 1 | 1 | 1 | 1 |
| Skips by reason | bracket 2, max_positions 10 | bracket 2, max_positions 9 | bracket 2, open_loss_cap 64 | bracket 2, open_loss_cap 57 |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

