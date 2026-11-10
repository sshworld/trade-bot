"""Round-7 majors. Offline fakes only. Long and short, more than one tick.

These assert the required behavior and fail on e66cd34.
"""
import pytest
from decimal import Decimal as D

from live_v6.engine import PROTECT_AUDIT_S, UNKNOWN_ORDER
from live_v6.exchange import ExchangeUnavailable
from live_v6.tests.test_protection_policy_v1 import _alerts, _sleeps, engine_for
from live_v6.tests.test_pr2_round3 import _markets, _pop_t1, _through
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _live_tp(offline, tail):
    return [o for o in offline.inner.algos.values()
            if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or "")
            and str(o.get("client_id") or "").endswith(tail)
            and str(o.get("status") or "NEW").upper() in {"NEW", "WORKING", ""}]


def _stop_algos(offline):
    return [o for o in offline.inner.algos.values()
            if o["symbol"] == DOGE and "STOP" in (o["type"] or "")]


def _empty_book(fn, s, **k):
    return [] if s == DOGE else fn(s)


def _hold(offline, eng, side):
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, _through(j, side))
    eng.cfg.trail_atr_k = 0
    eng._cp_hold.add(DOGE)
    eng._cp_retry_at[DOGE] = eng.clock() + 10**9
    eng._protect_audit_at = eng.clock()
    eng.save()
    return j, qty


def _inside(offline, eng):
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, D(eng.st["pos"][DOGE]["entry_px"]))
    offline.inner.last = {}


