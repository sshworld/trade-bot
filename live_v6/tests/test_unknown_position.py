"""TA R4 (2026-10-21): a position on the exchange that is NOT in the state file is never market-closed by the bot.

Root cause (testnet canary 13:00 KST): a DOGEUSDT position opened outside the H7-T model was closed at the next 4h
close by `model_sync` (the strategy closes live positions its model does not hold). With a lost / corrupted state
file the same path would have market-closed the bot's OWN positions. Now such positions live in st["unknown"]:
🚨 once, entries blocked for that coin only, risk counted, protective stop at the model's exit line if none exists
(existing stops never moved / cancelled), resolution manual (close by hand or tools/adopt_position.py).

Driven through tick() with a simulated clock and synthetic klines (same harness as test_bar_close_live)."""
import json
from decimal import Decimal

from live_v6 import strategy as S
from live_v6.engine import UNKNOWN_POS
from live_v6.strategies.h7t import H7T

from .test_bar_close_live import START, Clock, market

DOGE, SOL, XRP = "DOGEUSDT", "SOLUSDT", "XRPUSDT"
H4 = S.H4_MS


def make(offline, clk, **kw):
    strat = H7T(params=S.Params(h7_min_obs=10 ** 9))
    eng = offline.engine(clock=clk, strategy=strat, **kw)
    market(clk, offline.inner)
    return eng, strat


def close_calls(b):
    """reduceOnly MARKET orders the bot SENT (= closes)."""
    return [c for c in b.fx.calls if c[0] == "market" and len(c[1]) > 4 and c[1][4]]


def alerts(eng):
    return [m for m in eng.tg.sent if m.startswith("🚨")]


def stops(b, sym):
    return [o for o in b.inner.open_orders(sym) if (o["type"] or "").startswith("STOP")]


def next_close(clk, eng):
    """Advance past the next 4h close (+ bar delay) and tick → the strategy's on_bar_close runs (model_sync path)."""
    T0 = int(eng.meta["last_bar_close"])
    clk.ms = T0 + H4 + 10_000
    eng.tick()
    assert int(eng.meta["last_bar_close"]) == T0 + H4, "bar close not processed"


def expected_line(eng, strat, sym, side):
    line, atr = strat.exit_line(sym, side)
    return eng.rules[sym].price(line, "down" if side > 0 else "up"), atr


def started(offline, clk):
    eng, strat = make(offline, clk)
    eng.tick()
    assert eng.started
    return eng, strat


# ───────── long / short, without / with an existing stop ─────────
def test_unknown_long_without_stop_never_closed_stop_at_channel_low(offline):
    clk = Clock(START)
    eng, strat = started(offline, clk)                       # models ready (channel + ATR)
    offline.inner.open_position_raw(DOGE, 1000)
    eng.reconcile()
    u = eng.st["unknown"][DOGE]
    st = stops(offline, DOGE)
    line, _ = expected_line(eng, strat, DOGE, 1)
    assert len(st) == 1 and st[0]["close_position"] and st[0]["side"] == "SELL" and st[0]["stop_price"] == line
    assert u["stop_src"] == "20-bar channel exit line" and Decimal(u["stop_px"]) == line
    assert len([a for a in alerts(eng) if "기록 없는 포지션 발견" in a]) == 1
    next_close(clk, eng)
    next_close(clk, eng)
    assert offline.amt(DOGE) == 1000 and not close_calls(offline)          # no model_sync / any close
    assert [o["id"] for o in stops(offline, DOGE)] == [st[0]["id"]]       # stop untouched
    assert len([a for a in alerts(eng) if "기록 없는 포지션 발견" in a]) == 1     # 🚨 once, not per reconcile
    assert DOGE not in eng.st["pos"]


