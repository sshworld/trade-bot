"""-4116 is success only when that client id is still on the open-order book.

Offline fakes only. Long and short. A cancelled id must be replaced with a
fresh one. A filled take-profit is a fill, not a second order. An unreadable
book alerts once and does not close.
"""
import pytest
from decimal import Decimal as D

from live_v6.exchange import OrderRejected
from live_v6.tests.test_protection_policy_v1 import _alerts, _closes, _sleeps, engine_for
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _stops(b):
    return [o for o in b.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")]


def _tps(b):
    return [o for o in b.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"]


def _dup(cid):
    def reject(fn, s, side, trigger, c, qty=None, **k):
        if c == cid:
            raise OrderRejected(-4116, "ClientOrderId is duplicated.")
        return fn(s, side, trigger, c, qty=qty, **k)

    return reject


def _dup_any(fn, s, side, trigger, c, qty=None, **k):
    raise OrderRejected(-4116, "ClientOrderId is duplicated.")


@pytest.mark.parametrize("side", [1, -1])
def test_4116_live_cid_does_not_repost(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    live = next(o for o in _tps(offline) if str(o["client_id"]).endswith("t1"))
    before = {o["id"] for o in offline.inner.algos.values() if o["symbol"] == DOGE}
    _sleeps(eng)
    offline.fx.inject("take_profit", _dup(live["client_id"]), times=5)
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]))
    now = {o["id"] for o in offline.inner.algos.values() if o["symbol"] == DOGE}
    assert now == before, "a live client id was placed again"
    assert not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_4116_cancelled_stop_posts_a_fresh_cid(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    old = next(o for o in _stops(offline))
    offline.inner.cancel(DOGE, old)
    assert old["client_id"] not in {o["client_id"] for o in _stops(offline)}
    # Next _arm_stop reuses this consumed id, then must bump.
    suffix = old["client_id"][len(j["cid"]):]
    assert suffix.startswith("s")
    j["stop_seq"] = int(suffix[1:])
    eng.save()
    _sleeps(eng)
    offline.fx.inject("stop", _dup(old["client_id"]), times=5)
    eng._arm_stop(DOGE, j, offline.amt(DOGE))
    fresh = [o for o in _stops(offline) if o["client_id"] != old["client_id"]]
    assert fresh, "cancelled id was treated as live; no new stop"
    assert fresh[0]["client_id"] != old["client_id"]
    assert not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_4116_cancelled_tp_posts_a_fresh_cid(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    old = next(o for o in _tps(offline) if str(o["client_id"]).endswith("t1"))
    offline.inner.cancel(DOGE, old)
    assert old["client_id"] not in {o["client_id"] for o in _tps(offline)}
    _sleeps(eng)
    offline.fx.inject("take_profit", _dup(old["client_id"]), times=5)
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]))
    fresh = [o for o in _tps(offline) if o["client_id"] != old["client_id"]]
    assert fresh, "cancelled take-profit id was treated as live"
    assert not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_4116_filled_tp_is_a_fill_not_a_duplicate(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    t1 = next(o for o in _tps(offline) if str(o["client_id"]).endswith("t1"))
    q1 = D(j["tp"]["q1"])
    offline.inner.algos.pop(t1["id"], None)
    offline.inner.algo_hist[t1["client_id"]] = {
        "status": "FINISHED", "executed_qty": q1, "avg_price": D(j["tp"]["tp1"]), "order_id": "fill-1"}
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.fx.inject("take_profit", _dup(t1["client_id"]), times=5)
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), q1)
    assert not _tps(offline), "filled take-profit was placed again"
    assert eng.st["pos"][DOGE].get("tp1_done")
    assert offline.amt(DOGE) == qty and not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_4116_unknown_book_alerts_once_and_does_not_close(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    t1 = next(o for o in _tps(offline) if str(o["client_id"]).endswith("t1"))
    _sleeps(eng)
    offline.fx.inject("take_profit", _dup(t1["client_id"]), times=10)
    offline.fx.inject("open_orders", "unavailable", times=20)
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]))
    n = len([c for c in offline.fx.calls if c[0] == "take_profit"])
    holds = [m for m in _alerts(eng) if "보류" in m and "-4116" in m and DOGE in m]
    assert len(holds) == 1, holds
    assert not _closes(offline) and offline.amt(DOGE) == qty
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]))
    assert len([c for c in offline.fx.calls if c[0] == "take_profit"]) == n
    assert len([m for m in _alerts(eng) if "보류" in m and "-4116" in m and DOGE in m]) == 1
    assert not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_4116_unknown_stop_alerts_once_and_does_not_close(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.fx.inject("stop", _dup_any, times=10)
    offline.fx.inject("open_orders", "unavailable", times=20)
    eng._arm_stop(DOGE, j, qty)
    n = len([c for c in offline.fx.calls if c[0] == "stop"])
    holds = [m for m in _alerts(eng) if "보류" in m and "-4116" in m and DOGE in m]
    assert len(holds) == 1, holds
    assert not _closes(offline) and offline.amt(DOGE) == qty
    eng._arm_stop(DOGE, j, qty)
    assert len([c for c in offline.fx.calls if c[0] == "stop"]) == n
    assert len([m for m in _alerts(eng) if "보류" in m and "-4116" in m and DOGE in m]) == 1
    assert not _closes(offline)
