"""Round-9 ledger sizing. Offline fakes only. Long and short.

A rest is sized only after the stage ledger is updated, and never past the
room that must stay with the runner. These tests fail on b2b1fac.
"""
import pytest
from decimal import Decimal as D

from live_v6.exchange import ExchangeUnavailable
from live_v6.tests.test_chandelier_e import e_engine
from live_v6.tests.test_protection_policy_v1 import engine_for
from live_v6.tests.test_pr2_round3 import _through
from live_v6.tests.test_pr2_round8 import (
    _at_entry, _covered, _end, _ledger_sum, _live_tp, _prep, _shrink,
)
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _t1(offline):
    return next(o for o in offline.inner.algos.values()
                if o["symbol"] == DOGE and str(o.get("client_id") or "").endswith("t1"))


@pytest.mark.parametrize("side", [1, -1])
def test_t9_1_direct_place_records_the_partial_before_sizing(offline, side):
    """A direct _place_tp records cancelled exec 100 and rests q1-100, not q1."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    q1 = D(j["tp"]["q1"])
    _prep(offline, eng)
    t1 = _t1(offline)
    _end(offline, t1, D(100), "CANCELED")
    _shrink(offline, side, D(100))
    _at_entry(offline, eng)
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), q1)
    assert _ledger_sum(eng.st["pos"][DOGE], "t1") == D(100)
    live = _live_tp(offline, "t1")
    assert len(live) == 1 and D(live[0]["qty"]) == q1 - D(100)
    assert live[0]["client_id"] != t1["client_id"]


@pytest.mark.parametrize("side", [1, -1])
def test_t9_2_zero_exec_shrink_does_not_rest_the_runner(offline, side):
    """A q1 shrink with executedQty 0 leaves the leftover to the stop. No new t1."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _prep(offline, eng)
    _end(offline, _t1(offline), D(0), "CANCELED")
    _shrink(offline, side, q1)
    _at_entry(offline, eng)
    eng.tick()
    eng.clock.off += 1
    eng.tick()
    j = eng.st["pos"][DOGE]
    assert j.get("tp1_done") is not True
    assert _ledger_sum(j, "t1") == D(0)
    assert _live_tp(offline, "t1") == []
    offline.inner.stops_fire = True
    offline.inner.set_price(DOGE, _through(j, side))
    eng.tick()
    assert offline.amt(DOGE) == qty - side * q1
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t9_2_unrecorded_market_does_not_rest_another_slice(offline, side):
    """A q1 fill whose row was never saved still must not rest another q1 on the leftover."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _prep(offline, eng)
    _end(offline, _t1(offline), D(0), "CANCELED")
    _shrink(offline, side, q1)
    j.pop("tp_ledger", None)
    j.pop("tp_got", None)
    j.pop("tp_market_once", None)
    eng.save()
    _at_entry(offline, eng)
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), q1)
    eng.tick()
    assert _live_tp(offline, "t1") == []
    assert offline.amt(DOGE) == qty - side * q1
    assert eng.st["pos"][DOGE].get("tp1_done") is not True


@pytest.mark.parametrize("side", [1, -1])
def test_t9_3_legacy_tp_got_is_not_added_to_the_pending_market(offline, side):
    """A pre-ledger journal must not count tp_got and the same pending fill twice."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    filled = D(8000)
    _prep(offline, eng)
    _end(offline, _t1(offline), D(0), "CANCELED")
    _shrink(offline, side, filled)
    cid = f"{j['cid']}x0"
    offline.inner.orders[cid] = {
        "id": "m9", "client_id": cid, "status": "PARTIALLY_FILLED", "executed_qty": filled,
        "orig_qty": D(j["tp"]["q1"]), "symbol": DOGE, "reduce_only": True, "side": "SELL" if side > 0 else "BUY",
    }
    j["tp_got"] = {"t1": str(filled)}
    j["tp_market_once"] = {"t1": {"cid": cid, "before": str(abs(qty)), "accepted": True}}
    j.pop("tp_ledger", None)
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    eng2.cfg.trail_atr_k = 0
    j2 = eng2.st["pos"][DOGE]
    assert _ledger_sum(j2, "t1") == filled
    offline.inner.orders[cid]["status"] = "EXPIRED"
    _at_entry(offline, eng2)
    from live_v6.engine import PROTECT_AUDIT_S
    eng2.clock.off += PROTECT_AUDIT_S + 1
    eng2.tick()
    eng2.clock.off += 1
    eng2.tick()
    assert offline.amt(DOGE) == qty - side * filled
    assert eng2.st["pos"][DOGE].get("tp1_done") is not True
    assert _ledger_sum(eng2.st["pos"][DOGE], "t1") == filled
    live = _live_tp(offline, "t1")
    assert len(live) == 1 and D(live[0]["qty"]) == D(j["tp"]["q1"]) - filled


@pytest.mark.parametrize("side", [1, -1])
def test_m9_1_ledger_does_not_decrease_a_cid(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    cid = j["cid"] + "t1"
    eng._ledger_add(j, "t1", cid, D(j["tp"]["q1"]))
    eng._ledger_add(j, "t1", cid, D(0))
    assert eng._got(j, "t1") == D(j["tp"]["q1"])


@pytest.mark.parametrize("side", [1, -1])
def test_m9_3_post_rest_unknown_cid_is_not_success(offline, side):
    """An unreadable client id is not a successful rest, and nothing is posted."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    _prep(offline, eng)
    t1 = _t1(offline)
    offline.inner.algos.pop(t1["id"], None)

    def boom(fn, s, cid, **k):
        raise ExchangeUnavailable("cid unreadable")

    offline.fx.inject("algo_order", boom, times=10)
    before = [o["id"] for o in offline.inner.algos.values() if "TAKE_PROFIT" in (o.get("type") or "")]
    ok = eng._post_rest(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]), "CONTRACT_PRICE", "익절 t1")
    after = [o["id"] for o in offline.inner.algos.values() if "TAKE_PROFIT" in (o.get("type") or "")]
    assert ok is False
    assert after == before
