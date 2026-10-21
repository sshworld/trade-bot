"""Websocket layer faults: entries blocked while a feed is down/stale, REST reconcile keeps protecting positions,
resubscribe on recovery, user-stream fills trigger an immediate reconcile, pluggable strategy on the event stream.
Offline tests drive the engine with synthetic events; testnet tests use the real Binance TESTNET websockets."""
import queue
import time
from decimal import Decimal

import pytest

from live_v6 import engine as E
from live_v6.events import Kline, Mark, OrderUpdate, StreamStatus, Trade, parse_market, parse_user
from live_v6.exchange import TESTNET_WS, ws_base_for, TESTNET_URL, MainnetForbidden
from live_v6.strategies.base import Strategy, enter
from live_v6.stream import USER_EVENTS, MarketStream, UserStream, market_url, user_url

from .conftest import unique_T

DOGE = "DOGEUSDT"


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t


def stream_engine(b, **kw):
    eng = b.engine(use_streams=True, **kw)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None   # bar decisions off (covered by test_bar_close_live)          # these tests exercise the stream/safety path only
    eng.startup()
    return eng


# ───────────── offline ─────────────
def test_ws_down_blocks_entries_rest_reconcile_takes_over(offline):
    eng = stream_engine(offline)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T())
    eng.on_event(StreamStatus("market", False, "test drop"))
    assert E.WS_STALE in eng.blocks and not eng.entries_allowed()
    assert not eng.enter("SOLUSDT", offline.stop_dist("SOLUSDT"), unique_T())
    assert eng.meta["skip_log"][-1][2] == "safety_block"
    for o in offline.stops(DOGE):                    # stop vanishes while the stream is down
        offline.inner.cancel(DOGE, o)
    eng.tick()                                       # REST reconcile (safety net) re-arms it
    assert len(offline.stops(DOGE)) == 1
    offline.assert_safe()
    eng.on_event(StreamStatus("market", True, "reconnected"))
    assert eng._dirty                                # resubscribed → immediate reconcile on next tick
    eng.tick(force_reconcile=False)
    assert not eng._dirty and E.WS_STALE not in eng.blocks and eng.entries_allowed()


def test_ws_silent_feed_is_stale(offline):
    clk = Clock()
    eng = stream_engine(offline, clock=clk, stream_stale_s=15)
    eng.stream_health()
    assert eng.entries_allowed()
    clk.t += 16                                      # socket "up" but no market events for 16 s
    eng.stream_health()
    assert E.WS_STALE in eng.blocks
    eng.on_event(Mark(DOGE, Decimal("0.15"), int(clk.t * 1000)))
    eng.stream_health()
    assert E.WS_STALE not in eng.blocks


def test_user_stream_down_also_blocks(offline):
    eng = stream_engine(offline)
    eng.on_event(StreamStatus("user", False, "listenKeyExpired"))
    eng.stream_health()
    assert E.WS_STALE in eng.blocks
    eng.on_event(StreamStatus("user", True))
    eng.stream_health()
    assert eng.entries_allowed()


def test_order_update_triggers_immediate_reconcile(offline):
    clk = Clock()
    eng = stream_engine(offline, clock=clk)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T())
    eng.tick()
    stop = Decimal(eng.st["pos"][DOGE]["stop_px"])
    offline.inner.set_price(DOGE, stop - Decimal("0.001"))     # exchange stop fires
    eng.on_event(OrderUpdate(DOGE, {"X": "FILLED"}, 0))
    eng.tick(force_reconcile=False)                  # same second: no 5 s wait
    assert DOGE not in eng.st["pos"] and offline.amt(DOGE) == 0
    assert eng.meta["trades"][-1]["sym"] == DOGE


def test_mark_breach_on_stream_closes_only_that_position(offline):
    eng = stream_engine(offline)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert eng.enter("SOLUSDT", offline.stop_dist("SOLUSDT"), unique_T())
    offline.inner.stops_fire = False                 # exchange stop "does not fire"
    stop = Decimal(eng.st["pos"][DOGE]["stop_px"])
    offline.inner.price[DOGE] = stop - Decimal("0.001")
    eng.on_event(Mark(DOGE, stop - Decimal("0.001"), 0))   # reacts on the stream tick, not the next 5 s reconcile
    assert offline.amt(DOGE) == 0 and offline.amt("SOLUSDT") > 0 and offline.stops("SOLUSDT")
    assert not eng.meta.get("halted") and any(m.startswith("🚨") for m in eng.tg.sent)


