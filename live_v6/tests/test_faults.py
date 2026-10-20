"""Fault-injection suite for live_v6 (TA safety review). Every test runs offline (FakeExchange) and, when the
testnet keys are present, against Binance Futures TESTNET with real orders. Injection points:
FaultEx (method level, both backends) and FaultTransport (HTTP/network level, testnet)."""
import time
from decimal import Decimal

import pytest

from live_v6 import engine as E
from live_v6.exchange import BinanceREST, ExchangeUnavailable, OrderRejected, WouldTrigger
from live_v6.rules import floor_to
from live_v6.sizing import SizingParams

from .conftest import TEST_SYMBOLS, unique_T
from .fakes import ProcessKilled

DOGE, SOL, XRP = "DOGEUSDT", "SOLUSDT", "XRPUSDT"


def is_entry(s, side, qty, cid, reduce_only=False):
    return not reduce_only


def is_exit(s, side, qty, cid, reduce_only=False):
    return bool(reduce_only)


class OffsetClock:
    """Wall clock + adjustable offset (works on testnet too: only the engine's notion of elapsed time moves)."""
    def __init__(self):
        self.off = 0.0

    def __call__(self):
        return time.time() + self.off


def close_calls(backend):
    """Every reduceOnly MARKET (= close order) the bot SENT, whatever the exchange answered."""
    return [c for c in backend.fx.calls if c[0] == "market" and (len(c[1]) > 4 and c[1][4])]


def close_orders(backend) -> int:
    return len(close_calls(backend))


def alerts(eng):
    return [m for m in eng.tg.sent if m.startswith("🚨")]


def ready(b, **kw):
    eng = b.engine(**kw)
    eng.startup()
    assert eng.started and eng.entries_allowed(), eng.blocks
    return eng


def opened(b, eng, sym=DOGE):
    T = unique_T()
    assert eng.enter(sym, b.stop_dist(sym), T), eng.meta.get("skip_log", [])[-1:]
    return T


# ───────────── basics ─────────────
def test_stop_present_after_fill(backend):
    eng = ready(backend)
    opened(backend, eng)
    j = eng.st["pos"][DOGE]
    st = backend.stops(DOGE)
    assert backend.amt(DOGE) == Decimal(j["qty"]) > 0
    assert len(st) == 1 and st[0]["close_position"] and st[0]["side"] == "SELL"
    assert st[0]["stop_price"] == Decimal(j["stop_px"])
    # stop = fill − same distance, rounded toward entry (long → ceil to tick)
    assert Decimal(j["stop_px"]) >= Decimal(j["entry_px"]) - Decimal(j["stop_dist"])
    assert Decimal(j["stop_px"]) - (Decimal(j["entry_px"]) - Decimal(j["stop_dist"])) < eng.rules[DOGE].tick_size
    backend.assert_safe()


def test_isolated_set_and_read_back(backend):
    eng = ready(backend)
    pos = backend.inner.positions(TEST_SYMBOLS)
    assert all(pos[s]["margin_type"] == "ISOLATED" for s in TEST_SYMBOLS)


def test_isolated_failure_blocks_entries(backend):
    eng = ready(backend)
    backend.fx.inject("set_margin_type", "reject", times=99)

    def crossed(fn, symbols):
        out = fn(symbols)
        out[DOGE] = dict(out[DOGE], margin_type="CROSSED")
        return out
    backend.fx.inject("positions", crossed, times=99)
    assert not eng.ensure_isolated(DOGE)
    assert any(k.startswith(E.MARGIN) for k in eng.blocks) and alerts(eng)
    assert not eng.enter(DOGE, backend.stop_dist(), unique_T())
    assert eng.meta["skip_log"][-1][2] == "safety_block" and backend.amt(DOGE) == 0
    backend.fx.clear()
    eng.reconcile()                                  # flat → retried → read-back ISOLATED → unblocked
    assert eng.entries_allowed(), eng.blocks


