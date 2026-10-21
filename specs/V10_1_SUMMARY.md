# v10.1 results: H25-T, H25-M, H26-T, H26-M (one run, separate books vs a no-trade (0) baseline)

**Lock:** `/workspace/specs/prereg-lock-v10_1-h25-h26.md` sha256 `c5fc042fee2b0877e7ef093019cd3a532f86611d77150f6ad637f694baf13f84`, committed on repo `/workspace/trade-bot` branch `specs` as **commit `48fbc19`** (48fbc19b17b4dfe980e651cc48413e8d10c57a61). Verified: `git show 48fbc19:specs/prereg-lock-v10_1-h25-h26.md | sha256sum` = c5fc042f…3f84. Backup copy in `/home/box/agent-data/backup-ta-specs/` has the same sha.
**Backtest code (separate from the lock commit):** local git repo `/workspace/quant`, **commit `3ee8991`** (`v10_1/run_v10_1.py`). Pre-run commit `168262e` crashed (see "Rerun note").

## Pre-PnL fixed items (lock §5 / §8 / Appendix A), recorded before any PnL
1. H26 alt branch: **from 2021-12-01** (Appendix A.1: the 70 monthly files are present and checksums pass, but 2021-07 coverage is 83.87% < 99%). The first alt settlement, 2021-12-01 00:00, falls under the < 90% premium-coverage skip. BTC is from 2021-01-01.
2. Market data manifest `/workspace/trade-bot-research/data/v5/v10_1_market_manifest.sha256` sha256 `dd09ac6681d12dcbae8862c7dbe34d52c5fc82ac004daff4d95383b49e71a4d4`, 1,305 rows. **All 1,305 file hashes were re-verified by the script before loading.** Data was read directly from those zips: 1m klines, fundingRate, monthly 1m premiumIndexKlines. No parquet files, no daily premium zips, nothing outside the list.
3. `macro_events.csv` sha256 `803f9d586c6f78d887c2d60d87def172c6aa44a56453ba5d61790c0ffcdf1cf5` (verified).
4. H7-T replay 0d82b19: 355/355 ($100), 405/405 ($300) per Appendix A.4. C4-c uses `results/h7t/equity_H7T_100.csv` `18fad39c…313585` and `equity_H7T_300.csv` `7b87d7aa…897bd3` (both verified; identical to `results/h7t_replay_0d82b19/`).
5. Rule files verified: `hypotheses_h25.md` `8fbe123f…`, `hypotheses_h26.md` `8c39e4dc…`.
- Tick / step / min notional: `results/v3_live_v1/extra/exchangeInfo_snapshot.json` sha256 `e88d978c900169b9624abbace88a33006cadd2353fac8822513533e4625feb34`, used for the whole period (lock §7.10). This is not a data.binance.vision zip, so it is not in the manifest (the manifest SUMMARY notes this). Min notional: BTC $100 (team floor), ETH $20, others $5.

## Rerun note (lock §8)
Run 1 (code `168262e`) crashed in the C4-c function, before `v10_1_result.json` or any summary was written: `h.eq` resolved to the pandas DataFrame method instead of the column. Fix in `3ee8991`: `h['eq']`. No rule, parameter or data change. Run 1 had only written signals and H25-T $100 trade/order CSVs, which were moved unread to `results/v10_1_aborted_run1/`. They are byte-identical to run 2 (sha prefixes c02ed438, ba7d70a2, 8c4cbce9, 610474ce). Run 2 is the run of record.

## Signals
- H25: {'coin_events': 1092, 'gap': 2, 'no_trigger': 596}, giving **494 triggers** (same as the pre-lock count).
- H26: **1,727 signals** (SHORT/LONG): BTC 145/83, ETH 67/109, BNB 72/291, SOL 99/258, XRP 88/224, DOGE 113/178. Skips: BTC cov<90% 25, non-8h 0, ETH cov<90% 11, non-8h 0, BNB cov<90% 11, non-8h 0, SOL cov<90% 8, non-8h 27, XRP cov<90% 8, non-8h 0, DOGE cov<90% 11, non-8h 0.
  - The pre-lock count was 1,696. The +31 are all SOL LONG (258 vs 227). Lock §7.2 judges the 8h interval from the last two settlements before D, while the count script used the interval field at T. Rule as locked.
