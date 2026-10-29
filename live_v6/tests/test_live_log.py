"""TA live-log spec v1 (2026-10-29, /workspace/specs/live-log-spec-v1-2026-10-29.md): append-only JSONL per kind —
one line per closed trade (trades), per skipped signal (skips), per UTC day (daily, written at 00:00 UTC). Recording
only: quantities, stops, orders and sizing are unchanged, and a failing log write never blocks or delays trading.
Offline only (FakeExchange)."""
import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from live_v6 import strategy as S
from live_v6.events import Mark, OrderUpdate, StreamStatus, Trade
from live_v6.sizing import TAKER_FEE
from live_v6.tradelog import EventLog

from .conftest import unique_T
from .test_h7t import h7t_engine, seed, touch
from .test_sizing_minorder import _eng

DOGE, BTC = "DOGEUSDT", "BTCUSDT"
H4 = S.H4_MS
TRADE_FIELDS = ("trade_id", "coin", "side", "path", "signal_time", "signal_price", "entry_order_time", "entry_fill_time",
                "entry_fill_price", "entry_slip_bp", "qty", "notional", "leverage", "wallet_at_entry", "stop_price",
                "stop_confirmed_time", "stop_dist_frac", "planned_risk_pct", "actual_risk_pct", "open_risk_sum_after_entry",
                "same_side_open_count", "exit_time", "exit_price", "exit_reason", "exit_slip_bp", "fee_entry", "fee_exit",
                "funding_sum", "pnl_gross", "pnl_net", "R_net", "hold_minutes", "MFE_frac", "MFE_R", "MAE_frac", "MAE_R",
                "code_commit")
SKIP_FIELDS = ("time", "coin", "side", "signal_price", "reason", "detail", "open_positions", "open_risk_sum")
DAILY_FIELDS = ("date", "wallet", "equity", "open_positions", "open_risk_sum", "drawdown_from_peak", "distance_to_halt",
                "trades_today", "skips_today", "incidents")
OLD_TRADE_KEYS = {"sym", "cid", "reason", "qty", "entry_px", "exit_px", "stop_px", "opened_ms", "model_entry_open", "lev",
                  "wallet_at_entry", "risk_frac", "closed_ms", "gross", "fees", "funding", "net", "planned_R", "R", "source"}


def lines(tmp_path, kind):
    p = tmp_path / f"t_{kind}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def attach(eng, tmp_path):
    eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    return eng


def loss_usdt(eng, j):
    p = eng.cfg.sizing
    qty, fill, stop = D(j["qty"]), D(j["entry_px"]), D(j["stop_px"])
    return (fill - stop) * qty + qty * fill * (2 * TAKER_FEE + D(p.entry_slippage) + D(p.stop_slippage))


def D(x):
    return Decimal(str(x))


def alert_pct(eng):
    a = next(m for m in eng.tg.sent if "🟢 진입" in m)
    return D(a.rsplit("(", 1)[1].split("%")[0])


def stop_out(offline, eng, sym):
    """Exchange stop fires (FakeExchange), the user stream reports the fill, REST reconcile journals the close."""
    j = eng.st["pos"][sym]
    px = D(j["stop_px"]) - eng.rules[sym].tick_size
    offline.inner.set_price(sym, px)
    eng.on_event(OrderUpdate(sym, {"s": sym, "S": "SELL", "o": "MARKET", "ot": "STOP_MARKET", "x": "TRADE", "X": "FILLED",
                                   "i": "?", "c": f"{j['cid']}s1", "L": str(px), "ap": str(px), "T": int(time.time() * 1000)},
                             int(time.time() * 1000)))
    eng.tick()
    assert sym not in eng.st["pos"]
    return px


