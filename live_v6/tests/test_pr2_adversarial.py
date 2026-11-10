"""PR #2 live-safety adversarial probes. Offline fakes only: no network, no Telegram."""
from decimal import Decimal as D

import pytest

from live_v6.exchange import ExchangeError, ExchangeUnavailable
from live_v6.tests.test_protection_policy_v1 import (
    RETRY_S,
    SOL,
    _alerts,
    _closes,
    _enter,
    _fill_tp1,
    _orders,
    _pop_cid_suffix,
    _r_px,
    _runner_px,
    _sleeps,
    _stops,
    _tps,
    engine_for,
)
from live_v6.tests.test_qrmtf import DOGE, bot_orders, open_pos


def _ids(rows):
    return {o["id"] for o in rows}


def test_retry_timing_exactly_1_3_10_and_alert_per_attempt(offline):
    """Spec 2 / ruling (b): first try is immediate; sleeps are 1s, 3s, 10s; one alert per failed try; then 🚨 flatten."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    qty = abs(offline.amt(DOGE))
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    sleeps = _sleeps(eng)
    n = len(offline.fx.calls)
    offline.fx.inject("stop", "reject", times=4)
    eng.audit_protection()
    placed = [c for c in offline.fx.calls[n:] if c[0] == "stop"]
    assert len(placed) == 4 and sleeps == RETRY_S == [1.0, 3.0, 10.0]
    alerts = _alerts(eng)
    retry = [m for m in alerts if "재시도" in m]
    assert len(retry) == 3
    assert all(f"{i}회 실패" in retry[i - 1] for i in (1, 2, 3))
    assert any("시장가 청산" in m for m in alerts)
    closes = [c for c in _closes(offline) if c[1][0] == DOGE]
    assert len(closes) == 1 and closes[0][1][4] is True and D(closes[0][1][2]) == qty


def test_flatten_only_known_nonzero_reduceonly_market(offline):
    """Spec 2: exhausted retries flatten a known nonzero row with reduceOnly MARKET, and nothing else."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1, SOL)
    open_pos(offline, eng, 1)
    sol_amt = offline.amt(SOL)
    sol_ids = _ids(_orders(offline, SOL))
    _pop_cid_suffix(offline, "t1")
    _sleeps(eng)
    offline.fx.inject("take_profit", "reject", times=4)
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    assert offline.amt(SOL) == sol_amt and _ids(_orders(offline, SOL)) == sol_ids
    closes = [c for c in _closes(offline) if c[1][0] == DOGE]
    assert len(closes) == 1 and closes[0][1][4] is True
    assert not any(c[1][0] == SOL for c in _closes(offline))
    assert not str(eng.meta.get("halted") or "").startswith("emergency")


def test_flatten_skipped_when_position_row_missing(offline):
    """Missing row is unknown: retries run, but no market close and no cancel."""
    eng = engine_for(offline, "legacy")
    open_pos(offline, eng, 1)
    _pop_cid_suffix(offline, "t1")
    kept = _ids(_orders(offline))
    _sleeps(eng)

    def omit(fn, symbols):
        pos = fn(symbols)
        pos.pop(DOGE, None)
        return pos

    offline.fx.inject("positions", omit, times=99)
    offline.fx.inject("take_profit", "reject", times=4)
    j = eng.st["pos"][DOGE]
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]))
    assert not _closes(offline)
    assert _ids(_orders(offline)) == kept
    assert offline.amt(DOGE) != 0 and DOGE in eng.st["pos"]
    assert not any("시장가 청산" in m for m in _alerts(eng))
    assert any("보류" in m for m in _alerts(eng))


def test_flatten_failure_does_not_crash_or_busy_loop(offline):
    """Spec 2: if the reduceOnly market close also fails, the engine must not raise or recurse without bound."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    _sleeps(eng)
    offline.fx.inject("stop", "reject", times=8)
    offline.fx.inject("market", "reject", times=20)
    try:
        eng.audit_protection()
        eng.tick()
        eng.tick()
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"flatten-failure path raised {type(exc).__name__}: {exc}") from exc
    assert offline.amt(DOGE) != 0
    assert eng.st["pos"][DOGE].get("closing")
    assert any("시장가 청산" in m or "청산 미완료" in m or "보류" in m for m in eng.tg.sent)


def test_audit_does_not_stack_sl_or_tp_when_they_already_exist(offline):
    """Spec 3: a 1-minute check that sees the live SL and TP must not place a second copy of either."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    before_sl, before_tp = _ids(_stops(offline)), _ids(_tps(offline))
    assert before_sl and before_tp
    eng.audit_protection()
    eng.audit_protection()
    assert _ids(_stops(offline)) == before_sl
    assert _ids(_tps(offline)) == before_tp
    assert offline.amt(DOGE) != 0


