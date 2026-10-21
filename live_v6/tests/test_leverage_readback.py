"""Leverage read-back (live 2026-10-22 01:39 KST): POST /fapi/v1/leverage BNBUSDT 10x succeeded, the immediate
/fapi/v2/positionRisk read still showed 20x → entry skipped + 🚨; /fapi/v1/symbolConfig showed 10x afterwards.
A lagging positionRisk is now confirmed on symbolConfig when the set response echoed the requested leverage;
a leverage that really did not change still skips the entry with the same 🚨."""
import httpx

from live_v6.exchange import TESTNET_URL, BinanceREST

from .conftest import unique_T
from .test_faults import DOGE, alerts, ready


def _stale_positions_after_set(fx, old):
    """After set_leverage, the NEXT positions read still reports the old leverage (positionRisk lag)."""
    def set_then_lag(fn, s, lev):
        out = fn(s, lev)

        def stale(pfn, symbols):
            p = pfn(symbols)
            p[s] = dict(p[s], leverage=old)
            return p
        fx.inject("positions", stale, times=1)
        return out
    fx.inject("set_leverage", set_then_lag, times=1)


def test_positionrisk_lag_confirmed_on_symbolconfig_enters(offline):
    eng = ready(offline)
    old = offline.inner.lev[DOGE]
    _stale_positions_after_set(offline.fx, old)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T())
    lev = offline.inner.lev[DOGE]
    assert lev != old and ("leverage", (DOGE,)) in offline.fx.calls
    assert not alerts(eng) and DOGE in eng.st["pos"]
    assert not any(r[2] == "leverage" for r in eng.meta.get("skip_log", []))


def test_leverage_really_unchanged_still_skips_with_alert(offline):
    """Set call 'OK' (echoes the requested value) but nothing changed: positionRisk AND symbolConfig show the old
    leverage → entry skipped + 🚨 exactly as before."""
    eng = ready(offline)
    old = offline.inner.lev[DOGE]
    offline.fx.inject("set_leverage", lambda fn, s, lev: int(lev), times=1)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert eng.meta["skip_log"][-1][2] == "leverage"
    assert f"symbolConfig {old}x" in eng.meta["skip_log"][-1][3]
    assert any("레버리지" in a for a in alerts(eng)) and DOGE not in eng.st["pos"]


def test_no_echo_in_set_response_keeps_old_gate(offline):
    """No leverage in the set response → no symbolConfig fallback: positionRisk alone decides (old behaviour)."""
    eng = ready(offline)
    old = offline.inner.lev[DOGE]

    def no_echo(fn, s, lev):
        fn(s, lev)

    def stale(pfn, symbols):
        p = pfn(symbols)
        p[DOGE] = dict(p[DOGE], leverage=old)
        return p
    offline.fx.inject("set_leverage", no_echo, times=1)
    offline.fx.inject("positions", lambda pfn, symbols: pfn(symbols), times=1)   # pre-check read: untouched
    offline.fx.inject("positions", stale, times=1)                                # read-back lags
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert eng.meta["skip_log"][-1][2] == "leverage" and ("leverage", (DOGE,)) not in offline.fx.calls
    assert any("레버리지" in a for a in alerts(eng))


def test_rest_set_leverage_echo_and_symbolconfig_parse():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, dict(req.url.params)))
        if req.url.path == "/fapi/v1/leverage":
            return httpx.Response(200, json={"leverage": 10, "maxNotionalValue": "5000000", "symbol": "BNBUSDT"})
        if req.url.path == "/fapi/v1/symbolConfig":
            return httpx.Response(200, json=[{"symbol": "BNBUSDT", "marginType": "ISOLATED", "isAutoAddMargin": "false",
                                              "leverage": 10, "maxNotionalValue": "5000000"}])
        return httpx.Response(404, json={"code": -1, "msg": "x"})
    r = BinanceREST(TESTNET_URL, "k", "s", transport=httpx.MockTransport(handler))
    assert r.set_leverage("BNBUSDT", 10) == 10
    assert r.leverage("BNBUSDT") == 10
    assert [(m, p) for m, p, _ in seen] == [("POST", "/fapi/v1/leverage"), ("GET", "/fapi/v1/symbolConfig")]
    assert seen[1][2]["symbol"] == "BNBUSDT"