# ───────────── trades: normal (q0) path ─────────────
def test_trade_line_normal_path(offline, tmp_path):
    eng = attach(_eng(offline), tmp_path)
    T = unique_T()
    sig = Decimal("0.1499")
    assert eng.enter(DOGE, Decimal("0.0045"), T, model_id=T, signal_px=sig)
    j = dict(eng.st["pos"][DOGE])
    t0 = int(time.time() * 1000)
    for i, px in enumerate(("0.1510", "0.1520", "0.1490", "0.1500")):      # 1 s mark stream while holding
        eng.on_event(Mark(DOGE, Decimal(px), t0 + 1000 * i))
    xpx = stop_out(offline, eng, DOGE)
    (r,) = lines(tmp_path, "trades")
    assert all(k in r for k in TRADE_FIELDS), [k for k in TRADE_FIELDS if k not in r]
    fill, stop, qty, w = D(j["entry_px"]), D(j["stop_px"]), D(j["qty"]), D(j["wallet_at_entry"])
    loss = loss_usdt(eng, j)
    assert r["trade_id"] == j["cid"] and r["coin"] == DOGE and r["side"] == "long" and r["path"] == "normal"
    assert r["signal_time"] == T and D(r["signal_price"]) == sig and r["signal_time_kst"].endswith("+09:00")
    assert D(r["entry_slip_bp"]) == ((fill - sig) / sig * Decimal(10000)).quantize(Decimal("0.01"))
    assert D(r["entry_fill_price"]) == fill and D(r["qty"]) == qty and D(r["notional"]) == qty * fill
    assert D(r["stop_price"]) == stop and r["stop_confirmed_time"] and r["entry_order_time"] <= r["stop_confirmed_time"]
    assert D(r["stop_dist_frac"]) == ((fill - stop) / fill).quantize(Decimal("0.000001"))
    assert D(r["actual_risk_pct"]).quantize(Decimal("0.01")) == alert_pct(eng)           # same formula as the 🟢 alert
    assert D(r["actual_risk_pct"]) == (loss / w * 100).quantize(Decimal("0.0001"))
    assert r["planned_risk_pct"] == eng.cfg.sizing.risk_pct
    assert r["open_risk_sum_after_entry"] == pytest.approx(j["risk_frac"] * 100) and r["same_side_open_count"] == 0
    assert r["exit_reason"] == "exchange_close" and r["exit_reason_raw"] == "stop_loss"
    assert r["exit_order_type"] == "STOP_MARKET" and r["exit_order_ids"] == ["?"]
    assert D(r["exit_price"]) == xpx and r["exit_time"] >= r["entry_fill_time"]
    assert D(r["exit_slip_bp"]) == ((stop - xpx) / stop * Decimal(10000)).quantize(Decimal("0.01"))   # vs the stop
    t = eng.meta["trades"][-1]
    assert set(t) == OLD_TRADE_KEYS                                                      # stored record untouched
    assert D(r["pnl_net"]) == D(t["net"]) and D(r["pnl_gross"]) == D(t["gross"])
    assert D(r["fee_entry"]) + D(r["fee_exit"]) == D(t["fees"]) and D(r["fee_entry"]) == (qty * fill * TAKER_FEE)
    assert D(r["R_net"]) == (D(t["net"]) / loss).quantize(Decimal("0.0001"))
    assert r["mae_mfe_source"] == "mark" and r["mark_gaps"] == []
    assert D(r["MFE_frac"]) == ((Decimal("0.1520") - fill) / fill).quantize(Decimal("0.000001"))
    assert D(r["MAE_frac"]) == ((fill - Decimal("0.1490")) / fill).quantize(Decimal("0.000001"))
    assert D(r["MAE_R"]) == (D(r["MAE_frac"]) * fill * qty / loss).quantize(Decimal("0.0001"))
    assert r["code_commit"] == "c0ffee123456" and r["hold_minutes"] >= 0


# ───────────── trades: min-order (qty_floor) path ─────────────
def test_trade_line_min_order_path(offline, tmp_path):
    eng = attach(_eng(offline, wallet="117.46733957", prices={BTC: "84134.3"}, symbols=(BTC,), entry_order=(BTC,)), tmp_path)
    assert eng.enter(BTC, Decimal("1562.0"), unique_T(), signal_px=Decimal("84130.0"))
    j = dict(eng.st["pos"][BTC])
    assert j["qty"] == "0.001"
    stop_out(offline, eng, BTC)
    (r,) = lines(tmp_path, "trades")
    assert r["path"] == "qty_floor" and D(r["qty"]) == Decimal("0.001")
    assert D(r["actual_risk_pct"]).quantize(Decimal("0.01")) == alert_pct(eng)
    assert Decimal("1.3") < D(r["actual_risk_pct"]) < Decimal("1.6")
    assert D(r["R_net"]) == (D(r["pnl_net"]) / loss_usdt(eng, j)).quantize(Decimal("0.0001"))


