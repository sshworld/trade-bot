"""Margin-mode read-back through entry, startup and reconcile. All delays use the engine's fake sleep."""
from unittest.mock import Mock

import pytest

from live_v6.engine import MISMATCH
from live_v6.exchange import BinanceREST, ExchangeError

from .conftest import unique_T
from .test_faults import DOGE, SOL, ready


@pytest.fixture
def new_coin(offline):
    eng = ready(offline, symbols=(SOL,))
    assert eng.track_symbols([DOGE]) == [DOGE]
    assert offline.inner.mt[DOGE] == "CROSSED"
    sleeps = []
    eng.sleep = sleeps.append
    return eng, sleeps


def config_reads(offline):
    return offline.fx.calls.count(("margin_type", (DOGE,)))


def crossed_positions(read, symbols):
    rows = read(symbols)
    rows[DOGE] = dict(rows[DOGE], margin_type="CROSSED")
    return rows


def after_leverage(offline, action):
    """Run action() right after the entry's set_leverage, so it only hits the final-gate reads."""
    def set_leverage(set_lev, sym, lev):
        result = set_lev(sym, lev)
        action()
        return result
    offline.fx.inject("set_leverage", set_leverage)


def stale_after_leverage(offline):
    after_leverage(offline, lambda: offline.fx.inject("positions", crossed_positions))


def test_new_coin_enters_on_second_config_read(offline, new_coin, caplog):
    eng, sleeps = new_coin
    offline.fx.lag_margin_change(DOGE, position_reads=3, config_reads=1)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert offline.entry_orders(DOGE, 0) == 1
    assert not eng.blocks and not any(r[2] == "margin_mode" for r in eng.meta.get("skip_log", []))
    # positionRisk stayed stale through the final gate: two config reads after set (one wait), one at the final gate
    # (no wait).
    assert sleeps == [1.0]
    assert config_reads(offline) == 3
    assert f"{DOGE} margin mode ISOLATED: positionRisk CROSSED, symbolConfig ISOLATED (reads 2)" in caplog.messages


def test_persistent_crossed_blocks_entry(offline, new_coin):
    eng, sleeps = new_coin
    offline.fx.lag_margin_change(DOGE, position_reads=1, config_reads=5)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert config_reads(offline) == 5 and sleeps == [1.0] * 4
    assert "symbolConfig CROSSED" in eng.blocks[f"margin_mode:{DOGE}"]
    assert eng.meta["skip_log"][-1][1:3] == [DOGE, "margin_mode"]
    assert not offline.inner.accepted


@pytest.mark.parametrize("fault,detail", [
    ("unavailable", "injected: margin_type never sent"),
    (Mock(side_effect=ValueError("malformed read")), "ValueError"),
], ids=["exchange-error", "unexpected-error"])
def test_failed_config_read_blocks_without_retry(offline, new_coin, fault, detail):
    eng, sleeps = new_coin
    offline.fx.lag_margin_change(DOGE, position_reads=1)
    offline.fx.inject("margin_type", fault)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert config_reads(offline) == 1 and sleeps == []
    assert f"symbolConfig failed: {detail}" in eng.blocks[f"margin_mode:{DOGE}"]
    assert eng.meta["skip_log"][-1][1:3] == [DOGE, "margin_mode"]
    assert not offline.inner.accepted


@pytest.mark.parametrize("config_mt", ["ISOLATED", "CROSSED"])
def test_final_gate_reads_config_once_while_lag_persists(offline, new_coin, config_mt):
    """positionRisk still lags at the final gate (after leverage): ONE symbolConfig read decides, without waiting."""
    eng, sleeps = new_coin
    offline.fx.lag_margin_change(DOGE, position_reads=3)
    if config_mt == "CROSSED":
        after_leverage(offline, lambda: offline.fx.inject("margin_type", lambda read, s: "CROSSED"))
    entered = eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert any(name == "set_leverage" for name, _ in offline.fx.calls)
    assert config_reads(offline) == 2 and sleeps == []
    if config_mt == "ISOLATED":
        assert entered and offline.entry_orders(DOGE, 0) == 1
    else:
        assert not entered and not offline.inner.accepted
        assert f"margin_mode:{DOGE}" not in eng.blocks          # final gate: skip this entry only, no global block
        skip = eng.meta["skip_log"][-1]
        assert skip[1:3] == [DOGE, "margin_mode"] and "symbolConfig CROSSED" in skip[3]


