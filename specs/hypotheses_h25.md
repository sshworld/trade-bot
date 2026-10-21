# Quant hypothesis H25 v1 rev2: macro-release momentum scalp, both directions (DRAFT for TA pre-registration, v10)

v10.1 re-creation 2026-10-21 after box /workspace loss; rules unchanged from rev2 (old sha e15736c4… / b20d11f6…)

rev2 2026-10-21: Q-1 resolved by PM, clamp removed, ATR-scaled SL/TP. TA answers folded in: Q-1 (same as PM), Q-2 (2.5% total open-risk cap), Q-3 (separate book), min sample, multiple-testing family. Pre-lock draft revision, made before any run.

Status: draft. No backtest has been run and no H25 returns have been computed. The only computations were **event counts, trigger counts, SL-distance distribution and skip/cap shares** (scripts `/workspace/quant/v10_counts/count_v10.py`, `rev2_counts.py`; outputs `counts.json`, `rev2_counts.json`, `h25_event_rows.csv`). TA owns pass criteria (verdict = net PnL after all costs + C1–C4) in the TA criteria document. That includes the multiple-testing adjustment: TA treats H25-T, H25-M, H26-T and H26-M as **one family**. Sizing follows TA's v10 rule (§5). One run, no tuning; any change = new version.

**Data-informed flag.** Written after v8, which showed H22-F results (long-only 30-min macro momentum entry with H7-T trend exits; standalone PF 2.70 at $100 on 2021-01..2026-09). H25 uses the same events and the same period, so it is **not independent** of H22-F. Treat the prior as **low to moderate**. No intraday macro rule has been tested on this box.

## 0. What v8 already tested and how H25 differs
| | H21 / H21-X (v8) | H22-F (v8) | **H25 (v10)** |
|---|---|---|---|
| Role of event | entry **blackout** around CPI/NFP/FOMC (± XRP escrow) | **long-only** entry trigger | **both directions** entry trigger |
| Direction | n/a (H7-T long) | long, close > prior closed 4h high within 30 min | sign of the first-15-min move, if \|move\| ≥ 1.5 × pre-event ATR(14, 15m) |
| Regime / funding filter | H7-T | BTC 200D long + none | **none** (both directions by design) |
| Exit | H7-T (2×ATR4h stop, M20 channel, multi-day) | H7-T (multi-day) | **SL = TP = 1.0 × ATR14(15m), time exit ≤ 120 min, never across funding settlement** |
| Result | "no effect / not measurable" (§3(a)) | combined failed; standalone descriptive only | not run |

H19/H20 (short fixed-% TP on the 4h trend book) failed C3 (PF < 1.3). H25 shares their weakness: a 1×ATR TP truncates the right tail. The difference is that H25 does not graft a short TP onto a trend entry. It is a standalone intraday book whose entire edge must come from the first two hours after a release.

## 1. Universe, data, period
- 6 coins: BTC ETH BNB SOL XRP DOGE USDT-M perpetuals. Period 2021-01-01 to before 2026-10-01 UTC.
- Events: `/workspace/quant/data/macro_events.csv` (sha256 `fecbc016…c40ef9`), frozen. 182 events in the period: CPI 68, NFP 68, FOMC 46 (statement time). t = release time in UTC (12:30/13:30 for CPI/NFP, 18:00/19:00 for FOMC, with DST handled in the CSV).
- Bars: 1m klines (`data/parquet/v7_six_1m.parquet`) for the window, fills, stops and TPs. 15m bars are built from the 1m bars (left-labelled, a bar is valid only if all 15 minutes exist).

## 2. Signal (identical for -T and -M)
1. **Pre-event ATR** a = simple mean of the true range over the 14 closed 15m bars ending at t (the last one is [t−15m, t)). If any of those bars is invalid → skip the coin-event.
2. **Release window** W = the 15 1m bars opening in [t, t+15m). O_W = open of the first bar, C_W = close of the last, H_W/L_W = max high / min low. If any minute is missing → skip.
3. **Trigger:** m = C_W − O_W. If |m| ≥ 1.5·a → signal; direction = sign(m) (long if up, short if down). Otherwise no trade.
4. **Unit (SL = TP distance):** d = A / C_W, where A = simple mean of the true range over the **14 closed 15m bars before entry**, i.e. ending at t+15m (the last bar is the release bar [t, t+15m)). **No clamp.**
5. **Cost floor (a skip rule, not a clamp):** if d < 0.20% → **skip the trade**; never widen the stop. Reason: below 0.20% the -T loss cost of 0.17% would be ≥ 85% of the stop distance, and the -T round trip of 0.14% would be about 70% of the TP move.
6. One H25 trade per coin per event. No regime filter, no funding filter.

