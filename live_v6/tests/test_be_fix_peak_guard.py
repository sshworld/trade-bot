# TA 2026-11-03: (1) BE stop after TP1 = entry +/- 0.15 % (tick-rounded away from entry), (2) trade-close records /
# alerts carry the WHOLE trade (a closing leg userTrades has not returned yet comes from the stream fill; the exit
# reason comes from the order that closed it, not a "stop_loss" default) with net + R first, then each leg,
# (3) peak-drawdown entry guard: equity (incl. uPnL) < 80 % of the persisted peak -> new entries blocked, one alert,
# open orders untouched, survives restarts, cleared only by the team with tools/clear_peak_halt.py (not `resume`). (4) daily reconciliation tool. Offline only.
import json
from decimal import Decimal

from live_v6.events import OrderUpdate
from live_v6.runner import live_settings
from live_v6.tradelog import EventLog

from .conftest import unique_T
from .test_qrmtf import exit_engine, open_pos
from .test_ptp_short import _fill, _journal

SOL, DOGE = "SOLUSDT", "DOGEUSDT"


def D(x):
    return Decimal(str(x))


def test_live_be_offset_is_015pct():
    assert live_settings("qrmtf").be_offset == 0.0015


def _be_after_tp1(b, side):
    eng = exit_engine(b)
    j = open_pos(b, eng, side=side)
    e = D(j["entry_px"])
    b.inner.set_price(DOGE, D(j["tp"]["tp1"]))
    eng.reconcile()
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    return eng, j, e


def test_be_stop_short_at_entry_minus_015pct_rounded_down(offline):
    eng, j, e = _be_after_tp1(offline, -1)
    assert j["tp1_done"] and j["be_done"]
    tgt = eng.rules[DOGE].price(e * (1 - D("0.0015")), "down")
    assert D(j["stop_px"]) == tgt and (e - tgt) / e >= D("0.0015")


def test_be_stop_long_at_entry_plus_015pct_rounded_up(offline):
    eng, j, e = _be_after_tp1(offline, 1)
    assert j["tp1_done"] and j["be_done"]
    tgt = eng.rules[DOGE].price(e * (1 + D("0.0015")), "up")
    assert D(j["stop_px"]) == tgt and (tgt - e) / e >= D("0.0015")


def _ou(sym, cid, oid, side, px, qty, fee, rp, t, ot):
    return OrderUpdate(sym, {"x": "TRADE", "S": side, "i": oid, "c": cid, "o": "MARKET", "ot": ot, "X": "FILLED",
                             "T": t, "l": qty, "L": px, "n": fee, "rp": rp, "t": t}, t)


def _close(b, tmp_path, sym, j, fills, funding, stream=(), reason="stop_loss"):
    eng = exit_engine(b)
    eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    b.fx.inject("user_trades", lambda fn, *a: fills, times=99)
    b.fx.inject("income", lambda fn, *a: [{"amount": D(funding), "time": j["opened_ms"], "symbol": sym}], times=9)
    eng.st["pos"][sym] = j
    for ev in stream:
        eng._note_exit_order(ev)
    n = len(eng.tg.sent)
    eng.record_close(sym, reason)
    (line,) = [json.loads(x) for x in (tmp_path / "t_trades.jsonl").read_text().splitlines()]
    return eng.meta["trades"][-1], line, eng.tg.sent[n:]


def test_sol_1103_tp2_leg_missing_from_user_trades_taken_from_stream(offline, tmp_path):
    # live 2026-11-03 00:26 KST: short 3.39 @94.29, TP1 1.69 @93.21, TP2 1.70 @92.14; userTrades had only the TP1 leg at
    # the close -> recorded +1.6025 "stop_loss" (alert said 손절); actual whole trade +5.1792, closed by TP2
    t0, cid = 1793633163679, "v6SOL1793633163"
    j = _journal(cid, -1, "1.70", "94.2900", "94.19", "95.37", "1.69", t0, entry_qty="3.39")
    fills = [_fill("E1", "SELL", "94.29", "3.39", "0.15982155", "0", t0),
             _fill("254824457044", "BUY", "93.21", "1.69", "0.07876245", "1.8252", 1793635101103)]
    stream = [_ou(SOL, cid + "t1", 254824457044, "BUY", "93.21", "1.69", "0.07876245", "1.8252", 1793635101103,
                  "TAKE_PROFIT_MARKET"),
              _ou(SOL, cid + "t2", 254851315186, "BUY", "92.14", "1.70", "0.078319", "3.655", 1793641526295,
                  "TAKE_PROFIT_MARKET")]
    rec, line, sent = _close(offline, tmp_path, SOL, j, fills, "0.01589558", stream)
    assert D(rec["net"]) == D("5.17919258")
    assert rec["reason"] == "take_profit" and line["exit_reason_raw"] == "take_profit"
    assert [(x["price"], x["qty"]) for x in rec["exit_legs"]] == [("93.21", "1.69"), ("92.14", "1.7")]
    assert rec["R"] == "1.415" and not rec.get("fills_incomplete")
    msg = sent[-1].splitlines()
    assert "익절" in msg[0] and "전체 순손익 +5.1792 USDT" in msg[1] and "1.415R" in msg[1]
    assert any(m.startswith("• TP1 1.69@93.21") for m in msg[2:]) and any(m.startswith("• TP2 1.7@92.14") for m in msg[2:])


