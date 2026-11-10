"""Round-4 TP WouldTrigger holes. Offline fakes only. Long and short."""
import sys
import pytest
from decimal import Decimal as D

from live_v6.engine import PROTECT_AUDIT_S
from live_v6.exchange import ExchangeUnavailable, OrderRejected, WouldTrigger
from live_v6.tests.test_protection_policy_v1 import _alerts, _sleeps, engine_for
from live_v6.tests.test_pr2_round3 import _markets, _pop_t1, _stop_posts, _through, _tp_posts
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _fills(offline):
    return [o for o in offline.inner.orders.values()
            if o["symbol"] == DOGE and o.get("reduce_only") and D(o["executed_qty"]) > 0]


def _prime(offline, eng, side):
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, _through(j, side))
    _pop_t1(offline)
    return j, qty


@pytest.mark.parametrize("side", [1, -1])
def test_p1_unconfirmed_market_does_not_book_tp1(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _prime(offline, eng, side)
    offline.fx.inject("market", "unavailable", times=1)
    stops0 = len(_stop_posts(offline))
    eng.tick()
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    assert offline.amt(DOGE) == qty
    assert len(_stop_posts(offline)) == stops0
    assert not [o for o in offline.inner.open_orders(DOGE) if "t3" in str(o["client_id"])]
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1
    sent = len(_markets(offline))
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    # The order never landed: change nothing, and do not send a second market.
    assert len(_markets(offline)) == sent
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    assert offline.amt(DOGE) == qty
    assert len(_stop_posts(offline)) == stops0
    assert not [o for o in offline.inner.open_orders(DOGE) if "t3" in str(o["client_id"])]


@pytest.mark.parametrize("side", [1, -1])
def test_p1_qty_comes_from_the_position_reread(offline, side):
    """A confirmed fill books the position re-read, not the order's executed math."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _prime(offline, eng, side)
    before = len(_markets(offline))
    seen = D(9000)

    def reread(fn, symbols, **k):
        out = {s: dict(r) for s, r in fn(symbols).items()}
        if DOGE in out and len(_markets(offline)) > before:
            out[DOGE]["amt"] = side * seen
        return out

    offline.fx.inject("positions", reread, times=40)
    eng.tick()
    assert eng.st["pos"][DOGE].get("tp1_done") is True
    assert D(eng.st["pos"][DOGE]["qty"]) == seen
    runners = [o for o in offline.inner.open_orders(DOGE) if "t3" in str(o["client_id"])]
    assert len(runners) == 1 and runners[0]["qty"] == seen
    assert len(_fills(offline)) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_p2_below_min_notional_does_not_recurse(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    _sleeps(eng)
    offline.inner.stops_fire = False
    signed = D(1 if side > 0 else -1)
    p = offline.inner.pos[DOGE]
    p["amt"] = signed
    p["margin"] = abs(signed) * p["entry"] / offline.inner.lev[DOGE]
    j["qty"] = "1"
    j["tp1_done"] = True
    eng.save()
    runner = eng._runner_px(DOGE, j)
    offline.inner.set_price(DOGE, runner + side * D("0.01"))
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or ""):
            offline.inner.algos.pop(o["id"], None)
    before_tp = len(_tp_posts(offline))
    before_m = len(_markets(offline))
    stops0 = len(_stop_posts(offline))
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(80)
    try:
        eng._arm_unsplittable(DOGE, j)
    finally:
        sys.setrecursionlimit(old)
    assert len(_tp_posts(offline)) - before_tp <= 1
    assert not [o for o in offline.inner.open_orders(DOGE) if "TAKE_PROFIT" in (o["type"] or "")]
    fills = _fills(offline)
    assert len(_markets(offline)) == before_m + 1
    assert len(fills) == 1 and fills[0]["reduce_only"] is True and fills[0]["orig_qty"] == D(1)
    assert fills[0]["side"] == ("SELL" if side > 0 else "BUY")
    assert len(_stop_posts(offline)) == stops0


@pytest.mark.parametrize("side", [1, -1])
def test_p2_dust_slice_markets_the_whole_remainder(offline, side):
    """A slice under min notional does not split and does not rest another TP."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, _qty = _prime(offline, eng, side)
    whole = D(100)
    p = offline.inner.pos[DOGE]
    p["amt"] = whole if side > 0 else -whole
    p["margin"] = whole * p["entry"] / offline.inner.lev[DOGE]
    j["qty"] = str(whole)
    j["tp"]["q1"] = "1"
    eng.save()
    before_tp = len(_tp_posts(offline))
    before_m = len(_markets(offline))
    stops0 = len(_stop_posts(offline))
    eng.tick()
    assert len(_tp_posts(offline)) - before_tp <= 1
    assert not [o for o in offline.inner.open_orders(DOGE) if "TAKE_PROFIT" in (o["type"] or "")]
    fills = _fills(offline)
    assert len(_markets(offline)) == before_m + 1
    assert len(fills) == 1 and fills[0]["orig_qty"] == whole and fills[0]["reduce_only"] is True
    assert offline.amt(DOGE) == 0
    assert len(_stop_posts(offline)) == stops0


@pytest.mark.parametrize("side", [1, -1])
def test_p3_unknown_fill_is_not_sold_again(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _prime(offline, eng, side)
    q1 = D(j["tp"]["q1"])

    def hide(fn, s, cid, **k):
        if cid in offline.inner.orders:
            raise ExchangeUnavailable("status unknown")
        return fn(s, cid, **k)

    offline.fx.inject("market", "lost", times=1)
    offline.fx.inject("get_order", hide, times=40)
    eng.tick()
    after = offline.amt(DOGE)
    assert after == qty - side * q1
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    offline.fx.clear()

    def stale(fn, symbols, **k):
        out = {s: dict(r) for s, r in fn(symbols).items()}
        if DOGE in out:
            out[DOGE]["amt"] = qty
        return out

    offline.fx.inject("positions", stale, times=80)
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert offline.amt(DOGE) == after
    assert offline.amt(DOGE) != 0
    assert len(_fills(offline)) == 1
    # The read is still the old size, so this is not a confirmed shrink and not a second market.
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    offline.fx.clear()
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert offline.amt(DOGE) == after
    assert len(_fills(offline)) == 1
    assert eng.st["pos"][DOGE].get("tp1_done") is True
    assert D(eng.st["pos"][DOGE]["qty"]) == abs(after)
    runners = [o for o in offline.inner.open_orders(DOGE) if "t3" in str(o["client_id"])]
    assert len(runners) == 1 and runners[0]["qty"] == abs(after)


@pytest.mark.parametrize("side", [1, -1])
def test_p4_last_inside_replaces_even_if_bid_is_through(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    tp = D(j["tp"]["tp1"])
    qty = offline.amt(DOGE)
    inside = D(j["entry_px"])
    _sleeps(eng)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, inside)
    offline.inner.last = {DOGE: inside}
    bid = tp + side * D("0.01")

    def book_split(s):
        px = offline.inner.price[s]
        if s != DOGE:
            return {"bid": px, "ask": px}
        return {"bid": bid, "ask": inside}

    offline.inner.book = book_split
    _pop_t1(offline)

    def boom(fn, s, sd, trigger, c, qty=None, **k):
        raise WouldTrigger(-2021, "Order would immediately trigger.")

    offline.fx.inject("take_profit", boom, times=1)
    before = len(_markets(offline))
    eng.tick()
    assert len(_markets(offline)) == before
    assert offline.amt(DOGE) == qty
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    live = [o for o in offline.inner.open_orders(DOGE)
            if o["type"] == "TAKE_PROFIT_MARKET" and str(o["client_id"]).endswith("t1")]
    assert len(live) == 1


def _split_book(offline, bid, ask):
    def book_split(s):
        px = offline.inner.price[s]
        if s != DOGE:
            return {"bid": px, "ask": px}
        return {"bid": bid, "ask": ask}

    offline.inner.book = book_split


@pytest.mark.parametrize("side", [1, -1])
def test_p4_mark_through_last_inside_does_not_market(offline, side):
    """A MARK_PRICE runner is still judged from the last trade, never the mark."""
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

    def mark_through(s):
        if s == DOGE:
            return runner + side * D("0.01")
        return offline.inner.price[s]

    offline.inner.mark_price = mark_through
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or ""):
            offline.inner.algos.pop(o["id"], None)
    _split_book(offline, runner + side * D("0.01"), inside)

    def boom(fn, s, sd, trigger, c, qty=None, **k):
        raise WouldTrigger(-2021, "Order would immediately trigger.")

    offline.fx.inject("take_profit", boom, times=1)
    before = len(_markets(offline))
    qty = offline.amt(DOGE)
    eng.tick()
    assert len(_markets(offline)) == before
    assert offline.amt(DOGE) == qty
    live = [o for o in offline.inner.open_orders(DOGE) if "t3" in str(o["client_id"])]
    assert len(live) == 1 and live[0]["working_type"] == "MARK_PRICE"


@pytest.mark.parametrize("side", [1, -1])
def test_p4_last_through_markets_even_when_mark_is_inside(offline, side):
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
    offline.inner.last = {DOGE: runner + side * D("0.01")}
    offline.inner.mark_price = lambda s: inside if s == DOGE else offline.inner.price[s]
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or ""):
            offline.inner.algos.pop(o["id"], None)
    _split_book(offline, inside, inside)

    def boom(fn, s, sd, trigger, c, qty=None, **k):
        raise WouldTrigger(-2021, "Order would immediately trigger.")

    offline.fx.inject("take_profit", boom, times=1)
    before = len(_markets(offline))
    qty = offline.amt(DOGE)
    eng.tick()
    assert len(_markets(offline)) == before + 1
    assert len(_fills(offline)) == 1 and _fills(offline)[0]["orig_qty"] == abs(qty)


