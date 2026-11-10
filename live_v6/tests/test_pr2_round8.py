"""Round-8 fill ledger. Offline fakes only. Long and short, more than one tick.

A stage is booked only from the sum of that stage's exchange executedQty.
These tests fail on 4c57e01.
"""
import json
import random

import pytest
from decimal import Decimal as D

from live_v6.engine import PROTECT_AUDIT_S
from live_v6.tests.conftest import Backend
from live_v6.tests.fakes import FakeExchange
from live_v6.tests.test_chandelier_e import e_engine
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round3 import _through
from live_v6.tests.test_qrmtf import DOGE, open_pos

QUICK_SEEDS = (0, 1, 7, 42)


def _live_tp(offline, which):
    return [o for o in offline.inner.algos.values()
            if o["symbol"] == DOGE and "TAKE_PROFIT" in (o["type"] or "")
            and which in str(o.get("client_id") or "")
            and str(o.get("status") or "NEW").upper() in {"NEW", "WORKING", ""}]


def _stops(offline):
    return [o for o in offline.inner.algos.values()
            if o["symbol"] == DOGE and "STOP" in (o["type"] or "")]


def _covered(offline):
    amt = offline.amt(DOGE)
    if amt == 0:
        return True
    return any(o.get("close_position") or (o.get("reduce_only") and D(o.get("qty") or 0) >= abs(amt))
               for o in _stops(offline))


def _empty_book(fn, s, **k):
    return [] if s == DOGE else fn(s)


def _prep(offline, eng):
    _sleeps(eng)
    offline.inner.stops_fire = False
    eng.cfg.trail_atr_k = 0
    eng._protect_audit_at = eng.clock()


def _at_entry(offline, eng):
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, D(eng.st["pos"][DOGE]["entry_px"]))
    offline.inner.last = {}


def _shrink(offline, side, qty):
    p = offline.inner.pos[DOGE]
    p["amt"] = p["amt"] - side * qty
    p["margin"] = abs(p["amt"]) * p["entry"] / offline.inner.lev[DOGE]


def _end(offline, order, executed, status):
    offline.inner.algos.pop(order["id"], None)
    offline.inner.algo_hist[order["client_id"]] = {
        "status": status, "executed_qty": executed, "id": order["id"],
        "kind": "algo", "client_id": order["client_id"],
    }


def _ledger_sum(j, which):
    book = (j.get("tp_ledger") or {}).get(which) or {}
    return D(book.get("sum") or 0)


def _stage_exec(offline, base, which, q1=None):
    """Algo fills for this stage plus slice realization markets (`{base}xN`)."""
    prefix = f"{base}{which}"
    total = D(0)
    for cid, st in offline.inner.algo_hist.items():
        if cid == prefix or str(cid).startswith(prefix + "x"):
            total += D(st.get("executed_qty") or 0)
    if which != "t1":
        return total
    # q1 names the slice for callers. A market larger than it is still this stage's sell:
    # skipping it hid a breakeven flatten of the runner.
    del q1
    for o in offline.inner.orders.values():
        cid = str(o.get("client_id") or "")
        if o.get("symbol") != DOGE or not o.get("reduce_only"):
            continue
        tail = cid[len(base) + 1:] if cid.startswith(base + "x") else ""
        if not tail.isdigit():
            continue
        total += D(o.get("executed_qty") or 0)
    return total


def _sold(offline):
    total = D(0)
    for o in offline.inner.orders.values():
        if o.get("symbol") == DOGE and o.get("reduce_only"):
            total += D(o.get("executed_qty") or 0)
    for st in offline.inner.algo_hist.values():
        total += D(st.get("executed_qty") or 0)
    return total


