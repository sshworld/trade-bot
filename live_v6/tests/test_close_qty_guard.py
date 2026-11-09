"""Trade-journal close aggregation (SOL v6SOL1793588103 / v6SOL1793633163, 2026-11-02/03).

The exchange had already closed the remainder after TP1, but the journal committed a finished trade whose exit
legs were only the TP1 fill. Two mechanics in record_close do that:

* A remainder that fills as several partials of one order is merged by order id. Once userTrades has any slice,
  every other slice held on the user stream is discarded (1102: order 254785178715, fills 3623091255-3623091258).
* The position is popped and the trade appended even when summed exit qty != opened qty. A fill that is not in
  that poll — userTrades has not indexed it yet, or the user-stream event is still queued / was missed across a
  disconnect or restart (the stream is not replayed and stream_fills were not durable) — never attaches
  (1103: fill 3623696210). Daily-loss halt is not this path: record_close checks halts with daily=False, and a
  halt flatten is recorded as daily_loss_halt.

Offline only. Telegram is the existing alert() path with the HTTP sender mocked; nothing is sent.
"""
import json
from decimal import Decimal

import pytest

from live_v6.events import OrderUpdate
from live_v6.notify import _http_post
from live_v6.tradelog import EventLog

from .test_chandelier_e import DOGE, _trail_setup, e_engine
from .test_ptp_short import _fill, _journal
from .test_qrmtf import legacy_engine, open_pos

SOL = "SOLUSDT"
HOLD = "청산 기록 보류"


def D(x):
    return Decimal(str(x))


def _block_telegram(monkeypatch):
    def fail_http(*_a, **_k):
        raise AssertionError("telegram HTTP must not be called")

    monkeypatch.setattr("live_v6.notify._http_post", fail_http)
    assert _http_post  # the mock replaces the real sender the alert path would use


def _hold_alerts(eng):
    return [m for m in eng.tg.sent if HOLD in m]


def _exit_qty(rec):
    return sum((D(x["qty"]) for x in rec["exit_legs"]), Decimal(0))


def _ou(sym, cid, oid, side, px, qty, fee, rp, t, tid, ot="STOP_MARKET"):
    return OrderUpdate(sym, {"x": "TRADE", "S": side, "i": oid, "c": cid, "o": "MARKET", "ot": ot, "X": "FILLED",
                             "T": t, "l": str(qty), "L": str(px), "n": str(fee), "rp": str(rp), "t": tid}, t)


def _split(fill, n):
    """n partials of one order that sum to the fill (qty, fee, realized pnl), each with its own trade id."""
    q = D(fill["qty"])
    n = min(int(n), int(q)) if q == q.to_integral_value() else int(n)
    assert n >= 2 and q > 0
    if q == q.to_integral_value():
        base = q // n
        qtys = [base] * (n - 1) + [q - base * (n - 1)]
    else:
        step = (q / n).quantize(Decimal("0.00000001"))
        qtys = [step] * (n - 1) + [q - step * (n - 1)]
    assert all(x > 0 for x in qtys) and sum(qtys) == q
    fee, rp = D(fill["commission"]), D(fill["realized_pnl"])
    parts, acc_f, acc_r = [], Decimal(0), Decimal(0)
    for i, qty in enumerate(qtys):
        last = i == len(qtys) - 1
        f = fee - acc_f if last else (fee * qty / q).quantize(Decimal("0.00000001"))
        r = rp - acc_r if last else (rp * qty / q).quantize(Decimal("0.00000001"))
        acc_f, acc_r = acc_f + f, acc_r + r
        parts.append({**fill, "qty": qty, "commission": f, "realized_pnl": r,
                      "trade_id": f"{fill['order_id']}-{i + 1}", "time": int(fill["time"]) + i})
    return parts


def _shape_trades(b, drop_oid, partials, mode):
    """userTrades injector. mode['show'] is 'none' | 'first' | 'all' for `partials` (the raw fill `drop_oid` is removed)."""
    def trades(fn, sym, start):
        rows = [r for r in fn(sym, start) if str(r["order_id"]) != str(drop_oid)]
        show = mode["show"]
        if show == "first":
            rows.append(partials[0])
        elif show == "all":
            rows.extend(partials)
        return rows

    b.fx.inject("user_trades", trades, times=999)


def _note(eng, sym, j, parts, cid, ot):
    side = parts[0]["side"]
    for p in parts:
        eng.on_event(_ou(sym, cid, p["order_id"], side, p["price"], p["qty"], p["commission"], p["realized_pnl"],
                         p["time"], p["trade_id"], ot))


