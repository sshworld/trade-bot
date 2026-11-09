# exit-slip-sizing (TA-approved 2026-11-02): (4) exit slippage measured on the LAST exit leg against the trigger of
# the order that filled it (TP price / stop live at the close = BE stop after the move / book ref for market exits);
# (5) sizing rounds qty DOWN on the full stop distance so qty x |fill - stop| <= risk_pct of wallet for any fill;
# the live SOL 2026-11-01 record that lost its closing leg to userTrades lag. Offline only.
import json
from decimal import Decimal

from live_v6.runner import live_settings
from live_v6.rules import SymbolRules, stop_price
from live_v6.sizing import SizingParams, floor_to, size_entry
from live_v6.tradelog import EventLog

from .test_ptp_short import _close, _fill, _journal, _risk_pct
from .test_qrmtf import exit_engine

XRP, SOL, BTC, DOGE = "XRPUSDT", "SOLUSDT", "BTCUSDT", "DOGEUSDT"


def D(x):
    return Decimal(str(x))


def _bp(s, ref, px):
    return str((s * (D(ref) - D(px)) / D(ref) * 10000).quantize(D("0.01")))


def test_be_stop_exit_slip_vs_be_stop_not_initial_stop_or_avg(offline, tmp_path):
    # live XRP 2026-10-30: short 171.6 @1.2614, init stop 1.2886, TP1 85.8 @1.2337, BE stop 1.2601 filled @1.2602.
    # the old line said exit_slip_bp -104.36 (avg of both legs 1.24695 vs the 1.2886 initial stop)
    t0, cid = 1793344324450, "v6XRP1793344323"
    j = _journal(cid, -1, "85.8", "1.2614", "1.2601", "1.2886", "85.8", t0, wallet_at_entry="116.75172996",
                 tp={"tp1": "1.2342", "q1": "85.8", "tp2": "1.2070", "q2": "85.8"},
                 exit_orders=[{"id": "T1", "client_id": cid + "t1", "type": "MARKET"},
                              {"id": "S1", "client_id": cid + "s1", "type": "MARKET"}])
    fills = [_fill("E1", "SELL", "1.2614", "171.6", "0.10822812", "0", t0),
             _fill("T1", "BUY", "1.2337", "85.8", "0.05292573", "2.37666", t0 + 23_986_000),
             _fill("S1", "BUY", "1.2602", "85.8", "0.05406258", "0.10296", t0 + 29_155_000)]
    rec, line, _ = _close(offline, tmp_path, XRP, j, fills, "0.01790688", "stop_loss")
    assert line["exit_slip_ref"] == "1.2601" and line["exit_price"] == "1.2602"
    assert line["exit_slip_bp"] == _bp(-1, "1.2601", "1.2602") == "0.79"
    assert D(rec["exit_px_avg"]) == D("1.24695")                     # the avg is still recorded, just not slipped


def test_tp2_exit_slip_vs_tp2_price(offline, tmp_path):
    t0, cid = 1793341564002, "v6BTC1793341563"
    j = _journal(cid, -1, "0.002", "78521.2", "78442.6", "79651.8", "0.001", t0,
                 tp={"tp1": "77390.6", "q1": "0.001", "tp2": "76260.0", "q2": "0.002"},
                 exit_orders=[{"id": "T1", "client_id": cid + "t1"}, {"id": "T2", "client_id": cid + "t2"}])
    fills = [_fill("E1", "SELL", "78521.2", "0.003", "0.1177818", "0", t0),
             _fill("T1", "BUY", "77395.0", "0.001", "0.0386975", "1.1262", t0 + 3_600_000),
             _fill("T2", "BUY", "76271.5", "0.002", "0.0762715", "4.4994", t0 + 7_200_000)]
    _, line, _ = _close(offline, tmp_path, BTC, j, fills, "0", "take_profit")
    assert line["exit_slip_ref"] == "76260.0" and line["exit_price"] == "76271.5"
    assert line["exit_slip_bp"] == _bp(-1, "76260.0", "76271.5")


def test_time_exit_after_tp1_slip_vs_book_ref_on_last_leg(offline, tmp_path):
    t0, cid = 1793465644501, "v6SOL1793465643"
    j = _journal(cid, -1, "1.63", "95.92", "95.90", "96.95", "1.63", t0, exit_ref="94.70",
                 exit_orders=[{"id": "T1", "client_id": cid + "t1"}, {"id": "X1", "client_id": cid + "x"}])
    fills = [_fill("E1", "SELL", "95.92", "3.26", "0.1563496", "0", t0),
             _fill("T1", "BUY", "94.73", "1.63", "0.07720495", "1.9397", t0 + 69_691_560),
             _fill("X1", "BUY", "94.69", "1.63", "0.07717235", "2.0049", t0 + 86_400_892)]
    _, line, _ = _close(offline, tmp_path, SOL, j, fills, "0.07404347", "time_exit")
    assert line["exit_slip_ref"] == "94.70" and line["exit_slip_bp"] == _bp(-1, "94.70", "94.69")   # was -18.75