def test_audit_open_orders_all_failure_does_not_reinstall_or_cancel(offline):
    """Spec 3 / standing rule: a failed all-open-orders read is unknown — no reinstall, no cancel, no flatten."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    kept = _ids(_orders(offline))
    amt = offline.amt(DOGE)
    offline.fx.inject("open_orders_all", "unavailable", times=1)
    eng.audit_protection()
    assert _ids(_orders(offline)) == kept
    assert offline.amt(DOGE) == amt and not _closes(offline)


def test_audit_empty_open_orders_all_does_not_duplicate_or_flatten(offline):
    """A successful but empty all-open-orders read must not treat live SL/TP as missing (no stack, no flatten)."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    kept_sl, kept_tp = _ids(_stops(offline)), _ids(_tps(offline))
    amt = offline.amt(DOGE)
    _sleeps(eng)
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    eng.audit_protection()
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert _ids(_stops(offline)) == kept_sl, _stops(offline)
    assert _ids(_tps(offline)) == kept_tp, _tps(offline)


def test_audit_partial_open_orders_all_does_not_flatten_unseen_symbol(offline):
    """Partial all-open-orders (other symbols present, this coin omitted) must not flatten a still-protected coin."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1, SOL)
    open_pos(offline, eng, 1)
    doge_sl, doge_tp = _ids(_stops(offline)), _ids(_tps(offline))
    amt = offline.amt(DOGE)
    _sleeps(eng)

    def only_sol(fn):
        return [o for o in fn() if o.get("symbol") == SOL]

    offline.fx.inject("open_orders_all", only_sol, times=1)
    eng.audit_protection()
    assert offline.amt(DOGE) == amt and not any(c[1][0] == DOGE for c in _closes(offline))
    assert _ids(_stops(offline)) == doge_sl
    assert _ids(_tps(offline)) == doge_tp


def test_position_missing_from_check_is_untouched(offline):
    """Standing PR #1 rule: a coin absent from the positions snapshot is unknown — no cancel, no close."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    open_pos(offline, eng, 1, SOL)
    kept = _ids(_orders(offline))
    sol = _ids(_orders(offline, SOL))

    def omit(fn, symbols):
        pos = fn(symbols)
        pos.pop(DOGE, None)
        return pos

    offline.fx.inject("positions", omit, times=99)
    eng.audit_protection()
    assert _ids(_orders(offline)) == kept
    assert _ids(_orders(offline, SOL)) == sol
    assert offline.amt(DOGE) != 0 and DOGE in eng.st["pos"]
    assert not _closes(offline)
    assert eng._open_risk_pct() > 0


def test_cancel_after_close_only_after_fresh_zero_read(offline):
    """Spec 1: leftover protective orders are cancelled only after a fresh read still shows position 0."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    kept = _ids(_orders(offline))
    assert kept and offline.amt(DOGE) != 0

    def once_flat(fn, symbols):
        return {s: {"amt": D(0), "entry": D(0), "margin": D(0)} for s in symbols}

    offline.fx.inject("positions", once_flat, times=1)
    assert eng.close(DOGE, "probe") is True
    assert offline.amt(DOGE) != 0
    assert _ids(_orders(offline)) == kept
    assert DOGE in eng.st["pos"]


def test_t1_fill_during_retry_does_not_flatten_remainder(offline):
    """Spec 1+2: if TP1 fills while a missing-t1 retry is sleeping, the remainder must not be market-closed."""
    eng = engine_for(offline, "e")
    j = open_pos(offline, eng, 1)
    q1 = D(j["tp"]["q1"])
    start = abs(offline.amt(DOGE))
    _pop_cid_suffix(offline, "t1")
    filled = {"n": 0}
    rec = []

    def sleep_and_fill(dt):
        rec.append(dt)
        if filled["n"]:
            return
        filled["n"] = 1
        amt = offline.inner.pos[DOGE]["amt"]
        offline.inner.market(DOGE, "SELL" if amt > 0 else "BUY", q1, "sim-t1-fill", reduce_only=True)

    eng.sleep = sleep_and_fill
    offline.fx.inject("take_profit", "reject", times=4)
    eng.reconcile()
    left = abs(offline.amt(DOGE))
    assert rec[:3] == RETRY_S
    assert left == start - q1, f"remainder flattened or unchanged: left={left} start={start} q1={q1}"
    assert DOGE in eng.st["pos"]
    assert not any(c[1][0] == DOGE for c in _closes(offline))
    assert len(_stops(offline)) == 1


def test_restart_with_existing_orders_does_not_duplicate(offline):
    """Spec 4: a restart that already sees SL and TP must not stack another copy."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    before = [(o["client_id"], o["type"], o["stop_price"]) for o in _orders(offline)]
    sleeps = []
    eng2 = engine_for(offline, "e", sleep_log=sleeps)
    after = [(o["client_id"], o["type"], o["stop_price"]) for o in _orders(offline)]
    assert sorted(after) == sorted(before)
    assert len(_stops(offline)) == 1 and len(_tps(offline)) == 1
    assert not _closes(offline)
    assert not sleeps
    assert DOGE in eng2.st["pos"]


