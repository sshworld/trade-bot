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
    wallet per position, 10x max, longs + shorts, TP1 +1R 50 % → SL entry ± 0.1 %, TP2 +2R, 24 h time exit."""
    if name == "qrmtf":
        from .sizing import SizingParams
        sizing = SizingParams(risk_pct=4.0, max_risk_pct=5.0, portfolio_risk_cap=0.12, total_risk_cap=0.12, margin_cap=0.25,
                              max_leverage=10)            # max_risk_pct 5 % = 4 % + round-trip fee headroom
        kw = dict(dict(sizing=sizing, max_positions=3, enable_short=True, take_profit=True, tp1_r=1.0, tp1_frac=0.5,
                       tp2_r=2.0, be_offset=0.001, max_hold_s=24 * 3600, bar_delay_s=3), **kw)
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


def run(network=None):
    setup_logging()
    rest, eng = build(network)
    q: queue.Queue = queue.Queue()
    ws = ws_base_for(rest.base_url)
    s = eng.strategy
    streams = [MarketStream(ws, eng.cfg.symbols, s.stream_intervals or ("1m",), s.wants_trades, q=q), UserStream(ws, rest, q=q)]
    for st in streams:
        eng._stream_up[st.name_] = False
        st.start()
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *a: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *a: stop.update(flag=True))
    network = network or os.getenv("LIVE_V6_NETWORK", "testnet")
    from .tgcmd import maybe_start
    cmd = maybe_start(eng, network, os.getenv("LIVE_V6_CMD_LOG", os.path.join(
        os.path.dirname(os.getenv("LIVE_V6_STATE", f"/var/lib/live_v6/{network}.json")), f"{network}_commands.jsonl")))
    hooks = [cmd.poll] if cmd else []                  # read-only /status /today /more (mainnet only)
    serve(eng, q, lambda: stop["flag"], hooks=hooks)
    if cmd:
        cmd.stop()
    for st in streams:
        st.stop()
    eng.tg.send("⏹ live_v6 종료 (거래소 손절은 그대로 유지)")