def test_no_averaging(backend):
    eng = ready(backend)
    t0 = int(time.time() * 1000) - 5000
    opened(backend, eng)
    assert not eng.enter(DOGE, backend.stop_dist(), unique_T())
    assert backend.entry_orders(DOGE, t0) == 1


def test_margin_skip_alert(backend):
    eng = ready(backend)

    def poor(fn):
        a = fn()
        return dict(a, available=Decimal("0.5"))
    backend.fx.inject("account", poor, times=99)
    assert not eng.enter(DOGE, backend.stop_dist(), unique_T())
    assert eng.meta["skip_log"][-1][2] == "margin"
    assert any("증거금 부족" in m for m in alerts(eng))
    assert backend.amt(DOGE) == 0 and not any(c[0] == "market" for c in backend.fx.calls)


# ───────────── restart ─────────────
def test_kill_after_fill_then_restart(backend):
    """Process dies right after the entry fill: the PRE-ARMED reduceOnly stop already protects the position (no
    fill→stop window); restart resolves the intent by client id, upgrades protection, never re-sends the entry."""
    eng = ready(backend)
    t0 = int(time.time() * 1000) - 5000
    T = unique_T()
    backend.fx.inject("market", "kill_after", match=is_entry)
    with pytest.raises(ProcessKilled):
        eng.enter(DOGE, backend.stop_dist(), T)
    assert backend.amt(DOGE) > 0 and backend.stops(DOGE)        # protected while the bot is dead
    backend.assert_safe()
    eng2 = backend.engine()
    eng2.startup()
    assert DOGE in eng2.st["pos"] and not eng2.st["intents"]
    assert not eng2.enter(DOGE, backend.stop_dist(), T)          # replay of the same signal → refused
    assert backend.entry_orders(DOGE, t0) == 1
    assert close_orders(backend) == 0
    backend.assert_safe()


def test_kill_before_entry_sent_cleans_prearm(backend):
    """Dies after the pre-arm stop, before the entry order: restart finds no order by client id → stays flat and
    removes its own pre-armed stop."""
    eng = ready(backend)
    backend.fx.inject("market", "kill_before", match=is_entry)
    with pytest.raises(ProcessKilled):
        eng.enter(DOGE, backend.stop_dist(), unique_T())
    assert backend.amt(DOGE) == 0 and backend.stops(DOGE)        # pre-arm live, harmless (reduceOnly)
    eng2 = backend.engine()
    eng2.startup()
    assert backend.amt(DOGE) == 0 and not backend.stops(DOGE) and not eng2.st["intents"]


def test_new_stop_confirmed_before_old_cancelled(backend):
    """Entry: pre-arm (reduceOnly qty) → fill → closePosition stop confirmed → only then pre-arm cancelled.
    Replacement of an insufficient stop also places the new one first."""
    eng = ready(backend)
    seq = []
    for m in ("stop", "cancel", "market"):
        backend.fx.inject(m, (lambda name: lambda fn, *a, **kw: (seq.append(name), fn(*a, **kw))[1])(m), times=99)
    opened(backend, eng)
    assert seq[:4] == ["stop", "market", "stop", "cancel"], seq
    st = backend.stops(DOGE)
    assert len(st) == 1 and st[0]["close_position"]
    seq.clear()
    for o in backend.stops(DOGE):                                # replace with an insufficient qty stop of ours
        backend.inner.cancel(DOGE, o)
    backend.fx.clear()
    backend.inner.stop(DOGE, "SELL", Decimal(eng.st["pos"][DOGE]["stop_px"]), f"v6tsmall{unique_T()}", qty=eng.rules[DOGE].step_size)
    for m in ("stop", "cancel"):
        backend.fx.inject(m, (lambda name: lambda fn, *a, **kw: (seq.append(name), fn(*a, **kw))[1])(m), times=99)
    eng.reconcile()
    assert seq[:2] == ["stop", "cancel"], seq
    backend.assert_safe()
    assert close_orders(backend) == 0


