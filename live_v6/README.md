# live_v6 — clean live engine for the v6 H7 row (v4 base + H7 funding filter, 6 coins)

Built fresh per Trading Advisor's spec (2026-10-20); only verified safety rules were ported from live_v1.

## Architecture
```
Binance websockets ──► stream.MarketStream (markPrice@1s, kline 1m/4h, opt. aggTrade)  ┐
                   └─► stream.UserStream  (listenKey, keepalive 30 min; fills/positions)  ├─► queue ─► engine.on_event
REST (exchange.BinanceREST) ◄── engine.tick: 5 s reconcile (safety net), stream health, bar decision ◄────────┘
strategies/  pluggable: Strategy.on_event / on_bar_close → intents {enter, exit, skip}; the engine owns sizing,
             execution, stops, halts. v6_h7.py decides once per CLOSED 4h bar (research timing, unchanged).
             Future intrabar H12/H13: implement on_event + a "limit_enter" intent; execution/safety untouched.
```
Files: `engine.py` execution + safety · `strategy.py` pure v6 model (ATR/M20/H7/regime) · `sizing.py`/`rules.py`
§8a sizing, leverage, liq guard · `exchange.py` REST + mainnet guard · `events.py`/`stream.py` websockets ·
`runner.py`/`__main__.py` process · `replay/` deterministic replay · `tools/verify_stops.py` independent gate check.

## Safety rules (TA-binding)
- Mainnet is impossible unless `LIVE_V6_NETWORK=mainnet` AND `LIVE_V6_MAINNET_ACK=real-money` and not under pytest;
  tests strip `BINANCE_API_KEY/SECRET` before import and refuse testnet vars that hash-match a live key.
- **No fill→stop window:** a reduceOnly STOP_MARKET (planned qty) is confirmed on the exchange BEFORE the entry is sent;
  after the fill a closePosition STOP_MARKET (fill − same distance) is confirmed, THEN the pre-arm is cancelled.
  Every replacement places the new stop first (Binance allows one closePosition stop per side → overlap with a qty stop).
- Stops/halt exits: exchange STOP_MARKET (MARK_PRICE) or MARKET reduceOnly — never limit-with-timeout.
  "Cancel unfilled, don't chase" applies only to entries/take-profits. No averaging, ever. Partial fill → stop covers the
  filled qty; a remainder is closed in ONE reduceOnly order (no dust); a failed final exit is retried until flat + 🚨.
- §8c tiered response: L0 transient (ws drop, timeout, 5xx, 429/418) → never close; pause NEW entries, reconnect,
  reconcile, alert only after 60 s. L1 stop missing/rejected → re-place 3× within 10 s, else close ONLY that position.
  L2 mismatch → exchange is truth; protected positions are left alone; unknown position → see below (never closed).
  L3 flatten ALL + halt only on strategy equity ≤ `halt_fraction` (0.75) × S0 (−25 %, §8e-2), a position still unprotected after L1, or API dead > 5 min with an
  unprotected position. Flatten-all closes only positions in the state file.
- **Unknown positions (TA R4, 2026-10-21):** an exchange position that is NOT in the state file (opened by hand, or
  the state file was lost / corrupted) is NEVER market-closed by the bot — not by the strategy (`model_sync`), not by
  a breach / stop-failure close, not by flatten-all (`close()` refuses any symbol not in the state file). It is kept
  in `st["unknown"]`: 🚨 once on detection (Telegram on mainnet only; testnet/tests log only), new entries blocked for
  THAT coin only (`unknown_position` skip), its risk counted in the portfolio-risk sum and max positions. No exchange
  stop → a closePosition STOP_MARKET (MARK_PRICE) at the model's exit line (20-bar channel low for a long, high for a
  short), or 1×ATR(14, 4h) from the current mark if price is already beyond the line. Existing stops are never moved
  or cancelled. Resolution is manual: close it by hand (the bot then clears it, ✅), or ops adopts it into the state
  file with `python -m live_v6.tools.adopt_position --state … --sym … --unit …` (dry run by default; `--apply` only
  with the bot unit stopped; long only; see the tool's docstring — without a matching model trade the strategy will
  close an adopted position at the next 4h close).
- Idempotent orders by clientOrderId (journal before send; unknown outcome → query, never double-send); restart
  resolves intents and re-arms every stop; ISOLATED set + read-back (failure blocks entries); 2.5 % total-risk cap
  and max positions re-checked on a fresh exchange read at the placement step; ledger vs income check.