- H26 F̂ vs settled funding (all evaluated settlements, n=32671): sign agreement 0.844. Given an F̂ signal, the settled rate gives the same signal 0.708 of the time (F̂ signals 1727, actual-rate signals 1530).

## Criteria (lock §6), computed as defined; verdict by TA
C1 p = one-sided cluster bootstrap (10,000, seed 20261021) of mean trade r = net/K_entry. Holm runs per balance with m = 4. INCONCLUSIVE variants enter with p = 1 (none were inconclusive).

| variant | bal | trades | clusters | sample ≥200 & ≥100 | net USD | mean r | C1 p raw | Holm thr / reject | C2 front / back net | C3 PF / 2×cost / ex-best1 / ex-top5 | C4a MDD | C4b P(−15%) (report) | C4c daily MDD comb vs H7-T | C4c P15 comb vs H7-T+1pp |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H25-T | $100 | 293 | 110 | yes | -30.36 | -0.00119 | 0.9877 | 0.0167 / no | -6.59 / -23.77 | 0.689 / 0.367 / 0.680 / 0.647 | 35.4% | 1.0000 | 23.3% vs 20.6% | 0.1690 vs 0.0698 |
| H25-T | $300 | 296 | 111 | yes | -87.52 | -0.00112 | 0.9840 | 0.0167 / no | -20.97 / -66.55 | 0.701 / 0.365 / 0.692 / 0.659 | 34.2% | 1.0000 | 23.8% vs 19.9% | 0.1736 vs 0.0761 |
| H25-M | $100 | 275 | 109 | yes | -10.98 | -0.00037 | 0.7377 | 0.0125 / no | -1.27 / -9.71 | 0.892 / 0.690 / 0.883 / 0.847 | 23.2% | 0.4955 | 20.0% vs 20.6% | 0.1191 vs 0.0698 |
| H25-M | $300 | 278 | 109 | yes | -31.32 | -0.00034 | 0.7147 | 0.0125 / no | -4.93 / -26.39 | 0.898 / 0.692 / 0.889 / 0.853 | 21.9% | 0.4739 | 20.0% vs 19.9% | 0.1298 vs 0.0761 |
| H26-T | $100 | 1372 | 989 | yes | -93.55 | -0.00197 | 1.0000 | 0.0250 / no | -75.36 / -18.20 | 0.510 / 0.266 / 0.506 / 0.494 | 93.6% | 1.0000 | 82.9% vs 20.6% | 0.7245 vs 0.0698 |
| H26-T | $300 | 1503 | 1073 | yes | -282.65 | -0.00186 | 1.0000 | 0.0250 / no | -229.82 / -52.83 | 0.531 / 0.284 / 0.527 / 0.513 | 94.3% | 1.0000 | 83.1% vs 19.9% | 0.7347 vs 0.0761 |
| H26-M | $100 | 1361 | 972 | yes | -84.74 | -0.00134 | 1.0000 | 0.0500 / no | -66.75 / -17.99 | 0.641 / 0.479 / 0.637 / 0.625 | 84.8% | 1.0000 | 64.1% vs 20.6% | 0.5659 vs 0.0698 |
| H26-M | $300 | 1456 | 1044 | yes | -256.67 | -0.00129 | 1.0000 | 0.0500 / no | -199.75 / -56.91 | 0.657 / 0.494 / 0.654 / 0.641 | 85.9% | 1.0000 | 64.4% vs 19.9% | 0.5744 vs 0.0761 |