@pytest.mark.parametrize("side", [1, -1])
def test_p4_unreadable_last_sends_no_market(offline, side):
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
    offline.inner.set_price(DOGE, runner + side * D("0.01"))
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or ""):
            offline.inner.algos.pop(o["id"], None)
    offline.fx.inject("last_price", "unavailable", times=10)
    before = len(_markets(offline))
    qty = offline.amt(DOGE)
    stops0 = len(_stop_posts(offline))
    eng.tick()
    assert len(_markets(offline)) == before
    assert offline.amt(DOGE) == qty
    assert len(_stop_posts(offline)) == stops0
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_runner_market_close_is_take_profit(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    _sleeps(eng)
    offline.inner.stops_fire = False
    j["tp1_done"] = True
    j["be_done"] = True
    eng.cfg.trail_atr_k = 0
    eng.save()
    px = eng._runner_px(DOGE, j)
    offline.inner.set_price(DOGE, px + side * D("0.01"))
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or ""):
            offline.inner.algos.pop(o["id"], None)
    eng.tick()
    eng.tick()
    reasons = [t.get("reason") for t in eng.meta.get("trades") or []]
    assert reasons and reasons[-1] == "take_profit", reasons


@pytest.mark.parametrize("side", [1, -1])
def test_be_would_trigger_does_not_repost_during_the_cap_gate(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    eng._cp_hold.add(DOGE)
    j["tp1_done"] = True
    eng.save()
    tgt = eng._be_target(DOGE, j)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, tgt - side * D("0.01"))
    mk = tgt + side * D("0.002")
    _sleeps(eng)
    offline.fx.inject("market", "reject", times=10)
    before = len(_stop_posts(offline))
    eng._move_stop_be(DOGE, j, offline.amt(DOGE), offline.inner.open_orders(DOGE), mk)
    assert len(_stop_posts(offline)) == before + 1
    for _ in range(3):
        eng._move_stop_be(DOGE, eng.st["pos"][DOGE], offline.amt(DOGE), offline.inner.open_orders(DOGE), mk)
    assert len(_stop_posts(offline)) == before + 1


