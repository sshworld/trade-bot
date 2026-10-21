"""Regression (live bug 2026-10-20, deployed fae64af): `tick()` never called `on_bar_close()` (the call had been left
as dead code after `return` in `healthy()`), so the models never stepped after the start-up bootstrap and H7-T could
never enter (`on_event` requires model.last_open == running bar − 4h). Every earlier test stubbed `on_bar_close` or
called it directly; these tests drive ONLY `tick()` / `on_event()` with a simulated clock, exactly like the runner.

Also: TA stale-bar guard (block entries + 🚨 when a 4h close is not committed within bar_stale_s, ✅ on catch-up) and
restart catch-up from a persisted stale state (no spurious entry / alert)."""
from decimal import Decimal

from live_v6 import strategy as S
from live_v6.engine import BAR_STALE
from live_v6.events import Trade
from live_v6.strategies.h7t import H7T

DOGE = "DOGEUSDT"
H4, M1, DAY = S.H4_MS, 60_000, S.DAY_MS
D0 = 1792454400000                       # 2026-10-20 00:00 UTC
START = D0 + 9 * 3600_000 + 41 * 60_000 + 15_000   # live start 09:41:15 UTC


class Clock:
    def __init__(self, ms):
        self.ms = ms

    def __call__(self):
        return self.ms / 1000


def market(clk, ex, mult=None):
    """Synthetic REST klines as Binance returns them (incl. the running bar), flat range around the fake price;
    BTC daily rising (regime on)."""
    base = {s: float(p) for s, p in ex.price.items()}

    def klines(s, interval, limit):
        now = clk.ms
        if interval == "1d":
            iv, t = DAY, now // DAY * DAY
            return [{"open_time": t - i * iv, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1000.0 - i,
                     "close_time": t - i * iv + iv - 1} for i in reversed(range(limit))]
        iv = H4 if interval == "4h" else M1
        t = now // iv * iv
        p = base[s]
        return [{"open_time": t - i * iv, "open": p, "high": p * 1.001, "low": p * 0.99, "close": p * 0.995,
                 "close_time": t - i * iv + iv - 1, "volume": 1.0} for i in reversed(range(limit))]
    ex.klines = klines


def make(offline, clk, **kw):
    strat = H7T(params=S.Params(h7_min_obs=10 ** 9))
    eng = offline.engine(clock=clk, strategy=strat, **kw)
    market(clk, offline.inner)
    return eng, strat


def last_opens(strat):
    return {s: m["last_open"] for s, m in strat.state["models"].items()}


def alerts(eng):
    return [m for m in eng.tg.sent if m.startswith("🚨")]


def touch(eng, sym, px, t):
    eng.ex.inner.price[sym] = Decimal(repr(px))
    eng.on_event(Trade(sym, Decimal(repr(px)), Decimal(1), t))


def test_tick_commits_bar_closes_and_h7t_can_enter(offline):
    clk = Clock(START)
    eng, strat = make(offline, clk)
    eng.tick()                                            # startup (bootstrap) + first tick, like runner.run()
    assert eng.started
    # bootstrap drops the last closed bar (04:00) … and the SAME tick steps it: the live bug left it at 00:00 forever
    assert set(last_opens(strat).values()) == {D0 + 4 * 3600_000}
    assert eng.meta["last_bar_close"] == D0 + 8 * 3600_000
    t_trade = D0 + 11 * 3600_000                          # running bar 08:00: decisions allowed (last_open = 04:00)
    clk.ms = t_trade
    eng.tick(force_reconcile=False)
    assert strat.state["models"][DOGE]["last_open"] == D0 + 4 * 3600_000
    # next 4h close 12:00 → after bar_delay_s the plain tick steps 08:00
    clk.ms = D0 + 12 * 3600_000 + 1000
    eng.tick(force_reconcile=False)
    assert eng.meta["last_bar_close"] == D0 + 8 * 3600_000     # within bar_delay_s: not yet
    clk.ms = D0 + 12 * 3600_000 + 5000
    eng.tick(force_reconcile=False)
    assert eng.meta["last_bar_close"] == D0 + 12 * 3600_000
    assert set(last_opens(strat).values()) == {D0 + 8 * 3600_000}
    # entry allowed after the close: a touch ≥ trigger in bar 12:00 → MARKET entry + exchange stop
    trig = strat.trigger(DOGE, eng)
    clk.ms = D0 + 12 * 3600_000 + 30 * M1
    eng.tick(force_reconcile=False)
    touch(eng, DOGE, trig * 1.0005, clk.ms)
    assert offline.amt(DOGE) > 0 and DOGE in eng.st["pos"]
    offline.assert_safe()
    assert not alerts(eng), alerts(eng)