def test_restart_missing_orders_reinstalls(offline):
    """Spec 4: a restart with the SL and stage TP gone puts them back via the 1/3/10s procedure."""
    eng = engine_for(offline, "legacy")
    j = open_pos(offline, eng, 1)
    want = _r_px(eng, j, eng.cfg.tp2_r)
    for o in list(_orders(offline)):
        if o["type"] == "STOP_MARKET" or str(o["client_id"]).endswith("t2"):
            offline.inner.algos.pop(o["id"], None)
    sleeps = []
    eng2 = engine_for(offline, "legacy", sleep_log=sleeps)
    assert len(_stops(offline)) == 1
    back = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t2"]
    assert len(back) == 1 and back[0]["stop_price"] == want and back[0]["reduce_only"]
    assert back[0]["working_type"] == "CONTRACT_PRICE"
    assert not [o for o in _tps(offline) if str(o["client_id"]).endswith("t3")]
    assert not _closes(offline)
    assert DOGE in eng2.st["pos"]


def test_e_unsplittable_full_qty_gets_plus_3r_and_sl(offline):
    """Spec 1 / ruling (a): scheme E, qty that cannot be split, full size gets +3R TP and the SL."""
    eng = engine_for(offline, "e")
    j = open_pos(offline, eng, 1)
    offline.inner.pos[DOGE]["amt"] = D(1)
    j["qty"] = j["entry_qty"] = "1"
    for o in list(_tps(offline)):
        offline.inner.algos.pop(o["id"], None)
    j.pop("tp", None)
    j.pop("tp1_done", None)
    eng._place_tps(DOGE, j)
    tps = _tps(offline)
    assert len(tps) == 1 and tps[0]["client_id"] == j["cid"] + "t3"
    assert tps[0]["stop_price"] == _runner_px(eng, j)
    assert tps[0]["working_type"] == "MARK_PRICE" and tps[0]["reduce_only"]
    assert tps[0]["qty"] == D(1) and not tps[0]["close_position"]
    assert len(_stops(offline)) == 1 and _stops(offline)[0]["reduce_only"]
    assert j["tp"].get("full") is True


def test_legacy_missing_t2_reinstalls_at_plus_2r(offline):
    """Ruling (a): legacy second TP stays +2R; a missing t2 is restored at +2R, never +3R."""
    eng = engine_for(offline, "legacy")
    j = open_pos(offline, eng, 1)
    j = _fill_tp1(offline, eng)
    want = _r_px(eng, j, eng.cfg.tp2_r)
    gone = _pop_cid_suffix(offline, "t2")
    assert gone and gone[0]["stop_price"] == want
    eng.audit_protection()
    back = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t2"]
    assert len(back) == 1 and back[0]["stop_price"] == want
    assert back[0]["working_type"] == "CONTRACT_PRICE" and back[0]["reduce_only"]
    assert not [o for o in _tps(offline) if str(o["client_id"]).endswith("t3")]