@pytest.mark.parametrize("side", [1, -1])
def test_tp_fail_alert_is_per_slice_not_per_coin(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    eng._tp_fail_once(DOGE, "익절 t1", "거절")
    eng._tp_fail_once(DOGE, "익절 t3", "조회 실패")
    notes = [m for m in _alerts(eng) if "보류" in m and DOGE in m]
    assert len(notes) == 2, notes


@pytest.mark.parametrize("side", [1, -1])
def test_cooled_4116_sends_the_renewed_id_in_the_same_cycle(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    t1 = next(o for o in offline.inner.open_orders(DOGE) if str(o["client_id"]).endswith("t1"))
    old = t1["client_id"]
    offline.inner.algos.pop(t1["id"], None)
    offline.inner.algo_hist.pop(old, None)
    eng._tp_cooled.add((DOGE, "익절 t1"))
    eng._tp_retry_at.pop((DOGE, "익절 t1"), None)

    def dup(fn, s, sd, trigger, c, qty=None, **k):
        if c == old:
            raise OrderRejected(-4116, "ClientOrderId is duplicated.")
        return fn(s, sd, trigger, c, qty=qty, **k)

    offline.fx.inject("take_profit", dup, times=5)
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]))
    live = [o for o in offline.inner.open_orders(DOGE)
            if o["type"] == "TAKE_PROFIT_MARKET" and o["client_id"] != old]
    assert live and live[0]["client_id"] != old