Why these values, fixed and not gridded:
- 15 min (not 5): the first prints after CPI/NFP whipsaw, and 5 min often holds only the knee-jerk. 15 min is one full 15m bar, so the window and the ATR unit share the same timescale. For FOMC it closes before the 14:30 ET press conference.
- 1.5·a: the post-release bar must be 50% larger than an ordinary 15m bar to count as a repricing rather than noise. The value comes from round-number reasoning, not from data.
- SL = TP = 1.0 × ATR14(15m): a stop one ordinary 15m bar away is the smallest that is not hit by a single normal bar of noise. 1:1 keeps the hypothesis about direction, not payoff shape. The same unit is used in H26, for consistency. The rev1 'half of release range' idea is dropped: it has no better justification, and the ATR window ending at entry already contains the release bar, so it reflects post-release volatility.
- SL/TP **distribution at signals (count only, rev2):** see §7.

## 3. Execution variants
Common to both: SL = entry ∓ d·entry and TP = entry ± d·entry (1:1), both computed from the **actual fill price**. SL is always a STOP_MARKET reduceOnly, checked intrabar on 1m from the fill minute. If SL and TP are both touched in the same 1m bar, SL is assumed first. SL/TP distances are set at entry from the ATR above and are not updated afterwards. **Time exit** = market at the open of the 1m bar at min(t + 15m + 120m, next funding settlement − 2m). For these release times the 120-min deadline always comes first (latest flat time 21:15 UTC, before 00:00 settlement). **Never held across a funding settlement → no funding cash flow.** ISOLATED margin.

### H25-T (taker)
- Entry: market at the open of the 1m bar starting at t+15m. Modelled fill = open ± 1 tick adverse. Cost: taker 0.05% + 2bp.
- TP: TAKE_PROFIT_MARKET. Fill = TP price when the 1m high (long) / low (short) reaches it. Cost: taker 0.05% + 2bp.
- SL: STOP_MARKET. Fill = stop, or the bar open if the bar gapped through it. Cost: taker 0.05% + 2bp + 3bp.
- Round trip: win 0.14%, loss 0.17%, time exit 0.14%.

### H25-M (maker entry and TP)
- **Entry limit:** post-only limit at P = C_W (the signal price, i.e. the last trade of the window, at the touch). Placed at t+15m.
- **Fill rule (1m OHLC, conservative):** filled only if a later 1m bar trades **through** the limit by ≥ 1 tick (long: low ≤ P − 1 tick; short: high ≥ P + 1 tick). Fill price = P. Cost: maker 0.02%, slippage 0. A touch at exactly P is **not** a fill, because queue position is unknown.
- **Timeout:** cancel if unfilled by t+15m+5m (5 one-minute bars). No chase, no re-post, and no taker fallback. The event is recorded as a non-fill, and non-fills are reported (filled vs unfilled outcomes, as in H12/H13 `adverse_selection.csv`).
- **TP:** resting reduceOnly post-only limit at TP, placed at fill. Filled only if price trades through by ≥ 1 tick. Cost: maker 0.02%.
- **If TP is not filled by the time exit:** cancel the TP and close at market (taker 0.05% + 2bp). SL stays a STOP_MARKET (taker + 5bp).
- Round trip: win 0.04%, loss 0.12% (0.02 + 0.10), time exit 0.09%.
- **Partial fills (live/paper rule):** if the entry limit is partly filled at timeout, cancel the rest. Keep the filled quantity only if its notional ≥ min notional, otherwise close it at market (taker). TP and SL are placed for the **filled** quantity only (and resized on each further partial fill before timeout). The 1m-OHLC backtest cannot see partial fills, so there a trade-through counts as a full fill and a touch is no fill. This is optimistic on quantity, so live paper must report partial-fill frequency.
- Time exit counts from t+15m (not from the fill), so a late fill gets a shorter hold.
- **Main risk = adverse selection, as in H12/H13** (`results/h12h13/SUMMARY.md`). There, filled limits averaged −0.11%/−0.17% over the next 12h/6h, while unfilled ones averaged +2.6%/+1.5%. For a momentum entry this is worse by construction: a buy limit at C_W fills only if price comes back *against* the signal, and the strongest continuations never fill. -M can show a better per-fill cost and a worse per-signal result. TA should judge on signals, not on fills.

## 4. Break-even arithmetic (cost geometry only, not a result)
p* = (d + c_loss) / (2d + c_loss − c_win), the win rate needed at 1:1 with only SL/TP outcomes.