# ───────────── skips ─────────────
def test_skip_line_same_reason_as_skip_log(offline, tmp_path):
    eng = attach(_eng(offline), tmp_path)
    offline.fx.inject("mark_price", "unavailable", times=20)
    assert not eng.enter(DOGE, Decimal("0.0045"), unique_T(), signal_px=Decimal("0.15"))
    (r,) = lines(tmp_path, "skips")
    last = eng.meta["skip_log"][-1]
    assert all(k in r for k in SKIP_FIELDS)
    assert r["reason"] == last[2] == "filter_read_failed" and r["coin"] == DOGE and r["side"] == "long"
    assert D(r["signal_price"]) == Decimal("0.15") and r["detail"].startswith(last[3])
    assert r["open_positions"] == 0 and r["open_risk_sum"] == 0 and r["time"] == last[0]
    assert len(last) == 4                                                                # skip_log format unchanged


def test_h7t_log_only_skips_missed_and_bar_not_in_model(offline, tmp_path):
    eng, strat = h7t_engine(offline)
    attach(eng, tmp_path)
    before = (list(eng.meta.get("skip_log", [])), dict(eng.meta.get("skips", {})))
    trig, _ = seed(eng, strat, watching=False)
    offline.fx.inject("klines", "unavailable", times=99)                 # cannot prove not touched → bar missed
    touch(eng, DOGE, trig)
    touch(eng, DOGE, trig)
    assert offline.amt(DOGE) == 0
    trig2, _ = seed(eng, strat)
    strat.state["models"][DOGE]["last_open"] -= H4                       # previous bar not stepped into the model yet
    touch(eng, DOGE, trig2)
    touch(eng, DOGE, trig2)
    assert offline.amt(DOGE) == 0
    got = [(r["coin"], r["reason"]) for r in lines(tmp_path, "skips")]
    assert got == [(DOGE, "missed"), (DOGE, "bar_not_in_model")], got   # once per bar, log file only
    assert (eng.meta.get("skip_log", []), eng.meta.get("skips", {})) == before   # skip_log / counts / alerts unchanged


# ───────────── a failing log write never blocks or delays trading ─────────────
def _broken(mode, tmp_path, monkeypatch):
    if mode == "unwritable_path":
        (tmp_path / "f").write_text("x")
        return EventLog(str(tmp_path / "f"), "t", commit="c")               # a FILE as the directory → OSError
    ev = EventLog(str(tmp_path), "t", commit="c")
    exc = OSError(28, "No space left on device") if mode == "disk_full" else RuntimeError("writer bug")
    monkeypatch.setattr(ev, "write", lambda *a, **k: (_ for _ in ()).throw(exc))
    return ev


def _scenario(offline, events, sleeps):
    eng = _eng(offline)
    eng.sleep = lambda s: sleeps.append(s)
    eng.events = events
    offline.fx.calls.clear()
    t0 = time.perf_counter()
    assert eng.enter(DOGE, Decimal("0.0045"), unique_T(), signal_px=Decimal("0.1499"))
    eng.on_event(Mark(DOGE, Decimal("0.151"), int(time.time() * 1000)))
    stop_out(offline, eng, DOGE)
    eng.block("x_test", "forced")                                        # one skip as well
    assert not eng.enter(DOGE, Decimal("0.0045"), unique_T())
    eng.unblock("x_test")
    dt = time.perf_counter() - t0
    return eng, [c[0] for c in offline.fx.calls], dt


@pytest.mark.parametrize("mode", ["unwritable_path", "disk_full", "writer_exception"])
def test_log_write_failure_never_blocks_or_delays_trading(offline, tmp_path, monkeypatch, caplog, mode):
    from .conftest import Backend
    from .fakes import FakeExchange
    ref = Backend("offline", FakeExchange(), tmp=tmp_path / "ref")
    (tmp_path / "ref").mkdir()
    s_ref, s_bad = [], []
    e_ref, calls_ref, dt_ref = _scenario(ref, None, s_ref)
    with caplog.at_level(logging.ERROR, logger="live_v6"):
        e_bad, calls_bad, dt_bad = _scenario(offline, _broken(mode, tmp_path, monkeypatch), s_bad)
    assert calls_bad == calls_ref and "stop" in calls_bad and "market" in calls_bad   # entry, stop, close all went out
    assert s_bad == s_ref                                                # no extra waits
    assert dt_bad < dt_ref + 0.5                                         # no delay beyond noise
    assert [t["reason"] for t in e_bad.meta["trades"]] == [t["reason"] for t in e_ref.meta["trades"]] == ["stop_loss"]
    assert e_bad.meta["skip_log"][-1][2] == e_ref.meta["skip_log"][-1][2] == "safety_block"
    assert e_bad.st["pos"] == e_ref.st["pos"] == {}
    assert "log write failed" in caplog.text                             # journald error only
    assert sum(v.get("log_write_fail", 0) for v in e_bad.meta["log_day"].values()) >= 2   # counted for the daily line


