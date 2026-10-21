# Quant hypothesis H26 v1 rev2: funding-settlement flow, fade the crowded side before settlement, both directions (DRAFT for TA pre-registration, v10)

v10.1 re-creation 2026-10-21 after box /workspace loss; rules unchanged from rev2 (old sha e15736c4… / b20d11f6…)

rev2 2026-10-21: Q-1 resolved by PM, clamp removed, ATR-scaled SL/TP. TA answers folded in: Q-1, Q-2 (2.5% cap), Q-3 (separate book), min sample, multiple-testing family, alt premium-data rule. Pre-lock draft revision, made before any run.

Status: draft. No backtest has been run and no H26 returns have been computed. The only computations were **signal counts, SL-distance distribution, skip/cap shares and data coverage** (`/workspace/quant/v10_counts/count_v10.py`, `h26_d.py`, `rev2_counts.py`; `counts.json`, `rev2_counts.json`, `h26_settlement_rows.csv`). TA owns pass criteria (verdict = net PnL after all costs + existing C1–C4) in the TA criteria document. That includes the multiple-testing adjustment: H25-T/M + H26-T/M are **one family**. One run, no tuning; any change = new version.

**Data-informed flag and prior: LOW.** Two close relatives have already failed on this box:
- **v3 H1 "funding extreme fade"** (`specs/trade-bot-strategy-spec-v3.md`): previous funding in the top/bottom 5% of the coin's 90-day distribution, plus a ≥ 3% 24h move, entered at the next 1h open, SL/TP 1.5×ATR14(1h), 24h time stop. 2,631 trades, **PF 0.88 → FAIL** (per coin 0.80–1.02).
- **v5 E2a "settlement flow"** (`results/v5/phase1.md`): 60 min before / after each 00/08/16 settlement, conditioned only on the **sign** of predicted funding. 33,027 events, pre-settlement **+1.4bp** gross in the hypothesised direction (t 2.06, not significant after Bonferroni), post-settlement +0.4bp. Both are far below the 14bp taker round trip → FAIL.
H26 was written after seeing both. It bets that the small pre-settlement effect seen in E2a concentrates at **funding extremes**, which E2a did not isolate.

How H26 differs: from v3 H1, it is anchored to the settlement clock, uses the **predicted upcoming** rate rather than the last settled one, has no 3%-move condition, holds ≤ 58 min instead of 24h, and uses 1.0×ATR14(15m) SL/TP instead of 1.5×ATR14(1h). From v5 E2a, it trades only extremes (percentile plus an absolute floor), is a full trading rule with SL/TP, and has two execution variants. Not related to v8: H7-T's funding filter only blocks longs when funding is crowded and is not a timing rule.

## 1. Universe, data, period
- 6 coins (BTC ETH BNB SOL XRP DOGE USDT-M perps). Period 2021-01-01 to before 2026-10-01 UTC.
- Settlements T ∈ {00:00, 08:00, 16:00 UTC}. Only settlements where the coin's funding interval was 8h. SOL's 2h/4h-interval periods (101 settlements) are excluded.
- Data on the box: 1m klines `data/parquet/v7_six_1m.parquet` (2020→2026-09, all 6 coins); settled funding `data/parquet/v7_um_funding.parquet` (8h, all 6, complete); 1m premium index `data/v5/parquet/{SYM}_prem1m.parquet` (**BTC from 2020-09, the other five only from 2021-12-01** on the box now; see the pre-stated period rule below and §10).
- **Pre-stated period rule for the five alts (TA):** if the Developer's download of 1m premiumIndexKlines from 2020-10 succeeds before lock, the alts use it and are evaluable from 2021-01-01. "Succeeds" means every monthly file for 2020-10..2021-11 for ETH/BNB/SOL/XRP/DOGE is present, checksums are verified, and minute coverage is ≥ 99%. Otherwise the alts are locked from 2021-12-01. BTC is from 2021-01-01 either way. The lock records which branch applies; the choice is not revisited after any run.

## 2. Signal (identical for -T and -M)
At decision time D = T − 61 min (using only data before D):
1. **Predicted funding** F̂ = P̄ + clamp(0.01% − P̄, −0.05%, +0.05%), where P̄ = simple mean of 1m premium-index closes over [T − 8h, T − 61m]. This approximates Binance's time-weighted formula, as in v5 E2a. **Live must compute the same formula from the premiumIndex stream, not use the API's lastFundingRate field**, so that backtest and live match. If < 90% of those minutes exist → skip.
2. **Causal percentile band:** settled 8h rates of that coin in [T − 90d, T − 8h]. Need ≥ 200 values (else skip). hi = 95th percentile, lo = 5th percentile.
3. **Crowded long → SHORT** if F̂ ≥ hi **and** F̂ ≥ +0.03% per 8h. **Crowded short → LONG** if F̂ ≤ lo **and** F̂ ≤ −0.01% per 8h. Otherwise no trade.
4. **Unit:** d = ATR14(15m) / price, **no clamp**. ATR14 = simple mean of the true range of the **14 closed 15m bars before entry** (the last one is [T − 75m, T − 60m)); price = close of that bar. **SL = TP = 1.0 × d** (1:1), applied to the actual fill and not updated afterwards.
5. **Cost floor (a skip rule, not a clamp):** if d < 0.20% → **skip**; never widen. Below 0.20% the -T loss cost of 0.17% would be ≥ 85% of the stop and the 0.14% round trip about 70% of the TP move.

