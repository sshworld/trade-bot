"""Round-12 schema lock. Offline fakes only. Long and short.

A refused old file stays halted and must not send a reduceOnly market,
including the 24 h time exit and a closing retry that was already pending.
These tests fail on 07c450e.
"""
import pytest
from decimal import Decimal as D

from live_v6.tests.test_chandelier_e import e_engine
from live_v6.tests.test_protection_policy_v1 import engine_for
from live_v6.tests.test_pr2_round8 import _covered, _prep
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _sells(offline):
    return [o for o in offline.inner.orders.values()
            if o.get("symbol") == DOGE and o.get("reduce_only")]


def _refuse(eng):
    j = eng.st["pos"][DOGE]
    j.pop("entry_qty", None)
    eng.st.pop("schema", None)
    eng.save()
    return j


@pytest.mark.parametrize("side", [1, -1])
def test_t12_aged_hold_does_not_market_a_refused_book(offline, side):
    """opened_ms past max_hold_s on a refused file must not time-exit."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    j = _refuse(eng)
    j["opened_ms"] = eng.now_ms() - int(eng.cfg.max_hold_s * 1000) - 3_600_000
    eng.save()
    before = list(_sells(offline))
    eng2 = e_engine(offline, eng.clock)
    assert eng2.meta.get("halted")
    assert eng2._schema_lock is True
    assert offline.amt(DOGE) == qty
    assert DOGE in eng2.st["pos"]
    assert _sells(offline) == before
    assert _covered(offline)
    eng2.tick()
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t12_pending_close_does_not_retry_while_locked(offline, side):
    """A journal already marked closing is not market-sold while the schema lock holds."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    j = _refuse(eng)
    j["closing"] = True
    j["close_reason"] = "time_exit"
    eng.save()
    before = list(_sells(offline))
    eng2 = e_engine(offline, eng.clock)
    assert eng2.meta.get("halted")
    assert eng2._schema_lock is True
    assert offline.amt(DOGE) == qty
    assert DOGE in eng2.st["pos"]
    assert eng2.st["pos"][DOGE].get("closing") is True
    assert _sells(offline) == before
    assert _covered(offline)
    eng2.tick()
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before


@pytest.mark.parametrize("side", [1, -1])
def test_t12_locked_reconcile_does_not_resolve_intents(offline, side):
    """A filled entry intent stays unresolved while the schema lock is on."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _prep(offline, eng)
    j = _refuse(eng)
    cid = j["cid"] + "intent"
    eng.st["intents"][cid] = {"sym": DOGE, "cid": cid, "side": side}
    offline.inner.orders[cid] = {
        "id": "intent", "client_id": cid, "status": "FILLED", "executed_qty": D(1),
        "symbol": DOGE, "reduce_only": False,
    }
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    assert eng2._schema_lock is True
    assert cid in eng2.st["intents"]
    assert offline.amt(DOGE) != 0