@pytest.mark.parametrize("side", [1, -1])
def test_t8_1_partial_resting_fill_does_not_finish_tp1_or_flatten(offline, side):
    """FINISHED exec 10 adds 10. It does not set tp1_done and the next tick does not flatten."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _prep(offline, eng)
    t1 = next(o for o in offline.inner.algos.values() if str(o.get("client_id") or "").endswith("t1"))
    _end(offline, t1, D(10), "FINISHED")
    _shrink(offline, side, D(10))
    _at_entry(offline, eng)
    eng.tick()
    eng.clock.off += 1
    eng.tick()
    j = eng.st["pos"][DOGE]
    assert j.get("tp1_done") is not True
    assert j.get("be_done") is not True
    assert _ledger_sum(j, "t1") == D(10)
    assert offline.amt(DOGE) == qty - side * D(10)
    live = _live_tp(offline, "t1")
    assert len(live) == 1 and D(live[0]["qty"]) == q1 - D(10)
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t8_2_shrink_without_execution_does_not_book_tp1(offline, side):
    """A cancelled t1 with executedQty 0 does not become TP1 just because the position shrank by q1."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _prep(offline, eng)
    t1 = next(o for o in offline.inner.algos.values() if str(o.get("client_id") or "").endswith("t1"))
    _end(offline, t1, D(0), "CANCELED")
    _shrink(offline, side, q1)
    _at_entry(offline, eng)
    eng.tick()
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    j = eng.st["pos"][DOGE]
    assert j.get("tp1_done") is not True
    assert j.get("be_done") is not True
    assert _ledger_sum(j, "t1") == D(0)
    assert offline.amt(DOGE) == qty - side * q1
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t8_3_cancelled_partial_is_summed_and_the_rest_is_replaced(offline, side):
    """CANCELED exec 100 is recorded, and the replacement is q1 - 100, not q1."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    _prep(offline, eng)
    t1 = next(o for o in offline.inner.algos.values() if str(o.get("client_id") or "").endswith("t1"))
    _end(offline, t1, D(100), "CANCELED")
    _shrink(offline, side, D(100))
    _at_entry(offline, eng)
    eng.tick()
    eng.clock.off += 1
    eng.tick()
    j = eng.st["pos"][DOGE]
    assert j.get("tp1_done") is not True
    assert _ledger_sum(j, "t1") == D(100)
    cids = [row["cid"] for row in j["tp_ledger"]["t1"]["cids"]]
    assert t1["client_id"] in cids
    live = _live_tp(offline, "t1")
    assert len(live) == 1 and D(live[0]["qty"]) == q1 - D(100)
    assert live[0]["client_id"] != t1["client_id"]
    assert offline.amt(DOGE) == qty - side * D(100)
    raw = json.loads(offline.store_path.read_text())
    assert D(raw["pos"][DOGE]["tp_ledger"]["t1"]["sum"]) == D(100)
    clk = eng.clock
    eng2 = e_engine(offline, clk)
    eng2.cfg.trail_atr_k = 0
    assert _ledger_sum(eng2.st["pos"][DOGE], "t1") == D(100)
    assert D(eng2._got(eng2.st["pos"][DOGE], "t1")) == D(100)


@pytest.mark.parametrize("side", [1, -1])
def test_t8_4_runner_partial_does_not_finish_from_the_shrink(offline, side):
    """A finished runner that executed 5000 is not done. The rest is re-placed from the ledger."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    _prep(offline, eng)
    j["tp1_done"] = True
    j["be_done"] = True
    eng.save()
    _at_entry(offline, eng)
    eng.tick()
    j = eng.st["pos"][DOGE]
    t3 = next(o for o in _live_tp(offline, "t3"))
    q3 = D(j["tp"]["q3"])
    partial = D(5000)
    _end(offline, t3, partial, "FINISHED")
    _shrink(offline, side, partial)
    _at_entry(offline, eng)
    eng._place_tp(DOGE, j, "t3", D(j["tp"]["tp3"]), q3, working_type="MARK_PRICE")
    eng.clock.off += 1
    eng.tick()
    j = eng.st["pos"][DOGE]
    assert j.get("tp3_done") is not True
    assert _ledger_sum(j, "t3") == partial
    live = _live_tp(offline, "t3")
    assert len(live) == 1 and D(live[0]["qty"]) == q3 - partial
    assert live[0]["client_id"] != t3["client_id"]


