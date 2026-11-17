"""Process entry point: REST client + websockets + engine, single-threaded event loop.

  events (websocket threads) ──queue──► engine.on_event   (immediate: breach guard, fills → reconcile, strategy)
  every loop                     ──────► engine.tick       (5 s REST reconcile safety net, stream health, bar decision)
"""
from __future__ import annotations

import logging
import os
import queue
import signal
import time

from .engine import ENTRY_ORDER, Settings, V6Engine
from .exchange import MAINNET_URL, TESTNET_URL, BinanceREST, ws_base_for
from .notify import Notifier
from .store import JsonStore
from .stream import MarketStream, UserStream

log = logging.getLogger("live_v6.runner")


def tg_prefix(network: str | None = None) -> str:
    network = network or os.getenv("LIVE_V6_NETWORK", "testnet")
    return "" if network == "mainnet" else "🧪[TESTNET·모의] "


def tg_mode(network: str | None = None) -> str:
    """Telegram is hard-disabled unless this is the live (mainnet) bot."""
    return "live" if (network or os.getenv("LIVE_V6_NETWORK", "testnet")) == "mainnet" else "testnet"


def make_notifier(network: str | None = None) -> Notifier:
    network = network or os.getenv("LIVE_V6_NETWORK", "testnet")
    path = os.getenv("LIVE_V6_ALERT_LOG", f"/var/lib/live_v6/{network}_alerts.jsonl")
    return Notifier(prefix=tg_prefix(network), mode=tg_mode(network), log_path=path)


def telegram_check(n: Notifier) -> int:
    """Go-live one-shot: exactly one confirmation message, and only in live mode. Returns the process exit code."""
    if not n.live:
        print("telegram-check refused: Telegram is disabled outside live mode (LIVE_V6_NETWORK=mainnet on the live host)")
        return 2
    if not n.configured:
        print("telegram-check: missing env: " + ", ".join(n.missing_env()))
        return 2
    ok = n.send("✅ live_v6 텔레그램 연결 확인 (go-live 점검 1회 메시지)", kind="telegram_check")
    print("sent" if ok else "send failed")
    return 0 if ok else 1


def check_frozen(cfg: Settings) -> None:
    """Live refuses any simultaneous-signal tie order other than the frozen README list (TA review item 1)."""
    if tuple(cfg.entry_order) != ENTRY_ORDER:
        raise SystemExit(f"entry_order {cfg.entry_order} != frozen ENTRY_ORDER {ENTRY_ORDER}")


def live_settings(name: str, **kw) -> Settings:
    """Live Settings per strategy. qrmtf (PM final 2026-10-30): 4 % risk, 12 % open-risk Σ, max 3 positions, margin ≤ 25 % of
    wallet per position, 10x max, longs + shorts, TP1 +1R 50 % → SL entry ± 0.15 %, TP2 +2R, 24 h time exit."""
    if name == "qrmtf":
        from .sizing import SizingParams
        sizing = SizingParams(risk_pct=4.0, max_risk_pct=5.0, portfolio_risk_cap=0.12, total_risk_cap=0.12, margin_cap=0.25,
                              max_leverage=10, size_on_stop_dist=True)   # max_risk_pct 5 % = 4 % + round-trip fee headroom
        kw = dict(dict(sizing=sizing, max_positions=3, max_same_side=2, enable_short=True, take_profit=True, tp1_r=1.0, tp1_frac=0.5,
                       tp2_r=None, be_offset=0.0015, be_fee=0.0005, trail_atr_k=2.0,   # TA 2026-11-04: E chandelier, no TP2
                       max_hold_s=24 * 3600, bar_delay_s=3,
                       peak_dd_guard=0.80, peak_dd_init=132.88,   # TA 2026-11-03: BE entry ± 0.15 %, peak-DD entry guard
                       peak_dd_release_s=24 * 3600,   # user 2026-11-13: peak-DD halt clears itself after 24 h
                       halt_fraction=None, daily_loss_halt=0.10, startup_leverage=10,
                       daily_halt_s=0, daily_day_offset_s=9 * 3600, daily_halt_flatten=False,   # user 2026-11-13: KST day, -10 % → no new entries till 00:00 KST   # user 2026-10-30: -25 % total halt removed → daily -10 %, 24 h
                       bar_stale_s=180.0), **kw)   # bar_stale 180 s: 1m cadence, 3 missed minutes → block new entries
    if name == "bundle_v5":
        # bundle_v5: the strategy's own book sizes / stops / trails (fixed intents); the engine keeps the owner guards
        # (KST-day −10 % no new entries, peak −20 % 24 h) and the order safety machinery. No TP, no engine trail/time exit.
        kw = dict(dict(symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"), max_positions=7,
                       enable_short=True, take_profit=False, trail_atr_k=0.0, max_hold_s=0,
                       peak_dd_guard=0.80, peak_dd_release_s=24 * 3600, halt_fraction=None, daily_loss_halt=0.10,
                       daily_halt_s=0, daily_day_offset_s=9 * 3600, daily_halt_flatten=False, bar_delay_s=3, bar_stale_s=180.0,
                       entry_mode=os.getenv("LIVE_V6_ENTRY_MODE", "market"),
                       postonly_timeout_s=float(os.getenv("LIVE_V6_POSTONLY_TIMEOUT_S", "300"))), **kw)
    return Settings(**kw)