def _shrink(offline, side, qty):
    p = offline.inner.pos[DOGE]
    p["amt"] = p["amt"] - side * qty
    p["margin"] = abs(p["amt"]) * p["entry"] / offline.inner.lev[DOGE]


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("status", ["TRIGGERING", "TRIGGERED", "FILLED", "FINISHED"])
def test_t2_1_stale_qty_is_not_sold_after_the_status_changes(offline, side, status):
    """A t1 that leaves NEW after the size read is not sold again from that old size."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    q1 = D(j["tp"]["q1"])
    seen = {"n": 0}

    def flip(fn, s, cid, **k):
        st = fn(s, cid)
        if s != DOGE or not str(cid).endswith("t1") or not isinstance(st, dict):
            return st
        seen["n"] += 1
        st = dict(st)
        if seen["n"] <= 2:                          # exit-fill read, then the release read, both still NEW
            st["status"] = "NEW"
            st["executed_qty"] = D(0)
            return st
        st["status"] = status
        if status in {"FILLED", "FINISHED"} and abs(offline.amt(DOGE)) == abs(qty):
            st["executed_qty"] = q1
            _shrink(offline, side, q1)
        else:
            st["executed_qty"] = D(0)
        return st

    offline.fx.inject("open_orders", _empty_book, times=80)
    offline.fx.inject("algo_order", flip, times=20)
    before = len(_markets(offline))
    eng.tick()
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert len(_markets(offline)) == before
    assert offline.amt(DOGE) != 0
    if status in {"FILLED", "FINISHED"}:
        assert offline.amt(DOGE) == qty - side * q1
        assert eng.st["pos"][DOGE].get("tp1_done") is True
    else:
        assert offline.amt(DOGE) == qty
        offline.inner.stops_fire = True
        offline.inner.set_price(DOGE, offline.inner.price[DOGE])
        assert offline.amt(DOGE) == qty - side * q1


@pytest.mark.parametrize("side", [1, -1])
def test_t2_1_working_then_new_still_cancels_and_markets_the_slice(offline, side):
    """WORKING then NEW is still a resting order: cancel it, then sell only the slice."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    q1 = D(j["tp"]["q1"])
    seen = {"n": 0}

    def working_then_new(fn, s, cid, **k):
        st = fn(s, cid)
        if s != DOGE or not str(cid).endswith("t1") or not isinstance(st, dict):
            return st
        seen["n"] += 1
        st = dict(st)
        if seen["n"] == 2:                          # the release read: WORKING is still a resting order
            st["status"] = "WORKING"
        elif seen["n"] == 3:                        # the cancel read: it is NEW, so it can be cancelled
            st["status"] = "NEW"
        return st

    offline.fx.inject("open_orders", _empty_book, times=40)
    offline.fx.inject("algo_order", working_then_new, times=8)
    before = len(_markets(offline))
    eng.tick()
    assert seen["n"] >= 1
    assert len(_markets(offline)) == before + 1
    assert offline.amt(DOGE) == qty - side * q1
    assert not _live_tp(offline, "t1")
    assert _stop_algos(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t2_2_sub_min_remainder_does_not_flatten(offline, side):
    """13 units under min notional must not sell the other 8346."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    eng._cp_hold.discard(DOGE)
    q1 = D(j["tp"]["q1"])
    remain = D(13)
    got = q1 - remain
    left = abs(qty) - got
    assert remain * offline.inner.price[DOGE] < eng.rules[DOGE].min_notional
    p = offline.inner.pos[DOGE]
    p["amt"] = left if side > 0 else -left
    p["margin"] = left * p["entry"] / offline.inner.lev[DOGE]
    j["qty"] = str(left)
    j.setdefault("tp_got", {})["t1"] = str(got)
    eng.save()
    _pop_t1(offline)
    before = len(_markets(offline))
    eng.tick()
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert offline.amt(DOGE) == (left if side > 0 else -left)
    assert len(_markets(offline)) == before
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    assert len([m for m in _alerts(eng) if DOGE in m]) >= 1
    sold = [o for o in offline.inner.orders.values()
            if o["symbol"] == DOGE and o.get("reduce_only")]
    assert not any(D(o["orig_qty"]) > remain for o in sold)


@pytest.mark.parametrize("side", [1, -1])
def test_t2_3_runner_partial_is_replaced_for_the_remainder_only(offline, side):
    """A 5000/8333 runner fill is not subtracted twice. The next rest is the other 3333."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _sleeps(eng)
    offline.inner.stops_fire = False
    eng.cfg.trail_atr_k = 0
    left = abs(qty) - q1
    partial = D(5000)
    rest = left - partial
    p = offline.inner.pos[DOGE]
    p["amt"] = rest if side > 0 else -rest
    p["margin"] = rest * p["entry"] / offline.inner.lev[DOGE]
    j["qty"] = str(rest)
    j["tp1_done"] = True
    j["be_done"] = True
    j["tp"]["tp3"] = str(eng._runner_px(DOGE, j))
    j["tp"]["q3"] = str(left)
    j["tp_got"] = {"t3": str(partial)}
    eng.save()
    _inside(offline, eng)
    before = len(_live_tp(offline, "t3"))
    eng.tick()
    eng.clock.off += 1
    eng.tick()
    live = _live_tp(offline, "t3")
    assert len(live) == before + 1
    assert D(live[-1]["qty"]) == rest
    assert eng.st["pos"][DOGE].get("tp3_done") is not True
    assert offline.amt(DOGE) == (rest if side > 0 else -rest)


@pytest.mark.parametrize("side", [1, -1])
def test_t2_4_unsent_market_does_not_spend_the_permit(offline, side):
    """A market the exchange never accepted does not block the inside re-place."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    eng._cp_hold.discard(DOGE)
    _pop_t1(offline)
    offline.fx.inject("market", "unavailable", times=1)
    eng.tick()
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    assert offline.amt(DOGE) == qty
    assert not _live_tp(offline, "t1")
    _inside(offline, eng)
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    eng.clock.off += 1
    eng.tick()
    assert _live_tp(offline, "t1")
    assert offline.amt(DOGE) == qty
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    permit = (eng.st["pos"][DOGE].get("tp_market_once") or {}).get("t1")
    assert not permit


@pytest.mark.parametrize("side", [1, -1])
def test_t2_5_partial_shrink_does_not_book_the_whole_stage(offline, side):
    """8000 of 8333 is not the whole TP1. No breakeven, and the other 333 is still sold."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    q1 = D(j["tp"]["q1"])
    filled = D(8000)

    def partial(fn, s, sd, q, cid, reduce_only=False, **k):
        return fn(s, sd, q, cid, reduce_only=reduce_only, fill_qty=filled)

    offline.fx.inject("open_orders", _empty_book, times=30)
    offline.fx.inject("market", partial, times=1)
    eng.tick()
    assert offline.amt(DOGE) == qty - side * filled
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    eng._cp_hold.discard(DOGE)
    offline.fx.clear()
    _inside(offline, eng)
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    assert eng.st["pos"][DOGE].get("be_done") is not True
    offline.inner.stops_fire = True
    offline.inner.set_price(DOGE, _through(j, side))
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert offline.amt(DOGE) == qty - side * q1
    assert eng.st["pos"][DOGE].get("tp1_done") is True


@pytest.mark.parametrize("side", [1, -1])
def test_t2_6_live_partial_market_blocks_the_next_one(offline, side):
    """A PARTIALLY_FILLED market stays tracked. Completing it leaves the slice, not 10."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    eng._cp_hold.discard(DOGE)
    q1 = D(j["tp"]["q1"])
    _pop_t1(offline)
    first = D(10)

    def live_partial(fn, s, sd, q, cid, reduce_only=False, **k):
        out = fn(s, sd, q, cid, reduce_only=reduce_only, fill_qty=first)
        offline.inner.orders[cid]["status"] = "PARTIALLY_FILLED"
        out["status"] = "PARTIALLY_FILLED"
        return out

    offline.fx.inject("market", live_partial, times=1)
    eng.tick()
    assert offline.amt(DOGE) == qty - side * first
    cid = (eng.st["pos"][DOGE].get("tp_market_once") or {}).get("t1", {}).get("cid")
    assert cid
    sent = len(_markets(offline))
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert len(_markets(offline)) == sent
    assert offline.amt(DOGE) == qty - side * first
    order = offline.inner.orders[cid]
    rest = D(order["orig_qty"]) - first
    order["status"] = "FILLED"
    order["executed_qty"] = D(order["orig_qty"])
    _shrink(offline, side, rest)
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert len(_markets(offline)) == sent
    assert offline.amt(DOGE) == qty - side * q1
    assert eng.st["pos"][DOGE].get("tp1_done") is True


@pytest.mark.parametrize("side", [1, -1])
def test_m7_1_failed_query_after_cancel_replaces_the_tp(offline, side):
    """Cancel, then an unreadable pre-send query: the TP comes back after 60s and the stop never leaves."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _j, qty = _hold(offline, eng, side)
    assert _stop_algos(offline)

    def fail_exit_cid(fn, s, cid, **k):
        tail = str(cid).rsplit("x", 1)[-1]
        if "x" in str(cid) and tail.isdigit():
            raise ExchangeUnavailable("pre-send get_order failed")
        return fn(s, cid, **k)

    offline.fx.inject("open_orders", _empty_book, times=80)
    offline.fx.inject("get_order", fail_exit_cid, times=40)
    before = len(_markets(offline))
    eng.tick()
    assert len(_markets(offline)) == before
    assert offline.amt(DOGE) == qty
    assert _stop_algos(offline)
    _inside(offline, eng)
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    eng.clock.off += 1
    eng.tick()
    assert len(_markets(offline)) == before
    assert offline.amt(DOGE) == qty
    assert _live_tp(offline, "t1")
    assert _stop_algos(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_m7_2_unknown_order_stays_until_the_query_succeeds(offline, side):
    """A later clean pass does not clear UNKNOWN_ORDER or book the stage from the shrink."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _hold(offline, eng, side)
    eng._cp_hold.discard(DOGE)
    _pop_t1(offline)

    def hide(fn, s, cid, **k):
        if cid in offline.inner.orders:
            raise ExchangeUnavailable("status unknown")
        return fn(s, cid, **k)

    offline.fx.inject("market", "lost", times=1)
    offline.fx.inject("get_order", hide, times=80)
    eng.tick()
    sent = len(_markets(offline))
    assert UNKNOWN_ORDER in eng.blocks
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert UNKNOWN_ORDER in eng.blocks
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    assert not _live_tp(offline, "t3")
    assert offline.amt(DOGE) == qty - side * D(j["tp"]["q1"])
    assert len(_markets(offline)) == sent
