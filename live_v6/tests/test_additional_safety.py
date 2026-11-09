"""TA reproduction tests for the close-commit guard. Offline only; Telegram HTTP is mocked.

Assertions match the review probes: a position that reappears counts in risk again, a fresher
nonzero read must not be followed by cancelling SL/TP, and an id-less stream slice beside an
identified REST slice does not book P&L.
"""
import copy

import pytest

from live_v6.exchange import ExchangeError

from .test_close_hold_review import (
    D, DOGE, SOL, _block_telegram, _eng, _matched, _open_scheme, _protecting, _wire,
)
from .test_ptp_short import _fill
from .test_qrmtf import open_pos


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_reopened_position_reenters_risk_sum(offline, monkeypatch, scheme):
    _block_telegram(monkeypatch)
    eng, j = _open_scheme(offline, scheme, -1)
    j = eng.st["pos"][DOGE]
    j["risk_frac"] = .04
    saved = copy.deepcopy(offline.inner.pos[DOGE])
    offline.inner.pos.pop(DOGE)
    eng.reconcile()
    assert eng._open_risk_pct() == 0
    offline.inner.pos[DOGE] = saved
    eng.reconcile()
    assert offline.amt(DOGE) != 0
    assert eng._open_risk_pct() >= 4, "nonzero position stays excluded by stale flat confirmation"


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_no_cleanup_after_newer_nonzero_position_read(offline, monkeypatch, scheme):
    _block_telegram(monkeypatch)
    eng, j = _open_scheme(offline, scheme, -1)
    saved = copy.deepcopy(offline.inner.pos[DOGE])
    offline.inner.pos.pop(DOGE)

    def reopen(fn, syms):
        offline.inner.pos[DOGE] = saved
        return fn(syms)

    def firstflat(fn, syms):
        return {s: {"amt": D(0), "entry": D(0), "margin": D(0)} for s in syms}

    offline.fx.inject("positions", firstflat, times=1)
    offline.fx.inject("positions", reopen, times=1)
    eng.reconcile()
    assert offline.amt(DOGE) != 0
    assert offline.stops(DOGE), "fresh nonzero read must not be followed by cancelling all SL/TP"


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_earlier_symbol_query_failure_keeps_later_nonzero_in_risk(offline, monkeypatch, scheme):
    """A full positions snapshot already shows SOL nonzero. DOGE's open_orders read then fails.
    SOL's flat flag must already be cleared, and its SL/TP must still be on the book."""
    _block_telegram(monkeypatch)
    eng, _j = _open_scheme(offline, scheme, 1)
    open_pos(offline, eng, 1, SOL)
    eng.st["pos"][SOL]["risk_frac"] = 0.04
    saved = copy.deepcopy(offline.inner.pos[SOL])
    offline.inner.pos.pop(SOL)
    eng.record_close(SOL, "stop_loss")                 # held + flat-confirmed, without cancelling SOL's orders
    assert SOL in eng._flat_confirmed and eng.st["pos"][SOL].get("close_held")
    offline.inner.pos[SOL] = saved
    live = {o["client_id"] for o in _protecting(offline, SOL)}
    assert live and offline.amt(SOL) != 0
    doge_pct = float(eng.st["pos"][DOGE]["risk_frac"]) * 100

    def doge_orders(fn, sym, *a, **k):
        if sym == DOGE:
            raise ExchangeError("open_orders down")
        return fn(sym, *a, **k)

    offline.fx.inject("open_orders", doge_orders, times=99)
    with pytest.raises(ExchangeError):
        eng.reconcile()
    assert eng._open_risk_pct() == pytest.approx(doge_pct + 4)
    assert round(eng._open_risk_pct(), 5) == round(doge_pct + 4, 5)
    assert {o["client_id"] for o in _protecting(offline, SOL)} == live


def test_mixed_rest_id_and_unidentified_stream_fill_quarantines(offline, monkeypatch):
    _block_telegram(monkeypatch)
    eng = _eng(offline)
    j, t0, fills = _matched()
    j["stream_fills"] = [_fill("X1", "BUY", "98", ".4", ".02", ".8", t0 + 2000, "")]
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades"), "missing-id raw stream fill was discarded and P&L booked"
    assert eng.st["pos"][SOL].get("reconcile_pending")