def test_stop_exit_without_stream_order_ids_falls_back_to_stop_px_last_leg(offline, tmp_path):
    t0 = 1793380000000
    j = _journal("v6ETH1793380000", -1, "0.05", "2241.9", "2265.61", "2265.61", "0.025", t0, tp1_done=False,
                 be_done=False)
    fills = [_fill("E1", "SELL", "2241.9", "0.05", "0.0560475", "0", t0),
             _fill("S0", "BUY", "2265.5", "0.05", "0.0566375", "-1.18", t0 + 600_000)]
    _, line, _ = _close(offline, tmp_path, "ETHUSDT", j, fills, "0", "stop_loss")
    assert line["exit_slip_ref"] == "2265.61" and line["exit_slip_bp"] == _bp(-1, "2265.61", "2265.5")


def test_xrp_4_3pct_was_fee_inclusive_price_risk_is_under_4pct(offline, tmp_path):
    # live XRP 2026-10-31 01:38 KST: short 196.6 @1.2487, stop 1.2736, wallet 122.42674984 -> actual_risk_pct 4.3395
    # is the stop loss PLUS round-trip fees + slippage; the price-distance risk is 3.9986 %
    t0 = 1793378284094
    j = _journal("v6XRP1793378283", -1, "196.6", "1.2487", "1.2736", "1.2736", "98.3", t0, tp1_done=False,
                 be_done=False, wallet_at_entry="122.42674984")
    fills = [_fill("E1", "SELL", "1.2487", "196.6", "0.12274721", "0", t0),
             _fill("X1", "BUY", "1.2545", "196.6", "0.12331735", "-1.14028", t0 + 86_401_246)]
    rec, line, _ = _close(offline, tmp_path, XRP, j, fills, "0.06568556", "time_exit")
    assert D(rec["actual_risk_pct"]) == _risk_pct("196.6", "1.2487", "1.2736", "122.42674984") > D(4)
    assert line["price_risk_pct"] == "3.9986"


def _coarse():
    one, k = D("0.001"), D("1000000")
    return SymbolRules("TSTUSDT", D("0.01"), one, one, D("5"), max_qty=k, mkt_min_qty=one, mkt_step_size=one, mkt_max_qty=k)


def test_sizing_price_risk_never_above_4pct_for_any_fill_was_4_3(offline):
    # coarse tick vs stop: ref 1.00, stop_dist 0.1075 -> est stop 0.90 (rounded toward entry, 0.1000 away) -> the
    # old q0 = 40 / 0.1000 = 400; a fill at 1.0075 re-places the stop at 0.90 = 0.1075 away -> 43.0 = 4.3 %
    r, br = _coarse(), offline.inner.brackets(DOGE)
    p = live_settings("qrmtf").sizing
    assert p.size_on_stop_dist
    w, ref, sd = D(1000), D("1.00"), D("0.1075")
    old_q0 = floor_to(w * D("0.04") / abs(ref - stop_price(r, ref, 1, sd)), r.step_size)
    assert old_q0 * abs(D("1.0075") - stop_price(r, D("1.0075"), 1, sd)) / w * 100 == D("4.3")
    for side in (1, -1):
        sz = size_entry(r, br, w, w, ref, sd, side, (), p, mark=ref)
        assert sz.skip is None and sz.path == "q0", sz
        assert sz.qty == floor_to(w * D("0.04") / sd, r.step_size)            # rounded DOWN
        for i in range(-200, 201):
            fill = ref + D(i) * D("0.0005")
            risk = sz.qty * abs(fill - stop_price(r, fill, side, sd))
            assert risk <= w * D("0.04"), (side, fill, risk)


def test_sol_tp1_then_time_exit_record_waits_for_the_closing_fill(offline, tmp_path):
    # live SOL 2026-11-01 01:54 KST short 3.26 @95.92, stop 96.95: TP1 1.63 @94.73 21:15, 24 h exit 1.63 @94.69
    # 11-02 01:54. The record was written while userTrades only had the TP1 leg -> "time_exit 21:15, qty 1.63,
    # 0.530R"; the exchange truth is 3.7079 USDT = 1.104R closed at 01:54
    t0, cid = 1793465644501, "v6SOL1793465644"
    j = _journal(cid, -1, "1.63", "95.92", "95.90", "96.95", "1.63", t0, entry_qty="3.26",
                 wallet_at_entry="125.12")
    e = _fill("E1", "SELL", "95.92", "3.26", "0.1563496", "0", t0)
    t1 = _fill("T1", "BUY", "94.73", "1.63", "0.07720495", "1.9397", 1793535336061)
    x1 = _fill("X1", "BUY", "94.69", "1.63", "0.07717235", "2.0049", 1793552045393)
    calls = []

    def lagging(fn, *a):
        calls.append(a)
        return [e, t1] if len(calls) == 1 else [e, t1, x1]

    eng = exit_engine(offline)
    eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    offline.fx.inject("user_trades", lagging, times=9)
    offline.fx.inject("income", lambda fn, *a: [{"amount": D("0.07404347"), "time": t0, "symbol": SOL}], times=9)
    j["exit_orders"] = [{"id": "T1", "client_id": cid + "t1"}, {"id": "X1", "client_id": cid + "x0"}]
    eng.st["pos"][SOL] = j
    eng.record_close(SOL, "time_exit")
    rec = eng.meta["trades"][-1]
    (line,) = [json.loads(x) for x in (tmp_path / "t_trades.jsonl").read_text().splitlines()]
    assert len(calls) == 2
    assert abs(D(rec["net"]) - D("3.70791658")) < D("0.0000001") and rec["R"] == "1.104"
    assert [x["qty"] for x in rec["exit_legs"]] == ["1.63", "1.63"]
    assert line["exit_time"] == 1793552045393 and D(line["qty"]) == D("3.26")
