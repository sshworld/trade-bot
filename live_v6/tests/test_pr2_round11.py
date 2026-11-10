"""Round-11 state schema. Offline fakes only. Long and short.

An old state file is not migrated. A missing schema, a journal with no proved
opened size, or an exchange position/order the file does not describe refuses
trading: no entries, no take-profit, the stop stays, one alert, halted until
an operator clears it. A current-version ledger is re-read on restart.
These tests fail on 21e72ec.
"""
import pytest
from decimal import Decimal as D

from live_v6.engine import PROTECT_AUDIT_S
from live_v6.tests.test_chandelier_e import e_engine
from live_v6.tests.test_protection_policy_v1 import engine_for
from live_v6.tests.test_pr2_round8 import (
    _at_entry, _covered, _end, _ledger_sum, _live_tp, _prep, _shrink,
)
from live_v6.tests.test_qrmtf import DOGE, open_pos

STATE_SCHEMA = 2


def _t1(offline):
    return next(o for o in offline.inner.algos.values()
                if o["symbol"] == DOGE and str(o.get("client_id") or "").endswith("t1"))


@pytest.mark.parametrize("side", [1, -1])
def test_t11_reduced_qty_is_not_frozen_as_the_opened_size(offline, side):
    """qty already synced to the leftover is not proof of the opened size. No t1, and trading stops."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _prep(offline, eng)
    j.pop("entry_qty", None)
    j["qty"] = str(q1)
    _end(offline, _t1(offline), D(0), "CANCELED")
    _shrink(offline, side, q1)
    eng.st.pop("schema", None)
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    assert eng2.meta.get("halted")
    assert eng2.st["pos"][DOGE].get("entry_qty") in (None, "")
    assert _live_tp(offline, "t1") == []
    assert offline.amt(DOGE) == qty - side * q1
    assert _covered(offline)
    _at_entry(offline, eng2)
    eng2.tick()
    assert offline.amt(DOGE) == qty - side * q1
    assert _live_tp(offline, "t1") == []


@pytest.mark.parametrize("side", [1, -1])
def test_t11_ledger_add_never_plants_a_legacy_row(offline, side):
    """tp_got is not a fill. Adding a real cid does not invent a second row."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    j["tp_got"] = {"t1": "7000"}
    j.pop("tp_market_once", None)
    total = eng._ledger_add(j, "t1", j["cid"] + "t1", D(8000))
    rows = ((j.get("tp_ledger") or {}).get("t1") or {}).get("cids") or []
    assert total == D(8000)
    assert not any(str(r.get("cid") or "").endswith(":legacy") for r in rows)


@pytest.mark.parametrize("side", [1, -1])
def test_t11_doubled_old_ledger_is_refused_and_does_not_flatten(offline, side):
    """A 9c5d93d/21e72ec doubled ledger has no schema. It is not loaded and does not flatten."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    _end(offline, _t1(offline), D(100), "CANCELED")
    _shrink(offline, side, D(8100))
    cid = f"{j['cid']}x0"
    offline.inner.orders[cid] = {
        "id": "old", "client_id": cid, "status": "PARTIALLY_FILLED", "executed_qty": D(8000),
        "orig_qty": D(j["tp"]["q1"]), "symbol": DOGE, "reduce_only": True,
    }
    j["tp_ledger"] = {"t1": {"cids": [
        {"cid": j["cid"] + "t1:legacy", "executed": "8000"},
        {"cid": j["cid"] + "t1", "executed": "100"},
        {"cid": cid, "executed": "8000"},
    ], "sum": "16100"}}
    j["tp_got"] = {"t1": "8000"}
    j["tp_market_once"] = {"t1": {"cid": cid, "before": str(abs(qty)), "accepted": True}}
    j["tp1_done"] = False
    eng.st.pop("schema", None)
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    assert eng2.meta.get("halted")
    assert eng2.st["pos"][DOGE].get("tp1_done") is not True
    assert _ledger_sum(eng2.st["pos"][DOGE], "t1") != D(16100) or eng2.meta.get("halted")
    offline.inner.orders[cid]["status"] = "EXPIRED"
    _at_entry(offline, eng2)
    eng2.clock.off += PROTECT_AUDIT_S + 1
    eng2.tick()
    eng2.clock.off += 1
    eng2.tick()
    assert offline.amt(DOGE) == qty - side * D(8100)
    assert eng2.st["pos"][DOGE].get("tp1_done") is not True
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t11_restart_rereads_the_current_ledger(offline, side):
    """A current-version ledger is saved and comes back unchanged on the next start."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    _prep(offline, eng)
    _end(offline, _t1(offline), D(100), "CANCELED")
    _shrink(offline, side, D(100))
    _at_entry(offline, eng)
    eng.tick()
    assert _ledger_sum(eng.st["pos"][DOGE], "t1") == D(100)
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    assert eng2.st.get("schema") == STATE_SCHEMA
    assert _ledger_sum(eng2.st["pos"][DOGE], "t1") == D(100)
    assert not eng2.meta.get("halted")


