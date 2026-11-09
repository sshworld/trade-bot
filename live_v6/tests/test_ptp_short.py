# ptp-short (TA-approved 2026-11-01): entry gate order max_positions -> risk caps -> margin sizing (quiet log-only
# skips for the first two, 🚨 only for a real margin shortfall), and trade records keyed on the ENTRY qty and the
# INITIAL stop (R = net / (entry_qty x |entry - initial stop|)), with every exit leg recorded. Offline only.
import json
from decimal import Decimal

from live_v6.runner import live_settings
from live_v6.sizing import TAKER_FEE
from live_v6.tradelog import EventLog

from .conftest import unique_T
from .test_faults import alerts
from .test_qrmtf import exit_engine

DOGE, SOL, XRP, BTC = "DOGEUSDT", "SOLUSDT", "XRPUSDT", "BTCUSDT"


def D(x):
    return Decimal(str(x))


def _risk_pct(qty, e, stop0, w):
    # same loss model as the 🟢 entry alert (stop distance + round-trip fees + slippages), on the ENTRY qty
    p = live_settings("qrmtf").sizing
    q, e = D(qty), D(e)
    loss = q * abs(e - D(stop0)) + q * e * (2 * TAKER_FEE + D(p.entry_slippage) + D(p.stop_slippage))
    return (loss / D(w) * 100).quantize(D("0.0001"))


def _poor(fn):
    return dict(fn(), available=Decimal("0.5"))


def _gate_engine(b, tmp_path):
    eng = exit_engine(b)
    eng.strategy.log_path = tmp_path / "qrmtf_signals.jsonl"
    for s, sd in ((SOL, 1), (XRP, -1)):                 # one long + one short: the same-side cap (2) never fires here
        px = D(b.inner.price[s])
        assert eng.enter(s, px * Decimal("0.008"), unique_T(), side=sd), eng.meta.get("skip_log", [])[-1:]
    T = unique_T()
    eng.strategy.records.append({"T": T, "sym": DOGE, "kind": "entry", "side": 1, "total": 70.0, "big_n": 75.0,
                                 "mid": 0.5, "fast": 0.4, "tf": {"1d": {"contrib": 18.0}, "4h": {"contrib": 14.0},
                                                                 "1m": {"contrib": 6.0}}})
    return eng, T


def _signal_log(tmp_path):
    p = tmp_path / "qrmtf_signals.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _try_doge(b, eng, T):
    b.fx.inject("account", _poor, times=99)
    n_tg, n_calls = len(eng.tg.sent), len(b.fx.calls)
    ok = eng.enter(DOGE, D(b.inner.price[DOGE]) * Decimal("0.008"), T, model_id=T)
    return ok, eng.tg.sent[n_tg:], [c[0] for c in b.fx.calls[n_calls:]]


def test_three_open_max_positions_no_alert_skip_logged_with_scores(offline, tmp_path):
    eng, T = _gate_engine(offline, tmp_path)

    def third(fn, syms):
        p = dict(fn(syms))
        p[BTC] = dict(p[SOL], amt=Decimal("-0.003"))
        return p
    offline.fx.inject("positions", third, times=99)
    ok, sent, calls = _try_doge(offline, eng, T)
    assert not ok and eng.meta["skip_log"][-1][2] == "max_positions"
    assert sent == [] and not alerts(eng)                       # no Telegram at all
    assert "account" not in calls and "exchange_info" not in calls   # checked BEFORE margin sizing
    r = _signal_log(tmp_path)[-1]
    assert r["kind"] == "skipped" and r["sym"] == DOGE and r["side"] == 1 and r["reason"] == "max_positions"
    assert r["tf"]["1d"]["contrib"] == 18.0 and r["big_n"] == 75.0 and r["skip_ms"] and r["skip_kst"].endswith("+09:00")


def test_two_open_margin_short_sends_alert(offline, tmp_path):
    eng, T = _gate_engine(offline, tmp_path)
    ok, sent, _ = _try_doge(offline, eng, T)
    assert not ok and eng.meta["skip_log"][-1][2] == "margin"
    assert any(m.startswith("🚨") and "증거금 부족" in m for m in sent)
    assert not any(r.get("kind") == "skipped" for r in _signal_log(tmp_path))


def test_risk_cap_skip_before_margin_no_alert_logged(offline, tmp_path):
    eng, T = _gate_engine(offline, tmp_path)
    eng.st["pos"][SOL]["risk_frac"] = 0.10                      # 10% + XRP + new > 12% (margin also short)
    ok, sent, _ = _try_doge(offline, eng, T)
    assert not ok and eng.meta["skip_log"][-1][2] == "risk_cap_portfolio"
    assert sent == [] and not alerts(eng)
    r = _signal_log(tmp_path)[-1]
    assert r["kind"] == "skipped" and r["reason"] == "risk_cap_portfolio" and r["sym"] == DOGE and "tf" in r


# ───────────── trade record ─────────────
def _fill(oid, side, px, qty, fee, rpnl, t, trade_id=None):
    return {"symbol": "", "order_id": oid, "side": side, "price": D(px), "qty": D(qty), "commission": D(fee),
            "realized_pnl": D(rpnl), "time": t, "trade_id": f"{oid}@{t}" if trade_id is None else trade_id}