def _arm_legacy_short(b):
    eng = legacy_engine(b)
    open_pos(b, eng, -1)
    from .test_qrmtf import _tp1_then_be
    j = _tp1_then_be(b, eng, -1)
    known = {f["order_id"] for f in b.inner.fills if f["symbol"] == DOGE}
    b.inner.set_price(DOGE, D(j["stop_px"]))          # BE stop fills the remainder (one exchange fill)
    assert b.amt(DOGE) == 0 and DOGE in eng.st["pos"]
    (raw,) = [f for f in b.inner.fills if f["symbol"] == DOGE and f["order_id"] not in known]
    return eng, j, raw


# ───────────── old exit scheme (before 2026-11-04): TP1 then BE stop / TP2 ─────────────
def test_sol_1102_partial_fills_of_one_order_are_unioned_by_trade_id(offline, tmp_path, monkeypatch):
    # short 3.33 @94.87, TP1 1.66 @93.84, BE stop 1.67 @94.85 in four fills of order 254785178715.
    # userTrades has indexed only the first slice; the user stream has the other three. Main drops those three
    # because the order id is already present, and still marks the trade closed.
    _block_telegram(monkeypatch)
    t0, cid = 1793588104281, "v6SOL1793588103"
    oid = "254785178715"
    j = _journal(cid, -1, "1.67", "94.8700", "94.77", "95.91", "1.66", t0, entry_qty="3.33",
                 exit_orders=[{"id": "254757526603", "client_id": cid + "t1"}, {"id": oid, "client_id": cid + "s0"}])
    slices = [("3623091255", "0.07", "0.00331975", "0.0014"),
              ("3623091256", "0.07", "0.00331975", "0.0014"),
              ("3623091257", "0.07", "0.00331975", "0.0014"),
              ("3623091258", "1.46", "0.0692405", "0.02919999")]
    rest = [_fill(oid, "BUY", "94.85", q, f, rp, 1793626700082) | {"trade_id": tid} for tid, q, f, rp in slices[:1]]
    eng = legacy_engine(offline)
    eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    eng.st["pos"][SOL] = j
    for tid, q, f, rp in slices[1:]:
        eng.on_event(_ou(SOL, cid + "s0", oid, "BUY", "94.85", q, f, rp, 1793626700082, tid))
    fills = [_fill("E1", "SELL", "94.87", "3.33", "0.15795855", "0", t0),
             _fill("254757526603", "BUY", "93.84", "1.66", "0.0778872", "1.7098", 1793618257729)] + rest
    offline.fx.inject("user_trades", lambda fn, *a: fills, times=9)
    offline.fx.inject("income", lambda fn, *a: [{"amount": D("0.0313823"), "time": t0, "symbol": SOL}], times=9)
    eng.record_close(SOL, "stop_loss")
    assert SOL not in eng.st["pos"] and len(eng.meta["trades"]) == 1
    rec = eng.meta["trades"][-1]
    assert _exit_qty(rec) == D("3.33") and not rec.get("fills_incomplete")
    assert [(x["price"], x["qty"]) for x in rec["exit_legs"]] == [("93.84", "1.66"), ("94.85", "1.67")]
    assert D(rec["net"]) == D("1.45953679") and rec["R"] == "0.421" and rec["reason"] == "be_stop"
    assert _hold_alerts(eng) == []


