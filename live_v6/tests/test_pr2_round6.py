"""Round-6 majors and the TA additions. Offline fakes only. Long and short.

These assert the required behavior and fail on b56cd38.
"""
import pytest
from decimal import Decimal as D

from live_v6.engine import PROTECT_AUDIT_S, UNKNOWN_ORDER
from live_v6.exchange import ExchangeUnavailable, OrderRejected, WouldTrigger
from live_v6.tests.test_protection_policy_v1 import _alerts, _closes, _sleeps, engine_for
from live_v6.tests.test_pr2_round3 import _markets, _pop_t1, _stop_posts, _through
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _stops(offline):
    return [o for o in offline.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")]


def _covered(offline):
    amt = offline.amt(DOGE)
    if amt == 0:
        return True
    return any(o.get("close_position") or (o.get("reduce_only") and D(o.get("qty") or 0) >= abs(amt))
               for o in _stops(offline))


def _prime(offline, eng, side):
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, _through(j, side))
    _pop_t1(offline)
    eng.cfg.trail_atr_k = 0
    return j, qty


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("status", ["TRIGGERING", "PARTIALLY_FILLED"])
def test_r6_1_nonterminal_t1_is_live_and_blocks_the_market(offline, side, status):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, _through(j, side))
    t1 = next(o for o in offline.inner.algos.values()
              if o["symbol"] == DOGE and str(o["client_id"]).endswith("t1"))
    offline.inner.algo_hist[t1["client_id"]]["status"] = status
    offline.inner.algo_hist[t1["client_id"]]["executed_qty"] = D(0)
    eng.cfg.trail_atr_k = 0
    eng._cp_hold.add(DOGE)
    eng._cp_retry_at[DOGE] = eng.clock() + 10**9
    eng._protect_audit_at = eng.clock()
    eng.save()
    offline.fx.inject("open_orders", lambda fn, s, **k: [] if s == DOGE else fn(s), times=40)
    before = len(_markets(offline))
    eng.tick()
    assert len(_markets(offline)) == before
    assert any(o["id"] == t1["id"] for o in offline.inner.algos.values())
    assert offline.amt(DOGE) == qty
    assert len([m for m in _alerts(eng) if DOGE in m]) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_r6_1_unknown_status_does_not_market_or_replace(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _prime(offline, eng, side)
    offline.fx.inject("algo_order", "unavailable", times=10)
    before_m = len(_markets(offline))
    before_tp = len([c for c in offline.fx.calls if c[0] == "take_profit"])
    eng._on_tp_would_trigger(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]), "CONTRACT_PRICE")
    assert len(_markets(offline)) == before_m
    assert len([c for c in offline.fx.calls if c[0] == "take_profit"]) == before_tp
    assert offline.amt(DOGE) == qty
    assert len([m for m in _alerts(eng) if DOGE in m]) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_r6_2_replacement_and_market_use_the_remaining_slice(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _prime(offline, eng, side)
    q1 = D(j["tp"]["q1"])
    got = D(8000)
    left_pos = abs(qty) - got
    p = offline.inner.pos[DOGE]
    p["amt"] = left_pos if side > 0 else -left_pos
    j["qty"] = str(left_pos)
    j.setdefault("tp_got", {})["t1"] = str(got)
    eng.save()
    offline.inner.set_price(DOGE, D(j["entry_px"]))
    eng.tick()
    rest = [o for o in offline.inner.open_orders(DOGE) if str(o["client_id"]).endswith("t1")
            or (o["type"] == "TAKE_PROFIT_MARKET" and "t1" in str(o["client_id"]))]
    assert rest and rest[0]["qty"] == q1 - got
    assert all(o["qty"] != q1 for o in rest)
    offline.inner.set_price(DOGE, _through(j, side))
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or ""):
            offline.inner.algos.pop(o["id"], None)
            offline.inner.algo_hist.pop(o["client_id"], None)
    before = len(_markets(offline))
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    new = [c for c in _markets(offline)[before:] if len(c[1]) > 2]
    assert new and new[0][1][2] == q1 - got