def test_overreaction_ws_down_30s_offline(offline):
    """§8c: websocket down 30 s while holding → entries paused, REST reconcile every 5 s, ZERO close orders,
    no alert (< 60 s), resume on reconnect."""
    clk = Clock()
    eng = stream_engine(offline, clock=clk)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert eng.enter("SOLUSDT", offline.stop_dist("SOLUSDT"), unique_T())
    n_alerts = len([m for m in eng.tg.sent if m.startswith("🚨")])
    eng.on_event(StreamStatus("market", False, "drop"))
    eng.on_event(StreamStatus("user", False, "drop"))
    n_rec = 0
    real = eng.reconcile

    def counted():
        nonlocal n_rec
        n_rec += 1
        real()
    eng.reconcile = counted
    for _ in range(6):
        clk.t += 5
        eng.tick(force_reconcile=False)
        assert not eng.entries_allowed()
    assert n_rec == 6                                # REST safety net took over
    assert not [c for c in offline.fx.calls if c[0] == "market" and c[1][4]]
    assert len([m for m in eng.tg.sent if m.startswith("🚨")]) == n_alerts
    for name in ("market", "user"):
        eng.on_event(StreamStatus(name, True, "reconnected"))
    eng.on_event(Mark(DOGE, Decimal("0.15"), 0))
    eng.tick(force_reconcile=False)
    assert eng.entries_allowed() and not eng.meta.get("halted")
    offline.assert_safe()


def test_mark_breach_check_is_throttled(offline):
    clk = Clock()
    eng = stream_engine(offline, clock=clk)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T())
    calls = []
    eng.breach_check = lambda *a: calls.append(a)
    stop = Decimal(eng.st["pos"][DOGE]["stop_px"])
    for _ in range(10):                              # 1 s mark stream below the stop
        eng.on_event(Mark(DOGE, stop - Decimal("0.001"), 0))
    assert len(calls) == 1
    clk.t += 5
    eng.on_event(Mark(DOGE, stop - Decimal("0.001"), 0))
    assert len(calls) == 2


class PingStrategy(Strategy):
    """Toy intrabar strategy: buys DOGE on the first mark event. Proves a strategy plugs into the event stream and
    its intents go through the engine's sizing + safety gates unchanged."""
    name = "ping"
    stream_intervals = ("1m",)

    def on_event(self, ev, ctx):
        if isinstance(ev, Mark) and ev.sym == DOGE and not self.state.get("done"):
            self.state["done"] = True
            return [enter(DOGE, Decimal(str(ev.price)) * Decimal("0.03"), ctx.now_ms())]
        return []


def test_pluggable_strategy_on_event_stream(offline):
    eng = stream_engine(offline, strategy=PingStrategy())
    eng.on_event(StreamStatus("market", False))
    eng.on_event(Mark(DOGE, Decimal("0.15"), 0))     # blocked while stale → skipped, never sent
    assert offline.amt(DOGE) == 0 and eng.meta["skip_log"][-1][2] == "safety_block"
    eng.strategy.state.clear()
    eng.on_event(StreamStatus("market", True))
    eng.stream_health()
    eng.on_event(Mark(DOGE, Decimal("0.15"), 0))
    assert offline.amt(DOGE) > 0 and len(offline.stops(DOGE)) == 1
    offline.assert_safe()


def test_event_parsers():
    m = parse_market({"stream": "dogeusdt@markPrice@1s", "data": {"e": "markPriceUpdate", "s": "DOGEUSDT", "p": "0.1500", "E": 1}})
    assert isinstance(m, Mark) and m.price == Decimal("0.1500")
    k = parse_market({"data": {"e": "kline", "s": "DOGEUSDT", "E": 2, "k": {"i": "4h", "t": 0, "T": 1, "o": "1", "h": "2",
                                                                           "l": "0.5", "c": "1.5", "x": True}}})
    assert k.interval == "4h" and k.closed and k.bar["high"] == Decimal("2")
    assert isinstance(parse_user({"e": "ORDER_TRADE_UPDATE", "E": 3, "o": {"s": "DOGEUSDT"}}), OrderUpdate)
    st = parse_user({"e": "listenKeyExpired", "E": 4})
    assert isinstance(st, StreamStatus) and not st.up


def _kline(sym, t_ms):
    o = t_ms // 60000 * 60000
    return Kline(sym, "1m", {"open_time": o, "open": 1, "high": 1, "low": 1, "close": 1, "close_time": o + 59999}, False, t_ms)