def test_final_gate_crossed_after_lag_cleared_refuses(offline, new_coin):
    """Review 2: positionRisk lagged right after the change but read ISOLATED in the second snapshot; a CROSSED read
    at the final gate is then a real change, not lag: refuse as before, symbolConfig is not consulted."""
    eng, sleeps = new_coin
    offline.fx.lag_margin_change(DOGE, position_reads=1)
    stale_after_leverage(offline)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert config_reads(offline) == 1 and sleeps == [] and not offline.inner.accepted   # the pre-check read only
    assert eng.meta["skip_log"][-1][1:4] == [DOGE, "margin_mode", "read-back CROSSED"]
    assert f"margin_mode:{DOGE}" not in eng.blocks


def test_final_gate_crossed_without_own_change_refuses(offline):
    """Review 1: the pre-check read ISOLATED (no POST in this entry), then the final snapshot reads CROSSED. That is
    a real change (e.g. by hand), not the lag of our own change: refuse as before, symbolConfig is not consulted."""
    eng = ready(offline)
    sleeps = []
    eng.sleep = sleeps.append

    def on_open_orders(read, sym):
        out = read(sym)
        offline.fx.inject("positions", crossed_positions)  # the next snapshot = the final gate's
        return out

    offline.fx.inject("open_orders", on_open_orders, match=lambda sym: sym == DOGE)
    n0 = len(offline.fx.calls)                                   # startup already set ISOLATED on every coin
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert ("set_margin_type", (DOGE, "ISOLATED")) not in offline.fx.calls[n0:]
    assert config_reads(offline) == 0 and sleeps == [] and not offline.inner.accepted
    assert eng.meta["skip_log"][-1][1:4] == [DOGE, "margin_mode", "read-back CROSSED"]
    assert f"margin_mode:{DOGE}" not in eng.blocks


@pytest.mark.parametrize("manual", ["same-coin-position", "other-coin-position", "same-coin-order"])
def test_manual_trade_during_margin_wait_refuses(offline, manual):
    """Review 2: the pre-check waits for symbolConfig after the margin change. A position or entry order placed
    meanwhile (by hand) is seen by the second snapshot: no leverage call on that coin, no bot order."""
    eng = ready(offline, symbols=(SOL,), max_positions=1 if manual == "other-coin-position" else 7)
    assert eng.track_symbols([DOGE]) == [DOGE]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        if manual == "same-coin-position":
            offline.inner.open_position_raw(DOGE, 100)
        elif manual == "other-coin-position":
            offline.inner.open_position_raw(SOL, 1)
        else:
            offline.inner.limit_postonly(DOGE, "BUY", 100, offline.inner.book(DOGE)["bid"] / 2, "manual-1")

    eng.sleep = sleep
    offline.fx.lag_margin_change(DOGE, position_reads=1, config_reads=1)
    n0 = len(offline.fx.calls)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert sleeps == [1.0] and config_reads(offline) == 2
    assert not any(name == "set_leverage" for name, _ in offline.fx.calls[n0:])
    assert set(offline.inner.accepted) <= {"manual-1"}                     # no pre-arm stop, no market order
    if manual == "other-coin-position":
        assert eng.meta["skip_log"][-1][1:3] == [DOGE, "max_positions"]
    if manual == "same-coin-order":
        assert MISMATCH in eng.blocks


def test_crossed_after_isolated_readback_is_not_lag(offline, new_coin):
    """Review 3-1: positionRisk read ISOLATED right after the change, so no lag was seen; CROSSED in the second
    snapshot and at the final gate is a real change: refuse as before, symbolConfig is not consulted."""
    eng, sleeps = new_coin
    seen = []

    def crossed_from_third_read(read, symbols):    # 1 = first snapshot, 2 = read-back after the change (ISOLATED),
        seen.append(1)                              # 3 = second snapshot, 4 = final gate: CROSSED again
        return crossed_positions(read, symbols) if len(seen) >= 3 else read(symbols)

    offline.fx.inject("positions", crossed_from_third_read, times=4)
    offline.fx.inject("margin_type", lambda read, s: "ISOLATED", times=5)  # a stale symbolConfig must not be asked
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert config_reads(offline) == 0 and sleeps == [] and not offline.inner.accepted
    assert eng.meta["skip_log"][-1][1:4] == [DOGE, "margin_mode", "read-back CROSSED"]


def readback_once(offline, edit):
    """The positions read right after the next margin change on DOGE returns edit(rows)."""
    def after_set(fn, s, mt="ISOLATED"):
        result = fn(s, mt)
        offline.fx.inject("positions", lambda read, symbols: edit(read(symbols)))
        return result
    offline.fx.inject("set_margin_type", after_set, match=lambda s, mt="ISOLATED": s == DOGE)


