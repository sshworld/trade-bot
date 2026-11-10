"""Round-5 majors. Offline fakes only. Long and short.

These assert the required behavior and fail on e72b2a5.
"""
import pytest
from decimal import Decimal as D

from live_v6.engine import PROTECT_AUDIT_S
from live_v6.exchange import ExchangeUnavailable, OrderRejected
from live_v6.tests.test_protection_policy_v1 import _alerts, _closes, _sleeps, engine_for
from live_v6.tests.test_pr2_round3 import _markets, _pop_t1, _stop_posts, _through, _tp_posts
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _fills(offline):
    return [o for o in offline.inner.orders.values()
            if o["symbol"] == DOGE and o.get("reduce_only") and D(o["executed_qty"]) > 0]


def _empty_book(fn, s, **k):
    return [] if s == DOGE else fn(s)


def _live_t1(offline):
    return [o for o in offline.inner.algos.values()
            if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or "")
            and str(o.get("client_id") or "").endswith("t1")]


def _hold(offline, eng, side, pop_t1=False):
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, _through(j, side))
    if pop_t1:
        _pop_t1(offline)
    eng.cfg.trail_atr_k = 0
    eng._cp_hold.add(DOGE)
    eng._cp_retry_at[DOGE] = eng.clock() + 10**9
    eng._protect_audit_at = eng.clock()
    eng.save()
    return j, qty


def _fire(offline):
    offline.inner.stops_fire = True
    offline.inner.set_price(DOGE, offline.inner.price[DOGE])