def test_sol_1102_be_leg_reason_be_stop_and_whole_trade_first(offline, tmp_path):
    # live 2026-11-02 11:55 KST: short 3.33 @94.87, TP1 1.66 @93.84, BE stop 94.77 filled 1.67 @94.85 (4 fills)
    t0, cid = 1793588104281, "v6SOL1793588103"
    j = _journal(cid, -1, "1.67", "94.8700", "94.77", "95.91", "1.66", t0, entry_qty="3.33",
                 exit_orders=[{"id": "254757526603", "client_id": cid + "t1"}, {"id": "254785178715", "client_id": cid + "s0"}])
    fills = [_fill("E1", "SELL", "94.87", "3.33", "0.15795855", "0", t0),
             _fill("254757526603", "BUY", "93.84", "1.66", "0.0778872", "1.7098", 1793618257729)]
    fills += [_fill("254785178715", "BUY", "94.85", q, f, rp, 1793626700082)
              for q, f, rp in (("0.07", "0.00331975", "0.0014"),) * 3 + (("1.46", "0.0692405", "0.02919999"),)]
    rec, line, sent = _close(offline, tmp_path, SOL, j, fills, "0.0313823")
    assert D(rec["net"]) == D("1.45953679") and rec["R"] == "0.421" and rec["reason"] == "be_stop"
    msg = sent[-1].splitlines()
    assert msg[0].startswith("🔵") and "1차 익절 후 본절" in msg[0] and "손절" not in msg[0]
    assert rec["outcome"] == "1차 익절 후 본절" and line["outcome"] == "1차 익절 후 본절"
    assert "전체 순손익 +1.4595 USDT" in msg[1] and "0.421R" in msg[1]
    assert any(m.startswith("• TP1 1.66@93.84 손익 +1.7098") for m in msg)
    assert any(m.startswith("• 본절 1.67@94.85 손익 +0.0334") for m in msg)


def test_record_still_short_is_flagged(offline, tmp_path):
    t0, cid = 1793633163679, "v6SOL1793633163"
    j = _journal(cid, -1, "1.70", "94.2900", "94.19", "95.37", "1.69", t0, entry_qty="3.39")
    fills = [_fill("E1", "SELL", "94.29", "3.39", "0.15982155", "0", t0),
             _fill("254824457044", "BUY", "93.21", "1.69", "0.07876245", "1.8252", 1793635101103)]
    rec, line, _ = _close(offline, tmp_path, SOL, j, fills, "0")
    assert rec["fills_incomplete"] is True


# ───────────────────────── peak-drawdown entry guard ─────────────────────────
def _guard_engine(b, **kw):
    return exit_engine(b, peak_dd_guard=0.80, peak_dd_init=132.88, daily_loss_halt=None, **kw)   # isolate from the daily halt


def test_peak_init_is_max_of_current_and_floor(offline):
    offline.inner.wallet = D("100")
    eng = _guard_engine(offline)
    eng.reconcile()
    assert D(eng.meta["peak_equity"]) == D("132.88")
    offline.inner.wallet = D("150")
    eng.reconcile()
    assert D(eng.meta["peak_equity"]) == D("150")
    offline.inner.wallet = D("140")
    eng.reconcile()
    assert D(eng.meta["peak_equity"]) == D("150")      # a peak only ratchets up


def test_peak_includes_unrealized(offline):
    offline.inner.wallet = D("200")
    eng = _guard_engine(offline)
    j = open_pos(offline, eng, side=1)
    eng.reconcile()
    p0 = D(eng.meta["peak_equity"])
    offline.inner.set_price(DOGE, D(offline.inner.price[DOGE]) * D("1.004"))
    eng.reconcile()
    assert D(eng.meta["peak_equity"]) > p0 and D(eng.meta["peak_equity"]) == D(eng.meta["equity"])


