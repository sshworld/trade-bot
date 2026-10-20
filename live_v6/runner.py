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

from .engine import Settings, V6Engine
from .exchange import MAINNET_URL, TESTNET_URL, BinanceREST, ws_base_for
from .notify import Notifier
from .store import JsonStore
from .stream import MarketStream, UserStream

log = logging.getLogger("live_v6.runner")


def build(network: str | None = None):
    network = network or os.getenv("LIVE_V6_NETWORK", "testnet")
    if network == "mainnet":
        url, key, sec = MAINNET_URL, os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"]
    else:
        url, key, sec = TESTNET_URL, os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"]
    rest = BinanceREST(url, key, sec)          # guard_url refuses mainnet unless explicitly acknowledged
    cfg = Settings(use_streams=True)
    state = os.getenv("LIVE_V6_STATE", f"/var/lib/live_v6/{network}.json")
    name = os.getenv("LIVE_V6_STRATEGY", "h7t")          # §8d: live v1 = H7-T; "v6_h7" = bar-close entries
    if name == "h7t":
        from .strategies.h7t import H7T as Strat
    elif name == "v6_h7":
        from .strategies.v6_h7 import V6H7 as Strat
    else:
        raise SystemExit(f"unknown LIVE_V6_STRATEGY {name!r}")
    strat = Strat(params=cfg.params, kline_fetch=cfg.kline_fetch, bootstrap_bars=cfg.bootstrap_bars,
                  daily_fetch=cfg.daily_fetch, funding_lookback_ms=cfg.funding_lookback_ms)
    eng = V6Engine(rest, cfg, store=JsonStore(state), notifier=Notifier(), strategy=strat)
    from .deadman import DeadMan
    eng.deadman = DeadMan()                              # env HEARTBEAT_URL; no-op when unset
    return rest, eng


def run(network=None):
    logging.basicConfig(level=os.getenv("LIVE_V6_LOG", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
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
    eng.tick()
    while not stop["flag"]:
        deadline = time.time() + 1.0
        while time.time() < deadline:
            try:
                ev = q.get(timeout=max(0.0, deadline - time.time()))
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
    for st in streams:
        st.stop()
    eng.tg.send("⏹ live_v6 종료 (거래소 손절은 그대로 유지)")
