"""TA 2026-10-22 02:19 KST (leverage read-back fix, condition 1 + 2):
1. GET /fapi/v1/symbolConfig fails (exception / timeout / HTTP 429 / HTTP 418 / backoff active / rejected / malformed
   body) → the entry is NOT sent, that coin is skipped with 🚨, no exception escapes, nothing is left half-done (no
   intent, no pre-armed stop, no order, no journal row, risk book unchanged) and the next bar enters normally.
2. The liquidation guard / margin use the leverage that the exchange CONFIRMED (set response + symbolConfig), never the
   stale positionRisk value."""
from decimal import Decimal

import httpx
import pytest

from live_v6.engine import API_ERRORS, RATE_LIMIT
from live_v6.exchange import TESTNET_URL, BinanceREST, ExchangeError, ExchangeUnavailable, OrderRejected, RateLimited
from live_v6.rules import liquidation_ok

from .conftest import unique_T
from .fakes import FakeExchange
from .test_faults import DOGE, SOL, alerts, ready
from .test_rate_limit import BackoffFake, Clock

MODES = ["exception", "timeout", "rejected", "http429", "http418", "backoff_active"]


def _setup(offline):
    clk = Clock(__import__("time").time())
    offline.inner = BackoffFake(clk)
    offline.fx.inner = offline.inner
    eng = ready(offline, clock=clk)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None       # bar decisions off (entries driven by hand)
    return eng, clk


def _fail(offline, clk, mode):
    """symbolConfig failure, with the same side effects BinanceREST._req has for that failure."""
    inner = offline.inner

    def boom(fn, s):
        if mode == "exception":
            raise KeyError("leverage")                               # malformed body / unexpected bug (not ExchangeError)
        if mode == "timeout":
            raise ExchangeUnavailable("GET /fapi/v1/symbolConfig: ReadTimeout")
        if mode == "rejected":
            raise OrderRejected(-1121, "Invalid symbol.")
        if mode == "http429":
            inner.backoff_until = clk() + 60
            if inner.on_rate_limit:
                inner.on_rate_limit(429, 60.0)
            raise RateLimited("GET /fapi/v1/symbolConfig: HTTP 429 retry-after 60s")
        if mode == "http418":
            inner.ban(120)
            raise RateLimited("GET /fapi/v1/symbolConfig: HTTP 418 retry-after 120s")
        if mode == "backoff_active":                                 # a 429 elsewhere between the set and this read:
            inner.backoff_until = clk() + 60                         # the client refuses locally (not sent)
            return fn(s)
        raise AssertionError(mode)
    offline.fx.inject("leverage", boom, times=1)


def _raw(offline, name, *a):
    """Inspect the fake exchange WITHOUT BackoffFake's 429/418 guard (test-side reads, not bot requests)."""
    return getattr(FakeExchange, name)(offline.inner, *a)


def _no_trace(offline, eng, n_orders0):
    assert DOGE not in eng.st["pos"] and not eng.st["intents"]
    assert _raw(offline, "positions", (DOGE,))[DOGE]["amt"] == 0
    assert not _raw(offline, "open_orders", DOGE)                                   # no pre-armed stop left behind
    assert len(offline.inner.orders) == n_orders0                                   # no entry order sent
    assert not [c for c in offline.fx.calls if c[0] in ("market", "stop") and c[1][0] == DOGE]


def _lag_after_set(offline, old):
    """After set_leverage, the NEXT positions read still reports the old leverage (live 2026-10-22 positionRisk lag)."""
    def set_then_lag(fn, s, lev):
        out = fn(s, lev)

        def stale(pfn, symbols):
            p = pfn(symbols)
            p[s] = dict(p[s], leverage=old)
            return p
        offline.fx.inject("positions", stale, times=1)
        return out
    offline.fx.inject("set_leverage", set_then_lag, times=1)


@pytest.mark.parametrize("lag", [False, True], ids=["positionRisk_ok", "positionRisk_lags"])
@pytest.mark.parametrize("mode", MODES)
def test_symbolconfig_failure_skips_alerts_and_next_bar_enters(offline, mode, lag):
    eng, clk = _setup(offline)
    old = offline.inner.lev[DOGE]
    n_orders0 = len(offline.inner.orders)
    risk0 = eng._open_book(_raw(offline, "positions", eng.cfg.symbols))
    if lag:
        _lag_after_set(offline, old)
    _fail(offline, clk, mode)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T()) is False              # no exception escapes
    assert ("leverage", (DOGE,)) in offline.fx.calls and offline.inner.lev[DOGE] != old
    sk = eng.meta["skip_log"][-1]
    assert sk[1] == DOGE and sk[2] == "leverage" and "symbolConfig failed" in sk[3], sk
    assert any("레버리지" in a and "진입 건너뜀" in a for a in alerts(eng))
    if mode == "http418":
        assert any("418" in a for a in alerts(eng))                               # the ban's own 🚨 as well
    _no_trace(offline, eng, n_orders0)
    assert eng._open_book(_raw(offline, "positions", eng.cfg.symbols)) == risk0       # risk accounting unchanged
    # next bar (backoff / ban over, transient blocks cleared): the same coin enters normally, with a stop
    clk.t = max(clk.t, offline.inner.backoff_until, offline.inner.ban_until) + 1
    for _ in range(4):
        eng.tick(force_reconcile=True)
        clk.t += 5
    assert eng.entries_allowed(), eng.blocks
    assert API_ERRORS not in eng.blocks and RATE_LIMIT not in eng.blocks
    assert eng.enter(DOGE, offline.stop_dist(), unique_T()), eng.meta["skip_log"][-1:]
    assert DOGE in eng.st["pos"] and not eng.st["intents"] and offline.stops(DOGE)
    assert eng.st["pos"][DOGE]["lev"] == offline.inner.lev[DOGE]
    offline.assert_safe()


