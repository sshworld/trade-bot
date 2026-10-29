# H67 screen result (1m intrabar; frame fe2) -- 2026-10-29 13:03 KST

Runner: branch h48-screen @ b540344b9c; runtime 633 s (whole session), peak RSS 1513 MB; locks: prereg-lock-h61-h71.md 91aca63a05f6, prereg-lock-fullentry-v2.md 539c7585353b, prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0, prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830, prereg-lock-replace-losers-v1.md 31619c1507f2, prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811, prereg-lock-h61-h71-addendum-newcoin.md 66047175f09a, answers-h48plus-questions-2026-10-29.md 841c34b8dd7f, answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee, prereg-lock-h67-h68-v1_1.md 9ddc7ba9403c, prereg-lock-h46-h47-v1_3.md ebb1c3678c93; rule hypotheses_h61_h71.md 6623cd2cc42d; rule v1.1 hypotheses_h67_h68_v1_1.md 29c61c0b8ef9; membership sha d5eb81db7c9d.

No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.
gap_all is off; 1m bars are used for fills and stops only.

Spec notes: H67/H68 v1.1 (lock 9ddc7ba9403c): H67 flush bar closes in the LOWER 40% of its range, H68 in the UPPER 40%; v1 (top/bottom 40%) is void and never run. OI parquet exists for the six coins only: the new-coin book is untestable (all coins skipped 'no OI data'); per the lock the six-coin book is reused for the new-coin condition.

Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer; the sizing module receives them with times as datetimes): sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, gross_unit, fee_unit, slip_unit, funding_unit, R. stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid); R = unit / (stop_dist + 0.0017).

## H67 / six (primary), seed 95, N 74, bound 99.932% (q 0.000676), min trades 300

Coin list (6 coins with data): BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 414; excluded for coverage/funding/warmup (member months): 4 of 414 = 0.0097

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 9, months 7, win rate 0.222, mean R -0.4135 (0.30% cost -0.5482), PF 0.456, MDD 0.094, final wallet x0.925

Candidate list (unlimited, R units): trades 9
- S1-0 trades / months: trades 9 >= 300 and months 7 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: -0.4135 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.9815 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.5482 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.2928, -0.9786, 4, 5) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.0941 (threshold meets; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.6894, 1) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.9803, 99.8% -0.9812, lock bound index 6

Candidate list: 9 trades, average hold 2.57 h, annual n 3 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 6: BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT

### Old-frame limits book (report only here)

trades 9, months 7, win rate 0.222, mean R -0.4135 (0.30% cost -0.5482), PF 0.456, MDD 0.094, final wallet x0.925