@pytest.mark.parametrize("side", [1, -1])
def test_n1_live_t1_is_cancelled_before_the_slice_market(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    q1 = D(j["tp"]["q1"])
    assert _live_t1(offline)
    offline.fx.inject("open_orders", _empty_book, times=80)
    eng.tick()
    _fire(offline)
    assert not _live_t1(offline)
    assert offline.amt(DOGE) == qty - side * q1


@pytest.mark.parametrize("side", [1, -1])
def test_n1_unconfirmed_cancel_sends_no_market(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    assert _live_t1(offline)
    offline.fx.inject("open_orders", _empty_book, times=40)
    offline.fx.inject("cancel", "unavailable", times=5)
    before = len(_markets(offline))
    eng.tick()
    assert len(_markets(offline)) == before
    assert offline.amt(DOGE) == qty
    assert _live_t1(offline)
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_n1_fill_between_reads_does_not_market_the_remainder(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    q1 = D(j["tp"]["q1"])
    fired = {"n": 0}

    def fire_on_last(fn, s, **k):
        if s == DOGE and fired["n"] == 0 and _live_t1(offline):
            fired["n"] += 1
            _fire(offline)
        return fn(s, **k)

    offline.fx.inject("open_orders", _empty_book, times=80)
    offline.fx.inject("last_price", fire_on_last, times=5)
    before = len(_markets(offline))
    eng.tick()
    assert fired["n"] == 1
    assert len(_markets(offline)) == before
    assert offline.amt(DOGE) == qty - side * q1
    assert eng.st["pos"][DOGE].get("tp1_done") is True


@pytest.mark.parametrize("side", [1, -1])
def test_n2_unknown_cid_blocks_the_inside_replacement(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side, pop_t1=True)
    eng._cp_hold.discard(DOGE)

    def hide(fn, s, cid, **k):
        if cid in offline.inner.orders:
            raise ExchangeUnavailable("status unknown")
        return fn(s, cid, **k)

    def stale(fn, symbols, **k):
        out = {s: dict(r) for s, r in fn(symbols).items()}
        if DOGE in out:
            out[DOGE]["amt"] = qty
        return out

    offline.fx.inject("market", "lost", times=1)
    offline.fx.inject("get_order", hide, times=80)
    offline.fx.inject("positions", stale, times=80)
    eng.tick()
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    tps0 = len(_tp_posts(offline))
    markets0 = len(_markets(offline))
    cancels0 = len([c for c in offline.fx.calls if c[0] == "cancel"])
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, D(j["entry_px"]))
    offline.inner.last = {DOGE: D(j["entry_px"])}
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert len(_tp_posts(offline)) == tps0
    assert len(_markets(offline)) == markets0
    assert len([c for c in offline.fx.calls if c[0] == "cancel"]) == cancels0
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1
    offline.inner.last = {}
    _fire(offline)
    assert offline.amt(DOGE) != 0


@pytest.mark.parametrize("side", [1, -1])
def test_n3_partial_fill_does_not_finish_the_slice(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _sleeps(eng)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, _through(j, side))
    _pop_t1(offline)
    stops0 = len(_stop_posts(offline))

    def partial(fn, s, sd, q, cid, reduce_only=False, **k):
        return fn(s, sd, q, cid, reduce_only=reduce_only, fill_qty=D(1))

    offline.fx.inject("market", partial, times=1)
    eng.tick()
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    assert offline.amt(DOGE) == qty - side * D(1)
    assert len(_stop_posts(offline)) == stops0
    assert not [o for o in offline.inner.open_orders(DOGE) if "t3" in str(o["client_id"])]
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert sum(o["executed_qty"] for o in _fills(offline)) >= q1 - D(1)
    assert offline.amt(DOGE) == qty - side * q1
    assert eng.st["pos"][DOGE].get("tp1_done") is True


@pytest.mark.parametrize("side", [1, -1])
def test_n4_last_4116_then_4130_does_not_flatten(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    assert any(o.get("close_position") and (o["type"] or "").startswith("STOP")
               for o in offline.inner.open_orders(DOGE))
    n4116 = {"n": 0}

    def spent_then_natural(fn, s, sd, trigger, cid, qty=None, **k):
        if n4116["n"] < 4:
            n4116["n"] += 1
            raise OrderRejected(-4116, "ClientOrderId is duplicated.")
        return fn(s, sd, trigger, cid, qty=qty, **k)

    offline.fx.inject("stop", spent_then_natural, times=8)
    before = len(_closes(offline))
    eng._arm_stop(DOGE, j, qty)
    assert offline.amt(DOGE) == qty
    assert len(_closes(offline)) == before
    assert any(o.get("close_position") and (o["type"] or "").startswith("STOP")
               for o in offline.inner.open_orders(DOGE))


@pytest.mark.parametrize("side", [1, -1])
def test_n5_presend_read_failure_retries_after_a_minute(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _sleeps(eng)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, _through(j, side))
    _pop_t1(offline)

    def fail_exit_cid(fn, s, cid, **k):
        tail = str(cid).rsplit("x", 1)[-1]
        if "x" in str(cid) and tail.isdigit():
            raise ExchangeUnavailable("pre-send get_order failed")
        return fn(s, cid, **k)

    offline.fx.inject("get_order", fail_exit_cid, times=8)
    before = len(_markets(offline))
    eng.tick()
    assert len(_markets(offline)) == before
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    assert offline.amt(DOGE) == qty
    offline.fx.clear()
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert len(_markets(offline)) >= before + 1
    assert offline.amt(DOGE) == qty - side * q1
    assert eng.st["pos"][DOGE].get("tp1_done") is True


@pytest.mark.parametrize("side", [1, -1])
def test_n6_dust_hold_does_not_move_be_on_a_flat_coin(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, _qty = _hold(offline, eng, side, pop_t1=True)
    one = D(1)
    p = offline.inner.pos[DOGE]
    p["amt"] = one if side > 0 else -one
    p["margin"] = one * p["entry"] / offline.inner.lev[DOGE]
    j["qty"] = "1"
    j["tp"]["q1"] = "1"
    eng.save()
    offline.fx.inject("open_orders", _empty_book, times=40)
    stops0 = len(_stop_posts(offline))
    eng.tick()
    assert offline.amt(DOGE) == (one if side > 0 else -one)
    assert len(_stop_posts(offline)) == stops0


@pytest.mark.parametrize("side", [1, -1])
def test_n7_mark_through_last_inside_markets_the_runner(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    _sleeps(eng)
    offline.inner.stops_fire = False
    j["tp1_done"] = True
    j["be_done"] = True
    eng.cfg.trail_atr_k = 0
    eng.save()
    runner = eng._runner_px(DOGE, j)
    be = eng._be_target(DOGE, j)
    inside = (be + runner) / 2
    offline.inner.set_price(DOGE, inside)
    offline.inner.last = {DOGE: inside}
    offline.inner.mark_price = lambda s: runner + side * D("0.01") if s == DOGE else offline.inner.price[s]
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or ""):
            offline.inner.algos.pop(o["id"], None)
    qty = offline.amt(DOGE)

    def boom(fn, s, sd, trigger, c, qty=None, **k):
        from live_v6.exchange import WouldTrigger
        raise WouldTrigger(-2021, "Order would immediately trigger.")

    offline.fx.inject("take_profit", boom, times=3)
    before = len(_markets(offline))
    tps0 = len(_tp_posts(offline))
    eng.tick()
    assert len(_markets(offline)) == before + 1
    assert len(_fills(offline)) == 1 and _fills(offline)[0]["orig_qty"] == abs(qty)
    eng.tick()
    assert len(_tp_posts(offline)) == tps0 + 1          # the rejected POST, and no -2021 loop
    assert len(_markets(offline)) == before + 1


@pytest.mark.parametrize("side", [1, -1])
def test_n8_hold_realization_honors_the_minute_cooldown(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _hold(offline, eng, side, pop_t1=True)
    offline.fx.inject("open_orders", _empty_book, times=80)
    offline.fx.inject("last_price", "unavailable", times=10)
    eng.tick()
    reads = len([c for c in offline.fx.calls if c[0] == "last_price"])
    assert reads >= 1
    eng.tick()
    eng.tick()
    assert len([c for c in offline.fx.calls if c[0] == "last_price"]) == reads
    assert not [c for c in offline.fx.calls if c[0] == "market" and len(c[1]) > 3 and c[1][1] in ("BUY", "SELL")
                and c[1][3] != eng.st["pos"][DOGE]["cid"]]
