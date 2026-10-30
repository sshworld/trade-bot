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


# ───────────── live 2026-10-30 15:07 KST SOLUSDT: symbolConfig itself lagged right after the set ─────────────
def _cfg_lag(fx, old, n):
    """The next `n` symbolConfig reads still report the old leverage."""
    fx.inject("leverage", lambda fn, s: old, times=n)


def test_symbolconfig_lag_retried_then_enters(offline):
    eng = ready(offline)
    old = offline.inner.lev[DOGE]
    _stale_positions_after_set(offline.fx, old)
    _cfg_lag(offline.fx, old, 3)                    # reads 1-3 stale, read 4 shows the new value
    assert eng.enter(DOGE, offline.stop_dist(), unique_T()), eng.meta.get("skip_log", [])[-1:]
    assert sum(1 for c in offline.fx.calls if c == ("leverage", (DOGE,))) == 4
    assert not alerts(eng) and DOGE in eng.st["pos"]


def test_symbolconfig_still_wrong_after_5_reads_skips_with_alert(offline):
    eng = ready(offline)
    old = offline.inner.lev[DOGE]
    _stale_positions_after_set(offline.fx, old)
    _cfg_lag(offline.fx, old, 10)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert sum(1 for c in offline.fx.calls if c == ("leverage", (DOGE,))) == 5
    assert eng.meta["skip_log"][-1][2] == "leverage" and f"symbolConfig {old}x" in eng.meta["skip_log"][-1][3]
    assert len([a for a in alerts(eng) if "레버리지" in a]) == 1 and DOGE not in eng.st["pos"]


def test_startup_leverage_sets_flat_coins_idempotent(offline):
    eng = offline.engine(startup_leverage=7)
    eng.startup()
    syms = eng.cfg.symbols
    assert all(offline.inner.lev[s] == 7 for s in syms)
    sets = [c for c in offline.fx.calls if c[0] == "set_leverage"]
    assert sorted(c[1][0] for c in sets) == sorted(s for s in syms)
    eng2 = offline.engine(startup_leverage=7)       # second start: nothing to change -> no set call
    n = len(offline.fx.calls)
    eng2.startup()
    assert not [c for c in offline.fx.calls[n:] if c[0] == "set_leverage"]


def test_startup_leverage_off_by_default(offline):
    eng = offline.engine()
    eng.startup()
    assert not [c for c in offline.fx.calls if c[0] == "set_leverage"]