def test_peak_dd_blocks_new_entries_only_one_alert_orders_untouched_survives_restart(offline, tmp_path):
    offline.inner.wallet = D("200")
    eng = _guard_engine(offline)
    eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    j = open_pos(offline, eng, side=1)
    eng.reconcile()
    pk = D(eng.meta["peak_equity"])
    orders_before = sorted(o["client_id"] for o in offline.inner.open_orders(DOGE))
    n_alert, n_calls = len(eng.tg.sent), len(offline.fx.calls)
    offline.inner.wallet -= pk * D("0.21")              # equity now < 80 % of the peak
    eng.reconcile()
    eng.reconcile()
    eng.reconcile()
    pd = eng.meta["peak_dd"]
    assert D(pd["peak"]) == pk and D(pd["equity"]) < pk * D("0.8")
    new = eng.tg.sent[n_alert:]
    assert sum("고점 대비" in m for m in new) == 1            # one 🚨 on the transition, not every reconcile
    assert DOGE in eng.st["pos"] and offline.amt(DOGE) != 0   # open position kept
    assert sorted(o["client_id"] for o in offline.inner.open_orders(DOGE)) == orders_before
    assert not [c for c in offline.fx.calls[n_calls:] if c[0] in ("cancel", "cancel_algo", "stop", "take_profit",
                                                                    "submit_market", "market")]
    assert not eng._enter(SOL, D(offline.inner.price[SOL]) * D("0.008"), unique_T())
    assert eng.meta["skip_log"][-1][2] == "peak_dd"
    assert not [m for m in eng.tg.sent[n_alert:] if "고점 대비" not in m]   # skip is quiet: no alert per refused entry
    rs = [r for r in getattr(eng.strategy, "records", []) if r.get("kind") == "skipped"]
    assert rs and rs[-1]["reason"] == "peak_dd"                # qrmtf signal log: kind=skipped reason=peak_dd
    sk = [json.loads(x) for x in (tmp_path / "t_skips.jsonl").read_text().splitlines()]
    assert sk[-1]["reason"] == "peak_dd"
    eng2 = _guard_engine(offline)                             # restart: halt + peak come back from the state file
    assert eng2.meta.get("peak_dd") and D(eng2.meta["peak_equity"]) == pk
    eng2.reconcile()
    assert not eng2._enter(SOL, D(offline.inner.price[SOL]) * D("0.008"), unique_T())
    assert sum("고점 대비" in m for m in eng2.tg.sent) == 0


def _halted_engine(offline, tmp_path):
    from live_v6.store import JsonStore
    offline.inner.wallet = D("200")
    eng = _guard_engine(offline)
    eng.store = JsonStore(tmp_path / "mainnet.json")
    eng.reconcile()
    offline.inner.wallet = D("150")
    eng.reconcile()
    assert eng.meta.get("peak_dd")
    return eng


def test_resume_does_not_clear_peak_dd(offline, tmp_path):
    eng = _halted_engine(offline, tmp_path)
    eng.resume()
    assert eng.meta.get("peak_dd") and not eng.entries_allowed()


def test_clear_peak_halt_tool_reset_peak_audit_and_restart(offline, tmp_path, monkeypatch, capsys):
    from live_v6.tools import clear_peak_halt as cph
    eng = _halted_engine(offline, tmp_path)
    st = str(tmp_path / "mainnet.json")
    os_mode = 0o640
    import os
    os.chmod(st, os_mode)
    monkeypatch.setenv("SUDO_USER", "ops")
    monkeypatch.setattr(cph, "unit_active", lambda u: u == "live_v6-live")
    assert cph.main(["--state", st, "--by", "Developer"]) == 2                 # refuses while the service runs
    assert json.load(open(st))["meta"].get("peak_dd")
    assert cph.main(["--state", st, "--by", "Developer", "--unit", "", "--dry-run"]) == 0
    assert json.load(open(st))["meta"].get("peak_dd")
    assert cph.main(["--state", st, "--by", "Developer (TA ok)", "--unit", "", "--reset-peak"]) == 0
    m = json.load(open(st))["meta"]
    assert "peak_dd" not in m and D(m["peak_equity"]) == D("150")
    (a,) = m["peak_dd_clears"]
    assert a["by"] == "Developer (TA ok)" and a["sudo_user"] == "ops" and a["t_ms"] > 0 and D(a["peak_after"]) == D("150")
    assert json.loads((tmp_path / "peak_dd_clears.jsonl").read_text())["by"] == "Developer (TA ok)"
    assert list(tmp_path.glob("mainnet.json.bak-peakclear-*")) and os.stat(st).st_mode & 0o777 == os_mode
    assert cph.main(["--state", st, "--by", "x", "--unit", ""]) == 0 and "nothing to clear" in capsys.readouterr().out
    from live_v6.store import JsonStore
    eng2 = _guard_engine(offline)                                               # restart on the cleared file
    eng2.store = JsonStore(st)
    eng2.st = eng2.store.load()
    eng2.reconcile()
    assert not eng2.meta.get("peak_dd") and eng2.entries_allowed()


