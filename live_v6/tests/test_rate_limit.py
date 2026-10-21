"""TA rate-limit conditions: on 429 / 418 the client honours Retry-After (no polling during the backoff), NEW entries
are blocked and a 418 never flattens by itself (only the existing §8c L3 rules).
429: protective calls (stop placement / replacement, cancel, reduceOnly close + the reads that verify them) still go out.
418 (TA 2026-10-21, Binance docs: the IP is banned): NOTHING is sent until Retry-After, critical calls included; queued
protective actions go out on the first tick after the ban (see test_stop_monitor.py)."""
from decimal import Decimal

import httpx

from live_v6.engine import API_ERRORS, RATE_LIMIT
from live_v6.exchange import TESTNET_URL, BinanceREST, RateLimited

from .fakes import FakeExchange
from .test_faults import DOGE, SOL, alerts, close_calls, opened, ready

NON_CRITICAL = {"account", "mark_prices", "klines", "funding", "income", "user_trades", "exchange_info", "brackets",
                "book", "set_leverage", "set_margin_type", "leverage"}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


# ───────────── REST client ─────────────
def mock_rest(status_first=418, retry_after="60"):
    sent = []

    def handler(req):
        sent.append((req.method, req.url.path))
        if len(sent) == 1:
            h = {"X-MBX-USED-WEIGHT-1M": "2401"} | ({"Retry-After": retry_after} if retry_after else {})
            return httpx.Response(status_first, headers=h, json={"code": -1003, "msg": "banned"})
        p = req.url.path
        hdr = {"X-MBX-USED-WEIGHT-1M": "37"}
        if p in ("/fapi/v2/positionRisk", "/fapi/v1/openOrders", "/fapi/v1/openAlgoOrders"):
            return httpx.Response(200, headers=hdr, json=[])
        if p == "/fapi/v1/algoOrder":
            return httpx.Response(200, headers=hdr, json={"algoId": 1, "clientAlgoId": "c", "triggerPrice": "1"})
        if p == "/fapi/v1/order":
            return httpx.Response(200, headers=hdr, json={"orderId": 1, "clientOrderId": "c", "status": "FILLED",
                                                          "executedQty": "1", "avgPrice": "1", "origQty": "1"})
        if p == "/fapi/v2/account":
            return httpx.Response(200, headers=hdr, json={"assets": [{"asset": "USDT", "walletBalance": "1", "availableBalance": "1"}]})
        return httpx.Response(200, headers=hdr, json=[])
    r = BinanceREST(TESTNET_URL, "k", "s", transport=httpx.MockTransport(handler))
    r.clock = Clock()
    return r, sent


def test_rest_418_ban_sends_nothing_not_even_protective_calls():
    r, sent = mock_rest(418, "60")
    hooked = []
    r.on_rate_limit = lambda st, ra: hooked.append((st, ra))
    try:
        r.account()
        raise AssertionError
    except RateLimited:
        pass
    assert hooked == [(418, 60.0)] and r.ban_until == r.clock() + 60
    n = len(sent)
    for call in (r.account, lambda: r.positions((DOGE,)), lambda: r.open_orders(DOGE), lambda: r.get_order(DOGE, "v6x"),
                 lambda: r.stop(DOGE, "SELL", Decimal("0.1"), "v6s"), lambda: r.cancel(DOGE, {"kind": "algo", "id": "1"}),
                 lambda: r.market(DOGE, "SELL", Decimal(1), "v6x", reduce_only=True), r.keepalive_listen_key):
        try:
            call()
            raise AssertionError("request sent during a 418 ban")
        except RateLimited as e:
            assert "IP ban" in str(e) and "not sent" in str(e)
    assert len(sent) == n                                     # not a single request during the ban
    r.clock.t += 61
    r.stop(DOGE, "SELL", Decimal("0.1"), "v6s")               # ban over → protective call goes out at once
    r.account()
    assert [p for _, p in sent[n:]] == ["/fapi/v1/algoOrder", "/fapi/v2/account"]