## Commands (from the repo root)
```bash
VENV=/workspace/.venv-live6/bin/python
$VENV -m pip install -r live_v6/requirements-dev.txt                 # pytest + pylint (W0101 check must run)
LIVE_V6_REQUIRE_PYLINT=1 $VENV -m pytest live_v6/tests -m "not testnet and not slow"   # offline suite
$VENV -m pytest live_v6/tests -m testnet -v                          # TESTNET (real orders, DOGE/SOL/XRP, prefix v6t)
$VENV -m pytest live_v6/tests -m slow                                # replay vs trades_H7_100.csv
research/.venv/bin/python -m live_v6.replay.export_data              # one-off data export (research venv)
research/.venv/bin/python live_v6/replay/export_1m.py                # 1m bars for the H7-T replay
$VENV -m live_v6.replay.replay_h7t --out live_v6/replay/results/replay_h7t.json   # vs trades_H7T_100.csv
$VENV -m live_v6.replay.replay --order research --stop-fill research --out live_v6/replay/results/x.json
```

## Open questions for TA
1. ~~Tie order~~ → resolved by TA review (57b0888), see "Simultaneous-signal tie order (FROZEN)" below. Note: the
   research order is not a fixed coin order, so the frozen list reproduces research up to 2025-04-23 only.
2. Exchange stop = rounded trigger on MARK_PRICE vs backtest raw stop on last-price lows (trigger-fill replay: same 266
   trades, 14 qty diffs, 1 exit-time diff, final wallet 370.52 vs 370.31).