def test_unknown_long_with_existing_stop_untouched(offline):
    offline.inner.open_position_raw(DOGE, 1000)
    mine = offline.inner.stop(DOGE, "SELL", Decimal("0.12"), "manual-stop-1")     # the user's own stop
    clk = Clock(START)
    eng, _ = started(offline, clk)
    next_close(clk, eng)
    st = stops(offline, DOGE)
    assert [(o["id"], o["stop_price"]) for o in st] == [(mine["id"], Decimal("0.12"))]   # not moved, nothing added
    assert not any(c[0] in ("stop", "cancel") and c[1][0] == DOGE for c in offline.fx.calls)
    assert eng.st["unknown"][DOGE]["stop_src"].startswith("exchange (existing")
    assert offline.amt(DOGE) == 1000 and not close_calls(offline)


def test_unknown_short_without_stop_stop_at_channel_high(offline):
    clk = Clock(START)
    eng, strat = started(offline, clk)
    offline.inner.open_position_raw(SOL, -1)
    eng.reconcile()
    st = stops(offline, SOL)
    line, _ = expected_line(eng, strat, SOL, -1)
    assert len(st) == 1 and st[0]["close_position"] and st[0]["side"] == "BUY" and st[0]["stop_price"] == line
    next_close(clk, eng)
    assert offline.amt(SOL) == -1 and not close_calls(offline)
    assert [o["id"] for o in stops(offline, SOL)] == [st[0]["id"]]


def test_unknown_short_with_existing_stop_untouched(offline):
    offline.inner.open_position_raw(SOL, -1)
    mine = offline.inner.stop(SOL, "BUY", Decimal("170"), "manual-stop-2", qty=Decimal("1"))   # reduceOnly qty stop
    clk = Clock(START)
    eng, _ = started(offline, clk)
    next_close(clk, eng)
    assert [(o["id"], o["stop_price"]) for o in stops(offline, SOL)] == [(mine["id"], Decimal("170"))]
    assert not any(c[0] in ("stop", "cancel") and c[1][0] == SOL for c in offline.fx.calls)
    assert offline.amt(SOL) == -1 and not close_calls(offline)


def test_price_beyond_line_stop_one_atr_from_mark(offline):
    """Long whose mark is already below the 20-bar low → stop = mark − 1×ATR14 (4h)."""
    clk = Clock(START)
    eng, strat = started(offline, clk)                       # models built from bars around 0.15
    line, atr = strat.exit_line(DOGE, 1)
    mark = (line * Decimal("0.98")).quantize(Decimal("0.00001"))
    offline.inner.open_position_raw(DOGE, 1000, px=str(mark))
    eng.reconcile()
    st = stops(offline, DOGE)
    assert len(st) == 1 and st[0]["stop_price"] == eng.rules[DOGE].price(mark - atr, "down")
    assert eng.st["unknown"][DOGE]["stop_src"].startswith("1×ATR14 from mark")
    assert not close_calls(offline)


# ───────── state file lost → own positions survive ─────────
def test_state_file_deleted_restart_own_position_not_closed_stop_remains(offline):
    clk = Clock(START)
    eng, _ = started(offline, clk)
    T = int(eng.meta["last_bar_close"])
    assert eng.enter(DOGE, Decimal("0.005"), T)                # the bot's OWN position (journaled)
    own_stop = stops(offline, DOGE)
    assert len(own_stop) == 1
    offline.store_path.unlink()                                # state file lost / deleted
    clk2 = Clock(clk.ms + 60_000)
    eng2, _ = make(offline, clk2)
    eng2.tick()
    assert eng2.started and DOGE in eng2.st["unknown"] and DOGE not in eng2.st["pos"]
    next_close(clk2, eng2)
    next_close(clk2, eng2)
    assert offline.amt(DOGE) > 0 and not close_calls(offline)
    assert [o["id"] for o in stops(offline, DOGE)] == [own_stop[0]["id"]]   # same stop, never moved / cancelled
    assert any("기록 없는 포지션 발견" in a for a in alerts(eng2))
    saved = json.loads(offline.store_path.read_text())
    assert DOGE in saved["unknown"]