Why these values:
- Percentile 95/5 is the same extremity definition as v3 H1 and the H7-T crowding idea; it is not tuned.
- The absolute floors are needed because in calm periods many coins sit at the 0.01% default, so the 95th percentile can equal the default rate. +0.03% (3× the default) and −0.01% (any clearly negative funding) mean that a "crowded" signal reflects real pressure.
- **Timing: one choice, T − 60m → T − 2m.** The hypothesised payer is the crowded side closing *before* the snapshot to avoid paying. That flow can only be captured before T, and the PM rule forbids holding across a settlement. Entering after settlement would trade the re-entry of the same crowd, which is the opposite thesis and would need its own version.
- SL = TP = 1.0 × ATR14(15m): one ordinary 15m bar is the smallest stop that a single normal bar does not hit. 1:1 keeps the test about direction. It is the same unit as H25, for consistency. Wide-ATR signals (p95 ≈ 2%) will mostly end at the T − 2m time exit rather than at TP, which is accepted and reported.

## 3. Execution variants
Common: STOP_MARKET reduceOnly SL, checked intrabar on 1m from the fill minute. If SL and TP touch in the same 1m bar, SL is assumed first. **Hard time exit: market at the open of the T − 2m 1m bar. Flat before every settlement → no funding paid or received.** One H26 trade per coin per settlement. ISOLATED margin.

### H26-T (taker)
- Entry: market at the open of the T − 60m 1m bar, ± 1 tick adverse. Costs: taker 0.05% + 2bp.
- TP: TAKE_PROFIT_MARKET, fill at TP. SL: STOP_MARKET, fill at the stop or at a gapped open, + 3bp. Time exit at market.
- Round trip: win 0.14%, loss 0.17%, time exit 0.14%.

### H26-M (maker entry and TP)
- **Entry limit:** post-only at P = close of the T − 61m 1m bar (the signal price, at the touch). Placed at T − 60m.
- **Fill rule:** trade-through only. SHORT fills if a later 1m high ≥ P + 1 tick; LONG fills if a later low ≤ P − 1 tick. Fill at P, maker 0.02%. **A touch is not a fill** (queue unknown).
- **Timeout:** 10 min (cancel at T − 50m if unfilled). No chase, no taker fallback. Counted as a non-fill and reported.
- **Partial fills (live/paper):** at timeout, cancel the rest. Keep the filled quantity only if its notional ≥ min notional, otherwise close it at market. TP and SL are sized to the filled quantity. The 1m-OHLC backtest treats a trade-through as a full fill (optimistic on quantity), so paper must report partial-fill frequency.
- **TP:** resting reduceOnly post-only limit, trade-through rule, maker 0.02%. **If the TP is unfilled at T − 2m:** cancel it and close at market (taker + 2bp). SL is always STOP_MARKET (taker + 5bp).
- Round trip: win 0.04%, loss 0.12%, time exit 0.09%.
- **Main risk = adverse selection (H12/H13 FAIL).** There, filled limits averaged −0.11%/−0.17% while unfilled ones averaged +2.6%/+1.5%. A sell limit at P fills only if price ticks *up* first, i.e. when the crowded longs are still buying. TA should judge on signals (fills + non-fills), not fills alone.

## 4. Break-even (cost geometry, 1:1, SL/TP outcomes only)
| d | -T p* | -M p* |
|---|---|---|
| 0.20% | 86.0% | 66.7% |
| 0.30% | 74.6% | 61.8% |
| 0.40% | 68.7% | 59.1% |
| 0.60% (median signal) | 62.6% | 56.3% |
| 1.00% | 57.6% | 53.8% |

With a ≤ 58-min hold, many trades will end at the time exit rather than at SL/TP, so the table is only a guide.