def test_restart_with_stop_removed(backend):
    eng = ready(backend)
    opened(backend, eng)
    for o in backend.stops(DOGE):
        backend.inner.cancel(DOGE, o)
    assert not backend.stops(DOGE)
    eng2 = backend.engine()
    eng2.startup()
    assert backend.stops(DOGE) and any("손절 주문 없음" in m for m in alerts(eng2))
    backend.assert_safe()


def test_restart_multiple_positions_rearms_all(backend):
    """TA (a): restart while holding several positions → every stop re-armed, no duplicate entries."""
    eng = ready(backend)
    t0 = int(time.time() * 1000) - 5000
    Ts = {s: opened(backend, eng, s) for s in TEST_SYMBOLS}
    for s in TEST_SYMBOLS:
        for o in backend.stops(s):
            backend.inner.cancel(s, o)
    eng2 = backend.engine()
    eng2.startup()
    for s in TEST_SYMBOLS:
        assert backend.stops(s), s
        assert not eng2.enter(s, backend.stop_dist(s), Ts[s])
        assert backend.entry_orders(s, t0) == 1, s
    backend.assert_safe()


# ───────────── network / API faults ─────────────
def test_entry_response_lost_no_duplicate(backend):
    eng = ready(backend)
    t0 = int(time.time() * 1000) - 5000
    if backend.kind == "testnet":
        backend.transport.inject("/fapi/v1/order", "lost", method="POST")
    else:
        backend.fx.inject("market", "lost", match=is_entry)
    assert eng.enter(DOGE, backend.stop_dist(), unique_T())          # found by client id
    assert backend.entry_orders(DOGE, t0) == 1 and backend.stops(DOGE)
    backend.assert_safe()


def test_entry_never_sent_is_not_resent(backend):
    eng = ready(backend)
    if backend.kind == "testnet":
        backend.transport.inject("/fapi/v1/order", "connect", method="POST")
    else:
        backend.fx.inject("market", "unavailable", match=is_entry)
    assert not eng.enter(DOGE, backend.stop_dist(), unique_T())
    assert eng.meta["skip_log"][-1][2] == "order_absent"
    assert backend.amt(DOGE) == 0 and not eng.st["intents"]


def test_drop_during_status_query(backend):
    """Entry executed, response lost, AND every status query fails → entries blocked + 🚨; once the network is
    back, reconcile resolves the intent by client id, arms the stop and unblocks."""
    eng = ready(backend)
    t0 = int(time.time() * 1000) - 5000
    sent = {"market": False}

    def lost_mark(fn, *a, **kw):
        fn(*a, **kw)
        sent["market"] = True
        raise ExchangeUnavailable("injected: response lost")
    backend.fx.inject("market", lost_mark, match=is_entry)
    backend.fx.inject("get_order", "unavailable", times=eng.cfg.query_retries, match=lambda *a: sent["market"])
    assert not eng.enter(DOGE, backend.stop_dist(), unique_T())
    assert E.UNKNOWN_ORDER in eng.blocks and alerts(eng) and eng.st["intents"]
    backend.fx.clear()
    eng.reconcile()
    eng.reconcile()
    assert DOGE in eng.st["pos"] and backend.stops(DOGE) and not eng.st["intents"]
    assert E.UNKNOWN_ORDER not in eng.blocks and backend.entry_orders(DOGE, t0) == 1
    backend.assert_safe()


def test_outage_while_holding_never_closes(backend):
    """§8c L0: network down while holding → nothing is closed, the exchange stop is untouched, NEW entries are
    paused at once; alert only after 60 s; 3 successful calls after recovery resume entries."""
    clk = OffsetClock()
    eng = ready(backend, clock=clk)
    opened(backend, eng)
    stop_before = backend.stops(DOGE)
    n = len(alerts(eng))
    sd_sol = backend.stop_dist(SOL)
    if backend.kind == "testnet":
        backend.transport.inject("/fapi/", "connect", times=6)
    else:
        backend.fx.inject("account", "unavailable", times=6)
    for _ in range(3):
        with pytest.raises(ExchangeUnavailable):
            eng.reconcile()
    assert E.API_ERRORS in eng.blocks and len(alerts(eng)) == n         # paused, no alert yet
    assert not eng.enter(SOL, sd_sol, unique_T())
    clk.off += 61
    with pytest.raises(ExchangeUnavailable):
        eng.reconcile()
    eng.check_transient()
    assert any("일시 장애" in m for m in alerts(eng))
    backend.fx.clear()
    if backend.transport:
        backend.transport.rules.clear()
    assert backend.stops(DOGE) == stop_before
    eng.reconcile()
    assert E.API_ERRORS not in eng.blocks and not eng.meta.get("halted")
    assert close_orders(backend) == 0
    backend.assert_safe()