@pytest.mark.parametrize("scheme,side", [("e", 1), ("e", -1), ("legacy", 1), ("legacy", -1)])
def test_sl_after_partial_tp_is_breakeven_or_better(offline, scheme, side):
    """Standing rule: after TP1 the stop is at breakeven or better, never worse than the stop that was live."""
    eng = engine_for(offline, scheme)
    j0 = open_pos(offline, eng, side)
    stop0 = D(j0["stop_px"])
    entry = D(j0["entry_px"])
    j = _fill_tp1(offline, eng)
    stop = D(j["stop_px"])
    sl = _stops(offline)
    assert len(sl) == 1
    live = D(sl[0]["stop_price"])
    assert live == stop
    assert side * (stop - stop0) >= 0, f"{scheme} {side}: stop moved worse {stop0} -> {stop}"
    assert side * (stop - entry) >= 0, f"{scheme} {side}: stop {stop} is worse than entry {entry}"


def test_upgrade_unknown_result_keeps_confirmed_prearm(offline):
    """Ruling (b): if closePosition promotion cannot be verified, the already-confirmed pre-arm SL stays; no flatten."""
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def fail_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise ExchangeUnavailable("upgrade down")
        return fn(s, side, trigger, cid, qty=qty, **k)

    def oo_down_after_entry(fn, sym):
        entered = any(c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls)
        if entered:
            raise ExchangeUnavailable("open_orders down")
        return fn(sym)

    offline.fx.inject("stop", fail_cp, times=20)
    offline.fx.inject("open_orders", oo_down_after_entry, times=1000)
    _enter(eng)
    assert offline.amt(DOGE) != 0 and DOGE in eng.st["pos"]
    assert not any(c[1][0] == DOGE for c in _closes(offline))
    assert _stops(offline), "pre-arm stop must remain when promotion result is unknown"
    assert not any("시장가 청산" in m for m in _alerts(eng))


def test_protective_orders_reduceonly_and_working_type(offline):
    """Every SL/TP is reduceOnly. Stops and the E +3R runner use MARK_PRICE; legacy/E TP1 stay CONTRACT_PRICE (TA 2026-11-02)."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    for o in _stops(offline) + _tps(offline):
        assert o["reduce_only"]
        assert o["type"] in ("STOP_MARKET", "TAKE_PROFIT_MARKET")
    for o in _stops(offline):
        assert o["working_type"] == "MARK_PRICE"
    for o in _tps(offline):
        assert o["working_type"] == "CONTRACT_PRICE"
        assert str(o["client_id"]).endswith("t1")
    j = _fill_tp1(offline, eng)
    runners = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t3"]
    assert len(runners) == 1
    assert runners[0]["working_type"] == "MARK_PRICE" and runners[0]["reduce_only"]
    assert not runners[0]["close_position"]
    for o in _stops(offline):
        assert o["reduce_only"] and o["working_type"] == "MARK_PRICE"


def test_held_journal_after_protection_close_does_not_emergency_flatten_others(offline):
    """A successful reduceOnly flatten whose journal is held for fill confirmation must not flatten-all + halt."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1, SOL)
    open_pos(offline, eng, 1)
    sol_amt = offline.amt(SOL)
    sol_ids = _ids(_orders(offline, SOL))
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    _sleeps(eng)
    offline.fx.inject("stop", "reject", times=4, match=lambda s, *a, **k: s == DOGE)
    offline.fx.inject("user_trades", lambda fn, *a, **k: [], times=99)
    eng.reconcile()
    assert offline.amt(DOGE) == 0
    assert offline.amt(SOL) == sol_amt, "other protected position was emergency-flattened"
    assert _ids(_orders(offline, SOL)) == sol_ids
    assert not str(eng.meta.get("halted") or "").startswith("emergency")
    assert not any(c[1][0] == SOL for c in _closes(offline))


def test_exception_storm_tick_does_not_crash_or_flatten(offline):
    """Rate/exception storms must not raise out of tick() or flatten a still-protected position."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    amt = offline.amt(DOGE)
    kept = _ids(_orders(offline))
    for method in ("account", "positions", "open_orders", "open_orders_all", "mark_prices"):
        offline.fx.inject(method, "unavailable", times=8)
    try:
        for _ in range(12):
            eng.tick()
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"tick raised {type(exc).__name__}: {exc}") from exc
    assert offline.amt(DOGE) == amt
    assert _ids(_orders(offline)) == kept
    assert not _closes(offline)