3. Skip label `liq_guard` (spec) vs `leverage` (old code); BTC min notional floor 100 (v6) vs exchange 50.
4. Funding stamp not yet published at T: wait ≤ 600 s then skip `funding_data` — OK?
5. Stop rounded from the FILL (same distance) vs the bar open; pre-arm uses the book ask.
6. −25 % halt (halt_fraction 0.75, §8e-2), 15-min act window, max_positions=6, unknown position counted in the portfolio risk (|mark − stop| × qty / capital, floor 1 %): not in the backtest.
7. Mark-stream breach (mark ≤ stop, exchange stop not fired after 2 s) → close that position only (L1).
8. Notion daily settlement not implemented (Telegram 📊 only).
9. §8e-2 sizing base: C0 + REALISED PnL (= full wallet, as the backtest's realised-only W); the halt uses equity incl.
   unrealised. Confirm sizing should not use unrealised equity.
10. H7-T latency: touch → MARKET fill measured 2.6 s on testnet from this box (≈ 8 REST pre-checks incl. the fresh
    placement-gate read and the pre-armed stop); from a Tokyo VPS this should be ≪ 1 s. Slippage monitor alerts if worse.
11. ~~Phantom model hold~~ → fixed (TA review 57b0888): when reconcile finds the exchange flat but the journal + model
    still hold the same trade (stopped out while the bot was down), the model trade is closed as a stop-out and
    recorded (`strategy.state.model_stopouts`, trade record `model_closed: stop_out`); H7-T also marks that 4h bar
    `stopped` (no re-entry in it). Sizing-skip virtual holds (no live journal) stay untouched (research semantics).
12. H7-T backtest MDD (MTM) 27.7 % > the 25 % halt: a live halt is possible inside the backtest history (the realised-only
    replay did not trigger it).

## Simultaneous-signal tie order (FROZEN — TA review 57b0888, do not change without TA review)
When several symbols signal at the same 4h close (v6 H7 bar-close entries), they are sized and placed in this order:

    BTCUSDT, ETHUSDT, BNBUSDT, DOGEUSDT, XRPUSDT, SOLUSDT

`engine.ENTRY_ORDER`; it is the `Settings.entry_order` default and `runner.check_frozen` refuses to start live with
anything else. Why this list: the research portfolio (`research/v6.py::portfolio`) sorts the concatenated trades with
pandas' default (unstable) quicksort, so its tie order is a per-timestamp artefact, not a fixed coin order — e.g. the
two full 6-coin ties are BTC,ETH,BNB,DOGE,XRP,SOL (2023-01-14 00:00 UTC) and SOL,BNB,XRP,DOGE,ETH,BTC
(2025-04-23 00:00 UTC); with same-side halving at ≥3 open positions they need opposite coins halved, so no fixed list
can reproduce both. The frozen list is the research order of the first 6-coin tie: the replay with it matches the
research trades exactly up to 2025-04-23 and ends at 268 vs 266 trades (2 extra: ETH 2025-04-23 00:00 UTC, BTC
2025-06-29 12:00 UTC, which research skipped for min-notional after halving), final wallet 369.81 vs 370.31 USDT.
Every other tested fixed list (SIX and the 4 lists closest to research) diverges from 2023-01-14 already (216 qty
diffs). `replay --order research` (per-timestamp research order) stays as a validation-only harness: 266/266 exact.
H7-T (the live strategy) enters on websocket touches one event at a time → ties are resolved by arrival; the 355
research H7-T trades contain no simultaneous entries, so this order does not affect H7-T.

## H7-T live (§8d) — `LIVE_V6_STRATEGY=h7t` (default)
- `strategies/h7t.py`: entry on the first websocket aggTrade ≥ prior-55-bar high + 1 tick inside the running 4h bar,
  filters/ATR as already confirmed (prior closed bar ATR, BTC200D of the last completed day at the bar open, last
  settled funding ≤ touch). MARKET entry; no resting entry orders ever (the only pre-placed order is the reduceOnly
  protective stop, which cannot open a position). One entry per bar; stopped → no re-entry in that bar; touched while
  the bot was down / stream gap → bar `missed` (REST 1m check), no catch-up; touch event older than 5 s → dropped.
- Entry slippage of the first 30 entries vs model (trigger + 2 bp): > 10 bp worse → alert only.

## Capital & halt (§8e-2)
S0 = futures wallet at live start (persisted). Capital C0 = `capital_fraction` (1.0) × S0; sizing on C0 + realised PnL
since start (transfers excluded); margin guard: margin in use + new margin ≤ strategy equity. Flatten all + halt when
strategy equity (incl. unrealised, income TRANSFER rows excluded; a breach forces a fresh transfer sync first) ≤
`halt_fraction` (0.75) × C0. `halt_fraction` is the single source of truth (also §8c L3(a)).

## Websocket endpoints (network-specific, `stream.market_url` / `stream.user_url`)
- Mainnet: legacy `fstream.binance.com/ws` and `/stream` were retired on 2026-04-23 → market data
  `wss://fstream.binance.com/market/stream?streams=…` (markPrice@1s, kline, aggTrade), user data
  `wss://fstream.binance.com/private/ws?listenKey=K&events=ORDER_TRADE_UPDATE/ACCOUNT_UPDATE/ALGO_UPDATE/STRATEGY_UPDATE/CONDITIONAL_ORDER_TRIGGER_REJECT/listenKeyExpired`
  (no payload without `events`).
- Testnet (`fstream.binancefuture.com`): legacy `/stream?streams=…` and `/ws/<listenKey>` (still work there).
- `tools/ws_check_mainnet.py --minutes N`: READ-ONLY mainnet check of those URLs (6 coins markPrice@1s + kline_1m and
  the user stream; only listenKey create/keepalive, never deleted, no orders) → message counts / max gaps. Run on the
  VPS (the box is geo-blocked).

## Market-data staleness guard (TA)
Per feed the strategy subscribes (mark, kline; + aggTrade for H7-T): silent > `market_stale_s` (60 s) → block NEW
entries (`market_data_stale`) + one 🚨 (alerts log; Telegram only in live mode). Positions and their exchange stops are
untouched, nothing is closed (§8c L0). Fresh data on every feed → unblocked + ✅ recovery notice. (The 15 s
`stream_stale` pause stays as the fast L0 entry pause.)

## Dead-man heartbeat
`HEARTBEAT_URL` (e.g. healthchecks.io): GET every 60 s while healthy (started, not halted, REST reconcile OK in the
last 15 s, no unprotected position). Unset → no-op.
**Production: leave it unset in the bot env** (TA review 950438b). The external `deploy/heartbeat_ping.sh` (own env
file) is the dead-man; it also checks bar progress and sends `/fail`, which an in-process success ping on the same
URL would overwrite within 60 s. `tests/test_deadman.py::test_build_without_heartbeat_url_never_pings` pins the no-op.

## Telegram
Env `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (both required; without them messages are only logged).
Messages (Korean): 🚨 incidents · 🟢 entry (symbol, side, qty, fill, stop, leverage, risk) · 🔵/🔴 exit (reason, qty,
entry → exit, stop, net PnL, R, fees, funding) · 📊 daily settlement at 00:00 KST · 💓 heartbeat every 4 h.
**Only the live (mainnet) bot ever sends to Telegram** (`Notifier.mode == "live"`, set by `runner.tg_mode` only for
`LIVE_V6_NETWORK=mainnet`; the default mode is not live). Testnet, tests, replay and tools never call the Telegram API,
even with the env vars set. Every message that would be sent is appended to the alerts log
(`LIVE_V6_ALERT_LOG`, default `/var/lib/live_v6/<network>_alerts.jsonl`; also written in live mode) — one JSON line:
`event_ts` (what triggered it: touch/signal for entries, exit fill for exits, fault start for transient alerts,
else = decision), `decision_ts` (engine clock when it decided to send), `delay_s`, `type` (alert/entry/exit/daily/
heartbeat/start/resume/…), `mode`, `sent`, full `text`.
Go-live: `LIVE_V6_NETWORK=mainnet python -m live_v6 --telegram-check` sends ONE confirmation message (refuses in
any other mode). `tools/tg_e2e.py` only prints/logs the message set (never sends).