def _close_orders(b):
    return [c for c in b.fx.calls if c[0] == "market" and len(c[1]) > 4 and c[1][4]]


def test_market_data_stale_60s_blocks_entries_alerts_no_close_and_recovers(offline):
    """TA staleness guard: mark/kline silent > 60 s → NEW entries blocked + 🚨 (alerts log), positions and their
    exchange stops untouched (zero closes), fresh data on every feed → unblocked + recovery notice."""
    clk = Clock()
    eng = stream_engine(offline, clock=clk)
    assert eng.expected_feeds() == ("mark", "kline")
    assert eng.enter(DOGE, offline.stop_dist(), unique_T())
    stops0 = [o["id"] for o in offline.stops(DOGE)]
    t_last = clk.t
    eng.on_event(Mark(DOGE, Decimal("0.15"), int(t_last * 1000)))
    eng.on_event(_kline(DOGE, int(t_last * 1000)))
    for _ in range(12):                                     # 60 s of silence: still nothing (> 60 s required)
        clk.t += 5
        eng.on_event(StreamStatus("user", True))
        eng.market_data_guard()
    assert E.MARKET_STALE not in eng.blocks
    clk.t += 1
    eng.tick(force_reconcile=False)
    assert E.MARKET_STALE in eng.blocks and not eng.entries_allowed()
    al = [r for r in eng.tg.records if r["type"] == "alert" and "시장 데이터" in r["text"]]
    assert len(al) == 1 and 60 < al[0]["delay_s"] <= 61.5 and "mark" in al[0]["text"] and "kline" in al[0]["text"]
    assert not eng.enter("SOLUSDT", offline.stop_dist("SOLUSDT"), unique_T())
    for _ in range(6):                                      # outage continues: no repeat alert, no close
        clk.t += 5
        eng.tick(force_reconcile=False)
    assert len([r for r in eng.tg.records if "시장 데이터" in r["text"] and r["type"] == "alert"]) == 1
    assert not _close_orders(offline) and [o["id"] for o in offline.stops(DOGE)] == stops0
    eng.on_event(Mark(DOGE, Decimal("0.15"), int(clk.t * 1000)))          # mark only → kline still stale
    eng.tick(force_reconcile=False)
    assert E.MARKET_STALE in eng.blocks
    eng.on_event(_kline(DOGE, int(clk.t * 1000)))
    eng.tick(force_reconcile=False)
    assert E.MARKET_STALE not in eng.blocks and eng.entries_allowed()
    assert any(r["type"] == "recovery" and "시장 데이터 수신 재개" in r["text"] for r in eng.tg.records)
    assert not _close_orders(offline) and not eng.meta.get("halted")
    offline.assert_safe()


def test_market_data_guard_per_feed_includes_aggtrade_for_h7t(offline):
    from live_v6 import strategy as S
    from live_v6.strategies.h7t import H7T
    clk = Clock()
    eng = offline.engine(use_streams=True, clock=clk, strategy=H7T(params=S.Params(h7_min_obs=10 ** 9)))
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None   # bar decisions off (covered by test_bar_close_live)
    eng.startup()
    assert eng.expected_feeds() == ("mark", "kline", "trade")
    eng.market_data_guard()
    for _ in range(14):                                     # mark + kline flow, aggTrade silent 70 s
        clk.t += 5
        eng.on_event(Mark(DOGE, Decimal("0.15"), int(clk.t * 1000)))
        eng.on_event(_kline(DOGE, int(clk.t * 1000)))
        eng.market_data_guard()
    assert E.MARKET_STALE in eng.blocks and "trade" in eng.blocks[E.MARKET_STALE]
    eng.on_event(Trade(DOGE, Decimal("0.15"), Decimal(1), int(clk.t * 1000)))
    eng.market_data_guard()
    assert E.MARKET_STALE not in eng.blocks