def build(network: str | None = None):
    network = network or os.getenv("LIVE_V6_NETWORK", "testnet")
    if network == "mainnet":
        url, key, sec = MAINNET_URL, os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"]
    else:
        url, key, sec = TESTNET_URL, os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"]
    rest = BinanceREST(url, key, sec)          # guard_url refuses mainnet unless explicitly acknowledged
    name = os.getenv("LIVE_V6_STRATEGY", "qrmtf")        # qrmtf (2026-10-30); "h7t" = previous live; "v6_h7" = bar-close
    cfg = live_settings(name, use_streams=True)
    check_frozen(cfg)
    state = os.getenv("LIVE_V6_STATE", f"/var/lib/live_v6/{network}.json")
    if name == "qrmtf":
        from .strategies.qrmtf import QRMTF as Strat
    elif name == "h7t":
        from .strategies.h7t import H7T as Strat
    elif name == "bundle_v5":
        from .strategies.bundle_v5 import BundleV5 as Strat
    elif name == "v6_h7":
        from .strategies.v6_h7 import V6H7 as Strat
        cfg.bar_stale_s = max(cfg.bar_stale_s, cfg.funding_wait_s + 120)   # bar close may legitimately wait for funding
    else:
        raise SystemExit(f"unknown LIVE_V6_STRATEGY {name!r}")
    strat = Strat(params=cfg.params, kline_fetch=cfg.kline_fetch, bootstrap_bars=cfg.bootstrap_bars,
                  daily_fetch=cfg.daily_fetch, funding_lookback_ms=cfg.funding_lookback_ms)
    eng = V6Engine(rest, cfg, store=JsonStore(state), notifier=make_notifier(network), strategy=strat)
    from .deadman import DeadMan
    eng.deadman = DeadMan()                              # env HEARTBEAT_URL; no-op when unset
    from .tradelog import EventLog
    eng.events = EventLog(os.getenv("LIVE_V6_LOG_DIR") or os.path.dirname(state) or ".", network)   # live log v1 JSONL
    return rest, eng


def loop_once(eng, q, budget_s: float = 1.0, clock=time.time, block: bool = True, hooks=()):
    """One iteration of the production loop: drain websocket events for up to `budget_s`, then `eng.tick()` (REST
    reconcile, guards, 4h bar decision, dead-man). `block=False` drains without waiting (simulated-clock tests)."""
    deadline = clock() + budget_s
    while clock() < deadline or not block:
        try:
            ev = q.get(timeout=max(0.0, deadline - clock())) if block else q.get_nowait()
        except queue.Empty:
            break
        try:
            eng.on_event(ev)
        except Exception:  # noqa: BLE001  never let one event kill the loop; REST reconcile re-checks
            log.exception("event handling failed")
    try:
        eng.tick(force_reconcile=False)
    except Exception:  # noqa: BLE001
        log.exception("tick failed")
    for h in hooks:                                      # e.g. Telegram read-only commands; never raise into the loop
        try:
            h()
        except Exception:  # noqa: BLE001
            log.exception("loop hook failed")


