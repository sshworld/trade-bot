"""Round-3 majors and minors. Offline fakes only. Long and short where the side matters."""
import pytest
from decimal import Decimal as D

from live_v6.engine import MISMATCH, PROTECT_AUDIT_S
from live_v6.exchange import ExchangeUnavailable, OrderRejected
from live_v6.tests.test_protection_policy_v1 import _alerts, _closes, _sleeps, engine_for
from live_v6.tests.test_qrmtf import DOGE, open_pos

SOL = "SOLUSDT"


def _stop_posts(b):
    return [c for c in b.fx.calls if c[0] == "stop"]


def _tp_posts(b):
    return [c for c in b.fx.calls if c[0] == "take_profit"]


def _market_closes(b):
    return [c for c in b.fx.calls if c[0] == "market" and len(c[1]) > 4 and c[1][4]]


def _stops(b):
    return [o for o in b.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")]


def _reject_cp(fn, s, side, trigger, cid, qty=None, **k):
    if qty is None:
        raise OrderRejected(-4130, "closePosition exists")
    return fn(s, side, trigger, cid, qty=qty, **k)


def _drop_stops(offline):
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and (o["type"] or "").startswith("STOP"):
            offline.inner.algos.pop(o["id"], None)


@pytest.mark.parametrize("side", [1, -1])
def test_m1_tp_only_book_rearms_once_per_minute_and_first_tick_posts_once(offline, side):
    """Unchanged TP-only book retries on the 60s timer. The tick that enters the
    hold posts one stop, even when the minute audit is also due. -4130 stays quiet."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    _drop_stops(offline)
    assert any((o["type"] or "").startswith("TAKE_PROFIT") for o in offline.inner.open_orders(DOGE))
    offline.fx.inject("stop", _reject_cp, times=80)
    eng._protect_audit_at = eng.clock() - PROTECT_AUDIT_S - 1
    before = len(_stop_posts(offline))
    alerts = len([m for m in _alerts(eng) if "보류" in m and "-4130" in m and DOGE in m])
    eng.tick()
    assert len(_stop_posts(offline)) == before + 1, "first hold tick posted the stop more than once"
    assert DOGE in eng._cp_hold
    quiet = len(_stop_posts(offline))
    for _ in range(5):
        eng.tick()
    assert len(_stop_posts(offline)) == quiet
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert len(_stop_posts(offline)) == quiet + 1
    assert len([m for m in _alerts(eng) if "보류" in m and "-4130" in m and DOGE in m]) == alerts + 1
    assert offline.amt(DOGE) == qty and not _market_closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_m2_unread_flat_coin_does_not_hide_another_mismatch(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _sleeps(eng)
    eng._consistent = 3
    aid = f"foreign-limit-{side}"
    offline.inner.algos[aid] = {
        "kind": "algo", "id": aid, "client_id": "manual-limit", "symbol": DOGE,
        "type": "LIMIT", "side": "SELL" if side > 0 else "BUY", "stop_price": D("0"),
        "close_position": False, "reduce_only": False, "qty": D("10"), "working_type": "CONTRACT_PRICE",
    }

    def sol_down(fn, sym):
        if sym == SOL:
            raise ExchangeUnavailable("book down")
        return fn(sym)

    offline.fx.inject("open_orders", sol_down, times=40)
    eng.reconcile()
    assert MISMATCH in eng.blocks, dict(eng.blocks)
    assert eng._consistent == 0
    assert not _market_closes(offline)


def test_m2_existing_block_still_survives_unread_flat_coin(offline):
    """The older guard: an unread flat coin must not clear a block that is already up."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    eng.blocks[MISMATCH] = "seed"
    eng._consistent = 1

    def sol_down(fn, sym):
        if sym == SOL:
            raise ExchangeUnavailable("book down")
        return fn(sym)

    offline.fx.inject("open_orders", sol_down, times=40)
    eng.reconcile()
    eng.reconcile()
    assert MISMATCH in eng.blocks


@pytest.mark.parametrize("side", [1, -1])
def test_m3_accepted_stop_cid_survives_later_failed_attempts(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    live = next(o for o in _stops(offline))
    assert j.get("stop_cid") == live["client_id"]
    _sleeps(eng)
    offline.fx.inject("stop", _reject_cp, times=10)
    eng._arm_stop(DOGE, j, offline.amt(DOGE))
    assert eng.st["pos"][DOGE].get("stop_cid") == live["client_id"]
    offline.inner.algos.pop(live["id"], None)
    offline.inner.algo_hist[live["client_id"]] = {
        "status": "FINISHED", "executed_qty": D("6"), "avg_price": D(j["stop_px"]), "order_id": "1"}
    offline.inner.pos[DOGE]["amt"] = side * D(4)
    eng.reconcile()
    queried = [c[1][1] for c in offline.fx.calls if c[0] == "algo_order" and len(c[1]) > 1]
    assert live["client_id"] in queried, queried


@pytest.mark.parametrize("side", [1, -1])
def test_n3_upgrade_4130_alerts_only_when_confirm_misses(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    _sleeps(eng)
    offline.fx.inject("stop", _reject_cp, times=5)
    before = len([m for m in _alerts(eng) if "보류" in m and "-4130" in m])
    pre = {"id": "pre", "client_id": j["cid"] + "p", "stop_price": D(j["stop_px"])}
    assert eng._upgrade_stop(DOGE, j, pre) == "ok"
    assert len([m for m in _alerts(eng) if "보류" in m and "-4130" in m]) == before
    assert not _market_closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_tp_reject_unreadable_confirm_alerts_once(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and str(o["client_id"]).endswith("t1"):
            offline.inner.algos.pop(o["id"], None)
    _sleeps(eng)
    offline.fx.inject("take_profit", "reject", times=40)
    offline.fx.inject("algo_order", "unavailable", times=40)
    for _ in range(4):
        eng.tick()
    raw = [m for m in _alerts(eng) if "조회 불가" in m and DOGE in m]
    holds = [m for m in _alerts(eng) if "보류" in m and "익절 거절" in m and DOGE in m]
    assert raw == [], raw
    assert len(holds) == 1
    assert not _market_closes(offline) and offline.amt(DOGE) == qty


@pytest.mark.parametrize("side", [1, -1])
def test_persistent_tp_reject_backs_off_after_the_first_cycle(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and str(o["client_id"]).endswith("t1"):
            offline.inner.algos.pop(o["id"], None)
    sleeps = _sleeps(eng)
    offline.fx.inject("take_profit", "reject", times=40)
    eng.reconcile()
    assert sleeps == [1.0, 3.0, 10.0]
    first = len(_tp_posts(offline))
    sleeps.clear()
    eng.tick()
    eng.tick()
    assert sleeps == []
    assert len(_tp_posts(offline)) == first
    eng.clock.off += PROTECT_AUDIT_S + 1
    eng.tick()
    assert len(_tp_posts(offline)) == first + 1
    assert sleeps == []
    assert not _market_closes(offline)
    assert len([m for m in _alerts(eng) if "보류" in m and "익절" in m]) <= 1


def test_m5_audit_confirm_failure_waits_60s(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    _drop_stops(offline)
    _sleeps(eng)
    offline.fx.inject("open_orders", "unavailable", times=20)
    eng.audit_protection()
    assert not [m for m in _alerts(eng) if "보류" in m or "불명" in m]
    eng.clock.off += eng.cfg.transient_alert_s + 1
    offline.fx.inject("open_orders", "unavailable", times=20)
    eng.audit_protection()
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1
    assert not _market_closes(offline)


def test_missing_position_row_blocks_a_clean_consistency_pass(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    eng.blocks[MISMATCH] = "seed"
    eng._consistent = 1

    def drop_sol(fn, symbols):
        out = dict(fn(symbols))
        out.pop(SOL, None)
        return out

    offline.fx.inject("positions", drop_sol, times=10)
    eng.reconcile()
    eng.reconcile()
    assert MISMATCH in eng.blocks
    assert eng._consistent == 1


def test_tp_levels_exception_does_not_close(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    j = eng.st["pos"][DOGE]
    j.pop("tp", None)
    eng.save()

    def boom(*a, **k):
        raise RuntimeError("cannot price")

    eng._tp_levels = boom
    eng._place_tps(DOGE, j)
    eng._place_tps(DOGE, j)
    assert not _market_closes(offline)
    assert _stops(offline)
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_be_through_during_hold_does_not_market_close(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    old = next(o for o in _stops(offline))
    eng._cp_hold.add(DOGE)
    j["tp1_done"] = True
    eng.save()
    tgt = eng._be_target(DOGE, j)
    mk = tgt - side * D("0.01")
    eng._move_stop_be(DOGE, j, offline.amt(DOGE), offline.inner.open_orders(DOGE), mk)
    eng._move_stop_be(DOGE, j, offline.amt(DOGE), offline.inner.open_orders(DOGE), mk)
    assert not _market_closes(offline)
    assert any(o["id"] == old["id"] for o in _stops(offline))
    assert len([m for m in _alerts(eng) if "보류" in m or "유지" in m]) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_be_would_trigger_during_hold_does_not_market_close(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    old = next(o for o in _stops(offline))
    eng._cp_hold.add(DOGE)
    j["tp1_done"] = True
    eng.save()
    tgt = eng._be_target(DOGE, j)
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, tgt - side * D("0.01"))
    mk = tgt + side * D("0.002")
    eng._move_stop_be(DOGE, j, offline.amt(DOGE), offline.inner.open_orders(DOGE), mk)
    assert not _market_closes(offline)
    assert any(o["id"] == old["id"] for o in _stops(offline))
    assert len([m for m in _alerts(eng) if "보류" in m or "유지" in m]) == 1