@pytest.mark.parametrize("side", [1, -1])
def test_t8_5_hold_rearm_uses_the_unfilled_slice(offline, side):
    """After 8000 of q1, the hold re-place is the other 333 under a new client id."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    filled = D(8000)
    _prep(offline, eng)
    offline.inner.set_price(DOGE, _through(j, side))
    eng._cp_hold.add(DOGE)
    eng._cp_retry_at[DOGE] = eng.clock() + 10**9
    eng.save()

    def partial(fn, s, sd, q, cid, reduce_only=False, **k):
        return fn(s, sd, q, cid, reduce_only=reduce_only, fill_qty=filled)

    offline.fx.inject("open_orders", _empty_book, times=80)
    offline.fx.inject("market", partial, times=1)
    eng.tick()
    assert _ledger_sum(eng.st["pos"][DOGE], "t1") == filled or D((eng.st["pos"][DOGE].get("tp_got") or {}).get("t1") or 0) == filled
    offline.fx.inject("market", "unavailable", times=1)
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert (eng.st["pos"][DOGE].get("tp_rearm") or {}).get("t1")
    _at_entry(offline, eng)
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    eng.clock.off += 1
    eng.tick()
    live = _live_tp(offline, "t1")
    assert len(live) == 1 and D(live[0]["qty"]) == q1 - filled
    assert not str(live[0]["client_id"]).endswith("t1")
    assert eng.st["pos"][DOGE].get("tp1_done") is not True
    assert offline.amt(DOGE) == qty - side * filled
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_m8_1_filled_short_of_target_can_be_replaced(offline, side):
    """A FILLED market below the stage target releases the row. The leftover is the runner, so nothing new is rested."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    q1 = D(j["tp"]["q1"])
    unrelated = D(2000)
    _prep(offline, eng)
    t1 = next(o for o in offline.inner.algos.values() if str(o.get("client_id") or "").endswith("t1"))
    offline.inner.algos.pop(t1["id"], None)
    offline.inner.algo_hist.pop(t1["client_id"], None)
    _shrink(offline, side, unrelated)
    offline.inner.set_price(DOGE, _through(j, side))
    eng.tick()
    j = eng.st["pos"][DOGE]
    got = _ledger_sum(j, "t1") or D((j.get("tp_got") or {}).get("t1") or 0)
    assert got == q1 - unrelated
    assert j.get("tp1_done") is not True
    _at_entry(offline, eng)
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    eng.clock.off += 1
    eng.tick()
    j = eng.st["pos"][DOGE]
    assert (j.get("tp_market_once") or {}).get("t1") is None
    live = _live_tp(offline, "t1")
    assert live == []
    assert offline.amt(DOGE) == qty - side * q1
    assert _covered(offline)


KINDS = ("zero", "partial", "full", "reject", "unknown", "restart_mid", "legacy",
         "legacy_lag", "legacy_partial", "no_entry")


def _inv(offline, base, entry, q1, seed, side, tag):
    if _sold(offline) > entry:
        return f"seed {seed} side {side} {tag}: sold {_sold(offline)} > entry {entry}"
    sold = _stage_exec(offline, base, "t1", q1)
    if sold > q1:
        return f"seed {seed} side {side} {tag}: t1 sold {sold} > {q1}"
    if not _covered(offline):
        return f"seed {seed} side {side} {tag}: stop does not cover {offline.amt(DOGE)}"
    j = offline  # placeholder replaced below
    return None