def test_sol_1103_missing_remainder_stays_open_then_completes_after_restart(offline, tmp_path, monkeypatch):
    # short 3.39 @94.29, TP1 1.69 @93.21 already indexed; TP2 1.70 @92.14 (fill 3623696210) is not in userTrades
    # and the user stream has not delivered it (disconnect / event still queued). Must NOT commit the TP1-only row.
    _block_telegram(monkeypatch)
    t0, cid = 1793633163679, "v6SOL1793633163"
    j = _journal(cid, -1, "1.70", "94.2900", "94.19", "95.37", "1.69", t0, entry_qty="3.39")
    tp1 = [_fill("E1", "SELL", "94.29", "3.39", "0.15982155", "0", t0),
           _fill("254824457044", "BUY", "93.21", "1.69", "0.07876245", "1.8252", 1793635101103) | {"trade_id": "3623435047"}]
    eng = legacy_engine(offline)
    eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    eng.st["pos"][SOL] = j
    eng.save()

    def trades(fn, *_a):
        return tp1

    def income(fn, sym, typ, start):
        if typ == "FUNDING_FEE":
            return [{"type": "FUNDING_FEE", "amount": D("0.01589558"), "time": t0, "symbol": SOL}]
        return fn(sym, typ, start)

    offline.fx.inject("user_trades", trades, times=999)
    offline.fx.inject("income", income, times=99)
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    assert len(_hold_alerts(eng)) == 1 and "3.39" in _hold_alerts(eng)[0] and "1.69" in _hold_alerts(eng)[0]
    assert not (tmp_path / "t_trades.jsonl").exists()
    saved = json.loads((offline.store_path).read_text())
    assert saved["pos"][SOL]["cid"] == cid and "trades" not in saved["meta"]

    eng2 = legacy_engine(offline)                          # restart: userTrades still has no remainder
    assert SOL in eng2.st["pos"] and not eng2.meta.get("trades") and _hold_alerts(eng2) == []
    eng2.on_event(_ou(SOL, cid + "t2", "254851315186", "BUY", "92.14", "1.70", "0.078319", "3.655",
                      1793641526295, "3623696210", "TAKE_PROFIT_MARKET"))
    eng2.record_close(SOL, eng2.st["pos"][SOL].get("close_reason") or eng2.st["pos"][SOL].get("exit_fill") or "stop_loss")
    assert SOL not in eng2.st["pos"] and len(eng2.meta["trades"]) == 1
    rec = eng2.meta["trades"][-1]
    assert _exit_qty(rec) == D("3.39") and not rec.get("fills_incomplete")
    assert [(x["price"], x["qty"]) for x in rec["exit_legs"]] == [("93.21", "1.69"), ("92.14", "1.7")]
    assert D(rec["net"]) == D("5.17919258") and rec["reason"] == "take_profit"
    assert rec["reason"] != "daily_loss_halt"


def test_legacy_be_stop_multifill_remainder_records_the_whole_qty(offline, monkeypatch):
    # Pre-E path: TP1, then the BE stop closes the rest. userTrades has one slice; the stream has the other slices.
    _block_telegram(monkeypatch)
    eng, j, raw = _arm_legacy_short(offline)
    parts = _split(raw, 4)
    _note(eng, DOGE, j, parts[1:], j["stop_cid"], "STOP_MARKET")
    mode = {"show": "first"}
    _shape_trades(offline, raw["order_id"], parts, mode)
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and len(eng.meta["trades"]) == 1 and _hold_alerts(eng) == []
    rec = eng.meta["trades"][-1]
    assert rec["reason"] == "be_stop" and not rec.get("fills_incomplete")
    assert _exit_qty(rec) == D(rec["entry_qty"])
    assert D(next(x["qty"] for x in rec["exit_legs"] if x["order_id"] == str(raw["order_id"]))) == D(raw["qty"])


# ───────────── scheme E (2026-11-04): trail stop after TP1, and the 24h time exit ─────────────
def test_scheme_e_trail_stop_after_tp1_unions_multifill_remainder(offline, monkeypatch):
    _block_telegram(monkeypatch)
    clk, eng, j = _trail_setup(offline, 1)
    e = D(j["entry_px"])
    from .test_chandelier_e import add_m1, minute
    t = minute(clk, j, 1)
    add_m1(offline, t, float(e + D("0.0010")), float(e))
    offline.inner.set_price(DOGE, e + D("0.0008"))
    eng.reconcile()
    assert eng.st["pos"][DOGE].get("trailed")
    j = eng.st["pos"][DOGE]
    offline.inner.set_price(DOGE, D(j["tp"]["tp1"]))
    eng.reconcile()
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["tp1_done"] and j.get("trailed")
    known = {f["order_id"] for f in offline.inner.fills if f["symbol"] == DOGE}
    offline.inner.set_price(DOGE, D(j["stop_px"]))
    assert offline.amt(DOGE) == 0 and DOGE in eng.st["pos"]
    (raw,) = [f for f in offline.inner.fills if f["symbol"] == DOGE and f["order_id"] not in known]
    parts = _split(raw, 4)
    _note(eng, DOGE, j, parts[1:], j["stop_cid"], "STOP_MARKET")
    _shape_trades(offline, raw["order_id"], parts, {"show": "first"})
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and _hold_alerts(eng) == []
    rec = eng.meta["trades"][-1]
    assert rec["reason"] == "trail_stop" and not rec.get("fills_incomplete")
    assert _exit_qty(rec) == D(rec["entry_qty"])
    assert D(next(x["qty"] for x in rec["exit_legs"] if x["order_id"] == str(raw["order_id"]))) == D(raw["qty"])