def test_clear_without_reset_halts_again_if_still_below(offline, tmp_path):
    from live_v6.tools import clear_peak_halt as cph
    from live_v6.store import JsonStore
    _halted_engine(offline, tmp_path)
    st = str(tmp_path / "mainnet.json")
    assert cph.main(["--state", st, "--by", "Developer", "--unit", ""]) == 0
    eng2 = _guard_engine(offline)
    n = len(eng2.tg.sent)
    eng2.store = JsonStore(st)
    eng2.st = eng2.store.load()
    eng2.reconcile()
    assert eng2.meta.get("peak_dd") and sum("고점 대비" in m for m in eng2.tg.sent[n:]) == 1


def test_reconcile_daily_gap_and_timing_split():
    from live_v6.tools.reconcile_daily import reconcile
    d0 = 1793577600000                                            # 2026-11-02 00:00 UTC
    recs = [{"trade_id": "A", "sym": "XRPUSDT", "entry": d0 - 3600_000, "exit": d0 + 7200_000, "net": D("1.05792244"), "src": "log"},
            {"trade_id": "B", "sym": "SOLUSDT", "entry": d0 + 10_000_000, "exit": d0 + 50_000_000, "net": D("1.45953655"), "src": "override"},
            {"trade_id": "C", "sym": "SOLUSDT", "entry": d0 - 99_000_000, "exit": d0 - 50_000_000, "net": D("9"), "src": "log"}]

    def row(t, sym, typ, x):
        return {"time": t, "symbol": sym, "incomeType": typ, "income": x, "tranId": t}
    inc = [row(d0 - 3600_000, "XRPUSDT", "COMMISSION", "-0.150553"),
           row(d0, "XRPUSDT", "FUNDING_FEE", "0.06013931"),
           row(d0 + 7200_000, "XRPUSDT", "REALIZED_PNL", "1.29824"), row(d0 + 7200_000, "XRPUSDT", "COMMISSION", "-0.14990387"),
           row(d0 + 10_000_000, "SOLUSDT", "COMMISSION", "-0.15795855"), row(d0 + 20_000_000, "SOLUSDT", "FUNDING_FEE", "0.0313823"),
           row(d0 + 50_000_000, "SOLUSDT", "REALIZED_PNL", "1.7432"), row(d0 + 50_000_000, "SOLUSDT", "COMMISSION", "-0.1570872"),
           row(d0 + 60_000_000, "XRPUSDT", "COMMISSION", "-0.15"),                       # entry of a trade still open
           row(d0 + 70_000_000, "", "TRANSFER", "50")]
    r = reconcile(recs, inc, d0)
    assert r["n_trades"] == 2 and D(r["recorded_closed_trades"]) == D("2.51745899") and D(r["transfers"]) == 50
    assert D(r["ledger_wallet_change_ex_transfer"]) == D("2.51745899") - D("-0.150553") - D("0.15")
    assert D(r["timing_ledger_rows_of_trades_not_closed_today"]) == D("-0.15")
    assert D(r["timing_pre_day_rows_of_trades_closed_today"]) == D("-0.150553")
    assert D(r["residual_unexplained"]) == 0
    assert D(r["per_trade"]["A"]["gap"]) == 0 and D(r["per_trade"]["B"]["gap"]) == 0


def test_existing_live_be_stop_kept_no_duplicate_after_upgrade(offline):
    # a position whose BE stop the old build (entry + 0.10 %) already placed: the new build (0.15 %) leaves it as-is
    from .test_qrmtf import exit_engine as ee
    from decimal import Decimal as Dec
    eng = ee(offline, be_offset=0.001)
    open_pos(offline, eng)
    j = eng.st["pos"][DOGE]
    offline.inner.set_price(DOGE, Dec(j["tp"]["tp1"]))
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    old = Dec(j["stop_px"])
    assert j["be_done"] and abs(old / Dec(j["entry_px"]) - 1) <= Dec("0.0011")
    eng2 = ee(offline)                                       # restart on the new build (be_offset 0.0015)
    assert eng2.cfg.be_offset == 0.0015 and eng2.st["pos"][DOGE]["be_done"]
    n = len(offline.fx.calls)
    eng2.reconcile()
    eng2.reconcile()
    assert not [c for c in offline.fx.calls[n:] if c[0] in ("stop", "cancel", "cancel_algo")]
    stops = [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]
    assert len(stops) == 1 and stops[0]["stop_price"] == old


def test_guard_off_by_default(offline):
    from live_v6.engine import Settings
    assert Settings().peak_dd_guard is None
    assert live_settings("qrmtf").peak_dd_guard == 0.80 and live_settings("qrmtf").peak_dd_init == 132.88