def _property_script(offline, side, seed):
    """One mixed scenario. Returns (reason or None, occurrence info). Checks every tick."""
    from live_v6.exchange import ExchangeUnavailable, OrderRejected

    rng = random.Random(seed)
    kind = KINDS[seed % len(KINDS)]
    info = {"kind": kind, "reject_used": 0, "unknown_used": 0, "restart_mid": 0,
            "ticks": 0, "rest_checked": 0, "live_market_restart": 0}
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    entry = abs(offline.amt(DOGE))
    q1 = D(j["tp"]["q1"])
    base = j["cid"]
    _prep(offline, eng)

    def check(tag):
        info["ticks"] += 1
        if _sold(offline) > entry:
            return f"seed {seed} side {side} {tag}: sold {_sold(offline)} > entry {entry}"
        sold = _stage_exec(offline, base, "t1", q1)
        if sold > q1:
            return f"seed {seed} side {side} {tag}: t1 sold {sold} > {q1}"
        if not _covered(offline):
            return f"seed {seed} side {side} {tag}: stop missing over {offline.amt(DOGE)}"
        pos = eng.st["pos"].get(DOGE) or {}
        got = _ledger_sum(pos, "t1")
        if pos.get("tp1_done") and got < q1:
            return f"seed {seed} side {side} {tag}: tp1_done with ledger {got} < {q1}"
        rows = ((pos.get("tp_ledger") or {}).get("t1") or {}).get("cids") or []
        pending = ((pos.get("tp_market_once") or {}).get("t1") or {})
        if pending.get("cid") and any(str(r.get("cid") or "").endswith(":legacy") for r in rows):
            return (f"seed {seed} side {side} {tag}: legacy row beside pending {pending.get('cid')} "
                    f"ledger {got}")
        live = _live_tp(offline, "t1")
        reserve = entry - q1
        room = abs(offline.amt(DOGE)) - reserve
        for o in live:
            qty_o = D(o.get("qty") or 0)
            info["rest_checked"] += 1
            if qty_o > max(q1 - got, D(0)):
                return f"seed {seed} side {side} {tag}: replacement {qty_o} > slice left {q1 - got}"
            if qty_o > max(room, D(0)):
                return f"seed {seed} side {side} {tag}: replacement {qty_o} eats the runner (room {room})"
        return None

    def tick(tag):
        eng.tick()
        return check(tag)

    t1 = next(o for o in offline.inner.algos.values() if str(o.get("client_id") or "").endswith("t1"))
    if kind == "zero":
        _end(offline, t1, D(0), "CANCELED")
        _at_entry(offline, eng)
        err = tick("zero")
        return err, info
    if kind == "full":
        _end(offline, t1, q1, "FINISHED")
        _shrink(offline, side, q1)
        offline.inner.stops_fire = False
        offline.inner.set_price(DOGE, eng._be_target(DOGE, j) + side * D("0.002"))
        err = tick("full")
        return err, info
    if kind == "reject":
        _end(offline, t1, D(0), "CANCELED")

        def reject(fn, s, sd, q, cid, reduce_only=False, **k):
            info["reject_used"] += 1
            raise OrderRejected(-2010, "injected reject")

        offline.fx.inject("market", reject, times=3)
        offline.inner.set_price(DOGE, _through(j, side))
        err = tick("reject")
        return err, info
    if kind == "unknown":
        _end(offline, t1, D(0), "CANCELED")

        def hide(fn, s, cid, **k):
            # The pre-send lookup is a cid that does not exist yet. Raising there
            # swallows the inject and the lost market is never sent.
            if cid in offline.inner.orders:
                info["unknown_used"] += 1
                raise ExchangeUnavailable("status unknown")
            return fn(s, cid, **k)

        offline.fx.inject("market", "lost", times=1)
        offline.fx.inject("get_order", hide, times=6)
        offline.inner.set_price(DOGE, _through(j, side))
        err = tick("unknown")
        if err:
            return err, info
        eng.clock.off += 1
        err = tick("unknown-2")
        return err, info
    if kind == "legacy":
        _end(offline, t1, D(0), "CANCELED")
        filled = D(8000)
        _shrink(offline, side, filled)
        cid = f"{base}x0"
        offline.inner.orders[cid] = {
            "id": "leg", "client_id": cid, "status": "PARTIALLY_FILLED", "executed_qty": filled,
            "orig_qty": q1, "symbol": DOGE, "reduce_only": True,
        }
        j["tp_got"] = {"t1": str(filled)}
        j["tp_market_once"] = {"t1": {"cid": cid, "before": str(entry), "accepted": True}}
        j.pop("tp_ledger", None)
        eng.save()
        eng = e_engine(offline, eng.clock)
        eng.cfg.trail_atr_k = 0
        _sleeps(eng)
        info["restart_mid"] += 1
        err = check("legacy-reload")
        if err:
            return err, info
        offline.inner.orders[cid]["status"] = "EXPIRED"
        _at_entry(offline, eng)
        err = tick("legacy-expire")
        return err, info
    if kind in ("legacy_lag", "legacy_partial"):
        cancelled = D(100) if kind == "legacy_partial" else D(0)
        cached, filled = (D(8000), D(8000)) if kind == "legacy_partial" else (D(7000), D(8000))
        _end(offline, t1, cancelled, "CANCELED")
        _shrink(offline, side, cancelled + filled)
        cid = f"{base}x0"
        offline.inner.orders[cid] = {
            "id": "lag", "client_id": cid, "status": "PARTIALLY_FILLED", "executed_qty": filled,
            "orig_qty": q1, "symbol": DOGE, "reduce_only": True,
        }
        j["tp_got"] = {"t1": str(cached)}
        j["tp_market_once"] = {"t1": {"cid": cid, "before": str(entry), "accepted": True}}
        j.pop("tp_ledger", None)
        eng.save()
        eng = e_engine(offline, eng.clock)
        eng.cfg.trail_atr_k = 0
        _sleeps(eng)
        info["restart_mid"] += 1
        err = check("legacy-variant")
        if err:
            return err, info
        offline.inner.orders[cid]["status"] = "EXPIRED"
        _at_entry(offline, eng)
        err = tick("legacy-variant-expire")
        return err, info
    if kind == "no_entry":
        j.pop("entry_qty", None)
        _end(offline, t1, D(0), "CANCELED")
        _shrink(offline, side, q1)
        eng.save()
        _at_entry(offline, eng)
        err = tick("no-entry")
        if err:
            return err, info
        eng.clock.off += 1
        err = tick("no-entry-2")
        return err, info
    if kind == "restart_mid":
        partial = D(100)
        _end(offline, t1, partial, "CANCELED")
        _shrink(offline, side, partial + D(50))
        cid = f"{base}x0"
        offline.inner.orders[cid] = {
            "id": "rm", "client_id": cid, "status": "PARTIALLY_FILLED", "executed_qty": D(50),
            "orig_qty": q1, "symbol": DOGE, "reduce_only": True,
        }
        j["tp_market_once"] = {"t1": {"cid": cid, "before": str(entry), "accepted": True}}
        eng.save()
        eng = e_engine(offline, eng.clock)
        eng.cfg.trail_atr_k = 0
        _sleeps(eng)
        info["restart_mid"] += 1
        info["live_market_restart"] += 1
        err = check("restart-live-market")
        if err:
            return err, info
        err = tick("restart-still-live")
        return err, info
    partial = D(rng.choice([10, 100, 500, 8000]))
    status = rng.choice(["CANCELED", "EXPIRED", "FINISHED"])
    _end(offline, t1, partial, status)
    _shrink(offline, side, partial)
    _at_entry(offline, eng)
    err = tick("partial-1")
    if err:
        return err, info
    eng.clock.off += 1
    err = tick("partial-2")
    return err, info


