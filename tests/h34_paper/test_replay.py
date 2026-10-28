"""Replay tests against the real history (research venv: pandas + pyarrow + the parquet store). Skipped when the data is absent.

1. core.step (via history.replay) over the full history == the committed one-time screen result (trades_H34B.csv): the recorder
   refactor (Rule / gate hooks) did not change a single trade.
2. The recorder, driven bar by bar through a simulated clock and a windowed fake feed (1500 x 15m, 500 x 1h, forming bar masked),
   writes exactly the trades history.replay produces on the same slice."""
import csv
import datetime as dt
import json
import os

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
from h34_paper import history
from h34_paper.core import MS15, MS1D
from h34_paper.engine import Limits
from h34_paper.recorder import Recorder, load_config
from helpers import FakeFeed

CONF = os.path.join(os.path.dirname(__file__), "..", "..", "h34_paper", "deploy", "h34_paper.json")
REF = "/workspace/trade-bot-research/results/h34/trades_H34B.csv"

pytestmark = pytest.mark.skipif(not os.path.exists(history.P + "klines_15m.parquet"), reason="parquet store not available")


@pytest.fixture(scope="module")
def hist():
    return history.load_all()


def fmt(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@pytest.mark.skipif(not os.path.exists(REF), reason="committed screen output not available")
def test_replay_equals_committed_screen_trades(hist):
    data, daily, _ = hist
    _, led, _ = history.replay(data, daily)
    ref = list(csv.DictReader(open(REF)))
    a = sorted((t["strategy"], t["symbol"], fmt(t["entry_bar_open_ms"]), fmt(t["exit_ms"]), t["exit_reason"],
                round(t["net_ret_c015"], 6), round(t["net_ret_c030"], 6), round(t["r_c015"], 4)) for t in led)
    b = sorted((r["rule"], r["coin"], r["entry_time_utc"], r["exit_time_utc"], r["exit_reason"], round(float(r["net_return_c015"]), 6),
                round(float(r["net_return_c030"]), 6), round(float(r["r_c015"]), 4)) for r in ref)
    assert len(a) == len(b) > 1000
    assert a == b


def _src(data, daily):
    s = {}
    for sym, sd in data.items():
        s[(sym, "15m")], s[(sym, "1h")] = sd.s15.bars, sd.s1h.bars
    s[("BTCUSDT", "1d")] = daily.bars
    return s


def _simulate(hist, tmp, start_utc, days):
    data, daily, _ = hist
    start = int(dt.datetime.fromisoformat(start_utc).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    cfg, rules, off, _ = load_config(CONF)
    cfg["lock_ts_ms"] = start
    feed = FakeFeed(_src(data, daily), start)
    rec = Recorder(cfg, rules, off, Limits.off(), str(tmp), feed)
    end = start + days * MS1D
    t = (start // MS15) * MS15 + MS15 + 4000
    while t < end:
        feed.t = t
        rec.run_once()
        t += MS15
    return rec, start, end


@pytest.mark.parametrize("start_utc,days", [("2024-06-03T00:00:00", 21), ("2022-05-02T00:00:00", 21)])
def test_recorder_slice_equals_history_replay(hist, tmp_path, start_utc, days):
    data, daily, _ = hist
    rec, start, end = _simulate(hist, tmp_path, start_utc, days)
    _, led, ev = history.replay(data, daily, start_after_ms=start)
    last_T = rec.next_T                                           # bars processed: T < next_T
    want = sorted((t["strategy"], t["symbol"], t["entry_bar_open_ms"], t["exit_ms"], t["exit_reason"], round(t["r_c015"], 9),
                   round(t["r_c030"], 9)) for t in led if t["exit_ms"] <= last_T)
    got = [json.loads(l) for l in open(tmp_path / "trades.jsonl")]
    got = sorted((t["strategy"], t["symbol"], t["entry_bar_open_ms"], t["exit_ms"], t["exit_reason"], round(t["r_c015"], 9),
                  round(t["r_c030"], 9)) for t in got)
    assert len(want) >= 5, "slice should contain trades to be meaningful"
    assert got == want
    entries_want = [e for e in ev if e["event"] == "paper_entry" and e["signal_close_ms"] <= last_T]
    entries_got = [json.loads(l) for l in open(tmp_path / "events.jsonl")]
    entries_got = [e for e in entries_got if e["event"] == "paper_entry"]
    assert len(entries_got) == len(entries_want)
    assert all(t["signal_close_ms"] > start for t in map(json.loads, open(tmp_path / "trades.jsonl")))


def test_restart_in_the_middle_gives_same_ledger(hist, tmp_path):
    """Kill and restart the recorder (new process state = state.json) at an arbitrary cycle: no duplicate and no missing trade."""
    data, daily, _ = hist
    start = int(dt.datetime.fromisoformat("2024-06-03T00:00:00").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    cfg, rules, off, _ = load_config(CONF)
    cfg["lock_ts_ms"] = start
    src = _src(data, daily)

    def drive(rec, feed, t0, t1):
        t = t0
        while t < t1:
            feed.t = t
            rec.run_once()
            t += MS15

    t_first = (start // MS15) * MS15 + MS15 + 4000
    end = start + 30 * MS1D
    d1, d2 = tmp_path / "cont", tmp_path / "restart"
    f1 = FakeFeed(src, start)
    r1 = Recorder(cfg, rules, off, Limits(), str(d1), f1)
    drive(r1, f1, t_first, end)
    first = sorted((json.loads(l) for l in open(d1 / "trades.jsonl")), key=lambda t: t["entry_bar_open_ms"])
    first = next(t for t in first if t["bars_held"] >= 12)       # restart while this position is OPEN
    mid = first["entry_bar_open_ms"] + 5 * MS15 + 37_000
    assert first["exit_ms"] > mid + 3 * MS15
    f2 = FakeFeed(src, start)
    r2 = Recorder(cfg, rules, off, Limits(), str(d2), f2)
    drive(r2, f2, t_first, mid)
    r2b = Recorder(cfg, rules, off, Limits(), str(d2), f2)           # restart from disk
    drive(r2b, f2, mid, end)

    def keys(d):
        return sorted(json.loads(l)["_key"] for l in open(d / "trades.jsonl"))
    assert keys(d1) == keys(d2) and len(keys(d1)) >= 5
    assert open(d1 / "trades.csv").read().count("\n") == open(d2 / "trades.csv").read().count("\n")