@pytest.mark.parametrize("mode", ["http429", "http418", "http503", "http500", "timeout", "connect"])
def test_http_faults_map_to_unavailable(backend, mode):
    if backend.kind != "testnet":
        import httpx
        status = {"http429": 429, "http418": 418, "http503": 503, "http500": 500}.get(mode)

        def h(req):
            if status:
                return httpx.Response(status, json={"code": -1, "msg": "x"})
            raise (httpx.ReadTimeout if mode == "timeout" else httpx.ConnectError)("x", request=req)
        c = BinanceREST("https://testnet.binancefuture.com", "k", "s", transport=httpx.MockTransport(h))
    else:
        c = backend.inner
        backend.transport.inject("/fapi/v1/ticker/bookTicker", mode)
    with pytest.raises(ExchangeUnavailable):
        c.book(DOGE)
    if backend.kind == "testnet":
        assert c.book(DOGE)["bid"] > 0                   # next call fine


def test_rejection_codes_offline():
    import httpx

    def h(req):
        if "algoOrder" in req.url.path:
            return httpx.Response(400, json={"code": -2021, "msg": "Order would immediately trigger."})
        if "order" in req.url.path:
            return httpx.Response(400, json={"code": -1007, "msg": "Timeout waiting for response"})
        return httpx.Response(400, json={"code": -1102, "msg": "bad param"})
    c = BinanceREST("https://testnet.binancefuture.com", "k", "s", transport=httpx.MockTransport(h))
    with pytest.raises(WouldTrigger):
        c.stop(DOGE, "SELL", Decimal("0.1"), "x")
    with pytest.raises(ExchangeUnavailable):
        c.market(DOGE, "BUY", Decimal(1), "x")
    with pytest.raises(OrderRejected):
        c.book(DOGE)


# ───────────── stops / emergency ─────────────
def _drop_stops(backend, sym):
    for o in backend.stops(sym):
        backend.inner.cancel(sym, o)


def test_stop_rejected_closes_only_that_position(backend):
    """§8c L1: a missing stop is re-placed 3× (within 10 s); still rejected → close ONLY that position
    (reduceOnly MARKET). Other positions untouched, no halt."""
    eng = ready(backend)
    opened(backend, eng, SOL)
    opened(backend, eng)
    _drop_stops(backend, DOGE)
    backend.fx.inject("stop", "reject", times=eng.cfg.stop_attempts, match=lambda s, *a, **k: s == DOGE)
    t = time.time()
    eng.reconcile()
    assert time.time() - t < 15
    assert backend.amt(DOGE) == 0 and backend.amt(SOL) > 0 and backend.stops(SOL)
    assert not eng.meta.get("halted") and any("이 포지션만 정리" in m for m in alerts(eng))
    assert [c[1][0] for c in close_calls(backend)] == [DOGE]
    assert sum(1 for c in backend.fx.calls if c[0] == "stop" and c[1][0] == DOGE) >= eng.cfg.stop_attempts
    backend.assert_safe()


