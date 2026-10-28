# h34_paper — paper (virtual-fill) recorder

Records **virtual** signals and fills for the rules TA has locked, from bars that closed **after 2026-10-28 15:03 KST**.
Separate low-priority process: public market data only (Binance USDT-M `/fapi/v1/klines`, `/fapi/v1/time`), **no API key, no
order endpoint, no account endpoint**, stdlib only. It never touches `live_v6` or the h15 logger.

| file | what |
|---|---|
| `core.py` | the shared signal/fill core (indicators, `detect`, entry = next open ±1 tick adverse, exits, sizing, per-rule KST 5% cap). Same code the one-time screen replayed. `Rule` is the plug-in point. |
| `rules.py` | registry. `IMPLEMENTED` = H34-B, H34-B-S. `PLANNED` = H34-A(-S), H32(-S), H31(-S), H35, H36, H38-*: enabling one is a config **error** (fail closed). |
| `engine.py` | cross-rule limits (TA v1.1): 1 position/coin, max 3 concurrent, open risk ≤ 6%, one stop ≤ 2%, portfolio daily loss 5%. A blocked signal is logged as `signal_skipped` and **never entered later**. |
| `feed.py` | public REST client with a path allow-list (anything else raises `PermissionError`), windowed bar cache. |
| `recorder.py` | run loop, ledger, atomic state, status file, CLI. |
| `deploy/` | `h34_paper.json` (rule on/off, limits, lock time), `h34-paper-recorder.service`, `RUNBOOK.md`. |
| `../tools/ledger_score.py` | verdict score from the ledger (C1–C5, minimum, integrity). |
| `history.py`, `screen.py`, `stats.py` | research-side only (pandas/pyarrow); the recorder does not import them. |

## Run (local check; do not point at the live VPS before approval)

```bash
python3 -m h34_paper.recorder run --config h34_paper/deploy/h34_paper.json --state-dir /var/lib/h34_paper        # service
python3 -m h34_paper.recorder run --config … --state-dir /tmp/x --once                                           # one pass, exit
python3 -m h34_paper.recorder status --state-dir /var/lib/h34_paper                                              # status.json
python3 tools/ledger_score.py --dir /var/lib/h34_paper                                                           # verdict score
```

## What it writes (state dir, only)

* `trades.jsonl` / `trades.csv` — one line per closed virtual trade: rule, coin, side, signal bar close (KST), entry (next bar open),
  exit time + reason, entry/exit px, net R and net return at **0.15% and 0.30%** round-trip cost, size multiple, stop %,
  seconds between bar close and the record (`late` if > 90 s).
* `events.jsonl` — `paper_entry`, `signal_skipped` (reason: `limit_one_per_coin`, `limit_max_concurrent`, `limit_open_risk`,
  `limit_one_stop_loss`, `limit_portfolio_daily_5pct_kst`, `daily_cap_5pct_kst`, `open_position`, `next_bar_missing`,
  `rule_off_wind_down`), `signal_skipped_integrity` (data gap), `missing_signal_bar`, `catch_up_window_exceeded`.
* `state.json` (atomic replace after every processed bar; ledger lines are written first and are idempotent on their key, so a
  crash/restart neither duplicates nor drops a record), `status.json` (heartbeat: lag, open positions, counters), `recorder.lock`.

## Semantics worth knowing

* A bar `T` is processed once, in order, when it has closed **and** the next bar's open is published (entry price); after a 120 s
  grace the signal is logged as `next_bar_missing` instead of guessed. A still-forming bar is only ever read for its open.
* Rule parameters are **not** configurable (RSI 30/70, 0.5%/0.5%, 16 bars, costs 0.15%/0.30%, size 2%/(stop+0.15%)): they live in
  `core.py`, copied from TA's lock. The config holds rule on/off, the portfolio limits and the lock time only.
* Each rule keeps its own wallet and per-rule 5% KST cap (what the screen judged); the portfolio daily cap sums the rules'
  wallet-fraction losses (approximation, see the build note's open issues).
* Switching a rule off with a position open winds that position down to its exit, with no new entries; its wallet is kept.

## Adding a rule (H32, H34-A, H35, H36, H31, H38 …)

1. Write its pure detector on closed bars and (if needed) the exit types `core.manage_bar` lacks (signal exit, reversal, ATR stop),
   plus the series it needs in `feed.FEEDS_BASE` (4h, 1m …).
2. Register a `core.Rule` in `rules.IMPLEMENTED`; delete it from `PLANNED`.
3. Add replay-equals-screen test for the rule, then set `"enabled": true` in the config. Nothing else changes.

## Tests

```bash
PYTHONPATH=. /workspace/.venv-live6/bin/python -m pytest tests/h34_paper -q     # needs pandas+pyarrow+parquet for test_replay.py (skipped otherwise)
```
