"""Round-10 ledger and runner reserve. Offline fakes only. Long and short.

A pending realization order already describes its own fill, so a cached tp_got
must not be planted beside it. The runner reserve is the opened size, and a
take-profit is not sent when that size was never stored.
These tests fail on 9c5d93d.
"""
import pytest
from decimal import Decimal as D

from live_v6.engine import PROTECT_AUDIT_S
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


def _pending(offline, j, executed, orig):
    cid = f"{j['cid']}x0"
    offline.inner.orders[cid] = {
        "id": "m10", "client_id": cid, "status": "PARTIALLY_FILLED", "executed_qty": executed,
        "orig_qty": orig, "symbol": DOGE, "reduce_only": True,
        "side": "SELL" if int(j["side"]) > 0 else "BUY",
    }
    j["tp_market_once"] = {"t1": {"cid": cid, "before": str(abs(D(j["entry_qty"]))), "accepted": True}}
    j.pop("tp_ledger", None)
    return cid


def _expire_and_tick(offline, eng, cid):
    offline.inner.orders[cid]["status"] = "EXPIRED"
    _at_entry(offline, eng)
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    eng.clock.off += 1
    eng.tick()


@pytest.mark.parametrize("side", [1, -1])
def test_t10_1a_lagging_tp_got_is_not_added_to_a_larger_pending_market(offline, side):
    """tp_got 7000 is a lagging snapshot of the pending 8000, not a second fill."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    filled = D(8000)
    _prep(offline, eng)
    _end(offline, _t1(offline), D(0), "CANCELED")
    _shrink(offline, side, filled)
    j["tp_got"] = {"t1": "7000"}
    cid = _pending(offline, j, filled, D(j["tp"]["q1"]))
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    eng2.cfg.trail_atr_k = 0
    assert _ledger_sum(eng2.st["pos"][DOGE], "t1") == filled
    assert eng2.st["pos"][DOGE].get("tp1_done") is not True
    _expire_and_tick(offline, eng2, cid)
    assert offline.amt(DOGE) == qty - side * filled
    assert eng2.st["pos"][DOGE].get("tp1_done") is not True
    assert _ledger_sum(eng2.st["pos"][DOGE], "t1") == filled
    live = _live_tp(offline, "t1")
    assert len(live) == 1 and D(live[0]["qty"]) == D(j["tp"]["q1"]) - filled
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t10_1b_cancelled_partial_plus_pending_market_does_not_flatten(offline, side):
    """Cancelled exec 100 and the pending 8000 are the only fills. The 8566 leftover stays."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    cancelled, filled = D(100), D(8000)
    real = cancelled + filled
    _prep(offline, eng)
    _end(offline, _t1(offline), cancelled, "CANCELED")
    _shrink(offline, side, real)
    j["tp_got"] = {"t1": str(filled)}
    cid = _pending(offline, j, filled, D(j["tp"]["q1"]))
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    eng2.cfg.trail_atr_k = 0
    assert _ledger_sum(eng2.st["pos"][DOGE], "t1") == real
    assert eng2.st["pos"][DOGE].get("tp1_done") is not True
    _expire_and_tick(offline, eng2, cid)
    assert offline.amt(DOGE) == qty - side * real
    assert eng2.st["pos"][DOGE].get("tp1_done") is not True
    assert _ledger_sum(eng2.st["pos"][DOGE], "t1") == real
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t10_2_missing_entry_qty_does_not_rest_the_runner(offline, side):
    """Without entry_qty the reserve must not be the current leftover. No t1 of q1 on it."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    opened = j["entry_qty"]
    _prep(offline, eng)
    j.pop("entry_qty", None)
    _end(offline, _t1(offline), D(0), "CANCELED")
    _shrink(offline, side, q1)
    eng.save()
    _at_entry(offline, eng)
    eng.tick()
    eng.clock.off += 1
    eng.tick()
    j = eng.st["pos"][DOGE]
    assert j.get("entry_qty") == opened
    assert j.get("tp1_done") is not True
    assert _live_tp(offline, "t1") == []
    assert offline.amt(DOGE) == qty - side * q1
    offline.inner.set_price(DOGE, _through(j, side))
    eng.tick()
    assert offline.amt(DOGE) == qty - side * q1
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t10_2_unknown_opened_size_refuses_the_take_profit(offline, side):
    """A reduced journal with no entry_qty and a recorded fill is not a known opened size."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _prep(offline, eng)
    _end(offline, _t1(offline), D(0), "CANCELED")
    _shrink(offline, side, q1)
    j.pop("entry_qty", None)
    j["qty"] = str(abs(qty) - q1)
    j["tp_got"] = {"t1": "1"}
    j.pop("tp_ledger", None)
    eng.save()
    offline.inner.set_price(DOGE, _through(j, side))
    before = [o for o in offline.inner.orders.values() if o.get("symbol") == DOGE and o.get("reduce_only")]
    eng.tick()
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert eng.st["pos"][DOGE].get("entry_qty") in (None, "")
    assert _live_tp(offline, "t1") == []
    added = [o for o in offline.inner.orders.values()
             if o.get("symbol") == DOGE and o.get("reduce_only") and o not in before]
    assert added == []
    assert offline.amt(DOGE) == qty - side * q1


def test_adopt_persists_entry_qty():
    from live_v6.tools.adopt_position import build
    state = {
        "unknown": {"DOGEUSDT": {
            "side": 1, "qty": "10", "entry_px": "0.15", "stop_px": "0.14", "amt": "10",
            "stop_src": "exchange", "stop_cid": "c", "detected_ms": 1,
        }},
        "pos": {},
        "strategy": {},
    }
    j, _notes = build(state, "DOGEUSDT", "none", "v6", 1)
    assert j["entry_qty"] == "10"