| d | -T p* | -M p* |
|---|---|---|
| 0.20% | 86.0% | 66.7% |
| 0.30% | 74.6% | 61.8% |
| 0.40% | 68.7% | 59.1% |
| 0.60% (median signal) | 62.6% | 56.3% |
| 1.00% | 57.6% | 53.8% |

At the median d ≈ 0.60%, -T needs about 63% winners at 1:1 and -M about 56%. Time exits change this, so the table is only a guide.

## 5. Sizing (TA v10 rule, binding) + illustrative 5x row
**TA rule:** quantity such that one stop loss **including fees and stop slippage** ≤ 1% of sizing capital K. That is, N = min(0.01·K / (d + c_loss), 5K), with c_loss = 0.17% (-T) / 0.12% (-M).
- **5x leverage is a cap only.** When it binds, the risk is < 1%.
- **K = start wallet + realized PnL**; deposits do not raise K.
- Quantity is rounded **down** to stepSize. If notional < min notional (BTC: bot floor $100 / 0.001 BTC; ETH $20; others $5) → **skip, no rounding up**.
- ISOLATED margin, with the liquidation price beyond SL.
- **Total open-risk cap 2.5% of K (TA Q-2, confirmed)**, counting each position's stop loss incl. fees. Same-event entries are processed in the order BTC, ETH, BNB, SOL, XRP, DOGE. The last one is sized down to the remaining room if that is ≥ min notional, otherwise skipped.

Per-trade outcome as % of K at a few d (cost geometry, not a result):

| Sizing | d | -T notional / win / loss | -M notional / win / loss |
|---|---|---|---|
| **TA rule (binding)** | 0.30% | 2.13x / +0.34% / −1.00% | 2.38x / +0.62% / −1.00% |
| **TA rule (binding)** | 0.60% | 1.30x / +0.60% / −1.00% | 1.39x / +0.78% / −1.00% |
| **TA rule (binding)** | 1.50% | 0.60x / +0.81% / −1.00% | 0.62x / +0.90% / −1.00% |
| *Illustrative only, not the rule: 5x full balance, single coin* | 0.60% | *5x / +2.30% / −3.85%* | *5x / +2.80% / −3.60%* |

- The 5x cap would bind only if d + c_loss < 0.20%, i.e. d < 0.03% (-T) / 0.08% (-M). The 0.20% cost floor skips those first, so **the 5x cap never binds in H25** (counted share 0%, §7).
- BTC min notional: at K = $117 the $100 floor is cleared only while d ≤ ~1.0% (-T) / ~1.05% (-M), before stepSize rounding. Wider-ATR BTC signals are skipped. Counted shares are in §7, at fixed K = $117 (they move with K).
- −25% halt: about 29 consecutive full 1% stops. One event ≈ one correlated bet of up to 2.5%, so about 11–12 bad events at the cap.
- **Reported only, not criteria:** days with net ≥ +1% and ≥ +2% of K. H25 trades on ≤ 111 of ~2,100 days (≈ 1.6/month), so **H25 cannot by itself meet a daily 2% target.**
- Daily loss limit: value set by TA.
- **Verdict = net PnL after fees, slippage, funding (0 here) and non-fills, plus TA's existing C1–C4 and TA's multiple-testing adjustment.** Judged as a **separate book against a 'no trade (0)' baseline**, not mixed with H7-T (TA Q-3). If it passes, TA checks the combined drawdown with H7-T separately.

## 6. Who pays us and why
Scheduled US releases force a repricing of rates expectations. Crypto perps reprice through (i) systematic and discretionary macro traders hedging with BTC/ETH perps after the headline, and (ii) stop and liquidation flow from leveraged accounts positioned for the other side before the print. The first 15 minutes reveal the direction and the forced flow. If (ii) is still running (stop cascades and auto-deleveraging that arrive in waves), the move continues for minutes to hours, and the people paying are the late, forced unwinders. Against us: market makers widen spreads around releases (slippage beyond 2bp), and the first 15 minutes may already contain the whole move (no continuation).