def serve(eng, q, should_stop, clock=time.time, block=True, hooks=()):
    """Production loop (run() and the end-to-end runner test share it)."""
    eng.tick()
    while not should_stop():
        loop_once(eng, q, clock=clock, block=block, hooks=hooks)


NOISY_LOGGERS = ("httpx", "httpcore", "websockets")


def setup_logging():
    """Root handler → stderr (journald via systemd) at LIVE_V6_LOG (default INFO). The live_v6 INFO lines (bar_close, entered)
    are the journal's low-volume heartbeat; third-party libraries stay at WARNING (per-request lines would flood it)."""
    logging.basicConfig(level=os.getenv("LIVE_V6_LOG", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for noisy in NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def make_loop_io(eng, network, state_path, hooks, env):
    """Build measurement-only loop instrumentation, disabled only by literal '0'."""
    if env.get("LIVE_V6_STALL_METER") == "0":
        return queue.Queue(), None, hooks
    meter = None
    try:
        from .stallmeter import StallMeter, TimedQueue, install
        path = os.path.join(os.path.dirname(state_path) or ".", f"{network}_stall.jsonl")
        meter = StallMeter(path)
        meter.start()
        return TimedQueue(meter), meter, install(eng, meter, hooks) + [meter.maybe_flush]
    except Exception as e:  # noqa: BLE001  measurement must never stop the bot: run unmeasured
        if meter is not None:
            try:
                meter.close()
            except Exception:  # noqa: BLE001  cleanup cannot obstruct the fallback
                pass
        # Keep this independent of stallmeter: its import may be the failure.
        detail = f"{type(e).__name__}: {e}".replace("CRITICAL", "critical").replace("Traceback", "traceback")
        log.warning("stall meter disabled: %s", " ".join(detail.split())[:160])
        return queue.Queue(), None, hooks


def run(network=None):
    setup_logging()
    if os.getenv("LIVE_V6_PAPER") == "1":               # paper: public data only, no keys, no engine, no order client
        if os.getenv("LIVE_V6_STRATEGY") != "bundle_v5":
            raise SystemExit("LIVE_V6_PAPER=1 is implemented for LIVE_V6_STRATEGY=bundle_v5 only")
        from .bundle_paper import run_paper
        run_paper()
        return
    rest, eng = build(network)
    network = network or os.getenv("LIVE_V6_NETWORK", "testnet")
    state = os.getenv("LIVE_V6_STATE", f"/var/lib/live_v6/{network}.json")
    q, meter, _ = make_loop_io(eng, network, state, [], os.environ)
    ws = ws_base_for(rest.base_url)
    s = eng.strategy
    streams = [MarketStream(ws, eng.cfg.symbols, s.stream_intervals or ("1m",), s.wants_trades, q=q), UserStream(ws, rest, q=q)]
    for st in streams:
        eng._stream_up[st.name_] = False
        st.start()
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *a: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *a: stop.update(flag=True))
    from .tgcmd import maybe_start
    cmd = maybe_start(eng, network, os.getenv("LIVE_V6_CMD_LOG", os.path.join(
        os.path.dirname(os.getenv("LIVE_V6_STATE", f"/var/lib/live_v6/{network}.json")), f"{network}_commands.jsonl")))
    hooks = [cmd.poll] if cmd else []                  # read-only /status /today /more (mainnet only)
    if meter is not None:
        try:
            hooks = [meter.wrap("hook:" + getattr(h, "__name__", type(h).__name__), h, top=True)
                     for h in hooks] + [meter.maybe_flush]
        except Exception:  # noqa: BLE001  keep command handling and flushing if hook instrumentation fails
            hooks = hooks + [meter.maybe_flush]
    serve(eng, q, lambda: stop["flag"], hooks=hooks)
    if cmd:
        cmd.stop()
    for st in streams:
        st.stop()
    eng.tg.send("⏹ live_v6 종료 (거래소 손절은 그대로 유지)")
