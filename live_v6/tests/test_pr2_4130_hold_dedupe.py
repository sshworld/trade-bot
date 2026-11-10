"""-4130 hold alerts once per coin until a read shows the stop again.

Offline fakes only. The set is process memory, so a new engine alerts again.
"""
from live_v6.tests.test_protection_policy_v1 import (
    _alerts,
    _closes,
    _sleeps,
    _stops,
    engine_for,
)
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _ids(rows):
    return {o["id"] for o in rows}


def _holds(eng):
    return [m for m in _alerts(eng) if "점검 보류" in m and DOGE in m]


def _hold_once(offline, eng):
    """Empty bundled book, then a readable empty per-symbol book: place hits -4130."""
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", lambda fn, sym: [], times=8)
    eng.audit_protection()


def test_4130_hold_alerts_once_until_the_stop_is_seen(offline):
    """Repeated -4130 holds on one coin send one 🚨. A later read that shows
    the closePosition clears that, so the next hold alerts again."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    amt = offline.amt(DOGE)
    kept = _ids(_stops(offline))
    assert kept
    _sleeps(eng)

    _hold_once(offline, eng)
    _hold_once(offline, eng)
    assert len(_holds(eng)) == 1, _holds(eng)
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert _ids(_stops(offline)) == kept

    eng.audit_protection()  # real book: the live closePosition is visible
    assert len(_holds(eng)) == 1, _holds(eng)
    assert DOGE not in eng._cp_hold
    assert _ids(_stops(offline)) == kept and not _closes(offline)

    _hold_once(offline, eng)
    assert len(_holds(eng)) == 2, _holds(eng)
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert _ids(_stops(offline)) == kept