def test_ws_urls_are_network_specific():
    """Mainnet: routed /market and /private endpoints (legacy /ws, /stream retired 2026-04-23); testnet: legacy paths."""
    from live_v6.exchange import MAINNET_WS
    st = ["dogeusdt@markPrice@1s", "dogeusdt@kline_1m", "dogeusdt@aggTrade"]
    assert market_url(MAINNET_WS, st) == \
        "wss://fstream.binance.com/market/stream?streams=dogeusdt@markPrice@1s/dogeusdt@kline_1m/dogeusdt@aggTrade"
    assert market_url(TESTNET_WS, st) == \
        "wss://fstream.binancefuture.com/stream?streams=dogeusdt@markPrice@1s/dogeusdt@kline_1m/dogeusdt@aggTrade"
    assert user_url(MAINNET_WS, "KEY") == ("wss://fstream.binance.com/private/ws?listenKey=KEY&events="
                                           "ORDER_TRADE_UPDATE/ACCOUNT_UPDATE/ALGO_UPDATE/STRATEGY_UPDATE/"
                                           "CONDITIONAL_ORDER_TRIGGER_REJECT/listenKeyExpired")
    assert {"ORDER_TRADE_UPDATE", "ACCOUNT_UPDATE", "listenKeyExpired"} <= set(USER_EVENTS)
    assert user_url(TESTNET_WS, "KEY") == "wss://fstream.binancefuture.com/ws/KEY"
    for bad in ("wss://fstream.binance.com/ws", "wss://example.com"):
        with pytest.raises(ValueError):
            market_url(bad, st)
    ms = MarketStream(MAINNET_WS, ["DOGEUSDT"], ("1m",), trades=True)
    assert ms.url().startswith("wss://fstream.binance.com/market/stream?streams=dogeusdt@markPrice@1s/")
    assert "/ws/" not in ms.url() and "fstream.binance.com/stream" not in ms.url()

    class R:
        def listen_key(self):
            return "LK"
    assert UserStream(MAINNET_WS, R()).url().startswith("wss://fstream.binance.com/private/ws?listenKey=LK&events=")
    assert UserStream(TESTNET_WS, R()).url() == "wss://fstream.binancefuture.com/ws/LK"


def test_ws_url_guard():
    assert ws_base_for(TESTNET_URL) == TESTNET_WS
    with pytest.raises(MainnetForbidden):
        ws_base_for("https://fapi.binance.com")