## 5. Sizing (TA v10 rule, binding) + illustrative 5x row
- N = min(0.01·K / (d + c_loss), 5K), with c_loss = 0.17% (-T) / 0.12% (-M): one stop incl. fees and slippage ≤ 1% of K.
- **5x leverage is a cap only** (risk < 1% when it binds). **K = start wallet + realized PnL** (deposits don't raise K).
- Quantity is rounded down to stepSize. Below min notional (BTC bot floor $100 / 0.001 BTC; ETH $20; others $5) → **skip, no rounding up**.
- ISOLATED margin, with liquidation beyond SL.
- **Total open-risk cap 2.5% of K (TA Q-2, confirmed)**, processed in the order BTC, ETH, BNB, SOL, XRP, DOGE. The last position is sized to the remaining room if ≥ min notional, else skipped. 137 settlement times had ≥ 3 coins on the same side.

| Sizing | d | -T notional / win / loss (% of K) | -M notional / win / loss |
|---|---|---|---|
| **TA rule (binding)** | 0.30% | 2.13x / +0.34 / −1.00 | 2.38x / +0.62 / −1.00 |
| **TA rule (binding)** | 0.60% | 1.30x / +0.60 / −1.00 | 1.39x / +0.78 / −1.00 |
| **TA rule (binding)** | 1.50% | 0.60x / +0.81 / −1.00 | 0.62x / +0.90 / −1.00 |
| *Illustrative only, not the rule: 5x full balance, single coin* | 0.60% | *5x / +2.30 / −3.85* | *5x / +2.80 / −3.60* |

- The 5x cap binds only if d < 0.03% (-T) / 0.08% (-M). The 0.20% floor skips those first, so it **never binds** (counted 0%).
- BTC min notional at K = $117 fails once d > ~1.0% (counted shares in §7, at fixed K = $117).
- −25% halt ≈ 29 consecutive full 1% stops.
- **Reported only, not criteria:** days ≥ +1% / ≥ +2% of K.
- Daily loss limit: value set by TA.
- **Verdict = net PnL after fees, slippage, funding (0 by construction) and non-fills + TA's C1–C4 + TA's multiple-testing adjustment.** Judged as a **separate book against a 'no trade (0)' baseline**, not mixed with H7-T. If it passes, TA checks the combined drawdown with H7-T separately (TA Q-3).

## 6. Who pays us and why
When predicted funding is extreme, the crowded side faces a known, imminent cash charge (e.g. ≥ 0.03% of notional for longs at T). Holders for whom that charge exceeds the cost of stepping out, mainly low-fee and VIP/market-maker accounts, short-horizon leveraged accounts and funding-sensitive bots, close or hedge in the last hour and re-open after T. That one-sided flow pushes price against the crowd before T. We take the other side and exit at T − 2m, before the snapshot and before the re-entry. Against us: the crowd is crowded for a reason (trend), and in a strong trend one hour of de-risking is noise next to the trend. Also, for retail at taker fees, closing is irrational unless funding exceeds ~0.10%, so the payer pool may be small.

## 7. Signal counts (count only, 2021-01..2026-09)
Evaluable span: BTC 2021-01 →; ETH/BNB/SOL/XRP/DOGE 2021-12 → (premium-index gap).

| Coin | Settlements | No premium data | Gaps | SHORT | LONG |
|---|---|---|---|---|---|
| BTC | 6,297 | 0 | 25 | 145 | 83 |
| ETH | 6,297 | 1,003 | 10 | 67 | 109 |
| BNB | 6,297 | 1,003 | 10 | 72 | 291 |
| SOL | 6,271 | 1,003 | 7 | 99 | 227 |
| XRP | 6,297 | 1,003 | 7 | 88 | 224 |
| DOGE | 6,297 | 1,003 | 10 | 113 | 178 |

- **Total 1,696 signals (SHORT 584, LONG 1,112); 1,099 distinct settlement clusters (SHORT 278, LONG 842).**
- **rev2 SL/TP distance at signals (d = 1.0 × ATR14(15m)/price, SL = TP, same for -T/-M):** p5 0.24%, p25 0.40%, **p50 0.59%**, p75 0.95%, p95 2.03%. Median by coin: BNB 0.45, BTC 0.55, ETH 0.56, XRP 0.58, DOGE 0.74, SOL 0.84%.
- Cost-floor skips (d < 0.20%): 35 / 1,696 = **2.1%** (BNB 11, XRP 6, BTC 5, DOGE 5, SOL 5, ETH 3).
- 5x cap binding: **0%**.
- Min-notional skips at K = $117 (stepSize down, BTC floor $100): -T 77 / 1,661 = **4.6%**; -M 70 / 1,661 = **4.2%**, all BTC. Tradable: 1,584 (-T) / 1,591 (-M).
- 2.5% cap: at most ~3 positions per settlement. Upper bound on trades Σ min(n, 3) = **1,540** (86 settlement times had > 3 coins).
- By year (S/L): 2021 80/50, 2022 0/414, 2023 195/170, 2024 305/85, 2025 2/216, 2026 2/177. **Shorts are almost all in 2021, 2023 and 2024; longs dominate 2022 and 2025–26.** Direction is strongly regime-clustered.
- Proxy using the *actual* settled rate (look-ahead, count only, full span incl. 2021 alts): SHORT/LONG BTC 126/74, ETH 124/114, BNB 126/316, SOL 161/243, XRP 180/218, DOGE 189/187. Downloading the missing premium data should add a 2021 block of mostly SHORT signals for the alts.

## 8. Minimum sample (TA rule, confirmed)
**≥ 200 trades and ≥ 100 independent clusters (cluster = settlement time) per variant, else INCONCLUSIVE (not a pass).** Per-direction results are reported separately only if that direction has ≥ 100 clusters (draft; TA owns).
- H26-T: ≤ 1,540 trades / 1,099 clusters → **enough overall**, even on the 2021-12 branch (counts above already exclude the alts' 2021-01..11). SHORT has 278 clusters, almost all from 2021, 2023 and 2024. Halves (front/back) will differ in direction mix: front-heavy SHORT, back-heavy LONG. TA should pre-decide whether a per-half check by direction applies.
- H26-M: 1,696 × fill rate. Enough unless the fill rate is < ~15%.

## 9. Kill / failure modes (pre-stated)
1. No flow (E2a's +1.4bp is all there is, even at extremes) → costs dominate (14bp vs a 0.40% move needed).
2. Trend dominance: extreme funding co-occurs with strong trends (v3 H1 PF 0.88).
3. Stop inside the noise: 1×ATR15m is one ordinary bar. Wide-ATR signals mostly end at the time exit.
4. Predicted-funding error: F̂ (simple mean) ≠ the actual time-weighted rate, especially when it moves late in the window. Report sign/threshold agreement of F̂ with the settled rate.
5. -M adverse selection (H12/H13).
6. Funding interval changes (SOL 2h/4h) or Binance formula changes are excluded or reported.
7. Correlated settlements: up to 6 coins at the same T is one bet; the 2.5% cap bounds it.

## 10. Data gaps (must be resolved or accepted before lock)
- **1m premium index for ETH/BNB/SOL/XRP/DOGE, 2020-10..2021-11, is missing on the box** (v5 download started 2021-12; BTC has it from 2020-09). These are public files on data.binance.vision (`futures/um/monthly/premiumIndexKlines/{SYM}/1m/`), no key needed. The Developer's download is in progress. The **pre-stated rule in §1** decides: use 2020-10+ data if the download succeeds, else lock the alts from 2021-12-01 (about 1,003 fewer settlements per alt).
- No order-book or queue data → the -M fill model is OHLC trade-through only. Partial fills are invisible in the backtest.
- Settled funding: 8h, complete for all 6. SOL's 101 non-8h settlements are excluded.

## 11. Reporting (for TA)
Per variant (-T, -M) under the TA 1% rule (5x row illustrative only): trades, clusters, net PnL after fees, slippage, funding (0 by construction) and non-fills; PF; MDD; daily-loss-limit hits; −25% halt. Also exit reason split (TP/SL/time), by direction / coin / year (descriptive), F̂ vs settled-rate agreement, filled vs unfilled signal outcomes for -M, and days ≥ +1% / +2% (reported only). **Required distribution outputs:** p5/p25/p50/p75/p95 of the actual SL and TP distances (% of fill), share of trades where the 5x cap bound, share skipped by the cost floor, share skipped by min notional, and share skipped or downsized by the 2.5% cap. Plus partial-fill frequency in paper. Verdict: TA (net PnL + C1–C4).

## 12. TA answers (folded in rev2)
- Q-1: no clamp. SL = TP = 1.0 × ATR14(15m). The < 0.20% floor is a cost-based skip rule, not a clamp.
- Q-2: 2.5% total open-risk cap confirmed.
- Q-3: separate book vs 'no trade (0)'; combined drawdown with H7-T checked separately if it passes.
- Min sample: ≥ 200 trades and ≥ 100 clusters per variant, else INCONCLUSIVE.
- Multiple testing: one family of 4 variants (TA criteria doc).
- Alt premium data: pre-stated two-branch rule (§1).

## 13. Note on H15 (no new rules)
H15 (liquidation-cascade fade) is already locked (`specs/trade-bot-strategy-spec-h15.md`, sha256 `008bbdbf…b913da`). It is forward-only: there is no historical liquidation data, the verdict comes at ≥ 30 independent clusters, and the deadline is 2027-10-20. A grep on 2026-10-21 found **no forceOrder liquidation logger in `/workspace/trade-bot`**. Every day without the logger is lost sample. **Recommend the Developer builds and deploys it now**, per the H15 spec (Tokyo server, priority below the live bot, ≤ 100MB memory, stop on any impact on the live bot), so records start accruing. No rule changes.