Thresholds as locked: C2 both halves > 0. C3 PF ≥ 1.3, 2×cost ≥ 1.1, ex-best1 ≥ 1.1, ex-top5 ≥ 1.0. C4a < 25%. C4c comb MDD ≤ H7-T MDD **and** comb P15 ≤ H7-T P15 + 1pp (H7-T P15: $100 0.0598, $300 0.0661, using `p_touch_from_start` copied verbatim from research/v3_report.py). C4c daily series: UTC day-end, 2021-01-01..2026-09-30, 2,099 days.

## Required outputs (report only)
| variant | bal | start → end | gross / fees / slip / funding USD | win rate | exits TP/SL/time | SL dist % p5/25/50/75/95 (TP identical, 1:1) | 5x bound | skipped: floor / min-notional / 2.5%-cap / margin | downsized: cap / margin | worst day KST | days ≥+1% / ≥+2% (KST) | trades/day mean, max | −25% touched |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H25-T | $100 | 100 → 69.64 | 16.57 / 30.57 / 16.35 / 0.00 | 54.9% | 160/130/3 | 0.252 / 0.412 / 0.576 / 0.79 / 1.621 | 0.0% | 1.2 / 7.5 / 27.3 / 4.7% | 17.4 / 2.2% | 2022-03-10 -2.502% | 30 / 2 of 114 | 2.57, 4 | yes, first (realized) 2024-06-12 |
| H25-T | $300 | 300 → 212.48 | 58.64 / 95.40 / 50.76 / 0.00 | 56.1% | 165/127/4 | 0.254 / 0.397 / 0.548 / 0.747 / 1.434 | 0.0% | 1.2 / 0.0 / 34.0 / 4.9% | 17.6 / 2.4% | 2022-07-08 -2.503% | 32 / 3 of 114 | 2.6, 4 | yes, first (realized) 2024-06-12 |
| H25-M | $100 | 100 → 89.02 | 15.49 / 18.56 / 7.91 / 0.00 | 53.5% | 146/126/3 | 0.256 / 0.413 / 0.557 / 0.77 / 1.62 | 0.0% | 1.2 / 4.7 / 27.3 / 7.7% | 16.6 / 3.4% | 2024-02-13 -2.503% | 35 / 6 of 111 | 2.48, 4 | no |
| H25-M | $300 | 300 → 268.68 | 49.89 / 56.98 / 24.23 / 0.00 | 54.7% | 151/123/4 | 0.256 / 0.413 / 0.547 / 0.746 / 1.433 | 0.0% | 1.2 / 0.0 / 31.2 / 8.3% | 17.0 / 3.6% | 2022-07-08 -2.502% | 38 / 8 of 111 | 2.5, 4 | no |
| H26-T | $100 | 100 → 6.45 | -8.75 / 55.92 / 28.88 / 0.00 | 45.5% | 512/514/346 | 0.263 / 0.403 / 0.575 / 0.908 / 1.809 | 0.0% | 2.0 / 13.6 / 4.8 / 0.1% | 6.0 / 0.1% | 2024-01-02 -6.816% | 44 / 4 of 607 | 2.26, 9 | yes, first (realized) 2022-01-25 |
| H26-T | $300 | 300 → 17.35 | -18.98 / 174.06 / 89.61 / 0.00 | 45.7% | 564/550/389 | 0.262 / 0.41 / 0.594 / 0.922 / 1.812 | 0.0% | 2.0 / 4.8 / 5.9 / 0.3% | 7.6 / 0.3% | 2024-01-02 -7.304% | 55 / 5 of 651 | 2.31, 9 | yes, first (realized) 2022-01-14 |
| H26-M | $100 | 100 → 15.26 | -21.74 / 44.31 / 18.69 / 0.00 | 45.4% | 485/517/359 | 0.263 / 0.41 / 0.58 / 0.911 / 1.817 | 0.0% | 2.0 / 10.7 / 4.7 / 0.5% | 6.8 / 0.9% | 2024-01-02 -6.639% | 61 / 12 of 594 | 2.29, 9 | yes, first (realized) 2022-02-22 |
| H26-M | $300 | 300 → 43.33 | -57.49 / 140.45 / 58.72 / 0.00 | 45.5% | 517/548/391 | 0.263 / 0.408 / 0.593 / 0.932 / 1.808 | 0.0% | 2.0 / 2.6 / 5.2 / 2.7% | 7.4 / 1.6% | 2024-01-02 -6.86% | 67 / 15 of 633 | 2.3, 9 | yes, first (realized) 2022-01-20 |