@pytest.mark.parametrize("edit,shown", [
    (lambda rows: {k: v for k, v in rows.items() if k != DOGE}, "None"),
    (lambda rows: {**rows, DOGE: dict(rows[DOGE], margin_type="")}, ""),
    (lambda rows: {**rows, DOGE: dict(rows[DOGE], margin_type="UNKNOWN")}, "UNKNOWN"),
], ids=["missing-row", "blank", "unknown"])
def test_bad_readback_blocks_without_config(offline, new_coin, edit, shown):
    """Review 3-5: only the old value CROSSED can be lag. A missing row or a blank / unknown mode right after the
    change blocks at once, as before: no symbolConfig read, no wait."""
    eng, sleeps = new_coin
    readback_once(offline, edit)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert config_reads(offline) == 0 and sleeps == [] and not offline.inner.accepted
    assert eng.blocks[f"margin_mode:{DOGE}"] == f"{DOGE} read-back {shown}"


def test_confirm_reads_zero_reads_positionrisk_only(offline):
    """margin_confirm_reads=0: a lagging read-back blocks as before; symbolConfig is never read (so the final gate
    has no lag to confirm either)."""
    eng = ready(offline, symbols=(SOL,), margin_confirm_reads=0)
    assert eng.track_symbols([DOGE]) == [DOGE]
    sleeps = []
    eng.sleep = sleeps.append
    offline.fx.lag_margin_change(DOGE, position_reads=3)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert config_reads(offline) == 0 and sleeps == [] and not offline.inner.accepted
    assert eng.blocks[f"margin_mode:{DOGE}"] == f"{DOGE} read-back CROSSED"


def test_startup_keeps_positionrisk_only_check(offline):
    """Startup / reconcile: no symbolConfig fallback and no waits (as before). A lagging read-back blocks until
    the next reconcile reads it again."""
    eng = offline.engine(symbols=(DOGE,))
    sleeps = []
    eng.sleep = sleeps.append
    offline.fx.lag_margin_change(DOGE, position_reads=1, config_reads=1)
    eng.startup()
    assert eng.started and f"margin_mode:{DOGE}" in eng.blocks and not eng.entries_allowed()
    eng.reconcile()
    assert eng.entries_allowed()
    assert config_reads(offline) == 0 and sleeps == []


def test_reconcile_does_not_wait_while_margin_block_persists(offline):
    """Review 3: a margin block that stays must not add waits (or symbolConfig weight) to every 5 s reconcile."""
    eng = offline.engine(symbols=(DOGE,))
    sleeps = []
    eng.sleep = sleeps.append
    offline.fx.lag_margin_change(DOGE, position_reads=1, config_reads=5)
    eng.startup()
    offline.fx.inject("positions", crossed_positions, times=10)   # every read (reconcile snapshot + read-back)
    eng.reconcile()
    eng.reconcile()
    assert f"margin_mode:{DOGE}" in eng.blocks
    assert config_reads(offline) == 0 and sleeps == []


@pytest.mark.parametrize("raw,expected", [
    ("ISOLATED", "ISOLATED"), ("isolated", "ISOLATED"), ("CROSSED", "CROSSED"), ("cross", "CROSSED"),
])
def test_rest_margin_type_normalizes_symbol_row(raw, expected):
    rest = object.__new__(BinanceREST)
    rest._req = Mock(return_value=[{"symbol": SOL, "marginType": "CROSSED"}, {"symbol": DOGE, "marginType": raw}])
    assert rest.margin_type(DOGE) == expected
    rest._req.assert_called_once_with("GET", "/fapi/v1/symbolConfig", {"symbol": DOGE})


@pytest.mark.parametrize("response,error", [
    ([], "no row"), ([{"symbol": SOL, "marginType": "ISOLATED"}], "no row"), ([None], "no row"),
    ([{"symbol": DOGE}], "bad marginType"), ({"symbol": DOGE, "marginType": 1}, "bad marginType"),
    ({"symbol": DOGE, "marginType": " "}, "bad marginType"),
    ({"symbol": DOGE, "marginType": "UNKNOWN"}, "bad marginType"),
    ({"symbol": DOGE, "marginType": " ISOLATED"}, "bad marginType"),
    ({"symbol": DOGE, "marginType": "ısolated"}, "bad marginType"),   # dotless i: .upper() would read ISOLATED
], ids=["no-rows", "wrong-symbol", "invalid-row", "missing-field", "non-string", "blank", "unknown", "padded",
        "non-ascii"])
def test_rest_margin_type_rejects_bad_response(response, error):
    rest = object.__new__(BinanceREST)
    rest._req = Mock(return_value=response)
    with pytest.raises(ExchangeError, match=rf"symbolConfig: {error} for {DOGE}"):
        rest.margin_type(DOGE)
