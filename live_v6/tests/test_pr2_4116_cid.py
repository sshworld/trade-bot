"""-4116 on a spent take-profit id. Offline fakes only. Long and short, t1/t2/t3.

A cancelled id is not sent again: the next tick posts one new client id and
five ticks leave exactly one live order of that tranche. A fill the journal
missed is booked once (t1 then moves the stop to breakeven and arms t3).
An unreadable id is not a success and does not close; one alert.
"""
import pytest
from decimal import Decimal as D

from live_v6.exchange import OrderRejected
from live_v6.tests.test_protection_policy_v1 import _alerts, _closes, engine_for
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _tps(b):
    return [o for o in b.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"]


def _stops(b):
    return [o for o in b.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")]


def _posts(b, name, start):
    return [c for c in b.fx.calls[start:] if c[0] == name]


def _cid(call):
    return call[1][3]


def _ticks(eng, n=5):
    for _ in range(n):
        eng.tick()


def _park(offline, eng, j, side):
    """Mark on the profitable side of breakeven so a BE stop can rest."""
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, eng._be_target(DOGE, j) + side * D("0.002"))
    offline.inner.stops_fire = True


def _sync_qty(offline, j, qty, side):
    offline.inner.pos[DOGE]["amt"] = qty if side > 0 else -qty
    j["qty"] = str(qty)


def _spend(offline, order, executed=D(0), status="CANCELED"):
    offline.inner.algos.pop(order["id"], None)
    offline.inner.algo_hist[order["client_id"]] = {
        "status": status, "executed_qty": executed, "avg_price": order["stop_price"], "order_id": "spent"}


def _reject_cid(cid):
    def reject(fn, s, side, trigger, c, qty=None, **k):
        if c == cid:
            raise OrderRejected(-4116, "ClientOrderId is duplicated.")
        return fn(s, side, trigger, c, qty=qty, **k)

    return reject


def _arm_runner(offline, eng, side):
    """Scheme E: book TP1 by hand and let one tick place the +3R runner."""
    j = eng.st["pos"][DOGE]
    t1 = next(o for o in _tps(offline) if str(o["client_id"]).endswith("t1"))
    left = D(j["tp"]["q2"])
    _spend(offline, t1)
    _sync_qty(offline, j, left, side)
    j["tp1_done"] = True
    eng.save()
    _park(offline, eng, j, side)
    eng.tick()
    j = eng.st["pos"][DOGE]
    t3 = next(o for o in _tps(offline) if "t3" in str(o["client_id"]))
    return j, t3


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("which", ["t1", "t2", "t3"])
def test_4116_cancelled_posts_one_new_cid(offline, side, which):
    scheme = "legacy" if which == "t2" else "e"
    eng = engine_for(offline, scheme)
    open_pos(offline, eng, side)
    if which == "t3":
        j, old = _arm_runner(offline, eng, side)
    else:
        j = eng.st["pos"][DOGE]
        old = next(o for o in _tps(offline) if str(o["client_id"]).endswith(which))
    _spend(offline, old)
    qty = offline.amt(DOGE)
    offline.fx.inject("take_profit", _reject_cid(old["client_id"]), times=20)
    start = len(offline.fx.calls)
    _ticks(eng)
    posts = _posts(offline, "take_profit", start)
    assert [_cid(c) for c in posts].count(old["client_id"]) == 0
    assert len(posts) == 1 and _cid(posts[0]) != old["client_id"]
    live = [o for o in _tps(offline) if o["client_id"] == _cid(posts[0])]
    assert len(live) == 1
    assert not _closes(offline) and offline.amt(DOGE) == qty
    assert _stops(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_4116_unbooked_t1_arms_be_and_t3_once(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    t1 = next(o for o in _tps(offline) if str(o["client_id"]).endswith("t1"))
    _spend(offline, t1, executed=D(j["tp"]["q1"]), status="FINISHED")
    _sync_qty(offline, j, D(j["tp"]["q2"]), side)
    eng.save()
    _park(offline, eng, j, side)
    assert not j.get("tp1_done")
    offline.fx.inject("take_profit", _reject_cid(t1["client_id"]), times=20)
    start = len(offline.fx.calls)
    _ticks(eng)
    j = eng.st["pos"][DOGE]
    posts = _posts(offline, "take_profit", start)
    stops = _posts(offline, "stop", start)
    assert j.get("tp1_done") is True
    assert [_cid(c) for c in posts].count(t1["client_id"]) == 0
    assert len(posts) == 1 and "t3" in str(_cid(posts[0]))
    assert len(stops) == 1
    assert len(_tps(offline)) == 1 and _tps(offline)[0]["client_id"] == _cid(posts[0])
    assert not _closes(offline)
    assert _stops(offline)


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("which", ["t2", "t3"])
def test_4116_unbooked_later_tp_is_booked_once(offline, side, which):
    scheme = "legacy" if which == "t2" else "e"
    eng = engine_for(offline, scheme)
    open_pos(offline, eng, side)
    if which == "t3":
        j, old = _arm_runner(offline, eng, side)
        covered = D(j["tp"]["q3"])
    else:
        j = eng.st["pos"][DOGE]
        old = next(o for o in _tps(offline) if str(o["client_id"]).endswith("t2"))
        covered = D(j["tp"]["q2"])
        j["tp1_done"] = True
        j["be_done"] = True
    left = covered - D(1)
    _spend(offline, old, executed=covered, status="FINISHED")
    _sync_qty(offline, j, left, side)
    eng.save()
    offline.fx.inject("take_profit", _reject_cid(old["client_id"]), times=20)
    start = len(offline.fx.calls)
    _ticks(eng)
    j = eng.st["pos"][DOGE]
    posts = _posts(offline, "take_profit", start)
    assert posts == []
    assert j.get("tp2_done") is True if which == "t2" else j.get("tp3_done") is True
    if which == "t3":
        assert j.get("exit_fill") == "take_profit"
    assert not _closes(offline) and offline.amt(DOGE) != 0
    assert _stops(offline)


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("which", ["t1", "t2", "t3"])
def test_4116_unknown_is_not_success_and_alerts_once(offline, side, which):
    scheme = "legacy" if which == "t2" else "e"
    eng = engine_for(offline, scheme)
    open_pos(offline, eng, side)
    if which == "t3":
        j, old = _arm_runner(offline, eng, side)
    else:
        j = eng.st["pos"][DOGE]
        old = next(o for o in _tps(offline) if str(o["client_id"]).endswith(which))
    offline.inner.algos.pop(old["id"], None)
    qty = offline.amt(DOGE)
    before = {o["id"] for o in offline.inner.algos.values()}
    offline.fx.inject("algo_order", "unavailable", times=30)
    offline.fx.inject("take_profit", _reject_cid(old["client_id"]), times=20)
    start = len(offline.fx.calls)
    alerts0 = len(_alerts(eng))
    _ticks(eng)
    assert _posts(offline, "take_profit", start) == []
    assert {o["id"] for o in offline.inner.algos.values()} == before
    holds = [m for m in _alerts(eng)[alerts0:] if "보류" in m and "-4116" in m and DOGE in m]
    assert len(holds) == 1
    assert not _closes(offline) and offline.amt(DOGE) == qty
    assert _stops(offline)