@pytest.mark.parametrize("mode", ["exception", "rejected"])
def test_symbolconfig_failure_on_one_coin_does_not_stop_the_others_in_the_bar(offline, mode):
    """execute() of one bar with DOGE then SOL: DOGE's symbolConfig fails → DOGE skipped + 🚨, SOL still enters."""
    eng, clk = _setup(offline)
    _fail(offline, clk, mode)
    T = int(clk() * 1000)
    eng.execute([{"type": "enter", "sym": DOGE, "T": T, "stop_dist": offline.stop_dist(DOGE)},
                 {"type": "enter", "sym": SOL, "T": T, "stop_dist": offline.stop_dist(SOL)}], T)
    assert DOGE not in eng.st["pos"] and SOL in eng.st["pos"] and offline.stops(SOL)
    assert [s[1] for s in eng.meta["skip_log"] if s[2] == "leverage"] == [DOGE]
    assert sum("레버리지" in a for a in alerts(eng)) == 1
    offline.assert_safe()


def test_set_response_not_echoing_the_requested_value_skips_without_symbolconfig(offline):
    eng, _ = _setup(offline)
    offline.fx.inject("set_leverage", lambda fn, s, lev: (fn(s, lev), None)[1], times=1)    # applied, no echo
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert eng.meta["skip_log"][-1][2] == "leverage" and ("leverage", (DOGE,)) not in offline.fx.calls
    assert DOGE not in eng.st["pos"] and not eng.st["intents"]


# ───────────── REST client: every symbolConfig failure is an ExchangeError (caught by the engine) ─────────────
def _rest(handler):
    r = BinanceREST(TESTNET_URL, "k", "s", transport=httpx.MockTransport(handler))
    r.clock = Clock()
    return r


@pytest.mark.parametrize("resp,exc", [
    (lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("t", request=req)), ExchangeUnavailable),
    (lambda req: httpx.Response(503, json={}), ExchangeUnavailable),
    (lambda req: httpx.Response(429, headers={"Retry-After": "30"}, json={"code": -1003, "msg": "x"}), RateLimited),
    (lambda req: httpx.Response(418, headers={"Retry-After": "30"}, json={"code": -1003, "msg": "x"}), RateLimited),
    (lambda req: httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."}), OrderRejected),
    (lambda req: httpx.Response(200, json=[]), ExchangeError),
    (lambda req: httpx.Response(200, json=[{"symbol": DOGE}]), ExchangeError),
    (lambda req: httpx.Response(200, json=[{"symbol": DOGE, "leverage": "abc"}]), ExchangeError),
    (lambda req: httpx.Response(200, json=["junk"]), ExchangeError),
    (lambda req: httpx.Response(200, content=b"<html>"), ExchangeUnavailable),
], ids=["timeout", "http503", "http429", "http418", "http400", "empty", "no_leverage", "bad_leverage", "junk_row", "bad_json"])
def test_rest_symbolconfig_failures_raise_exchange_error(resp, exc):
    r = _rest(resp)
    with pytest.raises(exc):
        r.leverage(DOGE)


def test_rest_symbolconfig_not_sent_during_backoff_or_ban():
    sent = []
    r = _rest(lambda req: sent.append(req.url.path) or httpx.Response(200, json=[{"symbol": DOGE, "leverage": 10}]))
    r.backoff_until = r.clock() + 30
    with pytest.raises(RateLimited):
        r.leverage(DOGE)                                   # non-critical → refused locally during a 429 backoff
    r.backoff_until, r.ban_until = 0, r.clock() + 30
    with pytest.raises(RateLimited):
        r.leverage(DOGE)                                   # 418 ban → nothing sent
    assert sent == []
    r.ban_until = 0
    assert r.leverage(DOGE) == 10 and sent == ["/fapi/v1/symbolConfig"]


def test_rest_set_leverage_unparseable_echo_is_none():
    r = _rest(lambda req: httpx.Response(200, json={"leverage": "x", "symbol": DOGE}))
    assert r.set_leverage(DOGE, 10) is None


# ───────────── condition 2: liquidation guard uses the confirmed leverage ─────────────
def test_liq_guard_and_margin_use_confirmed_leverage_not_stale_positionrisk(offline):
    """positionRisk keeps showing 20x after the set (lag); set response + symbolConfig confirm 10x. The position is
    journaled at the confirmed leverage; the liquidation guard (sizing.size_entry → rules.liquidation_ok) was evaluated
    at that same leverage; positionRisk's value is never an input to it."""
    eng, _ = _setup(offline)
    old = offline.inner.lev[DOGE]
    _lag_after_set(offline, old)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T()), eng.meta["skip_log"][-1:]
    j = eng.st["pos"][DOGE]
    confirmed = offline.inner.lev[DOGE]
    assert confirmed != old and j["lev"] == confirmed
    stop_frac = float((Decimal(j["entry_px"]) - Decimal(j["stop_px"])) / Decimal(j["entry_px"]))
    assert liquidation_ok(stop_frac, j["lev"], j["mmr"])
    # the requested leverage that the guard checked is what the exchange holds; at the stale 20x it would not be:
    assert ("set_leverage", (DOGE, confirmed)) in offline.fx.calls