def test_unprotectable_position_flattens_all_and_halts(backend):
    """§8c L3(b): stop cannot be placed AND that position cannot be closed → flatten ALL + halt + 🚨."""
    eng = ready(backend)
    opened(backend, eng, SOL)
    opened(backend, eng)
    _drop_stops(backend, DOGE)
    backend.fx.inject("stop", "reject", times=eng.cfg.stop_attempts, match=lambda s, *a, **k: s == DOGE)
    backend.fx.inject("market", "reject", times=eng.cfg.exit_attempts, match=lambda s, *a, **k: s == DOGE)
    eng.reconcile()
    for _ in range(3):
        if backend.amt(DOGE) == 0 and backend.amt(SOL) == 0:
            break
        eng.reconcile()                                  # closing flags persist → retried until flat
    assert backend.amt(DOGE) == 0 and backend.amt(SOL) == 0
    assert str(eng.meta.get("halted")).startswith("emergency") and any("비상청산" in m for m in alerts(eng))
    assert not eng.enter(XRP, backend.stop_dist(XRP), unique_T())
    assert eng.meta["skip_log"][-1][2] == "safety_block"
    for s in TEST_SYMBOLS:
        assert not backend.stops(s)


def test_breach_closes_only_that_position(backend):
    """Mark beyond the stop but the exchange still holds the position (stop did not fire) → reduceOnly close of
    THAT position only + 🚨; other positions keep their stops; no halt."""
    eng = ready(backend)
    opened(backend, eng, SOL)
    opened(backend, eng)
    if backend.kind == "offline":
        backend.inner.stops_fire = False
        backend.inner.set_price(DOGE, Decimal(eng.st["pos"][DOGE]["stop_px"]) - Decimal("0.001"))
    else:          # testnet price can't be moved: the exchange mark is reported above the journal stop
        below = Decimal(eng.st["pos"][DOGE]["stop_px"]) - eng.rules[DOGE].tick_size
        backend.fx.inject("mark_prices", lambda fn: dict(fn(), DOGEUSDT=below))
    eng.reconcile()
    assert backend.amt(DOGE) == 0 and backend.amt(SOL) > 0 and backend.stops(SOL)
    assert not eng.meta.get("halted") and any("손절가 돌파" in m for m in alerts(eng))
    assert [c[1][0] for c in close_calls(backend)] == [DOGE]
    backend.assert_safe()


def test_drawdown_15pct_flattens_all_and_halts(backend):
    """§8c L3(a) / §8e-2: equity ≤ halt_fraction × S0 (−25 %) → flatten ALL + halt."""
    eng = ready(backend)
    opened(backend, eng, SOL)
    opened(backend, eng)
    s0 = Decimal(eng.meta["wallet"]) / Decimal("0.74")              # equity is now 74 % of S0 (< 75 %)
    eng.meta.update(start_wallet=str(s0), capital0=str(s0))
    eng.reconcile()
    assert backend.amt(DOGE) == 0 and backend.amt(SOL) == 0
    assert str(eng.meta.get("halted")).startswith("emergency")


def test_api_dead_5min_with_unprotected_position_flattens_all(offline):
    """§8c L3(c): stop placement outcome unknown (unprotected) and the API then stays dead > 5 min → flatten all.
    Counter-case: API dead > 5 min while every position is protected → nothing closed."""
    clk = OffsetClock()
    eng = ready(offline, clock=clk)
    opened(offline, eng, SOL)
    opened(offline, eng)
    offline.fx.inject("account", "unavailable", times=99)
    for _ in range(3):
        eng.tick()
    clk.off += 301
    eng.tick()
    assert close_orders(offline) == 0 and not eng.meta.get("halted")     # protected → never flatten
    offline.fx.clear()
    eng.reconcile()
    _drop_stops(offline, DOGE)
    offline.fx.inject("stop", "unavailable", times=99)
    eng.reconcile()                                      # stop not confirmable → unprotected, NOT closed yet
    assert eng.st["pos"][DOGE].get("unprotected") and offline.amt(DOGE) > 0 and close_orders(offline) == 0
    offline.fx.inject("account", "unavailable", times=99)
    eng.tick()
    clk.off += 301
    eng.tick()
    assert str(eng.meta.get("halted")).startswith("emergency")
    offline.fx.clear()
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and offline.amt(SOL) == 0


