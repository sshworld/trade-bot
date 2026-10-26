# size_entry on the real 6 coins — 2026-10-26 (TA condition 2)

Read-only. No keys, no orders, no service action. Branch `sizing-minorder-3pct`, code = `size_entry` of `live_v6/sizing.py` (spec v2.1), unchanged.

## Inputs
* **Filters:** the original `exchangeInfo_2026-10-26.json` (fetched 2026-10-26T00:06:56Z from the VPS, public; copy in `2026-10-26_sizing_real6/exchangeinfo_2026-10-26.json`),
  parsed with the project's `rules_from_info`. minNotional: BTC 50, ETH 20, SOL/BNB/XRP/DOGE 5 (no bot-side floor — the old `Settings.min_notional_floor` BTC=100 of release e2695d9 does not exist in this branch).
  step: BTC/ETH 0.001, SOL/BNB 0.01, XRP 0.1, DOGE 1.
* **Prices:** mainnet public `GET /fapi/v1/premiumIndex` (mark) + `/fapi/v1/ticker/bookTicker` (bid/ask) read **via the VPS** (`ops@`, read-only `curl` of public endpoints; the box is geo-blocked).
  Timestamp: **2026-10-26T02:00:57Z = 2026-10-26 11:00:57 KST**. Entry reference = ask (as the engine does), mark for the PERCENT_PRICE check.
  Raw: `2026-10-26_sizing_real6/real6_prices_raw.txt`.

  | coin | ask (ref) | mark | ATR14 (4h) | stop dist = 2×ATR |
  |---|---|---|---|---|
  | BTCUSDT | 79620.40 | 79634.34 | 719.28 | 1438.56 |
  | ETHUSDT | 2311.13 | 2310.90 | 33.840 | 67.681 |
  | SOLUSDT | 100.97 | 100.961 | 1.5251 | 3.0502 |
  | BNBUSDT | 738.22 | 738.22 | 7.8578 | 15.716 |
  | XRPUSDT | 1.2897 | 1.28965 | 0.018655 | 0.037310 |
  | DOGEUSDT | 0.07643 | 0.07644 | 0.0012847 | 0.0025695 |
* **Stop width:** H7-T convention `sd = k × ATR14` with k = 2.0, ATR14 = Wilder RMA of the **closed 4h bars** (199 bars from `/fapi/v1/klines?interval=4h&limit=200`, last closed bar ends 2026-10-26T00:00Z; same recurrence as `strategy._atr_update`;
  the live model warms up on a longer history, so its ATR can differ slightly). Raw: `real6_klines_raw.txt`. The stop is rounded to the tick toward the entry (`stop_price`).
* **Wallet / available:** 117.47 (the real wallet), plus 50 and 1000. Flat account, available = wallet, no open positions.
* **Leverage brackets:** the real ones need a signed endpoint (no keys) → the test fixture `fakes.BRACKETS` (≤50k notional: 50×, mmr as fixture). The chosen leverage (10×) therefore is *not* real evidence; it only matters for the margin check, which passes with a huge margin at these notionals. Qty/notional/loss do not depend on it.
* **Loss + fees:** `qty_floor`: the code's own `loss_frac` = (q·dist + q·ref·(2×0.05% fee + 0.04% entry slip + 0.03% stop slip)) / wallet. `q0`: same formula with the *rounded* stop width, computed here (the engine's q0 cap checks stop-only 0.5% and then stop+fees ≤ `max_risk_pct`); stop-only is shown in brackets.
  Reproduce: `/workspace/.venv-live6/bin/python real6_sizing.py` (reads the raw files above).

## Result
### Wallet 117.47 USDT (available = wallet, flat account, no open positions)

