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
- **429 / 418 (TA 2026-10-21):** Retry-After honoured (default 10 s / 120 s); no polling, NEW entries blocked, never a
  flatten by itself. 429: protective calls (stop / cancel / reduceOnly close + positions / open-order reads) still go out.
  418 = IP ban (Binance docs): 🚨 at once and NOTHING is sent until it ends, protective calls included; queued stop /
  close actions go out on the first tick after the ban. The exchange stop is the only protection during a 418.
  Protection monitor (user stream ORDER_TRADE_UPDATE / ALGO_UPDATE, no extra REST): a position's stop CANCELED / EXPIRED
  / REJECTED not by us → 🚨 + one replacement stop at once; replacement failed → reduceOnly MARKET close as soon as the
  mark crosses the original stop price.
- **Unknown positions (TA R4, 2026-10-21):** an exchange position that is NOT in the state file (opened by hand, or
  the state file was lost / corrupted) is NEVER market-closed by the bot — not by the strategy (`model_sync`), not by
  a breach / stop-failure close, not by flatten-all (`close()` refuses any symbol not in the state file). It is kept
  in `st["unknown"]`: 🚨 once on detection (Telegram on mainnet only; testnet/tests log only), new entries blocked for
  THAT coin only (`unknown_position` skip), its risk counted in the portfolio-risk sum and max positions. No exchange
  stop → a closePosition STOP_MARKET (MARK_PRICE) at the model's exit line (20-bar channel low for a long, high for a
  short), or 1×ATR(14, 4h) from the current mark if price is already beyond the line; channel/ATR data missing (e.g.
  at start-up, before the model bootstrap) → at once 3 % from the mark (`fallback_stop_pct`). A placed stop is never
  moved when data appears; existing stops are never moved or cancelled. **Last resort (protection beats ownership):**
  the exchange keeps REJECTING the stop and none is confirmed within 5 min of detection (`unknown_stop_deadline_s`)
  → reduceOnly MARKET close of that position + 🚨. Transient errors (timeouts / 5xx / no mark) are not rejections and
  never close. The detection time is persisted in the state file, so a restart keeps the original deadline; if the
  state file itself is lost, the position is detected anew and the 5-min window restarts (later, never earlier). Resolution is manual: close it by hand (the bot then clears it, ✅), or ops adopts it into the state
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

**qrmtf (2026-10-30):** the −25 % total halt is off (`halt_fraction=None`). Daily-loss halt instead (`daily_loss_halt=0.10`):
equity (wallet + unrealised, transfers excluded) ≤ 0.90 × the equity at 00:00 UTC (09:00 KST, `meta.dl_base`) → close every
state-file position (unknown ones untouched, TA R4), cancel bot orders, no new entries for 24 h from the trigger
(`meta.daily_halt`, survives restarts), then auto-resume. One 🚨 (with per-trade coin / side / PnL / entry TF scores) and one ✅
on resume, live mode only. Daily jsonl: `event=halt` line; `distance_to_halt` = % to the day line.

**Peak-drawdown entry guard (TA 2026-11-03/04, qrmtf `peak_dd_guard=0.80`, `peak_dd_init=132.88`):** `meta.peak_equity`
(name kept for state compatibility) = max(stored peak, every WALLET balance seen; realised only, uPnL never raises it;
persisted, not transfer-adjusted). The trigger is still on equity (wallet + uPnL). Equity < 0.80 × peak → `meta.peak_dd` set,
ONE 🚨 "고점 대비 -20% 도달", new entries blocked (skip reason `peak_dd`); open positions and their SL / TP are untouched.
Survives restarts; never auto-clears and `python -m live_v6 resume` does NOT clear it. The team clears it (Developer, after
TA judges; not the account owner) with the stdlib ops tool, no code change or redeploy:

    sudo systemctl stop live_v6-live
    sudo python3 /opt/tradebot/app/current/live_v6/tools/clear_peak_halt.py --by "Developer (TA ok <date>)" [--reset-peak] [--dry-run]
    sudo systemctl start live_v6-live

It refuses while `live_v6-live` is active, backs up the state (`mainnet.json.bak-peakclear-<UTC>`), removes `peak_dd`,
optionally rebases the peak to the last recorded wallet (without `--reset-peak` the engine halts again at once if equity is
still under the line), and logs who / when / sudo user / old halt / peak before-after in `meta.peak_dd_clears` and
`/var/lib/live_v6-live/peak_dd_clears.jsonl`.