Skip and downsize shares are % of signals. Settlement crossings: 0 in every variant, so funding = 0 by construction.

**-M fills (1m OHLC trade-through rule)**
- H25-M $100: orders 292, filled 275 (**fill rate 94.2%**), unfilled 17. Mean signal-direction move from P to the time-exit open: filled 0.0326% gross (to exit), unfilled 0.2427%. Mean r per signal (unfilled = 0): -0.00021 (same sign as per fill).
- H25-M $300: orders 293, filled 278 (**fill rate 94.9%**), unfilled 15. Mean signal-direction move from P to the time-exit open: filled 0.0459% gross (to exit), unfilled 0.1242%. Mean r per signal (unfilled = 0): -0.00019 (same sign as per fill).
- H26-M $100: orders 1417, filled 1361 (**fill rate 96.0%**), unfilled 56. Mean signal-direction move from P to the time-exit open: filled -0.0342% gross (to exit), unfilled 0.644%. Mean r per signal (unfilled = 0): -0.00106 (same sign as per fill).
- H26-M $300: orders 1511, filled 1456 (**fill rate 96.4%**), unfilled 55. Mean signal-direction move from P to the time-exit open: filled -0.0246% gross (to exit), unfilled 0.5749%. Mean r per signal (unfilled = 0): -0.00109 (same sign as per fill).
- Partial fills: not observable in the 1m-OHLC backtest (lock §4: trade-through = full fill, touch = no fill). They are reported in paper trading only.

**By coin / side / type / year** (n, net USD, PF): see `v10_1_result.json` → `variants.<tag>.by_coin|by_side|by_type|by_year`.

## Notes on implementation (as locked, no interpretation added)
- ATR14(15m): simple mean of the true range over 14 closed 15m bars. A bar is valid only if all 15 minutes exist; any invalid bar → skip. TR uses the close of the immediately preceding 15m bar (H−L if it is missing). H25 trigger ATR ends at t; the unit ends at t+15m. H26 unit ends at T−60m.
- Sizing per lock §2 / §7.5–7.6: N = min(0.01K/(d+c_loss), 5K). 2.5% open-risk and margin (ΣN/5 ≤ K) caps are processed in BTC, ETH, BNB, SOL, XRP, DOGE order, with downsizing only if the result is ≥ min notional. qty is floored to stepSize. K = start + realized PnL. -M reservations are taken at order time.
- -T: fill = 1m open ± 1 tick, plus 2bp slippage cost. SL fill = stop, or the gapped open (gap rule not applied in the entry minute). TP_MARKET fill = TP. Same-minute SL+TP = SL. Checks start in the entry minute.
- -M: limit at the signal price P, trade-through by ≥ 1 tick within the valid minutes of §7.3. In the fill minute only SL is checked. TP is a resting limit with the trade-through rule from the next minute. If unfilled at the time exit → market exit.
- Time exit: H25 at the open of the t+135m minute. H26 at the open of the T−2m minute. SL/TP prices are rounded to tick.
- MDD C4a: equity marked each minute at the adverse extreme of open positions (entry costs included), realized at exits. C4b: cluster-order shuffle, compounding trade r, 10,000 paths, seed 20261021.
- No daily loss limit and no −25% halt simulated (lock §7.7–7.8). Touch dates are reported above.

## Files
`/workspace/quant/results/v10_1/`: `v10_1_result.json`, `trades_<variant>_<bal>.csv` (8), `orders_<variant>_<bal>.csv` (8), `signals_H25.csv`, `signals_H26.csv`, `../v10_1_run.log`. Scripts: `/workspace/quant/v10_1/run_v10_1.py` (commit 3ee8991) and `write_summary.py`.
