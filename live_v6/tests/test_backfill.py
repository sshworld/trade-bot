"""ptp-short item 3: the read-only backfill rebuilds R from the ENTRY qty and the INITIAL stop (offline, no network)."""
import importlib.util
import json
import os

import pytest

_P = os.path.join(os.path.dirname(__file__), "..", "tools", "backfill_trades.py")
_spec = importlib.util.spec_from_file_location("backfill_trades", _P)
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)


def row(i, oid, side, px, qty, fee, rpnl="0", t=0):
    return {"id": i, "orderId": oid, "side": side, "price": px, "qty": qty, "commission": fee, "realizedPnl": rpnl,
            "time": 1793341000000 + t}


def test_btc_short_tp1_then_exit():
    fills = [row(1, 11, "SELL", "78521.2", "0.003", "0.1177818"),
             row(2, 12, "BUY", "77390.6", "0.001", "0.0386953", "1.1306", 60_000),
             row(3, 13, "BUY", "77260.9", "0.002", "0.0772609", "2.5206", 120_000)]
    fund = [{"income": "0.0410752", "time": 1793341090000, "tranId": 9}]
    meta = {1793341000500: {"stop0": "79651.8", "wallet": "100", "cid": "c1", "R": "0.3"}}
    [r] = bf.rebuild("BTCUSDT", fills, fund, meta)
    assert (r["status"], r["side"], r["entry_qty"], r["remaining_qty"]) == ("closed", "short", "0.003", "0")
    assert r["net"] == "3.4585372" and r["R"] == "1.020" and r["trade_id"] == "c1" and r["recorded_R"] == "0.3"
    assert r["tp1_qty"] == "0.001" and r["tp1_frac_actual"] == "0.3333" and r["init_stop_px"] == "79651.8"
    assert [(x["qty"], x["price"]) for x in r["exit_legs"]] == [("0.001", "77390.6"), ("0.002", "77260.9")]


def test_xrp_two_fills_one_order_and_open_trade():
    fills = [row(1, 21, "BUY", "1.2614", "100", "0.0504"), row(2, 21, "BUY", "1.2614", "71.6", "0.0361"),
             row(3, 22, "SELL", "1.2342", "171.6", "0.08", "-4.66752", 60_000),
             row(4, 23, "BUY", "1.25", "10", "0.005", t=120_000)]
    out = bf.rebuild("XRPUSDT", fills, [], {1793341000000: {"stop0": "1.2342"}})
    assert [r["status"] for r in out] == ["closed", "open"]
    assert out[0]["entry_qty"] == "171.6" and out[0]["tp1_qty"] == "0" and len(out[0]["exit_legs"]) == 1
    assert out[0]["R"] == str(round((-4.66752 - 0.1665) / (171.6 * 0.0272), 3))
    assert out[1]["R"] is None and out[1]["remaining_qty"] == "10" and out[1]["init_stop_px"] is None


def test_refuses_existing_or_input_output(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({}) + "\n")
    for out in (str(p), str(tmp_path / "state.json")):
        with pytest.raises(SystemExit):
            bf.main(["--trades-log", str(p), "--state", str(tmp_path / "state.json"), "--out", out, "XRPUSDT"])
    assert p.read_text() == "{}\n"


def test_only_read_paths():
    with pytest.raises(ValueError):
        bf.get("/fapi/v1/order", "k", "s")