# ───────── entry block (coin only), portfolio risk, other close paths ─────────
def test_entries_blocked_for_that_coin_only_and_risk_counted(offline):
    offline.inner.open_position_raw(DOGE, 1000)
    clk = Clock(START)
    eng, _ = started(offline, clk)
    T = int(eng.meta["last_bar_close"])
    assert eng.entries_allowed()                               # no global block
    assert not eng.enter(DOGE, Decimal("0.005"), T)
    assert eng.meta["skip_log"][-1][2] == UNKNOWN_POS
    book = eng._open_book(offline.inner.positions(eng.cfg.symbols))
    assert [b["sym"] for b in book] == [DOGE] and book[0]["risk_frac"] == eng.st["unknown"][DOGE]["risk_frac"] > 0
    assert eng.enter(XRP, Decimal("0.02"), T)                  # other coins trade normally
    assert not close_calls(offline)


def test_flatten_all_and_close_never_touch_unknown(offline):
    """Flatten-all (§8c L3) closes the journaled positions only; close() refuses a symbol not in the state file."""
    offline.inner.open_position_raw(DOGE, 1000)
    clk = Clock(START)
    eng, _ = started(offline, clk)
    assert eng.enter(XRP, Decimal("0.02"), int(eng.meta["last_bar_close"]))
    assert eng.close(DOGE, "stop_breach") is False
    eng.emergency_flatten_all("test")
    assert offline.amt(XRP) == 0 and offline.amt(DOGE) == 1000
    assert [c[1][0] for c in close_calls(offline)] == [XRP]
    assert stops(offline, DOGE)
    assert any("기록 없는 포지션은 그대로" in a for a in alerts(eng))


def test_resolved_by_hand_clears_block(offline):
    offline.inner.open_position_raw(DOGE, 1000)
    clk = Clock(START)
    eng, _ = started(offline, clk)
    offline.inner.market(DOGE, "SELL", Decimal(1000), "manual-close", reduce_only=True)   # the user closes it
    eng.reconcile()
    assert DOGE not in eng.st["unknown"] and not stops(offline, DOGE)
    assert any("기록 없는 포지션 해소" in m for m in eng.tg.sent)


# ───────── TA R4 add-on 1: fallback stop 3 % from the mark when channel/ATR data is missing ─────────
def test_fallback_stop_3pct_long_when_no_model_data_then_never_moved(offline):
    """Present at start-up: the first reconcile runs BEFORE the model bootstrap → no channel/ATR → closePosition
    MARK_PRICE stop 3 % below the mark at once. When the model data appears the stop is NOT moved."""
    offline.inner.open_position_raw(DOGE, 1000)
    clk = Clock(START)
    eng, strat = started(offline, clk)
    st = stops(offline, DOGE)
    want = eng.rules[DOGE].price(Decimal("0.15") * Decimal("0.97"), "down")
    assert len(st) == 1 and st[0]["close_position"] and st[0]["side"] == "SELL" and st[0]["stop_price"] == want
    assert eng.st["unknown"][DOGE]["stop_src"].startswith("fallback 3% from mark")
    assert strat.exit_line(DOGE, 1) is not None                # data is there now …
    next_close(clk, eng)
    assert [(o["id"], o["stop_price"]) for o in stops(offline, DOGE)] == [(st[0]["id"], want)]   # … stop not moved
    assert sum(1 for c in offline.fx.calls if c[0] == "stop" and c[1][0] == DOGE) == 1
    assert not any(c[0] == "cancel" and c[1][0] == DOGE for c in offline.fx.calls)
    assert offline.amt(DOGE) == 1000 and not close_calls(offline)


def test_fallback_stop_3pct_short_when_no_model_data(offline):
    offline.inner.open_position_raw(SOL, -1)
    clk = Clock(START)
    eng, strat = make(offline, clk)
    strat.exit_line = lambda sym, side: None                 # data missing for the whole test
    eng.tick()
    st = stops(offline, SOL)
    want = eng.rules[SOL].price(Decimal("150") * Decimal("1.03"), "up")
    assert len(st) == 1 and st[0]["close_position"] and st[0]["side"] == "BUY" and st[0]["stop_price"] == want
    next_close(clk, eng)
    assert [o["id"] for o in stops(offline, SOL)] == [st[0]["id"]] and offline.amt(SOL) == -1 and not close_calls(offline)


