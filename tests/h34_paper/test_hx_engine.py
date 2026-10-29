"""hx generic 1m position manager + rank-aware simulate_book (no research data)."""
import numpy as np
import pytest

from h34_paper import h46 as H
from h34_paper import hx_engine as E

M = 60_000
T0 = 1_700_000_000_000 // M * M


def bars(rows):
    """rows: list of (o,h,l,c) per minute starting T0."""
    a = np.array(rows, float)
    t = T0 + np.arange(len(a), dtype=np.int64) * M
    return dict(t=t, o=a[:, 0], h=a[:, 1], l=a[:, 2], c=a[:, 3])


def flat(n, px=100.0):
    return [(px, px, px, px)] * n


def run(rows, **kw):
    b = bars(rows)
    return E.manage(b["t"], b["o"], b["h"], b["l"], b["c"], **kw)


def test_stop_in_entry_minute_fills_at_stop():
    r = run([(100, 100.5, 94, 99)] + flat(5), i_e=0, epx=100.0, sl=95.0)
    assert r["reason"] == "stop" and r["i"] == 0 and r["px"] == 95.0 and not r["gap"]


def test_stop_gap_fills_at_open():
    r = run(flat(3) + [(90, 91, 89, 90)] + flat(3), i_e=0, epx=100.0, sl=95.0)
    assert r["reason"] == "stop" and r["i"] == 3 and r["px"] == 90.0 and r["gap"]


def test_stop_normal_touch_fills_at_stop_price():
    r = run(flat(3) + [(99, 99, 94, 96)] + flat(3), i_e=0, epx=100.0, sl=95.0)
    assert r["px"] == 95.0 and not r["gap"]


def test_target_touch_and_gap_and_stop_first_tie():
    r = run(flat(3) + [(100, 111, 99, 108)], i_e=0, epx=100.0, sl=90.0, tp=110.0)
    assert r["reason"] == "target" and r["px"] == 110.0
    r = run(flat(3) + [(112, 113, 111, 112)], i_e=0, epx=100.0, sl=90.0, tp=110.0)
    assert r["reason"] == "target" and r["px"] == 112.0
    r = run(flat(3) + [(100, 111, 89, 100)], i_e=0, epx=100.0, sl=90.0, tp=110.0)
    assert r["reason"] == "stop" and r["both"]


def test_short_mirror():
    r = run(flat(2) + [(100, 106, 99, 105)], i_e=0, epx=100.0, sl=105.0, side=-1)
    assert r["reason"] == "stop" and r["px"] == 105.0
    r = run(flat(2) + [(94, 95, 93, 94)], i_e=0, epx=100.0, sl=105.0, tp=95.0, side=-1)
    assert r["reason"] == "target" and r["px"] == 94.0


def test_scheduled_exit_at_open_and_stop_before_schedule():
    rows = [(100, 100, 100, 100)] * 10
    rows[5] = (101, 101, 101, 101)
    b = bars(rows)
    r = E.manage(b["t"], b["o"], b["h"], b["l"], b["c"], i_e=0, epx=100.0, sl=90.0, sched_ms=int(b["t"][5]), sched_reason="signal")
    assert r["reason"] == "signal" and r["i"] == 5 and r["px"] == 101.0
    rows[3] = (100, 100, 85, 100)
    b = bars(rows)
    r = E.manage(b["t"], b["o"], b["h"], b["l"], b["c"], i_e=0, epx=100.0, sl=90.0, sched_ms=int(b["t"][5]))
    assert r["reason"] == "stop" and r["i"] == 3


def test_end_of_data_and_delist():
    r = run(flat(5), i_e=0, epx=100.0, sl=90.0)
    assert r["reason"] == "end_of_data" and r["exit_ms"] == T0 + 5 * M and r["px"] == 100.0
    rows = flat(5)
    rows[3] = (100, 100, 100, 99.0)
    r = run(rows, i_e=0, epx=100.0, sl=90.0, dl=3)
    assert r["reason"] == "delist" and r["px"] == 99.0 and r["exit_ms"] == T0 + 4 * M
    b = bars(flat(10))
    r = E.manage(b["t"], b["o"], b["h"], b["l"], b["c"], i_e=0, epx=100.0, sl=90.0, sched_ms=int(b["t"][8]), dl=3)
    assert r["reason"] == "delist"
    r = E.manage(b["t"], b["o"], b["h"], b["l"], b["c"], i_e=0, epx=100.0, sl=90.0, sched_ms=int(b["t"][-1]) + 10 * M)
    assert r["reason"] == "end_of_data"


def test_chunked_scan_finds_far_hit():
    n = 40_000
    rows = flat(n)
    rows[31_234] = (100, 100, 80, 100)
    r = run(rows, i_e=0, epx=100.0, sl=90.0)
    assert r["i"] == 31_234 and r["reason"] == "stop"


def raw(sym, ms, ex, stop=0.04, **kw):
    d = dict(sym=sym, symbol=sym, side=1, sig_ms=ms, entry_ms=ms, exit_ms=ex, entry_px=100.0, exit_px=100.0, stop_pct=stop, sl=96.0,
             reason="time", gap=False, bars=0, fund=0.0, month="2022-01", group="g", in_h16=False, hole_cross=False)
    d.update(kw)
    return d


def test_simulate_book_rank_orders_same_minute_entries():
    day = 86_400_000
    base = 1_650_000_000_000
    raws = [raw(s, base, base + day, rank=rk) for s, rk in (("AAA", 3.0), ("BBB", 1.0), ("CCC", 2.0), ("DDD", 0.5))]
    led, sk = H.simulate_book(raws, "t", limits=True)
    assert sorted(t["symbol"] for t in led) == ["BBB", "CCC", "DDD"]
    assert [s["sym"] for s in sk] == ["AAA"]


def test_simulate_book_default_rank_is_symbol_order():
    day = 86_400_000
    base = 1_650_000_000_000
    raws = [raw(s, base, base + day) for s in ("DDD", "BBB", "CCC", "AAA")]
    led, sk = H.simulate_book(raws, "t", limits=True)
    assert sorted(t["symbol"] for t in led) == ["AAA", "BBB", "CCC"]
    assert sk[0]["sym"] == "DDD"


def test_tp_from_skips_fill_minute():
    rows = [(100, 112, 99, 100)] + flat(3)
    r = run(rows, i_e=0, epx=100.0, sl=90.0, tp=110.0, tp_from=1)
    assert r["reason"] == "end_of_data"
    r = run(rows, i_e=0, epx=100.0, sl=90.0, tp=110.0)
    assert r["reason"] == "target"