def test_t11_flat_book_starts_an_empty_current_ledger(offline):
    """Position 0 and no open orders: an old file becomes an empty current ledger."""
    eng = engine_for(offline, "e")
    eng.st.pop("schema", None)
    eng.st["pos"] = {}
    eng.meta.pop("halted", None)
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    assert eng2.st.get("schema") == STATE_SCHEMA
    assert eng2.st["pos"] == {}
    assert not eng2.meta.get("halted")


@pytest.mark.parametrize("side", [1, -1])
def test_t11_open_order_blocks_a_fresh_ledger(offline, side):
    """Position 0 with a resting order is not flat. No fresh ledger, trading stays halted."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    offline.inner.pos.pop(DOGE, None)
    offline.inner.algos["left"] = {
        "id": "left", "client_id": j["cid"] + "left", "symbol": DOGE, "type": "LIMIT",
        "side": "BUY" if side > 0 else "SELL", "close_position": False, "reduce_only": False,
        "qty": D(1), "stop_price": D(0), "status": "NEW",
    }
    eng.st["pos"] = {}
    eng.st.pop("schema", None)
    eng.meta.pop("halted", None)
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    assert eng2.meta.get("halted")
    assert eng2.st.get("schema") != STATE_SCHEMA


@pytest.mark.parametrize("side", [1, -1])
def test_t11_exchange_position_without_current_state_is_refused(offline, side):
    """A live position the file does not describe in the current schema is SL-only."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    stops = [o for o in offline.inner.algos.values() if o["symbol"] == DOGE and "STOP" in (o["type"] or "")]
    assert stops
    eng.st["pos"] = {}
    eng.st.pop("schema", None)
    eng.meta.pop("halted", None)
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    assert eng2.meta.get("halted")
    assert _covered(offline)
    assert DOGE not in eng2.st["pos"]
    assert _live_tp(offline, "t1") == [] or eng2.meta.get("halted")


def test_adopt_without_an_opened_size_is_refused():
    from live_v6.tools.adopt_position import build
    state = {
        "unknown": {"DOGEUSDT": {
            "side": 1, "qty": "10", "entry_px": "0.15", "stop_px": "0.14", "amt": "10",
            "stop_src": "exchange", "stop_cid": "c", "detected_ms": 1,
        }},
        "pos": {},
        "strategy": {},
    }
    with pytest.raises(SystemExit):
        build(state, "DOGEUSDT", "none", "v6", 1)


def test_adopt_uses_the_operator_opened_size():
    from live_v6.tools.adopt_position import build
    state = {
        "unknown": {"DOGEUSDT": {
            "side": 1, "qty": "10", "entry_px": "0.15", "stop_px": "0.14", "amt": "10",
            "stop_src": "exchange", "stop_cid": "c", "detected_ms": 1,
        }},
        "pos": {},
        "strategy": {},
    }
    j, _notes = build(state, "DOGEUSDT", "none", "v6", 1, opened_qty="7")
    assert j["entry_qty"] == "7"
    assert j["qty"] == "10"