def test_no_mark_price_unprotected_flag_never_closed(offline):
    """No mark price at all (transient) → no stop can be computed: flagged unprotected (dead-man stops pinging),
    never closed — transient errors are not rejections, so the 5-min last resort does not apply."""
    clk = Clock(START)
    eng, _ = started(offline, clk)
    offline.inner.open_position_raw(DOGE, 1000)
    offline.fx.inject("mark_prices", "unavailable", times=99)
    eng.reconcile()
    assert eng.st["unknown"][DOGE].get("unprotected") and not eng.healthy()
    clk.ms += 600_000
    eng.reconcile()
    assert offline.amt(DOGE) == 1000 and not close_calls(offline)


# ───────── TA R4 add-on 2: last resort after 5 min of REJECTED stops ─────────
def _rejecting(offline, sym):
    offline.fx.inject("stop", "reject", times=10 ** 6, match=lambda s, *a, **k: s == sym)


def test_stop_rejected_for_5_min_then_reduce_only_close_and_alert(offline):
    clk = Clock(START)
    eng, _ = started(offline, clk)
    offline.inner.open_position_raw(DOGE, 1000)
    _rejecting(offline, DOGE)
    eng.reconcile()                                          # detection (t0); stop rejected
    t0 = int(eng.st["unknown"][DOGE]["detected_ms"])
    for dt in (60_000, 180_000, 299_000):
        clk.ms = t0 + dt
        eng.reconcile()
        assert offline.amt(DOGE) == 1000 and not close_calls(offline), dt
    clk.ms = t0 + 300_000
    eng.reconcile()
    assert offline.amt(DOGE) == 0
    cc = close_calls(offline)
    assert len(cc) == 1 and cc[0][1][0] == DOGE and cc[0][1][1] == "SELL" and cc[0][1][4] is True   # reduceOnly MARKET
    assert DOGE not in eng.st["unknown"]
    assert any("최후 수단" in a for a in alerts(eng))
    assert eng.st["unknown"] == {} and offline.amt(SOL) == 0


def test_short_stop_rejected_for_5_min_then_close(offline):
    clk = Clock(START)
    eng, _ = started(offline, clk)
    offline.inner.open_position_raw(SOL, -1)
    _rejecting(offline, SOL)
    eng.reconcile()
    clk.ms = int(eng.st["unknown"][SOL]["detected_ms"]) + 300_000
    eng.reconcile()
    cc = close_calls(offline)
    assert offline.amt(SOL) == 0 and len(cc) == 1 and cc[0][1][1] == "BUY"


def test_stop_confirmed_at_4m59_no_close(offline):
    clk = Clock(START)
    eng, _ = started(offline, clk)
    offline.inner.open_position_raw(DOGE, 1000)
    _rejecting(offline, DOGE)
    eng.reconcile()
    t0 = int(eng.st["unknown"][DOGE]["detected_ms"])
    clk.ms = t0 + 120_000
    eng.reconcile()
    offline.fx.clear()                                       # exchange accepts the stop again
    clk.ms = t0 + 299_000
    eng.reconcile()                                          # stop placed at 4m59
    assert stops(offline, DOGE)
    for dt in (300_000, 600_000, 3_600_000):
        clk.ms = t0 + dt
        eng.reconcile()
    assert offline.amt(DOGE) == 1000 and not close_calls(offline)
    assert not eng.st["unknown"][DOGE].get("unprotected")


def test_transient_errors_only_never_trigger_last_resort(offline):
    clk = Clock(START)
    eng, _ = started(offline, clk)
    offline.inner.open_position_raw(DOGE, 1000)
    offline.fx.inject("stop", "unavailable", times=10 ** 6, match=lambda s, *a, **k: s == DOGE)
    eng.reconcile()
    clk.ms = int(eng.st["unknown"][DOGE]["detected_ms"]) + 900_000
    eng.reconcile()
    assert offline.amt(DOGE) == 1000 and not close_calls(offline)


