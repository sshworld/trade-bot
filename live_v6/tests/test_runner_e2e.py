"""End-to-end runner test (TA PASS condition 3): runner.build() wiring (H7-T, Settings(use_streams=True), JsonStore,
notifier, dead-man) + the production loop runner.serve() / loop_once() with a SIMULATED clock, websocket-format events
through the queue, and NO stubs of on_bar_close / bar_guard. Live start 09:41:15 UTC → closes 12:00 and 16:00 UTC
are committed by the loop itself, then a touch enters."""
import queue
from decimal import Decimal

from live_v6 import runner
from live_v6 import strategy as S
from live_v6.events import Kline, Mark, StreamStatus, Trade

from .fakes import FakeExchange, FaultEx
from .test_bar_close_live import D0, START, H4, market

SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")


class Clock:
    def __init__(self, ms):
        self.ms = ms

    def __call__(self):
        return self.ms / 1000


def test_full_runner_simulated_clock(monkeypatch, tmp_path):
    for k, v in {"BINANCE_TESTNET_API_KEY": "k", "BINANCE_TESTNET_API_SECRET": "s", "LIVE_V6_NETWORK": "testnet",
                 "LIVE_V6_STATE": str(tmp_path / "st.json"), "LIVE_V6_ALERT_LOG": str(tmp_path / "alerts.jsonl"),
                 "HEARTBEAT_URL": "https://hc.example/x"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    rest, eng = runner.build()
    assert eng.cfg.use_streams and eng.strategy.name == "h7t" and not eng.tg.live
    clk = Clock(START)
    inner = FakeExchange(wallet="1000")
    market(clk, inner)
    eng.ex, eng.clock, eng.sleep = FaultEx(inner), clk, (lambda s: None)
    eng._last_market_ev = clk()
    pings = []
    eng.deadman.get, eng.deadman.clock, eng.deadman.threaded = (lambda u, t: pings.append(clk.ms)), clk, False
    q = queue.Queue()
    for n in ("market", "user"):
        q.put(StreamStatus(n, True))
    snaps, entered = [], {}
    end = D0 + 16 * 3600_000 + 30 * 60_000
    touched = {"done": False}

    def feed():
        t = clk.ms
        for s in SIX:
            px = inner.price[s]
            q.put(Mark(s, px, t))
            q.put(Trade(s, px, Decimal(1), t))
            q.put(Kline(s, "1m", {"open_time": t // 60_000 * 60_000, "open": float(px), "high": float(px),
                                  "low": float(px), "close": float(px), "close_time": t // 60_000 * 60_000 + 59_999}, False, t))

    def should_stop():
        clk.ms += 5000
        lbc = eng.meta.get("last_bar_close")
        if not snaps or snaps[-1][0] != lbc:
            snaps.append((lbc, {s: m["last_open"] for s, m in eng.strategy.state["models"].items()}))
        if clk.ms >= D0 + 16 * 3600_000 + 10 * 60_000 and not touched["done"]:
            trig = eng.strategy.trigger("DOGEUSDT", eng)
            inner.price["DOGEUSDT"] = Decimal(repr(trig * 1.0005))
            touched["done"] = True
        if "DOGEUSDT" in eng.st["pos"] and not entered:
            entered["t"] = clk.ms
        feed()
        return clk.ms >= end

    feed()
    runner.serve(eng, q, should_stop, clock=clk, block=False)
    closes = [lbc for lbc, _ in snaps]
    assert closes[:3] == [D0 + 8 * 3600_000, D0 + 12 * 3600_000, D0 + 16 * 3600_000], closes
    for lbc, lo in snaps[:3]:
        assert set(lo.values()) == {lbc - H4}, (lbc, lo)        # every model stepped the bar closing at lbc
    assert entered and inner.positions(SIX)["DOGEUSDT"]["amt"] > 0
    assert any(o["close_position"] for o in inner.open_orders("DOGEUSDT"))
    assert not [m for m in eng.tg.sent if m.startswith("🚨")], [m for m in eng.tg.sent if m.startswith("🚨")]
    gaps = [b - a for a, b in zip(pings, pings[1:])]
    assert pings and max(gaps) <= 65_000                       # dead-man fed all the way (bars current)