| coin | path | qty | notional (USDT) | stop width (2×ATR14 4h) | stop % of price | loss+fees % of wallet | skip |
|---|---|---|---|---|---|---|---|
| BTCUSDT | qty_floor | 0.001 | 79.62 | 1438.56 (stop 78181.9) | 1.81% | 1.34% (stop-only 1.22%) | – |
| ETHUSDT | qty_floor | 0.009 | 20.80 | 67.6807 (stop 2243.45) | 2.93% | 0.55% (stop-only 0.52%) | – |
| SOLUSDT | q0 | 0.19 | 19.18 | 3.05021 (stop 97.92) | 3.02% | 0.52% (stop-only 0.49%) | – |
| BNBUSDT | q0 | 0.03 | 22.15 | 15.7157 (stop 722.51) | 2.13% | 0.43% (stop-only 0.40%) | – |
| XRPUSDT | q0 | 15.7 | 20.25 | 0.0373102 (stop 1.2524) | 2.89% | 0.53% (stop-only 0.50%) | – |
| DOGEUSDT | q0 | 229 | 17.50 | 0.00256950 (stop 0.07387) | 3.35% | 0.52% (stop-only 0.50%) | – |

### Wallet 50 USDT (available = wallet, flat account, no open positions)

| coin | path | qty | notional (USDT) | stop width (2×ATR14 4h) | stop % of price | loss+fees % of wallet | skip |
|---|---|---|---|---|---|---|---|
| BTCUSDT | – | – | – | 1438.56 | 1.81% | – | `min_order_risk_over_cap`: 1.5739 = 3.15% of wallet 50.00 > 3% (q0=0.000) |
| ETHUSDT | qty_floor | 0.009 | 20.80 | 67.6807 (stop 2243.45) | 2.93% | 1.29% (stop-only 1.22%) | – |
| SOLUSDT | q0 | 0.08 | 8.08 | 3.05021 (stop 97.92) | 3.02% | 0.52% (stop-only 0.49%) | – |
| BNBUSDT | q0 | 0.01 | 7.38 | 15.7157 (stop 722.51) | 2.13% | 0.34% (stop-only 0.31%) | – |
| XRPUSDT | q0 | 6.7 | 8.64 | 0.0373102 (stop 1.2524) | 2.89% | 0.53% (stop-only 0.50%) | – |
| DOGEUSDT | q0 | 97 | 7.41 | 0.00256950 (stop 0.07387) | 3.35% | 0.52% (stop-only 0.50%) | – |

### Wallet 1000 USDT (available = wallet, flat account, no open positions)

| coin | path | qty | notional (USDT) | stop width (2×ATR14 4h) | stop % of price | loss+fees % of wallet | skip |
|---|---|---|---|---|---|---|---|
| BTCUSDT | q0 | 0.003 | 238.86 | 1438.56 (stop 78181.9) | 1.81% | 0.47% (stop-only 0.43%) | – |
| ETHUSDT | q0 | 0.073 | 168.71 | 67.6807 (stop 2243.45) | 2.93% | 0.52% (stop-only 0.49%) | – |
| SOLUSDT | q0 | 1.63 | 164.58 | 3.05021 (stop 97.92) | 3.02% | 0.53% (stop-only 0.50%) | – |
| BNBUSDT | q0 | 0.31 | 228.85 | 15.7157 (stop 722.51) | 2.13% | 0.53% (stop-only 0.49%) | – |
| XRPUSDT | q0 | 134.0 | 172.82 | 0.0373102 (stop 1.2524) | 2.89% | 0.53% (stop-only 0.50%) | – |
| DOGEUSDT | q0 | 1953 | 149.27 | 0.00256950 (stop 0.07387) | 3.35% | 0.53% (stop-only 0.50%) | – |

## Reading
* **Wallet 117.47:** BTC and ETH take the `qty_floor` path (0.001 BTC = 79.62 USDT, loss+fees 1.34 %; 0.009 ETH = 20.80 USDT, 0.55 %); SOL/BNB/XRP/DOGE are normal `q0` entries (0.40–0.52 %). **No skip at 117.47.**
* **Wallet 50:** BTC is skipped `min_order_risk_over_cap` (smallest allowed 0.001 BTC loses 1.574 USDT = 3.15 % > 3 %); all other coins enter. ETH `qty_floor` at 1.29 %.
* **Wallet 1000:** everything is `q0` (0.47–0.53 % incl. fees).
* Per-coin stop width is 1.81 % (BTC) … 3.35 % (DOGE) of price.