def test_stale_bar_guard_blocks_alerts_and_clears(offline):
    clk = Clock(START)
    eng, strat = make(offline, clk)
    eng.tick()
    real = eng.on_bar_close
    eng.on_bar_close = lambda: None                       # simulate the decision never committing (the live bug)
    T = D0 + 12 * 3600_000
    clk.ms = T + 299_000
    eng.tick(force_reconcile=False)
    assert BAR_STALE not in eng.blocks and eng.entries_allowed()
    clk.ms = T + 301_000
    eng.tick(force_reconcile=False)
    assert BAR_STALE in eng.blocks and not eng.entries_allowed() and not eng.healthy()
    a = alerts(eng)
    assert len(a) == 1 and "4시간 봉 마감" in a[0] and "정리 안 함" in a[0]
    rec = [r for r in eng.tg.records if r["type"] == "alert"][-1]
    assert rec["event_ts"].startswith("2026-10-20T12:00:00")  # event time = the boundary (alerts log)
    trig = strat.trigger(DOGE, eng)
    touch(eng, DOGE, trig * 1.0005, clk.ms)               # blocked: no entry while stale
    assert offline.amt(DOGE) == 0
    clk.ms += 60_000
    eng.tick(force_reconcile=False)
    assert len(alerts(eng)) == 1                          # one alert per outage
    eng.on_bar_close = real
    clk.ms += 1000
    eng.tick(force_reconcile=False)
    assert BAR_STALE not in eng.blocks and eng.entries_allowed() and eng.healthy()
    assert eng.tg.sent[-1].startswith("✅ 4시간 봉 마감 반영 완료 — 신규 진입 재개")
    assert not [c for c in offline.fx.calls if c[0] == "market"]   # guard never trades


def test_stale_bar_guard_fires_on_lagging_model(offline):
    """meta.last_bar_close current but one model behind (e.g. state edited / partial) → also stale."""
    clk = Clock(START)
    eng, strat = make(offline, clk)
    eng.tick()
    eng.on_bar_close = lambda: None
    strat.state["models"][DOGE]["last_open"] -= H4
    clk.ms = D0 + 8 * 3600_000 + 301_000
    eng.tick(force_reconcile=False)
    assert BAR_STALE in eng.blocks and DOGE in eng.blocks[BAR_STALE]


def test_bar_decision_exception_never_kills_tick(offline):
    clk = Clock(START)
    eng, strat = make(offline, clk)
    eng.tick()

    def boom():
        raise RuntimeError("bug")
    eng.on_bar_close = boom
    pings = []
    eng.deadman = type("D", (), {"maybe_ping": lambda self, h: pings.append(h)})()
    clk.ms = D0 + 12 * 3600_000 + 301_000
    eng.tick(force_reconcile=False)                       # does not raise; guard + dead-man still run
    assert BAR_STALE in eng.blocks and pings == [False]


def test_restart_from_live_stale_state_catches_up_without_spurious_entry_or_alert(offline):
    """The exact VPS state: bootstrap at 09:41 UTC, models last_open = 00:00, strategy.bar = {}, no last_bar_close.
    Restart a day later with the fixed engine → one catch-up step over the missing bars (no '모델 재구성' rebuild,
    no alert, no order), then entries only on a fresh touch in the current bar."""
    clk = Clock(START)
    eng, strat = make(offline, clk)
    eng.on_bar_close = lambda: None                       # = deployed fae64af
    eng.tick()
    eng.save()
    assert set(last_opens(strat).values()) == {D0} and "last_bar_close" not in eng.meta and strat.state["bar"] == {}
    restart = D0 + DAY + 25 * M1                          # 2026-10-21 00:25 UTC (09:25 KST)
    clk.ms = restart
    eng2, strat2 = make(offline, clk)                     # same JsonStore path → persisted state
    assert set(last_opens(strat2).values()) == {D0}
    eng2.tick()
    assert eng2.meta["last_bar_close"] == D0 + DAY
    assert set(last_opens(strat2).values()) == {D0 + DAY - H4}
    assert not alerts(eng2), alerts(eng2)                 # no rebuild alert, no stale-bar alert
    assert not [c for c in offline.fx.calls if c[0] in ("market", "stop")]
    assert all(m["pos"] == 0 for m in strat2.state["models"].values())   # catch-up never creates a virtual entry
    # a price already above the trigger earlier in this bar (missed while down) → no late entry
    trig = strat2.trigger(DOGE, eng2)
    real_k = offline.inner.klines

    def k_touched(s, iv, limit):
        bars = real_k(s, iv, limit)
        if iv == "1m" and s == DOGE:
            bars[-3]["high"] = trig * 1.01
        return bars
    offline.inner.klines = k_touched
    touch(eng2, DOGE, trig * 1.0005, clk.ms)
    assert offline.amt(DOGE) == 0 and strat2.state["bar"][DOGE]["missed"]
    offline.inner.klines = real_k
    touch(eng2, "SOLUSDT", strat2.trigger("SOLUSDT", eng2) * 1.0005, clk.ms)   # not touched before → enters
    assert offline.amt("SOLUSDT") > 0
    offline.assert_safe()


def test_minus_1021_is_transient():
    import httpx

    from live_v6.exchange import RECV_WINDOW_MS, TESTNET_URL, BinanceREST, ExchangeUnavailable
    seen = {}

    def handler(req):
        seen["rw"] = req.url.params.get("recvWindow")
        return httpx.Response(400, json={"code": -1021, "msg": "Timestamp for this request is outside of the recvWindow."})
    r = BinanceREST(TESTNET_URL, "k", "s", transport=httpx.MockTransport(handler))
    try:
        r.account()
        raise AssertionError("no error")
    except ExchangeUnavailable:
        pass
    assert RECV_WINDOW_MS == 10000 and seen["rw"] == "10000"
