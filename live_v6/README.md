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
  L2 mismatch → exchange is truth; protected positions are left alone; unknown position → stop + alert.
  L3 flatten ALL + halt only on −15 % equity, a position still unprotected after L1, or API dead > 5 min with an
  unprotected position.
- Idempotent orders by clientOrderId (journal before send; unknown outcome → query, never double-send); restart
  resolves intents and re-arms every stop; ISOLATED set + read-back (failure blocks entries); 2.5 % total-risk cap
  and max positions re-checked on a fresh exchange read at the placement step; ledger vs income check.

## Commands (from the repo root)
```bash
VENV=/workspace/.venv-live6/bin/python
$VENV -m pytest live_v6/tests -m "not testnet and not slow"          # offline suite
$VENV -m pytest live_v6/tests -m testnet -v                          # TESTNET (real orders, DOGE/SOL/XRP, prefix v6t)
$VENV -m pytest live_v6/tests -m slow                                # replay vs trades_H7_100.csv
research/.venv/bin/python -m live_v6.replay.export_data              # one-off data export (research venv)
$VENV -m live_v6.replay.replay --order research --stop-fill research --out live_v6/replay/results/x.json
```

## Open questions for TA
1. Tie order of simultaneous entries: research = pandas sort artefact; replay matches only with it. SIX order gives
   268 vs 266 trades (halving at ≥3 open cascades). Live default = research order? (currently `entry_order=SIX`).
2. Exchange stop = rounded trigger on MARK_PRICE vs backtest raw stop on last-price lows (trigger-fill replay: same 266
   trades, 14 qty diffs, 1 exit-time diff, final wallet 370.52 vs 370.31).
3. Skip label `liq_guard` (spec) vs `leverage` (old code); BTC min notional floor 100 (v6) vs exchange 50.
4. Funding stamp not yet published at T: wait ≤ 600 s then skip `funding_data` — OK?
5. Stop rounded from the FILL (same distance) vs the bar open; pre-arm uses the book ask.
6. −15 % halt, 15-min act window, max_positions=6, unknown position counted as 1 % risk: not in the backtest.
7. Mark-stream breach (mark ≤ stop, exchange stop not fired after 2 s) → close that position only (L1).
8. Notion daily settlement not implemented (Telegram only).

## H7-T live (§8d) — `LIVE_V6_STRATEGY=h7t` (default)
- `strategies/h7t.py`: entry on the first websocket aggTrade ≥ prior-55-bar high + 1 tick inside the running 4h bar,
  filters/ATR as already confirmed (prior closed bar ATR, BTC200D of the last completed day at the bar open, last
  settled funding ≤ touch). MARKET entry; no resting entry orders ever (the only pre-placed order is the reduceOnly
  protective stop, which cannot open a position). One entry per bar; stopped → no re-entry in that bar; touched while
  the bot was down / stream gap → bar `missed` (REST 1m check), no catch-up; touch event older than 5 s → dropped.
- Entry slippage of the first 30 entries vs model (trigger + 2 bp): > 10 bp worse → alert only.

## Telegram
Env `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (both required; without them messages are only logged).
Messages (Korean): 🚨 incidents · 🟢 entry (symbol, side, qty, fill, stop, leverage, risk) · 🔵/🔴 exit (reason, qty,
entry → exit, stop, net PnL, R, fees, funding) · 📊 daily settlement at 00:00 KST · 💓 heartbeat every 4 h.
`python -m live_v6 tgtest` sends one real test message.
