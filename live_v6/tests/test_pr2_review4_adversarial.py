"""PR #2 review-4 probes for _cp_hold. Offline fakes only: no network, no Telegram."""
from decimal import Decimal as D

import pytest

from live_v6.tests.test_protection_policy_v1 import (
    SOL,
    _alerts,
    _closes,
    _orders,
    _sleeps,
    _stops,
    engine_for,
)
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _ids(rows):
    return {o["id"] for o in rows}


def _holds(eng, sym=None):
    rows = [m for m in _alerts(eng) if "점검 보류" in m and "-4130" in m]
    if sym is not None:
        rows = [m for m in rows if sym in m]
    return rows


def _empty_book_hold(offline, eng, times=4):
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", lambda fn, sym: [], times=times)
    eng.audit_protection()


def test_cp_hold_not_cleared_on_empty_or_uncovering_read(offline):
    """_cp_hold is discarded only when a covering SL is seen (right side and
    closePosition or qty ≥ position). Empty and uncovering reads must not clear it."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    amt = offline.amt(DOGE)
    kept = _ids(_stops(offline))
    _sleeps(eng)
    _empty_book_hold(offline, eng)
    assert len(_holds(eng, DOGE)) == 1
    assert DOGE in eng._cp_hold

    _empty_book_hold(offline, eng)
    assert len(_holds(eng, DOGE)) == 1
    assert DOGE in eng._cp_hold
    assert offline.amt(DOGE) == amt and not _closes(offline)

    def uncovering(fn, sym):
        rows = []
        for o in fn(sym):
            o = dict(o)
            if (o.get("type") or "").startswith("STOP"):
                o["side"] = "BUY"
                o["close_position"] = False
                o["qty"] = D("1")
            rows.append(o)
        return rows

    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", uncovering, times=8)
    eng.audit_protection()
    assert DOGE in eng._cp_hold, "uncovering re-read cleared _cp_hold"
    assert len(_holds(eng, DOGE)) == 1
    assert _ids(_stops(offline)) == kept and not _closes(offline)

    eng.audit_protection()  # real book: covering closePosition is visible
    assert DOGE not in eng._cp_hold
    assert _ids(_stops(offline)) == kept and not _closes(offline)


def test_cp_hold_two_coins_independent(offline):
    """A hold on coin A must not suppress the first 🚨 for coin B."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1, SOL)
    open_pos(offline, eng, 1)
    amt_d, amt_s = offline.amt(DOGE), offline.amt(SOL)
    _sleeps(eng)
    _empty_book_hold(offline, eng, times=10)
    assert len(_holds(eng, DOGE)) == 1, _holds(eng)
    assert len(_holds(eng, SOL)) == 1, _holds(eng)
    _empty_book_hold(offline, eng, times=10)
    assert len(_holds(eng, DOGE)) == 1
    assert len(_holds(eng, SOL)) == 1
    assert offline.amt(DOGE) == amt_d and offline.amt(SOL) == amt_s
    assert not _closes(offline)


def test_cp_hold_flapping_realerts(offline):
    """Seeing a covering stop clears the set, so the next -4130 hold 🚨s again."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    amt = offline.amt(DOGE)
    kept = _ids(_stops(offline))
    _sleeps(eng)
    _empty_book_hold(offline, eng)
    assert len(_holds(eng, DOGE)) == 1
    eng.audit_protection()
    assert DOGE not in eng._cp_hold
    _empty_book_hold(offline, eng)
    assert len(_holds(eng, DOGE)) == 2, _holds(eng, DOGE)
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert _ids(_stops(offline)) == kept


def test_cp_hold_cleared_when_position_closes(offline):
    """A closed journal must drop the coin from _cp_hold so a new position
    on the same symbol alerts on its first -4130 hold."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    _sleeps(eng)
    _empty_book_hold(offline, eng)
    assert len(_holds(eng, DOGE)) == 1
    assert DOGE in eng._cp_hold
    assert eng.close(DOGE, "probe") is True
    assert offline.amt(DOGE) == 0
    assert DOGE not in eng._cp_hold, (
        "_cp_hold leaked across close; a later -4130 hold on a new "
        "position of the same coin would stay silent (engine.py:1346-1348)"
    )