def test_rest_429_backoff_only_protective_calls_sent():
    r, sent = mock_rest(429, "60")
    hooked = []
    r.on_rate_limit = lambda st, ra: hooked.append((st, ra))
    try:
        r.account()
        raise AssertionError
    except RateLimited:
        pass
    assert hooked == [(429, 60.0)] and r.ban_until == 0 and r.backoff_until == r.clock() + 60 and r.weight_peaks and max(r.weight_peaks.values()) == 2401
    n = len(sent)
    for call in (r.account, lambda: r.klines(DOGE, "4h", 10), r.mark_prices, lambda: r.funding(DOGE, 0),
                 lambda: r.market(DOGE, "BUY", Decimal(1), "v6e", reduce_only=False), lambda: r.set_leverage(DOGE, 5),
                 lambda: r.income(None, None, 0), lambda: r.book(DOGE)):
        try:
            call()
            raise AssertionError("non-protective call went through during backoff")
        except RateLimited:
            pass
    assert len(sent) == n                                     # nothing was sent: Retry-After honoured
    r.positions((DOGE,))
    r.open_orders(DOGE)
    r.get_order(DOGE, "v6x")
    r.stop(DOGE, "SELL", Decimal("0.1"), "v6s")
    r.cancel(DOGE, {"kind": "algo", "id": "1"})
    r.market(DOGE, "SELL", Decimal(1), "v6x", reduce_only=True)
    paths = [p for _, p in sent[n:]]
    assert paths == ["/fapi/v2/positionRisk", "/fapi/v1/openOrders", "/fapi/v1/openAlgoOrders", "/fapi/v1/order",
                     "/fapi/v1/algoOrder", "/fapi/v1/algoOrder", "/fapi/v1/order"]
    r.clock.t += 61
    r.account()                                               # backoff over → normal
    assert sent[-1][1] == "/fapi/v2/account" and r.used_weight_1m == 37


def test_rest_429_without_retry_after_uses_default():
    r, _ = mock_rest(429, None)
    try:
        r.account()
    except RateLimited:
        pass
    assert r.backoff_until == r.clock() + 10


# ───────────── engine ─────────────
CRITICAL = {"positions", "open_orders", "get_order", "stop", "cancel"}


class BackoffFake(FakeExchange):
    """FakeExchange with BinanceREST's semantics: 429 backoff (same critical / non-critical split) and 418 ban (nothing
    sent). `sent` records every call that reached the "exchange"; `ban(s)` = a 418 with Retry-After s (fires the hook)."""
    def __init__(self, clock):
        super().__init__()
        self.clock, self.backoff_until, self.ban_until, self.sent = clock, 0.0, 0.0, []
        self.on_rate_limit = None

    def ban(self, seconds):
        self.ban_until = self.backoff_until = self.clock() + seconds
        if self.on_rate_limit:
            self.on_rate_limit(418, float(seconds))

    def __getattribute__(self, name):
        if name in NON_CRITICAL or name in CRITICAL or name == "market":
            fn = super().__getattribute__(name)

            def guarded(*a, **kw):
                if self.clock() < self.ban_until:
                    raise RateLimited(f"{name}: IP ban (not sent)")
                ro = name in CRITICAL or (name == "market" and (kw.get("reduce_only") or (len(a) > 4 and a[4])))
                if self.clock() < self.backoff_until and not ro:
                    raise RateLimited(f"{name}: backoff (not sent)")
                self.sent.append(name)
                return fn(*a, **kw)
            return guarded
        return super().__getattribute__(name)