# ───────────── §8c over-reaction: transient faults must send ZERO close orders ─────────────
def test_overreaction_5xx_three_in_a_row(backend):
    eng = ready(backend)
    opened(backend, eng, SOL)
    opened(backend, eng)
    before = {s: backend.stops(s) for s in (DOGE, SOL)}
    if backend.kind == "testnet":
        backend.transport.inject("/fapi/", "http503", times=3)
    else:
        backend.fx.inject("account", "unavailable", times=3)
    for _ in range(3):
        with pytest.raises(ExchangeUnavailable):
            eng.reconcile()
    assert E.API_ERRORS in eng.blocks
    eng.reconcile()
    assert close_orders(backend) == 0 and not eng.meta.get("halted")
    assert {s: backend.stops(s) for s in (DOGE, SOL)} == before
    assert E.API_ERRORS not in eng.blocks
    backend.assert_safe()


def test_overreaction_429_once(backend):
    eng = ready(backend)
    opened(backend, eng)
    if backend.kind == "testnet":
        backend.transport.inject("/fapi/", "http429", times=1)
    else:
        backend.fx.inject("account", "unavailable", times=1)
    with pytest.raises(ExchangeUnavailable):
        eng.reconcile()
    eng.reconcile()
    assert close_orders(backend) == 0 and not eng.meta.get("halted") and not alerts(eng)
    backend.assert_safe()


def test_overreaction_stop_rejected_once_then_retry_ok(backend):
    eng = ready(backend)
    opened(backend, eng, SOL)
    opened(backend, eng)
    _drop_stops(backend, DOGE)
    backend.fx.inject("stop", "reject", times=1, match=lambda s, *a, **k: s == DOGE)
    eng.reconcile()
    assert backend.stops(DOGE) and backend.amt(DOGE) > 0
    assert close_orders(backend) == 0 and not eng.meta.get("halted")
    backend.assert_safe()


# ───────────── exits / partial fills ─────────────
def test_exit_response_lost_no_duplicate(backend):
    eng = ready(backend)
    opened(backend, eng)
    t0 = int(time.time() * 1000) - 5000
    if backend.kind == "testnet":
        backend.transport.inject("/fapi/v1/order", "lost", method="POST")
    else:
        backend.fx.inject("market", "lost", match=is_exit)
    assert eng.close(DOGE, "signal_exit")
    assert backend.amt(DOGE) == 0 and not backend.stops(DOGE) and DOGE not in eng.st["pos"]
    exits = [c for c in backend.fx.calls if c[0] == "market" and c[1][4]]
    assert len(exits) == 1
    assert eng.meta["trades"][-1]["reason"] == "signal_exit"


def test_partial_fills_and_failed_final_exit(backend):
    """TA partial-fill rules:
      1. entry partially filled → stop armed IMMEDIATELY for the filled qty (closePosition), journal = filled qty;
      2. exit leaves a remainder below min notional → the whole remainder closes in ONE reduceOnly order (no dust);
      3. that final exit keeps failing (API errors) → retried until flat, 🚨, stop kept until flat."""
    eng = ready(backend)
    step = eng.rules[DOGE].step_size

    def partial_entry(fn, s, side, qty, cid, reduce_only=False):
        o = fn(s, side, floor_to(qty * Decimal("0.6"), step), cid, reduce_only)
        return dict(o, orig_qty=qty, status="EXPIRED")
    backend.fx.inject("market", partial_entry, match=is_entry)
    T = unique_T()
    assert eng.enter(DOGE, backend.stop_dist(), T)
    j = eng.st["pos"][DOGE]
    assert Decimal(j["qty"]) == backend.amt(DOGE) < Decimal(j["planned_qty"])
    assert backend.stops(DOGE) and any("부분 체결" in m for m in eng.tg.sent)
    assert Decimal(j["risk_usdt"]) == (Decimal(j["entry_px"]) - Decimal(j["stop_px"])) * Decimal(j["qty"])
    held = backend.amt(DOGE)
    assert held * backend.inner.book(DOGE)["bid"] > eng.rules[DOGE].min_notional

    def dusty_exit(fn, s, side, qty, cid, reduce_only=False):      # leaves 1 DOGE (≪ 5 USDT min notional)
        return fn(s, side, qty - step, cid, reduce_only)
    backend.fx.inject("market", dusty_exit, match=is_exit)
    backend.fx.inject("market", "unavailable", times=eng.cfg.exit_attempts + 3, match=is_exit)
    assert not eng.close(DOGE, "signal_exit")                       # remainder left, final exit failing
    assert backend.amt(DOGE) == step and backend.stops(DOGE)        # stop kept while not flat
    assert any("청산 미완료" in m for m in alerts(eng))
    assert eng.st["pos"][DOGE]["closing"]
    for _ in range(3):
        eng.reconcile()                                             # 5 s loop keeps retrying
        if backend.amt(DOGE) == 0:
            break
    assert backend.amt(DOGE) == 0 and not backend.stops(DOGE) and DOGE not in eng.st["pos"]
    sent = [c for c in backend.fx.calls if c[0] == "market" and c[1][4]]
    final = [c for c in sent if Decimal(c[1][2]) == step]
    assert final and all(Decimal(c[1][2]) in (held, step) for c in sent)   # remainder always in one order


