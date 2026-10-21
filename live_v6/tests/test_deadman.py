"""Dead-man heartbeat hook (HEARTBEAT_URL): pings every 60 s only while healthy; no-op if unset; never raises."""
from live_v6.deadman import DeadMan


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_noop_when_unset(monkeypatch):
    monkeypatch.delenv("HEARTBEAT_URL", raising=False)
    calls = []
    d = DeadMan(get=lambda u, t: calls.append(u), threaded=False)
    assert not d.maybe_ping(True) and not calls


def test_pings_every_60s_while_healthy():
    clk, calls = Clock(), []
    d = DeadMan("https://hc-ping.example/uuid", get=lambda u, t: calls.append(u), clock=clk, threaded=False)
    assert d.maybe_ping(True) and calls == ["https://hc-ping.example/uuid"]
    clk.t += 30
    assert not d.maybe_ping(True)
    clk.t += 30
    assert d.maybe_ping(True) and len(calls) == 2
    clk.t += 120
    assert not d.maybe_ping(False) and len(calls) == 2        # unhealthy → silence → external monitor alerts


def test_failure_never_raises():
    def boom(u, t):
        raise ConnectionError("down")
    d = DeadMan("https://x", get=boom, threaded=False)
    assert d.maybe_ping(True) and d.failures == 1


def test_engine_health_gates_ping(offline):
    clk, calls = Clock(), []
    clk.t = __import__("time").time()
    eng = offline.engine(clock=clk)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None   # bar decisions off (covered by test_bar_close_live)
    eng.deadman = DeadMan("https://x", get=lambda u, t: calls.append(u), clock=clk, threaded=False)
    eng.tick()
    assert len(calls) == 1
    eng.meta["halted"] = "test"
    clk.t += 61
    eng.tick()
    assert len(calls) == 1                                    # halted → no ping
    eng.meta.pop("halted")
    offline.fx.inject("account", "unavailable", times=99)
    clk.t += 61
    eng.tick()
    clk.t += 61
    eng.tick()
    assert len(calls) == 1                                    # REST reconcile failing → no ping
    offline.fx.clear()
    clk.t += 61
    eng.tick()
    assert len(calls) == 2