def _close(b, tmp_path, sym, j, fills, funding, reason):
    eng = exit_engine(b)
    eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    b.fx.inject("user_trades", lambda fn, *a: fills, times=9)
    b.fx.inject("income", lambda fn, *a: [{"amount": D(funding), "time": j["opened_ms"], "symbol": sym}], times=9)
    have = {str(o.get("id")) for o in j.get("exit_orders") or []}
    eid = str(j.get("entry_order_id") or "")
    extra = [{"id": str(f["order_id"]), "client_id": ""}
             for f in fills if str(f["order_id"]) not in have and str(f["order_id"]) != eid]
    if extra:
        j["exit_orders"] = list(j.get("exit_orders") or []) + extra
    eng.st["pos"][sym] = j
    n = len(eng.tg.sent)
    eng.record_close(sym, reason)
    (line,) = [json.loads(x) for x in (tmp_path / "t_trades.jsonl").read_text().splitlines()]
    return eng.meta["trades"][-1], line, eng.tg.sent[n:]


def _journal(cid, side, qty, e, stop, stop0, q1, opened, **kw):
    return dict({"cid": cid, "side": side, "qty": qty, "entry_px": e, "stop_px": stop, "stop_px_entry": stop0,
                 "stop_dist": "1", "risk_frac": 0.03, "lev": 10, "mmr": 0.004, "opened_ms": opened,
                 "entry_order_id": "E1", "wallet_at_entry": "116.97033846", "tp": {"tp1": "1", "q1": q1, "tp2": "1",
                                                                                  "q2": "1"},
                 "tp1_done": True, "be_done": True, "path": "q0", "risk_pct_used": 4.0}, **kw)


def test_btc_short_tp1_then_time_exit_R_from_entry_qty(offline, tmp_path):
    # live 2026-10-30 15:26 KST: short 0.003 @78521.2, stop 79651.8, TP1 0.001 @77390.6, rest 0.002 @77260.9 (24 h)
    t0 = 1793341564002
    j = _journal("v6BTC1793341563", -1, "0.002", "78521.20", "78442.6", "79651.8", "0.001", t0,
                 risk_usdt="2.2612")                            # journal already shrunk to the remainder (pre-fix)
    fills = [_fill("E1", "SELL", "78521.2", "0.003", "0.1177818", "0", t0),
             _fill("T1", "BUY", "77390.6", "0.001", "0.0386953", "1.1306", t0 + 3_600_000),
             _fill("X1", "BUY", "77260.9", "0.002", "0.0772609", "2.5206", t0 + 86_400_000)]
    rec, line, sent = _close(offline, tmp_path, BTC, j, fills, "0.0410752", "time_exit")
    assert D(rec["net"]) == D("3.4585372")
    assert rec["entry_qty"] == "0.003" and rec["remaining_qty"] == "0.002" and rec["tp1_qty"] == "0.001"
    assert rec["tp1_frac_actual"] == "0.3333"
    assert rec["init_stop_px"] == "79651.8"
    assert rec["R"] == "1.020"                                  # 3.4585 / (0.003 x 1130.6)
    assert [(x["price"], x["qty"]) for x in rec["exit_legs"]] == [("77390.6", "0.001"), ("77260.9", "0.002")]
    assert abs(D(rec["exit_px_avg"]) - D("77304.1333")) < D("0.001")
    assert D(rec["actual_risk_pct"]) == _risk_pct("0.003", "78521.2", "79651.8", "116.97033846") == D(line["actual_risk_pct"])
    assert "1.020R" in sent[-1] and "수량 0.003" in sent[-1]
    assert D(line["R_net"]).quantize(D("0.001")) == D(rec["R"]) and line["qty"] == "0.003"
    assert line["exit_legs"] == rec["exit_legs"] and line["tp1_qty"] == "0.001"


def test_xrp_alert_R_equals_record_R(offline, tmp_path):
    # live 2026-10-30 16:12 KST: short 171.6 @1.2614, stop 1.2886, TP1 85.8 @1.2342, BE stop 85.8 @1.2597; the alert
    # and record said 0.489R but the trades jsonl said R_net 0.9065 (remaining qty 85.8) -> one R everywhere
    t0 = 1793344324450
    j = _journal("v6XRP1793344323", -1, "85.8", "1.2614", "1.2601", "1.2886", "85.8", t0, risk_usdt="4.66752",
                 wallet_at_entry="116.75172996")
    fills = [_fill("E1", "SELL", "1.2614", "171.6", "0.10822812", "0", t0),
             _fill("T1", "BUY", "1.2342", "85.8", "0.05294718", "2.33376", t0 + 3_600_000),
             _fill("S1", "BUY", "1.2597", "85.8", "0.05404113", "0.14586", t0 + 29_000_000)]
    rec, line, sent = _close(offline, tmp_path, XRP, j, fills, "0.01790688", "stop_loss")
    assert D(rec["net"]) == D("2.28231045")
    assert rec["R"] == "0.489" and rec["entry_qty"] == "171.6" and rec["tp1_frac_actual"] == "0.5000"
    assert D(line["R_net"]).quantize(D("0.001")) == D(rec["R"])          # was 0.9065
    assert "0.489R" in sent[-1]
    assert D(line["qty"]) == D("171.6")
    assert D(line["actual_risk_pct"]) == D(rec["actual_risk_pct"]) == _risk_pct("171.6", "1.2614", "1.2886", "116.75172996")


def test_new_journal_keeps_entry_qty_after_tp1(offline):
    eng = exit_engine(offline)
    px = D(offline.inner.price[DOGE])
    assert eng.enter(DOGE, px * Decimal("0.008"), unique_T())
    j = eng.st["pos"][DOGE]
    q0 = j["qty"]
    assert j["entry_qty"] == q0
    offline.inner.set_price(DOGE, D(j["tp"]["tp1"]))
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["tp1_done"] and j["entry_qty"] == q0 and D(j["qty"]) < D(q0)
