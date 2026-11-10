"""PR #2 review-3 adversarial probes. Offline fakes only: no network, no Telegram.

Regressions the 9e09b06→c5ac35c fixes can introduce: alert dedup hiding
another coin or a later flap, unknown→readable-but-missing-SL not following
spec 2/3, dedup surviving a restart, a persistent hold that is not
re-checked, and any new unknown→place/cancel/flatten path.
"""
from decimal import Decimal as D

import pytest

from live_v6.exchange import ExchangeUnavailable
from live_v6.tests.test_protection_policy_v1 import (
    SOL,
    _alerts,
    _closes,
    _orders,
    _sleeps,
    _stops,
    _tps,
    engine_for,
)
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _ids(rows):
    return {o["id"] for o in rows}


def _holds(eng, sym=None):
    rows = [m for m in _alerts(eng) if "점검 보류" in m]
    if sym is not None:
        rows = [m for m in rows if sym in m]
    return rows


def test_dedup_does_not_suppress_other_coin(offline):
    """Dedup is per coin: A unknown then B unknown must both 🚨."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1, SOL)
    open_pos(offline, eng, 1)
    amt_d, amt_s = offline.amt(DOGE), offline.amt(SOL)
    kept = _ids(_orders(offline)) | _ids(_orders(offline, SOL))
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", "unavailable", times=99)
    eng.audit_protection()
    assert any("점검 보류" in m and DOGE in m for m in _alerts(eng)), _alerts(eng)
    assert any("점검 보류" in m and SOL in m for m in _alerts(eng)), _alerts(eng)
    assert offline.amt(DOGE) == amt_d and offline.amt(SOL) == amt_s
    assert not _closes(offline)
    assert _ids(_orders(offline)) | _ids(_orders(offline, SOL)) == kept


def test_unknown_then_readable_missing_sl_reinstalls(offline):
    """Spec 3 then 2: once the per-symbol book is readable and the SL is
    actually gone, the audit must place it (retry schedule), not stay held."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    amt = offline.amt(DOGE)
    assert not _stops(offline)
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", "unavailable", times=1)
    eng.audit_protection()
    assert not _stops(offline) and not _closes(offline)
    assert _holds(eng, DOGE), "first unknown confirm must alert"
    _sleeps(eng)
    eng.audit_protection()
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert _stops(offline), "readable + missing SL must reinstall the stop"
    sl = _stops(offline)[0]
    assert sl["reduce_only"] and sl["type"] == "STOP_MARKET"


def test_flapping_unknown_known_realerts(offline):
    """After a confirm succeeds the coin leaves the dedup set, so a later
    unknown must 🚨 again (not stay silenced forever)."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    amt = offline.amt(DOGE)
    kept = _ids(_orders(offline))
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", "unavailable", times=1)
    eng.audit_protection()
    assert len(_holds(eng, DOGE)) == 1
    eng.audit_protection()  # bundled + per-symbol readable, SL still there
    assert _ids(_orders(offline)) == kept and offline.amt(DOGE) == amt
    assert not _closes(offline)
    n = len(_holds(eng, DOGE))
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", "unavailable", times=1)
    eng.audit_protection()
    assert len(_holds(eng, DOGE)) == n + 1, _holds(eng, DOGE)
    assert _ids(_orders(offline)) == kept and not _closes(offline)


def test_dedup_state_does_not_survive_restart(offline):
    """_audit_unknown is in-memory. A new process must 🚨 again if the
    confirm is still unread (the operator may have missed the first one)."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    amt = offline.amt(DOGE)
    kept = _ids(_orders(offline))
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", "unavailable", times=1)
    eng.audit_protection()
    assert len(_holds(eng, DOGE)) == 1
    eng2 = engine_for(offline, "e")
    assert DOGE in eng2.st["pos"]
    assert not getattr(eng2, "_audit_unknown", set())
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", "unavailable", times=1)
    eng2.audit_protection()
    assert len(_holds(eng2, DOGE)) == 1, eng2.tg.sent
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert _ids(_orders(offline)) == kept


def test_persistent_unknown_is_rechecked_each_audit(offline):
    """Spec 3: every 1-minute pass must try to confirm. A lasting unread book
    is not treated as missing (no place, no flatten). One 🚨 until readable
    again is backoff, not a skipped check."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    kept = _ids(_orders(offline))
    amt = offline.amt(DOGE)
    n = {"n": 0}

    def boom(fn, sym):
        n["n"] += 1
        raise ExchangeUnavailable("still down")

    offline.fx.inject("open_orders_all", lambda fn: [], times=5)
    offline.fx.inject("open_orders", boom, times=5)
    for _ in range(5):
        eng.audit_protection()
    assert n["n"] == 5, f"confirm was not retried each audit: {n['n']}"
    assert _ids(_orders(offline)) == kept
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert len(_holds(eng, DOGE)) == 1, _holds(eng, DOGE)


def test_4130_hold_does_not_flatten_and_later_visible_stop_is_left(offline):
    """-4130 hold must not flatten. When a later audit can see the live
    closePosition, it must not stack a second stop or flatten."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    amt = offline.amt(DOGE)
    kept_sl = _ids(_stops(offline))
    _sleeps(eng)
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", lambda fn, sym: [], times=99)
    eng.audit_protection()
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert _ids(_stops(offline)) == kept_sl
    assert any("점검 보류" in m for m in _alerts(eng))
    # book readable again (no injects left for open_orders_all)
    eng.audit_protection()
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert _ids(_stops(offline)) == kept_sl, _stops(offline)


def test_wouldtrigger_still_flattens_that_position(offline):
    """WouldTrigger stays definitive: flatten that coin, do not file as kept."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    qty = abs(offline.amt(DOGE))
    j = eng.st["pos"][DOGE]
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    offline.inner.set_price(DOGE, D(j["stop_px"]))
    _sleeps(eng)
    eng._arm_stop(DOGE, j, offline.amt(DOGE) or D(j["qty"]))
    closes = [c for c in _closes(offline) if c[1][0] == DOGE]
    assert len(closes) == 1 and closes[0][1][4] is True
    assert D(closes[0][1][2]) == qty or offline.amt(DOGE) == 0
    assert any("시장가 청산" in m or "즉시 발동" in m for m in _alerts(eng) + eng.tg.sent)


def test_unknown_confirm_never_places_cancels_or_flattens(offline):
    """Principle: an unread per-symbol confirm is not absence — no new order,
    no cancel, no flatten. The 🚨 hold is required."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    kept = _ids(_orders(offline))
    amt = offline.amt(DOGE)
    n_stop = len([c for c in offline.fx.calls if c[0] == "stop"])
    n_tp = len([c for c in offline.fx.calls if c[0] == "take_profit"])
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", "unavailable", times=1)
    offline.fx.inject("cancel", "unavailable", times=1)
    eng.audit_protection()
    assert _ids(_orders(offline)) == kept
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert len([c for c in offline.fx.calls if c[0] == "stop"]) == n_stop
    assert len([c for c in offline.fx.calls if c[0] == "take_profit"]) == n_tp
    assert _holds(eng, DOGE)
