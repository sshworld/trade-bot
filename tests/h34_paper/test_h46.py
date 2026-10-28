"""H46/H47 screen: limits book, date-block bootstrap, S1 / U clauses, verdicts, lock file, engine path on synthetic data and the
H7-T six-coin replay (355 trades / +1.69). No H46/H47 outcome is computed here."""
import datetime as dt
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from h34_paper import h46 as H
from h34_paper import h46_data as D

ROOT = Path(__file__).resolve().parents[2]
HAVE_RESEARCH = (D.RESEARCH_ROOT / "research" / "v8.py").exists()
needs_research = pytest.mark.skipif(not HAVE_RESEARCH, reason="research tree not available")
DAY = 86_400_000
T0 = int(dt.datetime(2022, 6, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def raw(sym, entry_h, exit_h, stop=0.04, gross=0.0, sig=None, side=1, fund=0.0, **kw):
    ep = 100.0
    xp = ep * (1 + side * gross)
    d = dict(sym=sym, symbol=sym, side=side, sig_ms=T0 + (sig if sig is not None else entry_h // 4 * 4) * 3_600_000, entry_ms=T0 + entry_h * 3_600_000,
             exit_ms=T0 + exit_h * 3_600_000, entry_px=ep, exit_px=xp, stop_pct=stop, sl=ep * (1 - side * stop), reason="signal_exit",
             gap=False, bars=3, fund=fund, month="2022-06", group="new", in_h16=False, hole_cross=False)
    d.update(kw)
    return d


# ---------------------------------------------------------------- limits book
def test_r_uses_sizing_cost_017():
    led, _ = H.simulate_book([raw("A", 1, 5, stop=0.03, gross=0.06)], "t", limits=True)
    assert len(led) == 1
    assert led[0]["r_c015"] == pytest.approx((0.06 - 0.0015) / (0.03 + 0.0017))
    assert led[0]["r_c030"] == pytest.approx((0.06 - 0.003) / (0.03 + 0.0017))
    assert led[0]["size_mult"] == pytest.approx(0.02 / (0.03 + 0.0017))
    assert H.raw_r(raw("A", 1, 5, stop=0.03, gross=0.06)) == pytest.approx(led[0]["r_c015"])


def test_funding_enters_r():
    led, _ = H.simulate_book([raw("A", 1, 5, stop=0.03, gross=0.06, fund=0.002)], "t")
    assert led[0]["r_c015"] == pytest.approx((0.06 - 0.0015 - 0.002) / (0.03 + 0.0017))


def test_max_three_concurrent_and_skips_recorded():
    rs = [raw(c, 1 + i, 40) for i, c in enumerate("ABCD")] + [raw("E", 50, 52)]
    led, sk = H.simulate_book(rs, "t", limits=True)
    assert sorted(t["symbol"] for t in led) == ["A", "B", "C", "E"]
    assert [(s["sym"], s["reason"]) for s in sk] == [("D", "max_concurrent")]
    led_u, sk_u = H.simulate_book(rs, "t", limits=False)
    assert len(led_u) == 5 and not sk_u


def test_one_position_per_coin_and_exit_frees_slot_same_hour():
    rs = [raw("A", 1, 10), raw("A", 5, 20), raw("B", 10, 30)]
    led, sk = H.simulate_book(rs, "t")
    assert len(led) == 2 and sk[0]["reason"] == "coin_busy"
    # a trade exiting at hour 10 frees its slot for an entry at hour 10 (exits first)
    rs = [raw("A", 1, 10), raw("B", 2, 40), raw("C", 3, 40), raw("D", 10, 20)]
    led, sk = H.simulate_book(rs, "t")
    assert {t["symbol"] for t in led} == {"A", "B", "C", "D"} and not sk


def test_trade_exiting_in_its_entry_minute_does_not_leak_a_slot():
    rs = [raw("A", 5, 5, gross=-0.04), raw("B", 6, 7), raw("C", 6, 7), raw("D", 6, 7)]
    led, sk = H.simulate_book(rs, "t")
    assert len(led) == 4 and not sk


def test_daily_loss_cap_blocks_rest_of_kst_day_not_next_day():
    # three -2%-ish stops confirm >5% loss within the KST day; later entries same KST day are skipped, next KST day is allowed
    base = int(dt.datetime(2022, 6, 1, 0, 0, tzinfo=dt.timezone.utc).timestamp())  # 09:00 KST
    def r_(sym, e, x):
        d = raw(sym, 0, 1, stop=0.04, gross=-0.04)
        d["entry_ms"], d["exit_ms"] = T0 + e * 3_600_000, T0 + x * 3_600_000
        return d
    rs = [r_("A", 1, 2), r_("B", 1, 2), r_("C", 1, 3), r_("D", 4, 6), r_("E", 20, 22)]   # D at +4h (13:00 KST) blocked; E at +20h = 05:00 KST next day
    led, sk = H.simulate_book(rs, "t")
    assert [(s["sym"], s["reason"]) for s in sk] == [("D", "daily_loss_cap")]
    assert "E" in {t["symbol"] for t in led}


def test_open_risk_rule_is_three_trades_of_two_percent():
    assert H.MAX_OPEN * H.RISK == pytest.approx(H.MAX_OPEN_RISK)


# ---------------------------------------------------------------- bootstrap
def test_boot_index():
    assert H.boot_index(0.0005) == 5 and H.boot_index(0.05 / 46) == 10 and H.boot_index(0.01) == 100 and H.boot_index(0.002) == 20


def test_date_block_bounds_matches_reference_loop_and_is_deterministic():
    rng = np.random.default_rng(1)
    rs = rng.normal(0.2, 1.0, 120)
    dates = rng.integers(0, 30, 120)
    got = H.date_block_bounds(rs, dates, 67, (0.0005, 0.01), n_boot=500, chunk=100)
    # straightforward reference: same generator stream, chunked identically
    u, inv = np.unique(dates, return_inverse=True)
    s, c = np.bincount(inv, weights=rs), np.bincount(inv).astype(float)
    g = np.random.default_rng(67)
    means = []
    for _ in range(5):
        i = g.integers(0, len(u), (100, len(u)))
        means += [s[r].sum() / c[r].sum() for r in i]
    means.sort()
    assert got[0.0005] == pytest.approx(means[H.boot_index(0.0005, 500)])
    assert got[0.01] == pytest.approx(means[H.boot_index(0.01, 500)])
    assert H.date_block_bounds(rs, dates, 67, (0.0005,), n_boot=500, chunk=100) == {0.0005: got[0.0005]}
    assert H.date_block_bounds(rs, dates, 68, (0.0005,), n_boot=500, chunk=100)[0.0005] != got[0.0005]


def test_date_block_is_wider_than_iid_when_trades_cluster_by_date():
    rng = np.random.default_rng(3)
    day_effect = rng.normal(0, 1, 40)
    dates = np.repeat(np.arange(40), 10)
    rs = np.repeat(day_effect, 10) + 0.05 * rng.normal(size=400) + 0.1
    lb_date = H.date_block_bounds(rs, dates, 67, (0.01,), n_boot=2000)[0.01]
    from h34_paper import stats
    lb_iid = stats.bootstrap_lowers(list(rs), 67, 2000, (0.01,))[0.01]
    assert lb_date < lb_iid


def test_empty_bootstrap_nan():
    assert math.isnan(H.date_block_bounds([], [], 1, (0.01,))[0.01])


# ---------------------------------------------------------------- S1 / U / verdict
def mk_ledger(n=400, mean_gross=0.05, coins=40, months=24, seed=5, in_h16_every=0):
    rng = np.random.default_rng(seed)
    rs = []
    for k in range(n):
        h = k * 40 + 1                                     # sequential, never overlapping -> limits book == unlimited
        g = rng.normal(mean_gross, 0.06)
        t = raw(f"C{k % coins}USDT", h, h + 30, stop=0.04, gross=g)
        t["entry_ms"] = int(dt.datetime(2022 + (k * months // n) // 12, (k * months // n) % 12 + 1, 1 + k % 25, tzinfo=dt.timezone.utc).timestamp() * 1000)
        t["exit_ms"] = t["entry_ms"] + 3_600_000 * 30
        t["sig_ms"] = t["entry_ms"]
        t["month"] = H.utc_month(t["entry_ms"])
        t["in_h16"] = bool(in_h16_every and k % in_h16_every == 0)
        rs.append(t)
    rs.sort(key=lambda r: r["entry_ms"])
    return rs


def test_s1_passes_on_strong_edge_and_fails_on_no_edge():
    led, _ = H.simulate_book(mk_ledger(), "t")
    sc = H.s1(led, "H46", n_boot=1000)
    assert sc["S1-0"][0] and sc["S1-2"][0] and sc["all_pass"], {k: sc[k] for k in H.S1_KEYS if k in sc}
    assert sc["boot_index"] == H.boot_index(0.0005, 1000)
    led, _ = H.simulate_book(mk_ledger(mean_gross=-0.005), "t")
    assert not H.s1(led, "H46", n_boot=1000)["all_pass"]


def test_s1_0_thresholds_differ_between_h46_and_h47():
    led, _ = H.simulate_book(mk_ledger(n=150), "t")
    assert not H.s1(led, "H46", n_boot=500)["S1-0"][0]
    assert H.s1(led, "H47", n_boot=500)["S1-0"][0]
    assert H.CFG["H46"]["seed"] == 67 and H.CFG["H47"]["seed"] == 68
    assert H.CFG["H46"]["q"] == 0.0005 and H.CFG["H47"]["q"] == pytest.approx(0.05 / 46)


def test_s1_year_concentration_fails():
    led = mk_ledger(n=400, mean_gross=0.0)
    for t in led:                                           # all profit in the first year
        t["exit_px"] = 100 * (1 + (0.12 if t["month"].startswith("2022") else -0.001))
    led, _ = H.simulate_book(led, "t")
    sc = H.s1(led, "H46", n_boot=500)
    assert sc["S1-Y"][0] is False


def test_s1_empty_ledger():
    sc = H.s1([], "H46", n_boot=100)
    assert sc["all_pass"] is False and sc["S1-0"][0] is False


def test_u_clauses_and_verdicts():
    led, _ = H.simulate_book(mk_ledger(), "t")
    u = H.u_clauses(led)
    assert u["U1"][0] and u["U2"][0] and u["U3"][0]
    # one coin carries everything -> U2 fails, U3 fails
    led2 = mk_ledger(coins=40, mean_gross=-0.002)
    for t in led2:
        if t["sym"] == "C0USDT":
            t["exit_px"] = 100 * 1.5
    l2, _ = H.simulate_book(led2, "t")
    u2 = H.u_clauses(l2)
    assert not u2["U2"][0] and u2["U2"][1]["best"] == "C0USDT" and not u2["U3"][0]


def test_u4_split_and_verdict_rules():
    sc_ok = {k: (True, 0) for k in H.S1_KEYS}
    sc_ok["x"] = 1
    u_ok = {"U1": (True, {}), "U2": (True, {}), "U3": (True, {})}
    led, _ = H.simulate_book(mk_ledger(n=400, in_h16_every=2), "t")
    r = H.u4(led)
    assert r["H16"]["n"] == 200 and r["not_H16"]["n"] == 200 and r["enough"] and r["pass"]
    assert H.verdict_h46(sc_ok, u_ok, r, 0.0)[0] == "PASS"
    bad = dict(r, pass_=False)
    r_fail = dict(r, **{"pass": False})
    assert H.verdict_h46(sc_ok, u_ok, r_fail, 0.0)[0].startswith("FAIL") and "U4" in H.verdict_h46(sc_ok, u_ok, r_fail, 0.0)[0]
    r_few = H.u4(H.simulate_book(mk_ledger(n=400, in_h16_every=1), "t")[0])           # nothing outside H16 -> n 0 < 100
    assert not r_few["enough"] and r_few["pass"] is None
    assert H.verdict_h46(sc_ok, u_ok, r_few, 0.0)[0].startswith("conditional PASS")
    assert "REFERENCE ONLY" in H.verdict_h46(sc_ok, u_ok, r, 0.101)[0]
    assert "REFERENCE ONLY" not in H.verdict_h46(sc_ok, u_ok, r, 0.10)[0]
    sc_bad = dict(sc_ok, **{"S1-3": (False, -1)})
    assert H.verdict_h46(sc_bad, u_ok, r_few, 0.0)[0].startswith("FAIL")        # a failed clause beats conditional
    assert H.verdict_h47(sc_ok)[0] == "PASS" and H.verdict_h47(sc_bad)[0].startswith("FAIL (S1-3")


def test_report_only_helpers():
    rs = [raw("A", 1, 5, sig=0), raw("B", 2, 6, sig=0), raw("C", 9, 12, sig=8)]
    ov = H.overlap_rate(rs)
    assert ov["shared"] == 2 and ov["rate"] == pytest.approx(2 / 3) and ov["max_same_bar"] == 2
    mo = H.min_order_skips([raw("A", 1, 5, stop=0.02)], {"A": (5.0, 0.001, 0.001)}, 100.0)
    assert mo["A"]["signals"] == 1 and mo["A"]["skipped"] == 0      # 100 * 0.02/(0.0217) = $92 notional
    mo = H.min_order_skips([raw("A", 1, 5, stop=0.02)], {"A": (100.0, 0.001, 0.001)}, 100.0)
    assert mo["A"]["skipped"] == 1                                    # below a $100 minimum (BTC floor)
    ss = H.skip_summary([dict(reason="max_concurrent", r=1.0), dict(reason="max_concurrent", r=-1.0)])
    assert ss["max_concurrent"] == dict(n=2, mean_r=0.0)


def test_hole_windows_in_ms():
    assert [pd_ms for pd_ms in H.HOLE_MS][0][0] == int(dt.datetime(2022, 2, 26, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert H.HOLE_MS[1][1] - H.HOLE_MS[1][0] == 2 * DAY and H.HOLE_MS[0][1] - H.HOLE_MS[0][0] == 3 * DAY


# ---------------------------------------------------------------- coverage helpers (pure)
def test_month_cov_and_has_hole():
    import pandas as pd
    idx = pd.date_range("2022-01-01", "2022-03-15 23:00", freq="1h")
    assert D.month_cov(idx, D.H1N, "2022-02") == (1.0, 28 * 24)
    assert D.month_cov(idx, D.H1N, "2022-03")[0] == 1.0                 # data end inside the month: expected only until the end
    assert D.month_cov(idx, D.H1N, "2022-04")[0] == 0.0                 # month after the data end
    hole = idx.delete(np.arange(24 * 56, 24 * 59))                       # drop 3 days from 2022-02-26 00:00
    assert D.month_cov(hole, D.H1N, "2022-02")[0] == pytest.approx(1 - 72 / (28 * 24))
    assert D.has_hole(hole, D.H1N, np.datetime64("2022-02-26", "ns"), np.datetime64("2022-03-01", "ns"))
    assert not D.has_hole(idx, D.H1N, np.datetime64("2022-02-26", "ns"), np.datetime64("2022-03-01", "ns"))
    late = idx[idx >= "2022-03-01"]                                       # listed after the window -> no hole
    assert not D.has_hole(late, D.H1N, np.datetime64("2022-02-26", "ns"), np.datetime64("2022-03-01", "ns"))


# ---------------------------------------------------------------- lock file / CLI
def test_cli_requires_explicit_mode_and_final_flag(capsys):
    sys.path.insert(0, str(ROOT / "tools"))
    import run_screen_h46_h47 as cli
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2


def test_take_lock_refuses_second_run(tmp_path):
    sys.path.insert(0, str(ROOT / "tools"))
    import run_screen_h46_h47 as cli
    p = cli.take_lock(tmp_path, "h46", "1m", {"head": "x"})
    assert json.loads(p.read_text())["spec"] == "h46"
    with pytest.raises(SystemExit) as e:
        cli.take_lock(tmp_path, "h46", "1m", {"head": "x"})
    assert "REFUSED" in str(e.value)
    cli.take_lock(tmp_path, "h47", "1m", {"head": "x"})                  # other spec has its own lock


# ---------------------------------------------------------------- engine path on synthetic data
def _synth(side=1, crowd=False, sl_hit=False, n=30, bl=None, allow=None):
    import pandas as pd
    v8 = D.research()
    idx = pd.date_range("2022-06-01", periods=n * 4, freq="1h")
    o = np.full(len(idx), 100.0)
    k = pd.DataFrame(dict(open=o, high=o.copy(), low=o.copy(), close=o.copy(), volume=1.0), index=idx)
    i0 = 10 * 4
    if side > 0:
        k.iloc[i0 + 1, k.columns.get_loc("high")] = 103.0
        k.iloc[i0 + 1:, k.columns.get_loc("close")] = 102.0
        k.iloc[i0 + 2:, k.columns.get_loc("open")] = 102.0
        k.iloc[i0 + 2:, k.columns.get_loc("high")] = 102.0
        k.iloc[i0 + 2:, k.columns.get_loc("low")] = 102.0
        if sl_hit:
            k.iloc[11 * 4 + 1, k.columns.get_loc("low")] = 98.0
    else:
        k.iloc[i0 + 1, k.columns.get_loc("low")] = 97.0
        k.iloc[i0 + 1:, k.columns.get_loc("close")] = 98.0
        k.iloc[i0 + 2:, k.columns.get_loc("open")] = 98.0
        k.iloc[i0 + 2:, k.columns.get_loc("high")] = 98.0
        k.iloc[i0 + 2:, k.columns.get_loc("low")] = 98.0
        if sl_hit:
            k.iloc[11 * 4 + 1, k.columns.get_loc("high")] = 102.0
    b = v8.v3.resample(k, "4h")
    b["atr"] = 1.0
    P = v8.SymPrep.__new__(v8.SymPrep)
    P.b, P.k1h, P.side, P.sym = b, k, side, "TESTUSDT"
    P.lvl = pd.Series(101.0 if side > 0 else 99.0, index=b.index)
    P.lvl.iloc[:2] = np.nan
    P.lvl.iloc[13:] = np.nan                                           # no second breakout after the exit
    el = pd.Series(False, index=b.index)
    el.iloc[12] = True
    P.el = el
    P.f = pd.Series([0.0001], index=[idx[0]])
    P.crowd = pd.Series([bool(crowd)], index=[idx[0]])
    P.reg_open = pd.Series(1.0 if side > 0 else 0.0, index=b.index)
    opts = dict(allow=allow if allow is not None else np.ones(len(b), bool))
    if bl is not None:
        opts["blackout"] = bl
    return v8.engine("TESTUSDT", k, P, 0.01, opts), b


@needs_research
def test_engine_long_entry_stop_and_channel_exit():
    r, b = _synth(1)
    assert len(r) == 1
    t = r.iloc[0]
    assert t.entry_px == pytest.approx(101.01) and t.stop_dist == pytest.approx(2 / 101.01)
    assert t.reason == "signal_exit" and t.exit_px == pytest.approx(102.0)                 # next 4h open after the exit bar close
    assert pd_ts(t.exit_time) == pd_ts(b.index[13])


def pd_ts(x):
    import pandas as pd
    return pd.Timestamp(x)


@needs_research
def test_engine_long_stop_fills_at_stop_not_beyond():
    r, _ = _synth(1, sl_hit=True)
    t = r.iloc[0]
    assert t.reason == "stop" and t.exit_px == pytest.approx(101.01 - 2.0)


@needs_research
def test_engine_short_mirror():
    r, _ = _synth(-1)
    t = r.iloc[0]
    assert t.side == -1 and t.entry_px == pytest.approx(98.99) and t.stop_dist == pytest.approx(2 / 98.99)
    r2, _ = _synth(-1, sl_hit=True)
    assert r2.iloc[0].reason == "stop" and r2.iloc[0].exit_px == pytest.approx(98.99 + 2.0)


@needs_research
def test_engine_crowd_allow_and_blackout_block_entries():
    assert len(_synth(1, crowd=True)[0]) == 0
    assert len(_synth(1, allow=np.zeros(30, bool))[0]) == 0
    bl = (np.array([np.datetime64("2022-06-02 00:00", "ns")]), np.array([np.datetime64("2022-06-03 04:00", "ns")]))
    assert len(_synth(1, bl=bl)[0]) == 0


@needs_research
def test_short_funding_mirror_thresholds():
    import pandas as pd
    idx = pd.date_range("2022-01-01", periods=400, freq="8h")
    rng = np.random.default_rng(0)
    f = pd.Series(rng.normal(0.0, 0.0001, 400), index=idx)
    f.iloc[-3:] = -0.0004                                              # extreme negative -> crowded short
    c = D.crowd_short_mirror(f)
    assert bool(c.iloc[-1]) is True
    g = pd.Series(np.full(400, -0.00005), index=idx)                   # F3 <= p5 can hold (ties) but F3 > -0.0001 -> never crowded
    assert not D.crowd_short_mirror(g).any()


@needs_research
def test_to_raws_applies_actual_funding_and_h16_flag():
    import pandas as pd
    r, b = _synth(1)
    f = pd.Series([0.001, 0.001, 0.001], index=pd.DatetimeIndex(["2022-06-02 08:00", "2022-06-02 16:00", "2022-06-03 00:00"]))
    eng = dict(sym="TESTUSDT", raw=r.assign(sig_bar_time=b.index[r.sig_bar.to_numpy()]), f=f, holes=[])
    # engine OOS filter needs entry >= 2021-01-01 (true here)
    raws = D.to_raws(eng, 1, in_h16={("TESTUSDT", "2022-06")}, group="new")
    assert len(raws) == 1 and raws[0]["in_h16"] and raws[0]["month"] == "2022-06"
    assert raws[0]["fund"] == pytest.approx(0.001)                     # only the 06-03 00:00 settlement lies in (entry, exit]


# ---------------------------------------------------------------- the reference replay through the same engine call
@needs_research
@pytest.mark.skipif(not (D.PQ / "v7_six_1m.parquet").exists(), reason="six-coin 1m data not available")
def test_h7t_six_coin_replay_reproduces_355_trades(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "run_screen_h46_h47.py"), "--replay-check", "--intrabar", "1m", "--out", str(tmp_path)],
                       capture_output=True, text=True, timeout=900)
    assert p.returncode == 0, p.stderr[-2000:]
    r = json.loads((tmp_path / "replay_check_1m.json").read_text())
    assert r["trades"] == 355
    assert r["mean_R"] == pytest.approx(1.69, abs=0.006)