## 7. Event counts (count only, 2021-01..2026-09)
- 182 events × 6 = 1,092 coin-events. 1,090 valid (2 gaps: SOL 1, XRP 1, the known SOL/XRP 1m holes).
- **Triggers: 494** (long 258 / short 236). By coin: BTC 87, ETH 90, BNB 77, SOL 82, XRP 75, DOGE 83. By type: CPI 236, NFP 149, FOMC 109. By year: 2021 48, 2022 145, 2023 80, 2024 95, 2025 77, 2026 (to Sep) 49.
- **Independent clusters (events with ≥ 1 trigger): 111** (CPI 49, NFP 35, FOMC 27). Coins per triggered event: mean 4.45.
- -M trade count = tradable × fill rate. Unknown before the run, and probably well below the -T count.
- **rev2 SL/TP distance at signals (d = 1.0 × ATR14(15m)/price; SL = TP, so the distributions are the same; same for -T and -M):** p5 0.27%, p25 0.44%, **p50 0.60%**, p75 0.83%, p95 1.59%. Median by coin: BTC 0.44, BNB 0.52, ETH 0.59, XRP 0.60, DOGE 0.69, SOL 0.81%.
- Cost-floor skips (d < 0.20%): 6 / 494 = **1.2%** (BTC 3, BNB 2, DOGE 1).
- 5x cap binding: **0%** (-T and -M).
- Min-notional skips at K = $117 (stepSize rounding down, BTC floor $100): -T 15 / 488 = **3.1%**; -M 13 / 488 = **2.7%**. All are BTC. That leaves 473 (-T) / 475 (-M) tradable signals.
- **The 2.5% cap limits each event to about 3 positions** (2 at 1%, 1 at 0.5%). 80 of the 111 events have > 3 triggers. Upper bound on trades: Σ min(n, 3) = **296** (-T; -M is further cut by non-fills).

## 8. Minimum sample (proposal; TA owns)
**TA rule (confirmed): ≥ 200 trades and ≥ 100 independent clusters per variant, else INCONCLUSIVE (not a pass).** Cluster = event.
- H25-T: ≤ 296 trades after the 2.5% cap, 111 clusters → **just enough**. Floor/min-notional skips remove few whole events, but the margin over 100 is only 11. Per-type or per-direction splits (27–49 clusters) are **not** enough and should be descriptive only.
- H25-M: clusters with ≥ 1 fill ≤ 111 and likely far fewer → **probably not enough**. If the fill rate is below ~90% of events, the cluster floor fails. Under the TA rule that means INCONCLUSIVE.
- Forward accrual is slow: about 3 events/month, i.e. about 36 clusters/year.

## 9. Kill / failure modes (pre-stated)
1. No continuation: the first 15 min holds the whole move; entries at t+15m buy the top (−d + costs).
2. Stop inside the noise: 1×ATR is one ordinary 15m bar, and post-release bars are larger than ordinary ones. Ordinary retracement can hit SL.
3. FOMC press conference (t+30m) reverses the statement move inside the hold.
4. Event slippage: spreads and impact at t+15m exceed 2bp, especially SOL/DOGE/XRP. Report fills against the 1m open.
5. -M adverse selection (H12/H13): fills only on pullbacks against the signal, so continuations go unfilled.
6. Correlation: about 4.5 coins per event are one bet; one bad event ≈ the full 2.5% total-risk cap.
7. Revised/cancelled release dates (2025–26 BLS lapses) are already in the CSV. Any mismatch → stop, per the v8 §3(a) practice.

## 10. Reporting (for TA)
Separate standalone book vs a 'no trade (0)' baseline, at $100/$300 and at S0 = $117 if TA wants. Per variant (-T, -M) under the TA 1% rule (5x row illustrative only): trades, clusters, net PnL after fees, slippage, funding (0 by construction) and non-fills; PF; MDD; daily-loss-limit hits; −25% halt; count of days ≥ +1% and ≥ +2% (report only). Also by type/coin/direction (descriptive), exit reason split (TP/SL/time), and for -M filled vs unfilled signal outcomes and partial-fill frequency (paper). **Required distribution outputs:** p5/p25/p50/p75/p95 of the actual SL and TP distances (% of fill price), share of trades where the 5x cap bound, share skipped by the cost floor, share skipped by min notional, and share skipped or downsized by the 2.5% cap. Pass criteria: **TA**.

## 11. TA answers (folded in rev2)
- Q-1 (resolved by PM, TA agrees): no clamp. One pre-stated multiple, SL = TP = 1.0 × ATR14(15m). The < 0.20% cost floor is a skip rule only.
- Q-2: 2.5% total open-risk cap confirmed.
- Q-3: separate book, not mixed with H7-T. Judged vs 'no trade (0)'. If it passes, the combined drawdown with H7-T is checked separately.
- Min sample: ≥ 200 trades and ≥ 100 independent clusters per variant, else INCONCLUSIVE.
- Multiple testing: H25-T/M + H26-T/M are one family; the adjustment is in TA's criteria document.