def test_scheme_e_time_exit_after_tp1_holds_until_multifill_remainder_arrives(offline, monkeypatch):
    # 24h market exit. The closing order's fills are not indexed yet (and the stream event is not applied until
    # the reconcile that called close() returns). A later slice on the stream must complete the same trade.
    _block_telegram(monkeypatch)
    clk, eng, j = _trail_setup(offline, -1)
    offline.inner.set_price(DOGE, D(j["tp"]["tp1"]))
    eng.reconcile()
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["tp1_done"] and D(j["qty"]) < D(j["entry_qty"])
    known = {f["order_id"] for f in offline.inner.fills if f["symbol"] == DOGE}
    mode = {"show": "none"}
    # the market fill does not exist until close(); the injector drops whatever order id is not already known
    def trades(fn, sym, start):
        rows = fn(sym, start)
        if mode["show"] == "all":
            return rows
        kept = [r for r in rows if r["order_id"] in known]
        if mode["show"] == "first" and mode.get("parts"):
            kept.append(mode["parts"][0])
        return kept
    offline.fx.inject("user_trades", trades, times=999)
    eng.st["pos"][DOGE]["opened_ms"] = eng.now_ms() - 24 * 3600_000 - 1000
    clk.off += 24 * 3600 + 5
    eng.reconcile()                                         # time exit runs, userTrades has no closing fill yet
    assert offline.amt(DOGE) == 0 and DOGE in eng.st["pos"] and not eng.meta.get("trades")
    assert len(_hold_alerts(eng)) == 1
    (raw,) = [f for f in offline.inner.fills if f["symbol"] == DOGE and f["order_id"] not in known]
    parts = _split(raw, 3)
    mode["show"] = "first"
    mode["parts"] = parts
    j = eng.st["pos"][DOGE]
    _note(eng, DOGE, j, parts[1:], f"{j['cid']}x0", "MARKET")
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and len(eng.meta["trades"]) == 1
    rec = eng.meta["trades"][-1]
    assert rec["reason"] == "time_exit" and rec["reason"] != "daily_loss_halt" and not rec.get("fills_incomplete")
    assert _exit_qty(rec) == D(rec["entry_qty"])
    assert D(next(x["qty"] for x in rec["exit_legs"] if x["order_id"] == str(raw["order_id"]))) == D(raw["qty"])
    assert len(_hold_alerts(eng)) == 1                      # the held close warned once; the completion is the exit notice


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_restart_keeps_stream_partials_already_noted(offline, monkeypatch, scheme):
    # Fills noted on the user stream, then the process restarts before reconcile. userTrades still lacks them
    # (not replayed on reconnect). The noted partials have to survive on the journal or the row is TP1-only.
    _block_telegram(monkeypatch)
    if scheme == "legacy":
        eng, j, raw = _arm_legacy_short(offline)
        cid = j["stop_cid"]
        reason = "be_stop"
    else:
        clk, eng, j = _trail_setup(offline, 1)
        e = D(j["entry_px"])
        from .test_chandelier_e import add_m1, minute
        t = minute(clk, j, 1)
        add_m1(offline, t, float(e + D("0.0010")), float(e))
        offline.inner.set_price(DOGE, e + D("0.0008"))
        eng.reconcile()
        j = eng.st["pos"][DOGE]
        offline.inner.set_price(DOGE, D(j["tp"]["tp1"]))
        eng.reconcile()
        eng.reconcile()
        j = eng.st["pos"][DOGE]
        known = {f["order_id"] for f in offline.inner.fills if f["symbol"] == DOGE}
        offline.inner.set_price(DOGE, D(j["stop_px"]))
        assert offline.amt(DOGE) == 0 and DOGE in eng.st["pos"]
        (raw,) = [f for f in offline.inner.fills if f["symbol"] == DOGE and f["order_id"] not in known]
        cid = j["stop_cid"]
        reason = "trail_stop"
    parts = _split(raw, 4)
    _note(eng, DOGE, j, parts, cid, "STOP_MARKET")          # all slices on the stream; REST has none of them yet
    _shape_trades(offline, raw["order_id"], parts, {"show": "none"})
    maker = legacy_engine if scheme == "legacy" else (lambda b: e_engine(b, clk))
    eng2 = maker(offline)                                   # restart
    assert DOGE not in eng2.st["pos"] and len(eng2.meta.get("trades") or []) == 1
    rec = eng2.meta["trades"][-1]
    assert rec["reason"] == reason and not rec.get("fills_incomplete")
    assert _exit_qty(rec) == D(rec["entry_qty"])
    assert D(next(x["qty"] for x in rec["exit_legs"] if x["order_id"] == str(raw["order_id"]))) == D(raw["qty"])