Limits book: trades 9
- S1-0 trades / months: trades 9 >= 300 and months 7 >= 12 (threshold does not meet; mechanical, verdict is TA's)
- S1-1 mean R: -0.4135 (threshold does not meet; mechanical, verdict is TA's)
- S1-2 date-block bootstrap lower bound: -0.9815 (threshold does not meet; mechanical, verdict is TA's)
- S1-3 mean R at 0.30% cost: -0.5482 (threshold does not meet; mechanical, verdict is TA's)
- S1-4 halves (first, second mean): (0.2928, -0.9786, 4, 5) (threshold does not meet; mechanical, verdict is TA's)
- S1-5 MDD (limits book) and top-5%-removed mean: 0.0941 (threshold meets; mechanical, verdict is TA's)
- S1-6 top-5% removed mean: (-0.6894, 1) (threshold does not meet; mechanical, verdict is TA's)
- S1-Y largest year share of profit: (nan, '2022') (threshold meets; mechanical, verdict is TA's)
- date-block bounds: 99% -0.9803, 99.8% -0.9812, lock bound index 6
end_of_data trades: 0

Lock aux numbers: trades 9 (>= 100: False), mean R -0.4135 (> 0: False), mean R at 2x cost -0.5482 (> 0: False)

- U1: coins with >= 10 trades 0, positive 0, share nan (need >= 0.667; does not meet)
- U2: best coin SOLUSDT share nan of total R -3.72 (need <= 0.35; does not meet)
- U3: mean R without SOLUSDT: -0.6494, n 7 (does not meet)
- U4: in H16 universe: trades 9, coins 5, mean R -0.4135; not in H16: trades 0, coins 0, mean R nan (not-H16 trades >= 100: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|
| SOLUSDT | 2 | 0.4123 | 0.82 |
| XRPUSDT | 3 | -0.2144 | -0.64 |
| BTCUSDT | 1 | -0.9768 | -0.98 |
| DOGEUSDT | 1 | -0.9809 | -0.98 |
| ETHUSDT | 2 | -0.9725 | -1.95 |

Coins with trades 5; with >= 10 trades 0; mean R > 0 among those 0.

Annual n (limits book): 1.57 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 1.57 per year.
By year (KST entry year): 2022: n 4 mean 0.293, 2023: n 1 mean -0.979, 2025: n 3 mean -0.982, 2026: n 1 mean -0.969

Average hold 2.57 h (median 1.65); realized cost 0.1347 R per trade; mean slippage on stops 0.0000 R (all trades 0.0000); mean funding paid per trade 0.00064 (return units); exit reasons {'stop': 7, 'target': 2}

Trades per month: 2022-09 1, 2022-11 3, 2023-06 1, 2025-05 1, 2025-11 1, 2025-12 1, 2026-04 1

H7-T entry overlap (limits book): same week any coin 0.111, same week same coin 0.000; same day any coin 0.000, same day same coin 0.000 (week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks)

Signals skipped by the live limits: 0 of 9 raw signals (mean unsized R of the skipped, descriptive only):

Same-4h-bar signal overlap across coins: 0 of 9 (0.000), max coins in one bar 1

- min-order skips at $100: 0 of 9
- min-order skips at $300: 0 of 9

Generator counters (summed over coins): entries 9, flush_bars 100, no_oi_data 0, signals 79, skip_busy 0, skip_no_minute 0, skip_other 0, skip_rr 61, skip_stop_range 2, skip_wide 0, skip_window 7

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

Candidates 9; sized 9; variants run: A, B, C.
Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C BTCUSDT 0.5, ETHUSDT 0.1, SOLUSDT 0.1, BNBUSDT 0.1, XRPUSDT 0.1, DOGEUSDT 0.1.

Candidate ledger columns passed to the sizing module: sym, side, entry_time, exit_time, entry_px, stop_dist, mae, unit, fee1, R (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).

Unlimited candidate-list R statistics (n 9, mean R -0.4135; seed 95, N 74, q 0.000676): S1-1 pass=False value=-0.41349694101409656; S1-2 pass=False value=-0.9815418456949964; S1-3 pass=False value=-0.5737815948158881; S1-4 pass=False value=(0.2928492138728271, -0.9785738649236354); S1-6 pass=True value=nan

RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): A: reference only (S1-5 pass=False MDD=5.05% top5-removed mean R=-0.6894), B: reference only (S1-5 pass=False MDD=12.66% top5-removed mean R=-0.6894), C: reference only (S1-5 pass=False MDD=5.47% top5-removed mean R=-0.6894)

|  | A_off | A_on | B_off | B_on | C_off | C_on |
|---|---|---|---|---|---|---|
| Signals sized | 9 | 9 | 9 | 9 | 9 | 9 |
| Entered | 9 | 9 | 8 | 8 | 9 | 9 |
| Annual n (nearest int) | 3 | 3 | 2 | 2 | 3 | 3 |
| S1-0 tier | undecidable | undecidable | undecidable | undecidable | undecidable | undecidable |
| Mean R (sizing, R = net / loss at stop incl. fee) | -0.4129 | -0.4129 | -0.6894 | -0.6894 | -0.4129 | -0.4129 |
| Average hold (min) | 154.33 | 154.33 | 135.88 | 135.88 | 154.33 | 154.33 |
| Closed by replacement | 0 | 0 | 0 | 0 | 0 | 0 |
| Mean R of replaced | n/a | n/a | n/a | n/a | n/a | n/a |
| Replace attempts failed | none | none | none | no_loser 1 | none | none |
| Final wallet | 114.95 | 114.95 | 102.62 | 102.62 | 111.07 | 111.07 |
| Max concurrent | 2 | 2 | 1 | 1 | 2 | 2 |
| Max open loss (fraction of wallet) | 3.17% | 3.17% | 3.41% | 3.41% | 4.27% | 4.27% |
| FE-Z1 real-order MDD | 5.05% | 5.05% | 12.66% | 12.66% | 5.47% | 5.47% |
| FE-Z2 share reaching -25% (seed 88) | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| FE-Z2 n (annual) | 3 | 3 | 2 | 2 | 3 | 3 |
| FE-Z3 worst trade loss/wallet | 1.26% | 1.26% | 3.15% | 3.15% | 4.17% | 4.17% |
| First -25% touch vs initial (report only) | n/a | n/a | n/a | n/a | n/a | n/a |
| First -25% touch vs peak (report only) | n/a | n/a | n/a | n/a | n/a | n/a |
| Sized by margin cap / by loss | 9 / 0 | 9 / 0 | 8 / 0 | 8 / 0 | 9 / 0 | 9 / 0 |
| Liquidated | 0 | 0 | 0 | 0 | 0 | 0 |
| Skips by reason | none | none | open_loss_cap 1 | open_loss_cap 1 | none | none |

Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.

## H67 / new (aux), seed 95, N 74, bound 99.932% (q 0.000676), min trades 100

Coin list (197 coins with data): 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

Coins in the universe skipped for NO DATA: 0
Universe coin-months 2251; excluded for coverage/funding/warmup (member months): 2 of 2251 = 0.0009

Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).

trades 0, months 0, win rate nan, mean R nan (0.30% cost nan), PF nan, MDD nan, final wallet x1.000

Candidate list (unlimited, R units): trades 0
- S1-0 trades / months: trades 0 >= 100 and months 0 >= 12 (threshold does not meet; mechanical, verdict is TA's)

Candidate list: 0 trades, average hold n/a h, annual n 0 (trades / (days first entry to last exit / 365.25), nearest integer); coins with data 197: 1000BONKUSDT, 1000FLOKIUSDT, 1000LUNCUSDT, 1000PEPEUSDT, 1000SATSUSDT, 1000SHIBUSDT, 1INCHUSDT, AAVEUSDT, ACEUSDT, ADAUSDT, AGIXUSDT, AKEUSDT, ALGOUSDT, ALICEUSDT, ALPHAUSDT, ANKRUSDT, APEUSDT, API3USDT, APTUSDT, ARBUSDT, ARCUSDT, ARPAUSDT, ARUSDT, ASTERUSDT, ATOMUSDT, AUCTIONUSDT, AUDIOUSDT, AVAXUSDT, AXSUSDT, BAKEUSDT, BANDUSDT, BANKUSDT, BATUSDT, BCHUSDT, BELUSDT, BERAUSDT, BIGTIMEUSDT, BIOUSDT, BLESSUSDT, BLURUSDT, BLZUSDT, BNXUSDT, BULLAUSDT, CAKEUSDT, CELRUSDT, CFXUSDT, CHRUSDT, CHZUSDT, CKBUSDT, COMPUSDT, COTIUSDT, CRVUSDT, CTKUSDT, CTSIUSDT, DASHUSDT, DENTUSDT, DEXEUSDT, DOTUSDT, DUSKUSDT, DYDXUSDT, EGLDUSDT, ENAUSDT, ENJUSDT, ENSUSDT, EOSUSDT, ESPORTSUSDT, ETCUSDT, ETHFIUSDT, EVAAUSDT, FARTCOINUSDT, FETUSDT, FHEUSDT, FILUSDT, FLMUSDT, FRONTUSDT, FTMUSDT, GALAUSDT, GMTUSDT, GRTUSDT, HBARUSDT, HEIUSDT, HIFIUSDT, HIGHUSDT, HNTUSDT, HOMEUSDT, HUSDT, HYPEUSDT, ICPUSDT, ICXUSDT, IDUSDT, IMXUSDT, INJUSDT, IOSTUSDT, IOTAUSDT, IPUSDT, JASMYUSDT, JELLYJELLYUSDT, JUPUSDT, KAVAUSDT, KLAYUSDT, KNCUSDT, KSMUSDT, LABUSDT, LDOUSDT, LINAUSDT, LINKUSDT, LITUSDT, LPTUSDT, LRCUSDT, LTCUSDT, LUNA2USDT, LUNAUSDT, MAGICUSDT, MANAUSDT, MASKUSDT, MATICUSDT, MINAUSDT, MKRUSDT, MOODENGUSDT, MTLUSDT, NEARUSDT, NEIROUSDT, NEOUSDT, NMRUSDT, OCEANUSDT, OGNUSDT, OMGUSDT, OMUSDT, ONDOUSDT, ONEUSDT, ONTUSDT, OPUSDT, ORDIUSDT, PENDLEUSDT, PENGUUSDT, PEOPLEUSDT, PIPPINUSDT, PIXELUSDT, PLAYUSDT, POPCATUSDT, PUMPUSDT, QTUMUSDT, REEFUSDT, RENUSDT, RLCUSDT, RNDRUSDT, RSRUSDT, RUNEUSDT, RVNUSDT, SANDUSDT, SEIUSDT, SFPUSDT, SIRENUSDT, SKYAIUSDT, SNXUSDT, SRMUSDT, STMXUSDT, STORJUSDT, STOUSDT, STRKUSDT, STXUSDT, SUIUSDT, SUSHIUSDT, SXPUSDT, SYNUSDT, TAOUSDT, THETAUSDT, TIAUSDT, TNSRUSDT, TOMOUSDT, TONUSDT, TRBUSDT, TRUMPUSDT, TRXUSDT, TUTUSDT, UBUSDT, UMAUSDT, UNFIUSDT, UNIUSDT, VELVETUSDT, VETUSDT, VIRTUALUSDT, VOXELUSDT, VVVUSDT, WAVESUSDT, WIFUSDT, WLDUSDT, XLMUSDT, XMRUSDT, XPLUSDT, XTZUSDT, YFIUSDT, YGGUSDT, ZECUSDT, ZENUSDT, ZILUSDT, ZRXUSDT

### Old-frame limits book (report only here)

trades 0, months 0, win rate nan, mean R nan (0.30% cost nan), PF nan, MDD nan, final wallet x1.000

Limits book: trades 0
- S1-0 trades / months: trades 0 >= 100 and months 0 >= 12 (threshold does not meet; mechanical, verdict is TA's)
end_of_data trades: 0

Lock aux numbers: trades 0 (>= 100: False), mean R nan (> 0: False), mean R at 2x cost nan (> 0: False)

### Per coin (top 15 by R-sum; all coins in per_coin csv)

| coin | trades | mean R | R-sum |
|---|---|---|---|

Coins with trades 0; with >= 10 trades 0; mean R > 0 among those 0.

Annual n (limits book): 0.00 trades per year over the 5.75-year entry window 2021-01..2026-09; unlimited candidate list: 0.00 per year.
By year (KST entry year): 

Signals skipped by the live limits: 0 of 0 raw signals (mean unsized R of the skipped, descriptive only):

Same-4h-bar signal overlap across coins: 0 of 0 (nan), max coins in one bar 0

- min-order skips at $100: 0 of 0
- min-order skips at $300: 0 of 0

Generator counters (summed over coins): entries 0, flush_bars 0, no_oi_data 197, signals 0, skip_busy 0, skip_no_minute 0, skip_other 0, skip_rr 0, skip_stop_range 0, skip_wide 0, skip_window 0

Trades open across a data hole window: 0

### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet 117.5; min stop 0.60%)

Inputs: exchangeinfo_sha256 008342ef31e5; brackets_sha256 1270358aab51; rules_new_coins research exchangeInfo (v8.EXI); sizing_module h34_paper/sizing_full.py (sizing-full 1f1c05e); ledger_cols ['sym', 'side', 'entry_time', 'exit_time', 'entry_px', 'stop_dist', 'mae', 'unit', 'fee1', 'gross_unit', 'fee_unit', 'slip_unit', 'funding_unit', 'R']

no candidate trades: nothing to size