# ───────────── testnet (real websockets) ─────────────
def pump(q, eng, until, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            ev = q.get(timeout=0.5)
        except queue.Empty:
            continue
        eng.on_event(ev)
        if until(ev):
            return ev
    raise AssertionError("timed out waiting for stream event")


@pytest.mark.testnet
def test_testnet_market_stream_drop_and_resubscribe(backend):
    if backend.kind != "testnet":
        pytest.skip("testnet only")
    eng = stream_engine(backend)
    q = queue.Queue()
    ms = MarketStream(TESTNET_WS, [DOGE], ("1m",), q=q, backoff=(1,))
    ms.start()
    try:
        pump(q, eng, lambda e: isinstance(e, StreamStatus) and e.up, 20)
        pump(q, eng, lambda e: isinstance(e, Mark) and e.sym == DOGE, 20)
        eng.stream_health()
        assert eng.entries_allowed()
        ms.kill_socket()                                         # network drop
        pump(q, eng, lambda e: isinstance(e, StreamStatus) and not e.up, 20)
        assert E.WS_STALE in eng.blocks
        assert not eng.enter(DOGE, backend.stop_dist(), unique_T())   # entries blocked while stale
        eng.reconcile()                                          # REST still works as the safety net
        pump(q, eng, lambda e: isinstance(e, StreamStatus) and e.up, 30)   # auto-reconnect + resubscribe
        pump(q, eng, lambda e: isinstance(e, Mark) and e.sym == DOGE, 20)  # events resume
        assert ms.connects >= 2
        eng.tick(force_reconcile=False)
        assert eng.entries_allowed(), eng.blocks
    finally:
        ms.stop()
    assert backend.amt(DOGE) == 0


@pytest.mark.testnet
def test_testnet_user_stream_fill_and_keepalive(backend):
    if backend.kind != "testnet":
        pytest.skip("testnet only")
    eng = stream_engine(backend)
    q = queue.Queue()
    us = UserStream(TESTNET_WS, backend.inner, q=q, backoff=(1,))
    us.start()
    try:
        pump(q, eng, lambda e: isinstance(e, StreamStatus) and e.up and e.name == "user", 20)
        backend.inner.keepalive_listen_key()                     # listenKey keepalive accepted
        us.KEEPALIVE_S = 0                                       # force the thread's own keepalive path
        assert eng.enter(DOGE, backend.stop_dist(), unique_T())
        ev = pump(q, eng, lambda e: isinstance(e, OrderUpdate) and e.sym == DOGE, 20)
        assert ev.raw
        assert eng._dirty
        eng.tick(force_reconcile=False)
        assert not eng._dirty
        backend.assert_safe()
        time.sleep(6)
        assert us.keepalives >= 1
        eng.close(DOGE, "test")
        assert backend.amt(DOGE) == 0
    finally:
        us.stop()


@pytest.mark.testnet
def test_testnet_overreaction_ws_down_30s(backend):
    """Real TESTNET websocket dropped and kept down ~30 s while holding 2 positions: entries paused, REST reconcile
    every 5 s, ZERO close orders, then auto-resubscribe and resume."""
    if backend.kind != "testnet":
        pytest.skip("testnet only")
    eng = stream_engine(backend)
    assert eng.enter(DOGE, backend.stop_dist(), unique_T())
    assert eng.enter("SOLUSDT", backend.stop_dist("SOLUSDT"), unique_T())
    q = queue.Queue()
    ms = MarketStream(TESTNET_WS, [DOGE, "SOLUSDT"], ("1m",), q=q, backoff=(30,))
    ms.start()
    try:
        pump(q, eng, lambda e: isinstance(e, Mark), 20)
        ms.kill_socket()
        pump(q, eng, lambda e: isinstance(e, StreamStatus) and not e.up, 20)
        t0, recs, back = time.time(), 0, False
        while time.time() - t0 < 30:
            try:
                ev = q.get(timeout=5)
                eng.on_event(ev)
                back |= isinstance(ev, StreamStatus) and ev.up
            except queue.Empty:
                pass
            eng.reconcile()
            recs += 1
            eng.stream_health()
            if time.time() - t0 < 25:
                assert not eng.entries_allowed()
        assert recs >= 5
        if not back:
            pump(q, eng, lambda e: isinstance(e, StreamStatus) and e.up, 30)
        pump(q, eng, lambda e: isinstance(e, Mark), 20)
        eng.tick(force_reconcile=False)
        assert eng.entries_allowed(), eng.blocks
    finally:
        ms.stop()
    assert not [c for c in backend.fx.calls if c[0] == "market" and c[1][4]]
    assert not eng.meta.get("halted")
    backend.assert_safe()


@pytest.mark.testnet
def test_testnet_market_stream_killed_stale_guard(backend):
    """TA staleness guard on the real TESTNET market stream: stream killed while holding → entries blocked, 🚨 within
    60–65 s of the last market data, ZERO close orders, exchange stop untouched, resume after recovery."""
    if backend.kind != "testnet":
        pytest.skip("testnet only")
    eng = stream_engine(backend)
    assert eng.enter(DOGE, backend.stop_dist(), unique_T())
    stops0 = sorted(o["id"] for o in backend.stops(DOGE))
    q = queue.Queue()

    def feed_up(ms):
        ms.start()
        seen = set()
        pump(q, eng, lambda e: (seen.add(type(e).__name__) or {"Mark", "Kline"} <= seen), 60)
    ms = MarketStream(TESTNET_WS, [DOGE], ("1m",), q=q, backoff=(1,))
    feed_up(ms)
    eng.tick(force_reconcile=False)
    assert E.MARKET_STALE not in eng.blocks
    ms.stop()                                                   # market stream killed (no reconnect)
    t_last = max(eng._feed_last["mark"], eng._feed_last["kline"])
    t_block = None
    while time.time() - t_last < 75:
        while not q.empty():
            eng.on_event(q.get())                               # drain the down status
        eng.tick(force_reconcile=False)
        if t_block is None and E.MARKET_STALE in eng.blocks:
            t_block = time.time()
        time.sleep(0.5)
    assert t_block is not None and 60 <= t_block - t_last <= 65, (t_block, t_last)
    al = [r for r in eng.tg.records if r["type"] == "alert" and "시장 데이터" in r["text"]]
    assert len(al) == 1 and 60 <= al[0]["delay_s"] <= 65, al
    assert not eng.entries_allowed() and not eng.enter("SOLUSDT", backend.stop_dist("SOLUSDT"), unique_T())
    assert not _close_orders(backend) and backend.amt(DOGE) > 0
    assert sorted(o["id"] for o in backend.stops(DOGE)) == stops0          # exchange stop untouched
    ms2 = MarketStream(TESTNET_WS, [DOGE], ("1m",), q=q, backoff=(1,))
    try:
        feed_up(ms2)                                            # recovery: fresh mark + kline
        eng.on_event(StreamStatus("user", True))
        eng.tick(force_reconcile=False)
        assert E.MARKET_STALE not in eng.blocks and eng.entries_allowed(), eng.blocks
        assert any(r["type"] == "recovery" for r in eng.tg.records)
    finally:
        ms2.stop()
    assert not _close_orders(backend)
    backend.assert_safe()