# ───────────── restart: MAE/MFE resume from the saved values, gap flagged ─────────────
def test_restart_resumes_mae_mfe_and_flags_gap(offline, tmp_path):
    eng = attach(_eng(offline), tmp_path)
    assert eng.enter(DOGE, Decimal("0.0045"), unique_T(), signal_px=Decimal("0.15"))
    fill = D(eng.st["pos"][DOGE]["entry_px"])
    t0 = int(time.time() * 1000)
    eng.on_event(Mark(DOGE, Decimal("0.1530"), t0))                      # MFE before the restart
    eng.on_event(Mark(DOGE, Decimal("0.1488"), t0 + 1000))               # MAE before the restart
    eng.save()                                                           # the regular 5 s save
    eng2 = attach(offline.engine(), tmp_path)                            # restart from the state file
    eng2.startup()
    assert DOGE in eng2.st["pos"]
    t1 = t0 + 10 * 60_000                                                # 10 min down
    eng2.on_event(Mark(DOGE, Decimal("0.1510"), t1))
    eng2.on_event(Mark(DOGE, Decimal("0.1495"), t1 + 1000))
    stop_out(offline, eng2, DOGE)
    (r,) = lines(tmp_path, "trades")
    assert D(r["MFE_frac"]) == ((Decimal("0.1530") - fill) / fill).quantize(Decimal("0.000001"))
    assert D(r["MAE_frac"]) == ((fill - Decimal("0.1488")) / fill).quantize(Decimal("0.000001"))
    assert r["mark_gaps"] == [[t0 + 1000, t1]]


def test_mark_stream_gap_flagged(offline, tmp_path):
    eng = attach(_eng(offline), tmp_path)
    assert eng.enter(DOGE, Decimal("0.0045"), unique_T())
    t0 = int(time.time() * 1000)
    eng.on_event(Mark(DOGE, Decimal("0.150"), t0))
    eng.on_event(StreamStatus("market", False, "test"))
    eng.on_event(StreamStatus("market", True, "test"))
    eng.on_event(Mark(DOGE, Decimal("0.150"), t0 + 120_000))
    eng.unblock("ws_stale")
    stop_out(offline, eng, DOGE)
    assert lines(tmp_path, "trades")[0]["mark_gaps"] == [[t0, t0 + 120_000]]


# ───────────── daily: one line at 00:00 UTC (📊 stays at KST midnight) ─────────────
def test_daily_line_at_utc_midnight(offline, tmp_path, monkeypatch):
    t = [datetime(2026, 10, 29, 23, 59, 50, tzinfo=timezone.utc).timestamp()]
    eng = attach(_eng(offline, clock=lambda: t[0]), tmp_path)
    eng.reports()
    eng.block("x_test", "forced")
    eng.enter(DOGE, Decimal("0.0045"), unique_T())                       # one skip today
    eng.unblock("x_test")
    eng.alert("test incident")                                           # one 🚨 today
    monkeypatch.setattr(eng.events, "write", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    eng.skip(DOGE, "late", "x")                                          # write fails → counted
    monkeypatch.undo()
    n_daily = sum(1 for m in eng.tg.sent if m.startswith("📊"))
    eng.reports()
    assert not lines(tmp_path, "daily")
    t[0] += 15                                                            # 00:00:05 UTC = 09:00:05 KST
    eng.reports()
    eng.reports()
    (r,) = lines(tmp_path, "daily")
    assert all(k in r for k in DAILY_FIELDS)
    assert r["date"] == "2026-10-29" and r["skips_today"] == 2 and r["incidents"] == 1 and r["log_write_fail"] == 1
    assert r["trades_today"] == 0 and r["open_positions"] == [] and r["open_risk_sum"] == 0
    assert D(r["wallet"]) == D(eng.meta["wallet"]) and D(r["equity"]) == D(eng.meta["equity"])
    hit, eq, thr = eng.drawdown_breached()
    assert not hit and D(r["distance_to_halt"]) == ((eq - thr) / eq * 100).quantize(Decimal("0.01"))
    assert D(r["drawdown_from_peak"]) == 0
    assert sum(1 for m in eng.tg.sent if m.startswith("📊")) == n_daily  # KST 📊 not moved