@pytest.mark.parametrize("side", [1, -1])
def test_r6_2_below_min_qty_remainder_is_not_placed(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _prime(offline, eng, side)
    q1 = D(j["tp"]["q1"])
    j.setdefault("tp_got", {})["t1"] = str(q1 - D("0.4"))
    eng.save()
    offline.inner.set_price(DOGE, D(j["entry_px"]))
    before = len([c for c in offline.fx.calls if c[0] == "take_profit"])
    eng.tick()
    assert len([c for c in offline.fx.calls if c[0] == "take_profit"]) == before
    assert len([m for m in _alerts(eng) if DOGE in m]) == 1
    assert offline.amt(DOGE) == qty


@pytest.mark.parametrize("side", [1, -1])
def test_r6_3_tp2_done_requires_a_stage_fill(offline, side):
    eng = engine_for(offline, "legacy")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    q1, q2 = D(j["tp"]["q1"]), D(j["tp"]["q2"])
    _sleeps(eng)
    offline.inner.stops_fire = False
    left = abs(D(j["entry_qty"])) - q1
    p = offline.inner.pos[DOGE]
    p["amt"] = left if side > 0 else -left
    j["tp1_done"] = True
    j["qty"] = str(left)
    eng.save()
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and str(o["client_id"]).endswith("t2"):
            offline.inner.algos.pop(o["id"], None)
            offline.inner.algo_hist.pop(o["client_id"], None)
    offline.inner.set_price(DOGE, D(j["tp"]["tp2"]) + side * D("0.001"))
    before = len(_markets(offline))
    eng._on_tp_would_trigger(DOGE, j, "t2", D(j["tp"]["tp2"]), q2, "CONTRACT_PRICE")
    assert j.get("tp2_done") is not True or len(_markets(offline)) > before
    assert not (j.get("tp2_done") and len(_markets(offline)) == before)


@pytest.mark.parametrize("side", [1, -1])
def test_r6_4_partial_runner_fill_does_not_use_the_tp1_shrink(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    q2 = D(j["tp"]["q2"])
    _sleeps(eng)
    offline.inner.stops_fire = False
    left = abs(D(j["entry_qty"])) - D(j["tp"]["q1"])
    p = offline.inner.pos[DOGE]
    p["amt"] = left if side > 0 else -left
    j["tp1_done"] = True
    j["be_done"] = True
    j["qty"] = str(left)
    eng.cfg.trail_atr_k = 0
    eng.save()
    eng._bind_runner(DOGE, j, p["amt"])
    px = eng._runner_px(DOGE, j)
    offline.inner.set_price(DOGE, px + side * D("0.01"))
    offline.inner.mark_price = lambda s: px + side * D("0.01") if s == DOGE else offline.inner.price[s]
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or ""):
            offline.inner.algos.pop(o["id"], None)
            offline.inner.algo_hist.pop(o["client_id"], None)

    def one(fn, s, sd, q, cid, reduce_only=False, **k):
        return fn(s, sd, q, cid, reduce_only=reduce_only, fill_qty=D(1))

    offline.fx.inject("market", one, times=1)

    def boom(fn, *a, **k):
        raise WouldTrigger(-2021, "Order would immediately trigger.")

    offline.fx.inject("take_profit", boom, times=1)
    eng.tick()
    assert eng.st["pos"][DOGE].get("tp3_done") is not True
    assert abs(offline.amt(DOGE)) == left - D(1)


@pytest.mark.parametrize("side", [1, -1])
def test_r6_5_reject_does_not_spend_the_permit_and_inside_can_replace(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _prime(offline, eng, side)
    offline.fx.inject("market", "reject", times=1)
    before = len(_markets(offline))
    eng.tick()
    assert len(_markets(offline)) == before + 1
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, D(j["entry_px"]))
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    live = [o for o in offline.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET" and "t1" in str(o["client_id"])]
    assert live, "a never-accepted market must not block the inside re-place"


@pytest.mark.parametrize("side", [1, -1])
def test_r6_5_unknown_market_is_queried_and_not_sold_twice(offline, side):
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
    assert offline.amt(DOGE) == qty - side * q1
    assert UNKNOWN_ORDER in eng.blocks
    sent = len(_markets(offline))
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert len(_markets(offline)) == sent
    assert abs(offline.amt(DOGE)) == abs(qty) - q1
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_r6_sl_never_gaps_across_partial_and_replace(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j, qty = _prime(offline, eng, side)
    naked = []

    def partial(fn, s, sd, q, cid, reduce_only=False, **k):
        return fn(s, sd, q, cid, reduce_only=reduce_only, fill_qty=D(8000))

    offline.fx.inject("market", partial, times=1)
    for _ in range(3):
        eng.tick()
        if not _covered(offline):
            naked.append(eng.clock())
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, D(j["entry_px"]))
    for _ in range(3):
        eng.clock.off += 1
        eng.tick()
        if not _covered(offline):
            naked.append(eng.clock())
    assert naked == []
    assert abs(offline.amt(DOGE)) == abs(qty) - D(8000)


@pytest.mark.parametrize("side", [1, -1])
def test_r6_hold_does_not_cancel_t1_when_the_later_read_aborts(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    _sleeps(eng)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, _through(j, side))
    t1 = next(o for o in offline.inner.algos.values()
              if o["symbol"] == DOGE and str(o["client_id"]).endswith("t1"))
    n = {"p": 0}

    def late(fn, symbols, **k):
        n["p"] += 1
        if n["p"] >= 2:
            raise ExchangeUnavailable("position read failed after the cancel")
        return fn(symbols)

    offline.fx.inject("positions", late, times=6)
    before = len(_markets(offline))
    eng._on_tp_would_trigger(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]), "CONTRACT_PRICE", place_tp=False)
    assert len(_markets(offline)) == before
    assert any(o["id"] == t1["id"] for o in offline.inner.algos.values())


@pytest.mark.parametrize("side", [1, -1])
def test_r6_book_fill_does_not_subtract_tp_got_twice(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    got, extra = D(8000), D(333)
    left = abs(D(j["entry_qty"])) - got
    p = offline.inner.pos[DOGE]
    p["amt"] = left if side > 0 else -left
    j["qty"] = str(left)
    j.setdefault("tp_got", {})["t1"] = str(got)
    cid = f"{j['cid']}x0"
    offline.inner.orders[cid] = {"id": "9", "client_id": cid, "status": "FILLED", "executed_qty": extra,
                                 "avg_price": p["entry"], "symbol": DOGE, "reduce_only": True}
    j["tp_market_once"] = {"t1": {"cid": cid, "before": str(left)}}
    eng.save()
    eng._on_tp_would_trigger(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]), "CONTRACT_PRICE", place_tp=False)
    assert D(eng.st["pos"][DOGE]["qty"]) == left - extra


@pytest.mark.parametrize("side", [1, -1])
def test_r6_realization_market_is_visible_as_reduce_only(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _prime(offline, eng, side)
    before = len(_closes(offline))
    eng.tick()
    assert len(_closes(offline)) == before + 1


@pytest.mark.parametrize("side", [1, -1])
def test_r6_shrink_of_one_lot_does_not_finish_the_slice(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    p = offline.inner.pos[DOGE]
    p["amt"] = (abs(p["amt"]) - D(1)) * (1 if side > 0 else -1)
    assert eng._shrink_booked(DOGE, j, "t1", abs(D(j["entry_qty"]))) != "filled"
    assert j.get("tp1_done") is not True