# ───────────── portfolio caps at the order-placement step ─────────────
def _external_position_before_placement(backend, sym_ext):
    """An external position appears AFTER the sizing reads (hooked on the book fetch) and BEFORE the final
    placement read (set_leverage is skipped when the leverage is already right)."""
    def hook(fn, s):
        out = fn(s)
        if s == DOGE and backend.amt(sym_ext) == 0:
            px = backend.inner.book(sym_ext)["ask"]
            q = floor_to(Decimal(12) / px, Decimal(FILT_STEP[sym_ext]))
            backend.inner.market(sym_ext, "BUY", q, f"v6text{int(time.time() * 1000)}", False)
        return out
    backend.fx.inject("book", hook, times=99, match=lambda s: s == DOGE)


FILT_STEP = {"DOGEUSDT": "1", "SOLUSDT": "0.01", "XRPUSDT": "0.1"}


def test_risk_cap_enforced_at_placement(backend):
    """TA (c): the 2.5% open-risk cap is re-checked on a FRESH exchange read right before the order. A position
    that appears between sizing and placement (unknown risk → counted as 1%) must block the entry."""
    eng = ready(backend, sizing=SizingParams(portfolio_risk_cap=0.012))
    opened(backend, eng, SOL)                                    # 0.5% open
    _external_position_before_placement(backend, XRP)
    assert not eng.enter(DOGE, backend.stop_dist(), unique_T())  # sizing saw 0.5%+0.5% ≤ 1.2%; placement sees 2%
    assert eng.meta["skip_log"][-1][2] == "risk_cap_portfolio"
    assert backend.amt(DOGE) == 0


def test_max_positions_enforced_at_placement(backend):
    eng = ready(backend, max_positions=2)
    opened(backend, eng, SOL)
    _external_position_before_placement(backend, XRP)
    assert not eng.enter(DOGE, backend.stop_dist(), unique_T())
    assert eng.meta["skip_log"][-1][2] == "max_positions"
    assert backend.amt(DOGE) == 0


# ───────────── ledger ─────────────
def test_ledger_matches_income_after_round_trip(backend):
    """Wallet change over a full trade must equal the income ledger (income field parsing, USDT rows only)."""
    eng = ready(backend)
    opened(backend, eng)
    assert eng.close(DOGE, "signal_exit")
    time.sleep(2 if backend.kind == "testnet" else 0)
    eng.reconcile()
    eng.reconcile()
    assert E.LEDGER not in eng.blocks
    assert abs(Decimal(eng.meta["wallet"]) - Decimal(eng.meta["ledger_balance"])) < Decimal("0.01")


def test_ledger_gap_blocks_entries(backend):
    eng = ready(backend)

    def richer(fn):
        a = fn()
        return dict(a, wallet=a["wallet"] * Decimal("1.02"))
    backend.fx.inject("account", richer, times=99)
    eng.reconcile()
    eng.reconcile()
    assert E.LEDGER in eng.blocks and any("장부-거래소" in m for m in alerts(eng))
    assert not eng.entries_allowed()