def test_engine_429_blocks_entries_keeps_protection_never_flattens(offline):
    clk = Clock(__import__("time").time())
    offline.inner = BackoffFake(clk)
    offline.fx.inner = offline.inner
    eng = ready(offline, clock=clk)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None   # bar decisions off (covered elsewhere)
    opened(offline, eng, SOL)
    opened(offline, eng)
    n_close0 = len(close_calls(offline))
    sd_xrp = offline.stop_dist("XRPUSDT")
    offline.inner.backoff_until = clk() + 600                 # long 429 backoff (Retry-After 600)
    n_sent = len(offline.inner.sent)
    n_calls = len(offline.fx.calls)
    for _ in range(110):                                      # 550 s of 5 s ticks (> api_dead_s = 300 s)
        clk.t += 5
        eng.tick(force_reconcile=False)
    assert RATE_LIMIT in eng.blocks and not eng.entries_allowed()
    assert len(offline.inner.sent) == n_sent                  # no polling at all
    assert len(offline.fx.calls) == n_calls                   # no REST polling at all during the ban (Retry-After)
    assert not eng.enter("XRPUSDT", sd_xrp, int(clk() * 1000))     # entries blocked
    assert eng.meta["skip_log"][-1][2] == "safety_block"
    assert len(close_calls(offline)) == n_close0 and not eng.meta.get("halted")          # never a flatten by itself
    assert offline.amt(DOGE) > 0 and offline.amt(SOL) > 0
    assert sum("일시 장애" in a for a in alerts(eng)) == 1     # one transient alert (> 60 s), no close
    # protective actions still go through during a 429 backoff: stop replacement …
    for o in offline.inner.open_orders(DOGE):
        offline.inner.cancel(DOGE, o)
    j = eng.st["pos"][DOGE]
    assert eng.ensure_stop(DOGE, offline.amt(DOGE), Decimal(j["stop_px"]), j["cid"]) == "ok"
    assert offline.stops(DOGE)
    # … and a close (stop breach on the mark stream, exchange stop "does not fire")
    offline.inner.stops_fire = False
    px = Decimal(eng.st["pos"][SOL]["stop_px"]) - Decimal("0.01")
    offline.inner.set_price(SOL, px)
    eng.breach_check(SOL, px, "test")
    assert offline.amt(SOL) == 0 and len(close_calls(offline)) == n_close0 + 1
    assert offline.amt(DOGE) > 0 and not eng.meta.get("halted")          # only that position (§8c L1)
    # backoff over → reconcile resumes, block clears
    clk.t = offline.inner.backoff_until + 1
    for _ in range(4):
        eng.tick(force_reconcile=False)
        clk.t += 5
    assert RATE_LIMIT not in eng.blocks and API_ERRORS not in eng.blocks and eng.entries_allowed(), eng.blocks
    offline.assert_safe()


def test_engine_418_ban_sends_nothing_alerts_and_never_flattens(offline):
    clk = Clock(__import__("time").time())
    offline.inner = BackoffFake(clk)
    offline.fx.inner = offline.inner
    eng = ready(offline, clock=clk)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    opened(offline, eng, SOL)
    opened(offline, eng)
    n_close0 = len(close_calls(offline))
    n_alert0 = len(alerts(eng))
    offline.inner.ban(600)                                    # 418, Retry-After 600
    assert any("418" in a for a in alerts(eng)[n_alert0:])    # 🚨 immediately on the 418
    n_sent = len(offline.inner.sent)
    for _ in range(110):                                      # 550 s of 5 s ticks (> api_dead_s = 300 s)
        clk.t += 5
        eng.tick(force_reconcile=False)
    j = eng.st["pos"][DOGE]
    assert eng.ensure_stop(DOGE, Decimal(j["qty"]), Decimal(j["stop_px"]), j["cid"]) == "unavailable"
    assert len(offline.inner.sent) == n_sent                  # NOTHING reached the exchange during the ban
    assert RATE_LIMIT in eng.blocks and not eng.entries_allowed() and not eng.meta.get("halted")
    assert len(close_calls(offline)) == n_close0
    assert offline.inner.pos[DOGE]["amt"] > 0 and offline.inner.pos[SOL]["amt"] > 0
    clk.t = offline.inner.ban_until + 1
    for _ in range(4):
        eng.tick(force_reconcile=False)
        clk.t += 5
    assert RATE_LIMIT not in eng.blocks and API_ERRORS not in eng.blocks and eng.entries_allowed(), eng.blocks
    offline.assert_safe()


def test_startup_pacing_waits_when_weight_high(offline):
    from live_v6.strategies.h7t import H7T
    from live_v6 import strategy as S
    slept = []
    state = {"w": 0}
    offline.inner.weight_now = lambda: state["w"]
    eng = offline.engine(strategy=H7T(params=S.Params()))
    eng.sleep = slept.append
    eng.startup()
    assert not slept                                          # normal startup: no pacing
    eng2 = offline.engine(strategy=H7T(params=S.Params()))
    eng2.st["strategy"] = {}
    eng2.strategy.state = {"models": {}, "bar": {}}
    eng2.sleep = slept.append
    state["w"] = 1100
    eng2.startup()
    assert slept and all(0 < s <= 61 for s in slept)          # waited for the next minute before heavy calls