def _run_seeds(tmp_path, side, seeds):
    from collections import Counter
    failed = []
    counts = Counter()
    for seed in seeds:
        backend = Backend("offline", FakeExchange(), tmp=tmp_path / f"{side}-{seed}")
        reason, info = _property_script(backend, side, seed)
        counts[info["kind"]] += 1
        counts["reject_used"] += info["reject_used"]
        counts["unknown_used"] += info["unknown_used"]
        counts["restart_mid"] += info["restart_mid"]
        counts["ticks"] += info["ticks"]
        counts["rest_checked"] += info["rest_checked"]
        counts["live_market_restart"] += info["live_market_restart"]
        if reason:
            failed.append((seed, reason))
    return failed, counts


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("seed", QUICK_SEEDS)
def test_ledger_invariants_quick(offline, side, seed):
    reason, info = _property_script(offline, side, seed)
    assert info["ticks"] >= 1
    assert reason is None, reason


@pytest.mark.slow
@pytest.mark.parametrize("side", [1, -1])
def test_ledger_invariants_1000(tmp_path, side):
    failed, counts = _run_seeds(tmp_path, side, range(1000))
    for kind in KINDS:
        assert counts[kind] >= 100, counts
    assert counts["reject_used"] >= 100
    assert counts["unknown_used"] >= 100
    assert counts["restart_mid"] >= 100
    assert counts["live_market_restart"] >= 100
    assert counts["rest_checked"] >= 100
    assert counts["ticks"] >= 1000
    assert failed == [], failed[:8]


@pytest.mark.slow
@pytest.mark.parametrize("side", [1, -1])
def test_ledger_invariants_alt_1000(tmp_path, side):
    """Second seed range, same generator. Run with the slow property suite."""
    failed, counts = _run_seeds(tmp_path, side, range(1000, 2000))
    for kind in KINDS:
        assert counts[kind] >= 100, counts
    assert counts["reject_used"] >= 100 and counts["unknown_used"] >= 100
    assert counts["live_market_restart"] >= 100 and counts["rest_checked"] >= 100
    assert failed == [], failed[:8]