def test_restart_mid_window_keeps_original_detection_time(offline):
    """Documented choice: the detection time is persisted in the state file (st["unknown"][sym]["detected_ms"]), so a
    restart mid-window KEEPS it — the 5-min deadline is not extended by a restart. If the state file itself is lost,
    the position is detected anew and the window restarts from that detection (later close, never earlier)."""
    clk = Clock(START)
    eng, _ = started(offline, clk)
    offline.inner.open_position_raw(DOGE, 1000)
    _rejecting(offline, DOGE)
    eng.reconcile()
    t0 = int(eng.st["unknown"][DOGE]["detected_ms"])
    clk.ms = t0 + 200_000
    eng.reconcile()
    clk2 = Clock(t0 + 250_000)                              # restart at 4m10
    eng2, _ = make(offline, clk2)
    eng2.tick()
    assert int(eng2.st["unknown"][DOGE]["detected_ms"]) == t0 and offline.amt(DOGE) == 1000
    clk2.ms = t0 + 300_000
    eng2.reconcile()
    assert offline.amt(DOGE) == 0 and len(close_calls(offline)) == 1


def test_state_lost_mid_window_restarts_window(offline):
    clk = Clock(START)
    eng, _ = started(offline, clk)
    offline.inner.open_position_raw(DOGE, 1000)
    _rejecting(offline, DOGE)
    eng.reconcile()
    t0 = int(eng.st["unknown"][DOGE]["detected_ms"])
    offline.store_path.unlink()
    clk2 = Clock(t0 + 250_000)
    eng2, _ = make(offline, clk2)
    eng2.tick()
    t1 = int(eng2.st["unknown"][DOGE]["detected_ms"])
    assert t1 >= t0 + 250_000
    clk2.ms = t0 + 300_000
    eng2.reconcile()
    assert offline.amt(DOGE) == 1000 and not close_calls(offline)   # new window from t1
    clk2.ms = t1 + 300_000
    eng2.reconcile()
    assert offline.amt(DOGE) == 0


# ───────── ops tool: adopt_position (dry-run by default) ─────────
def _unknown_state(offline, side_amt=1000):
    offline.inner.open_position_raw(DOGE, side_amt)
    clk = Clock(START)
    eng, _ = started(offline, clk)
    return eng, clk


def test_adopt_tool_dry_run_writes_nothing(offline, capsys):
    from live_v6.tools import adopt_position as A
    _unknown_state(offline)
    before = offline.store_path.read_text()
    assert A.main(["--state", str(offline.store_path), "--sym", DOGE]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "model_sync" in out              # warns: model does not hold it
    assert offline.store_path.read_text() == before


def test_adopt_tool_apply_requires_stopped_unit_then_bot_manages_it(offline, monkeypatch):
    import pytest
    from live_v6.tools import adopt_position as A
    eng, clk = _unknown_state(offline)
    args = ["--state", str(offline.store_path), "--sym", DOGE, "--apply"]
    with pytest.raises(SystemExit):
        A.main(args)                                             # no --unit
    monkeypatch.setattr(A, "unit_active", lambda u: True)
    with pytest.raises(SystemExit):
        A.main(args + ["--unit", "live_v6-citest"])              # unit running → refused
    monkeypatch.setattr(A, "unit_active", lambda u: False)
    assert A.main(args + ["--unit", "live_v6-citest", "--cid-prefix", "v6t"]) == 0
    saved = json.loads(offline.store_path.read_text())
    assert DOGE in saved["pos"] and DOGE not in saved["unknown"] and saved["pos"][DOGE]["adopted"]
    assert list(offline.store_path.parent.glob("state.json.bak-adopt-*"))
    eng2, _ = make(offline, Clock(clk.ms + 60_000))              # restarted bot: journaled, no longer unknown
    eng2.tick()
    assert DOGE in eng2.st["pos"] and DOGE not in eng2.st["unknown"] and stops(offline, DOGE)


def test_adopt_tool_refuses_short_and_unknown_symbol(offline):
    import pytest
    from live_v6.tools import adopt_position as A
    offline.inner.open_position_raw(SOL, -1)
    _unknown_state(offline)
    with pytest.raises(SystemExit, match="SHORT"):
        A.main(["--state", str(offline.store_path), "--sym", SOL])
    with pytest.raises(SystemExit, match="not an unknown position"):
        A.main(["--state", str(offline.store_path), "--sym", XRP])
