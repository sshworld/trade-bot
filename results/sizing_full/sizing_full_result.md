# FE-v2.2 (A, B, C) x RP-v1 off/on: one-time run on the 355 H7-T ledger (numbers only, no verdict)

started 2026-10-29T10:22:00+09:00 (Asia/Seoul); commit e2e0d501bab5f31028dec4c4ac9e05f2b1d00233 branch sizing-full; ledger 2a147ab723f5 (355 trades, mean ledger R +1.6885); start wallet 117.5; min_stop_dist 0.006; 1m opens from the six-coin 1m series (h46_data.load_1m); exchange filters 008342ef31e5, brackets 1270358aab51.

Lock files verified (sha256): prereg-lock-fullentry-v2.md 539c7585353b; prereg-lock-h61-h71-addendum-fe2.md 9bc7869cd811; prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0; prereg-lock-replace-losers-v1.md 31619c1507f2; prereg-lock-fullentry-v2_2-variantC.md 03a2d0898830; answers-fullentry-R1-R10-C1-C6-2026-10-29.md b9c172688fee

## Per ledger

| ledger | RP verdict applies (gate) | signals | trades | annual n | S1-0 tier | mean R (net/stop-loss) | final wallet | mean hold (days) | Z1 max DD | Z2 share (10,000, seed 88, n=annual) | Z3 worst realised loss/wallet | first -25% touch vs initial | first -25% touch vs peak | liquidated |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_off | - (base ledger) | 355 | 121 | 21 | undecidable | 1.8757 | 7215.27 | 5.91 | 0.5177 | 0.4082 | 0.0619 | None | 2023-01-18 15:55:00 | 0 |
| A_on | NO (reference only, base ledger failed S1-1..S1-6) | 355 | 140 | 25 | undecidable | 1.5933 | 6024.53 | 5.46 | 0.5104 | 0.3819 | 0.0619 | None | 2023-02-05 20:00:00 | 0 |
| B_off | - (base ledger) | 355 | 107 | 19 | undecidable | 2.0558 | 11262.04 | 5.83 | 0.5889 | 0.6017 | 0.0618 | None | 2021-12-24 19:59:00 | 0 |
| B_on | NO (reference only, base ledger failed S1-1..S1-6) | 355 | 127 | 22 | undecidable | 1.5960 | 6959.81 | 5.00 | 0.5875 | 0.6207 | 0.0619 | None | 2023-02-01 17:45:00 | 0 |
| C_off | - (base ledger) | 355 | 114 | 20 | undecidable | 2.0673 | 8745.18 | 6.13 | 0.5177 | 0.3804 | 0.0619 | None | 2023-01-18 15:55:00 | 0 |
| C_on | NO (reference only, base ledger failed S1-1..S1-6) | 355 | 133 | 23 | undecidable | 1.7485 | 7195.84 | 5.59 | 0.5104 | 0.3555 | 0.0619 | None | 2023-02-05 20:00:00 | 0 |

## Skipped signals by reason (labels as in sizing_full; with RP on, signals blocked by max_positions / open_loss_cap that were not replaced keep the blocking label)

- A_off: {'stop_vs_liq': 26, 'stop_too_wide': 9, 'open_loss_cap': 199}; sized_by {'cap': 92, 'loss': 29}; max concurrent 2; max open stop-loss sum 0.0598
- A_on: {'stop_vs_liq': 26, 'stop_too_wide': 9, 'open_loss_cap': 180}; sized_by {'cap': 111, 'loss': 29}; max concurrent 2; max open stop-loss sum 0.0597
- B_off: {'stop_vs_liq': 26, 'stop_too_wide': 9, 'open_loss_cap': 213}; sized_by {'loss': 101, 'cap': 6}; max concurrent 1; max open stop-loss sum 0.0500
- B_on: {'stop_vs_liq': 26, 'stop_too_wide': 9, 'open_loss_cap': 193}; sized_by {'loss': 120, 'cap': 7}; max concurrent 1; max open stop-loss sum 0.0500
- C_off: {'stop_vs_liq': 26, 'stop_too_wide': 9, 'open_loss_cap': 206}; sized_by {'cap': 82, 'loss': 32}; max concurrent 2; max open stop-loss sum 0.0590
- C_on: {'stop_vs_liq': 26, 'stop_too_wide': 9, 'open_loss_cap': 187}; sized_by {'cap': 100, 'loss': 33}; max concurrent 2; max open stop-loss sum 0.0590

## Replace-losers (switch ON ledgers)

| ledger | closed by replacement | mean R of those closed | mean hold (days), all trades | replace attempts (no_loser / no_price / still_blocked) | no_price (missing 1m bar, no replacement) |
|---|---|---|---|---|---|
| A_on | 18 | -0.2448 | 5.46 | 177 / 0 / 3 | 0 |
| B_on | 20 | -0.2184 | 5.00 | 193 / 0 / 0 | 0 |
| C_on | 19 | -0.2383 | 5.59 | 187 / 0 / 0 | 0 |

## Gate for the RP verdict (R10): S1-1..S1-6 on each variant's switch-off ledger

| variant | S1-1 mean R | S1-2 date-block lower bound (q=0.05/74, seed 88) | S1-3 mean R at 2x cost | S1-4 halves | S1-5 MDD / top-5% removed mean | S1-6 max year share | gate |
|---|---|---|---|---|---|---|---|
| A | 1.6885 (True) | 0.1894 (True) | 1.6457 (True) | 2.4374 / 0.9438 (True) | 0.5177 / 0.0257 (False) | 0.5166 in 2021 (True) | False |
| B | 1.6885 (True) | 0.1894 (True) | 1.6457 (True) | 2.4374 / 0.9438 (True) | 0.5889 / 0.0257 (False) | 0.5166 in 2021 (True) | False |
| C | 1.6885 (True) | 0.1894 (True) | 1.6457 (True) | 2.4374 / 0.9438 (True) | 0.5177 / 0.0257 (False) | 0.5166 in 2021 (True) | False |

## Limitations and readings

- Funding during the replacement window is NOT modelled (R4): a replaced trade's unit = price move at the close fill - 0.0015 round-trip cost; the ledger's own fee/slippage/funding units apply to trades that exit on the ledger.
- Replacement uses 1m opens: rank at the open of the signal's entry minute, close at the open of the next minute; a missing bar means no replacement (no_price) and the original skip stands. The new trade keeps its ledger entry price/time (R2).
- The only candidate ledger available is the 355-trade H7-T six-coin replay (ledger_355.csv); no separate H48/H61-H71 ledger exists on this box. Variant R = net P&L / (fee-inclusive loss at the stop); 'ledger R' is the $100 replay R.
- Gate: S1-1..S1-4 and S1-6 are computed once on the ledger R (variant-independent, per the lock); S1-5 uses each variant's switch-off wallet (MDD <= 20%) and the ledger R with the top ceil(5%) removed. S1-2 uses the date-block bootstrap with N=74 (q = 0.05/74) and seed 88 (no seed is locked for this ledger: reading). S1-3 subtracts 0.0015/stop_dist from each R (reading). S1-6 uses entry years. S1-0 tier is reported, not gated.
- FE-Z3 = worst realised net loss / wallet at entry (fees, slippage, funding included); a liquidated trade counts the larger of the realised loss and its margin share. FE-Z2: 10,000 resamples of the entered trades' returns on entry wallet, n = annual trade count, seed 88, reaching -25%.
- No -25% halt in the replay; the first -25% touch dates are reported against the initial wallet and against the running peak.