**BinHV45 (TA PASS 2026-11-10, `LIVE_V6_STRATEGY=binhv45`, the process default):** long only, closed 1m,
Bollinger(40, 2, ddof=1), `buy_bbdelta=7`, `buy_closedelta=17`, `buy_tail=25`. Post-only (GTX) limit buy at the
signal bar's close; a fill is taken only from the exchange report; the order is cancelled 24h after the signal if it
is still open. One position or one resting entry per symbol. While that limit rests and the symbol is flat, the
engine keeps a Binance countdown cancel (`POST /fapi/v1/countdownCancelAll`, 120s, refreshed about every 30s) so a
dead process cannot leave the limit up. A reduce-only qty stop is not rested under the limit: the exchange cancels
those within about a second when there is no position. On a fill the countdown is stopped. That call does not cancel a resting take-profit or a closePosition
stop. If the fill lands while the order lookup is down, there is no journal yet and the pending
intent does not skip protection: reconcile audits the exchange position and places a closePosition SL and a
covering TP anyway. A foreign closePosition stop is
cancelled (one alert) and replaced with this entry's `{cid}sN` stop. `-4130` is a second closePosition stop,
not a closePosition take-profit: the engine cancels the other stop and retries, and does not market-close
while any closePosition stop is still on the symbol. The intent stays until the lookup succeeds. A partial fill keeps the remainder of the limit working, places a closePosition SL, and resizes
the reduce-only TP to the live position (`journal["tp"]` stays set while the position exists). On the fill:
full-qty `TAKE_PROFIT_MARKET` at
`entry*1.020` (`CONTRACT_PRICE`) and `STOP_MARKET` at `entry*0.9925` (`MARK_PRICE`), both tick-rounded toward entry.
Risk 1% of equity at that 0.75% stop (notional ≈ 1.333× equity), leverage fixed at 3x and never raised. `restart_gate_mode`
`halt_on_negative` (default) blocks new entries once the net after fees of binhv45 trades closed since
`meta.restart_gate_anchor` (set on the first binhv45 start, kept across restarts) is negative. One alert.
The halt stays, including after a restart, until `live_v6/tools/clear_restart_gate.py` moves the anchor forward.
The open position keeps its SL and TP. qrmtf trades, and anything closed before the anchor, are not counted.
`lock30` stays selectable: after 30 binhv45 trades since the anchor, if their net is negative, one alert and stay at 3x. Daily −10% halt and the peak-drawdown latch are unchanged
(`clear_peak_halt.py` is still the only clear). Rollback to the previous entry: `LIVE_V6_STRATEGY=qrmtf`.

**Live exit (TA lock, qrmtf `exit_mode="full_tp_pct"`, `tp_pct=0.002`):** one reduce-only TAKE_PROFIT_MARKET for the full
quantity at entry×(1±0.002), workingType CONTRACT_PRICE. Rounded to the tick toward entry (an exact half-tick goes
toward entry) and never past the raw 0.2% level. Price already through that level → reduce-only market for the
remaining qty. No TP1/TP2 split, no breakeven move, no ATR trail in this mode. The initial SL stays MARK_PRICE
STOP_MARKET. 24 h time exit, the 10x cap and the daily −10 % halt are unchanged. Reconcile: a position missing its SL
or this TP gets one 🚨 per incident and the order is re-placed from a fresh position read (qty never above the live
position). Any existing reduce-only TAKE_PROFIT_MARKET on the closing side counts as the TP, so a restart does not
place a second one. `exit_mode="r"` keeps the previous path (`tp1_r` / `tp2_r` / trail / breakeven).

**E chandelier (`exit_mode="r"`, `trail_atr_k=2.0`, `be_fee=0.0005`, `be_offset=0.0015`, `tp2_r=None`):** from entry the
exchange SL trails `tighter(SL, best ∓ 2·ATR14)` — ATR14 = Wilder ATR of the last CLOSED 1h
bar (one 150-bar read per hour, cached in the journal), best = the 1m high (long) / low (short) extreme since entry, read
once per closed minute (effective from the next candle). Never looser than the current / initial SL. TP1 +1R 50 %
unchanged; after TP1 SL = tighter(SL, be·(1 ± 0.0015)) with be = fee-inclusive breakeven entry·(1±f)/(1∓f), f = 0.0005
(≈ entry ± 0.25 %). No TP2 order. A move = new reduceOnly STOP_MARKET (MARK_PRICE, qty = position) placed and read back,
THEN the old stop cancelled (never zero protection; a brief overlap of two reduceOnly stops). Mark already through the
new level → reduceOnly market close (`trail_stop_breach`). `best`, `trail_t`, `atr`, `atr_h`, `trailed` persist in the
journal, so a restart catches up from the 1m bars and the SL never moves back. Positions opened by an earlier build are
adopted: best seeded from entry + catch-up, TP2 cancelled, an old BE stop tightened to the fee-BE floor. 24 h time exit,
daily −10 % halt, dir cap and peak guard unchanged. Exit label `trail_stop` (추적 손절).

**Same-direction cap (TA PASS 2026-11-03 23:26 KST, qrmtf `max_same_side=2`):** at most 2 open positions on one side (long
or short); the total cap stays `max_positions=3`. Gate order: max_positions → dir_cap → risk caps → margin, at both the first
check and the final check right before the order. The count comes from the fresh exchange positions read (state-file and
unknown positions alike), so it holds after a restart. A refused 3rd same-side signal is logged quietly: skip reason `dir_cap`
(skip log + `*_skips.jsonl`) and a qrmtf signal-log line `kind=skipped reason=dir_cap` with coin / side / time / scores; no 🚨.
Replay basis (Jul–Sep, live rules, BE ±0.10 %): 157 trades, mean −0.148 R, max DD 58.8 % vs 168 / −0.171 R / 68.1 % without it.
**The first-30-trades live comparison baseline is −0.148 R** for trades opened after this deploy (TA 2026-11-03).

**Daily reconciliation (read-only):** `BINANCE_API_KEY=… BINANCE_API_SECRET=… python3 live_v6/tools/reconcile_daily.py --day
YYYY-MM-DD --trades-log /var/lib/live_v6-live/mainnet_trades.jsonl` prints the recorded net of the trades closed that UTC day,
the wallet change from `/fapi/v1/income` (all types except TRANSFER, shown apart), the gap, its timing part (fees / funding of
trades open across midnight) and the unexplained residual (should be 0).

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
