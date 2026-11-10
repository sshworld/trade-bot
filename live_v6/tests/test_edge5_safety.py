"""Fifth review: incomplete positions snapshot must not open extra exposure. Offline only."""
import pytest

from .conftest import unique_T
from .test_close_hold_review import DOGE, SOL, _block_telegram
from .test_dircap import XRP, _sd
from .test_qrmtf import exit_engine, open_pos


def _drop(offline, *missing):
    def drop(fn, symbols):
        pos = fn(symbols)
        for s in missing:
            pos.pop(s, None)
        return pos

    offline.fx.inject("positions", drop, times=99)


@pytest.mark.parametrize("scheme_side", [1, -1])
def test_missing_other_symbol_does_not_bypass_same_side_cap(offline, monkeypatch, scheme_side):
    """Live cap: at most 2 same-side positions. A missing SOL row must not let a 3rd same-side entry through."""
    _block_telegram(monkeypatch)
    eng = exit_engine(offline)
    assert eng.enter(SOL, _sd(offline, SOL), unique_T(), side=scheme_side)
    assert eng.enter(XRP, _sd(offline, XRP), unique_T(), side=scheme_side)
    assert set(eng.st["pos"]) == {SOL, XRP}
    _drop(offline, SOL)
    ok = eng.enter(DOGE, _sd(offline, DOGE), unique_T(), side=scheme_side)
    assert ok is False, (
        f"third same-side entry opened while {SOL} was missing from the snapshot; "
        f"DOGE amt={offline.amt(DOGE)} skip={eng.meta.get('skip_log', [])[-1:]}"
    )
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]


def test_missing_other_symbol_does_not_bypass_max_positions(offline, monkeypatch):
    """max_positions=1: SOL is open but omitted from the snapshot; DOGE must not open."""
    _block_telegram(monkeypatch)
    eng = exit_engine(offline, max_positions=1)
    assert eng.enter(SOL, _sd(offline, SOL), unique_T(), side=1)
    _drop(offline, SOL)
    ok = eng.enter(DOGE, _sd(offline, DOGE), unique_T(), side=1)
    assert ok is False, (
        f"max_positions=1 bypassed; DOGE amt={offline.amt(DOGE)} skip={eng.meta.get('skip_log', [])[-1:]}"
    )
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]


def test_missing_other_symbol_does_not_bypass_risk_cap(offline, monkeypatch):
    """SOL journal risk 20% already exceeds the 12% book cap; omitting SOL must not allow DOGE."""
    _block_telegram(monkeypatch)
    eng = exit_engine(offline, max_same_side=None)
    open_pos(offline, eng, 1, SOL)
    eng.st["pos"][SOL]["risk_frac"] = 0.20
    _drop(offline, SOL)
    ok = eng.enter(DOGE, _sd(offline, DOGE), unique_T(), side=1)
    assert ok is False, (
        f"risk cap bypassed with unknown SOL 20% still live; "
        f"DOGE amt={offline.amt(DOGE)} skip={eng.meta.get('skip_log', [])[-1:]}"
    )
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]


def test_second_snapshot_missing_entry_symbol_refuses_without_keyerror(offline, monkeypatch):
    """The post-leverage positions re-read can omit the coin we are about to enter. That is unknown, not a crash."""
    _block_telegram(monkeypatch)
    eng = exit_engine(offline)
    n = {"n": 0}

    def later_drop(fn, symbols):
        n["n"] += 1
        pos = fn(symbols)
        if n["n"] >= 2:
            pos.pop(DOGE, None)
        return pos

    offline.fx.inject("positions", later_drop, times=99)
    try:
        ok = eng.enter(DOGE, _sd(offline, DOGE), unique_T(), side=1)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"enter raised {type(exc).__name__}: {exc}") from exc
    assert ok is False
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
