"""hand-built price paths for the generators that a random walk does not trigger (H50, H65, H67/H68, H71)."""
import sys
import os
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from h34_paper import hx_specs as S1, hx_specs3 as S3
from hx_synth import synth_coin

HR, DAY = 3_600_000, 86_400_000


def mk(o, h, l, c, v=None, oi=None, start="2021-12-01"):
    k = synth_coin(o, h, l, c, start=start, sym="TESTUSDT", v=v)
    k.ok_m = set(k.months)
    day0 = (k.t[0] // DAY) * DAY
    days = np.arange(day0, k.t[-1] + DAY, DAY)
    ctx = dict(reg=(days, np.ones(len(days))))
    if oi is not None:
        ctx["oi"] = {k.sym: oi(k)}
    return k, ctx


def flat(n, px=100.0, wob=0.002, seed=0):
    rng = np.random.default_rng(seed)
    c = px * (1 + rng.normal(0, wob, n))
    o = np.concatenate([[px], c[:-1]])
    return o, np.maximum(o, c) * 1.0005, np.minimum(o, c) * 0.9995, c


def cat(*parts):
    return tuple(np.concatenate([p[i] for p in parts]) for i in range(4))


def bars(rows):
    a = np.array(rows, float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


# ---------------------------------------------------------------- H50
def h50_path(after):
    pre = flat(24 * 60)
    day = bars([(100, 100.2, 99, 99.5)] + [(99.5, 99.6, 85, 86)] * 11 + [(86, 93, 86, 90)] * 6 + [(90, 93, 89, 92), (92, 93, 91.5, 92.5), (92.5, 93, 92, 92.8), (92.8, 93, 92.4, 93), (93, 93.2, 92.8, 93)] + [(93, 93.1, 92.9, 93)])
    assert len(day[0]) == 24
    return cat(pre, day, after)


def test_h50_capitulation_bounce_enters_next_open_and_hits_target():
    rise = bars([(93 + 0.5 * i, 93.6 + 0.5 * i, 92.9 + 0.5 * i, 93.5 + 0.5 * i) for i in range(24 * 6)])
    o, h, l, c = h50_path(rise)
    v = np.full(len(o), 6000.0)
    v[24 * 60:24 * 61] = 6000.0 * 6
    k, ctx = mk(o, h, l, c, v=v)
    raws, notes = S1.gen_h50(k, ctx)
    assert len(raws) == 1, notes
    r = raws[0]
    day61 = k.t[0] + 61 * DAY
    assert r["entry_ms"] == day61 and r["entry_px"] == pytest.approx(k.o[int(np.searchsorted(k.t, day61))])
    assert r["reason"] == "target"
    assert r["exit_px"] > r["entry_px"]
    assert r["stop_pct"] > 0.02


def test_h50_needs_the_volume_climax():
    rise = bars([(93, 93.6, 92.9, 93.5)] * (24 * 3))
    o, h, l, c = h50_path(rise)
    k, ctx = mk(o, h, l, c)                                             # flat volume: condition (2) fails
    raws, notes = S1.gen_h50(k, ctx)
    assert raws == [] and notes["signals"] == 0


def test_h50_time_exit_after_ten_daily_bars():
    flatafter = bars([(93, 93.1, 92.9, 93)] * (24 * 14))
    o, h, l, c = h50_path(flatafter)
    v = np.full(len(o), 6000.0)
    v[24 * 60:24 * 61] = 6000.0 * 6
    k, ctx = mk(o, h, l, c, v=v)
    raws, _ = S1.gen_h50(k, ctx)
    assert len(raws) == 1 and raws[0]["reason"] == "time"
    assert raws[0]["exit_ms"] - raws[0]["entry_ms"] == 10 * DAY


# ---------------------------------------------------------------- H65 / H66
def sine(seed, n=24 * 60, wick=0.5):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    c = 100 * (1 + 0.02 * np.sin(2 * np.pi * t / 72)) + rng.normal(0, 0.05, n)
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) + np.abs(rng.normal(0, wick, n))
    l = np.minimum(o, c) - np.abs(rng.normal(0, wick, n))
    return o, h, l, c


@pytest.mark.parametrize("side", [1, -1])
def test_h65_h66_invariants_on_a_ranging_coin(side):
    k, ctx = mk(*sine(1))
    raws, notes = S3.gen_h65(k, ctx, side)
    assert len(raws) >= 3 and notes["ranges"] >= 3
    for r in raws:
        assert r["side"] == side
        assert r["stop_pct"] >= 0.006
        assert r["exit_ms"] - r["entry_ms"] <= 49 * HR + 60_000
        if r["reason"] == "target":
            assert side * (r["exit_px"] - r["entry_px"]) > 0
        if r["reason"] == "stop":
            assert side * (r["exit_px"] - r["entry_px"]) < 0 or r["exit_px"] == pytest.approx(r["sl"], rel=1e-3)
    assert len({(r["hi30"], r["lo30"]) for r in raws}) == len(raws), "one signal per range per direction"


# ---------------------------------------------------------------- H67 / H68
def flush_path(side):
    pre = flat(24 * 30, seed=2)
    if side > 0:
        fl = bars([(100, 100, 93, 97.5), (97.5, 99, 97, 98.5)])
    else:
        fl = bars([(100, 107, 100, 102.5), (102.5, 103, 101.5, 101.5)])
    post = flat(24 * 3, px=fl[3][-1], seed=3)
    return cat(pre, fl, post)


def oi_with_drop(at_hour):
    def f(k):
        t = k.t[::5]
        v = np.full(len(t), 1e6)
        v[t >= k.t[0] + at_hour * HR + 20 * 60_000] = 0.95e6
        return t, v
    return f


def flush_path_v11(side):
    """v1.1: H67 flush bar closes in the LOWER 40% of its range, H68 in the UPPER 40%."""
    pre = flat(24 * 30, seed=2)
    if side > 0:
        fl = bars([(100, 100.2, 94.0, 94.6), (94.6, 95.3, 94.5, 95.0)])       # ret -5.4%, pos 0.10 (lower 40%); next close 95.0 > 94.6
    else:
        fl = bars([(100, 106.0, 99.8, 105.4), (105.4, 105.5, 104.9, 105.0)])  # ret +5.4%, pos 0.90 (upper 40%); next close 105.0 < 105.4
    post = flat(24 * 3, px=fl[3][-1], seed=3)
    return cat(pre, fl, post)


@pytest.mark.parametrize("side", [1, -1])
def test_h67_h68_v1_1_flush_in_lower_upper_40pct_trades_and_target_is_beyond_entry(side):
    o, h, l, c = flush_path_v11(side)
    k, ctx = mk(o, h, l, c, oi=oi_with_drop(24 * 30))
    raws, notes = S3.gen_h67(k, ctx, side)
    assert notes["flush_bars"] == 1
    assert len(raws) == 1, notes
    r = raws[0]
    assert side * (r["tp"] - r["entry_px"]) > 0, "target is on the profit side of the entry"
    flush_open, flush_ext = (100.0, 94.0) if side > 0 else (100.0, 106.0)
    assert r["tp"] == pytest.approx((flush_open + flush_ext) / 2)
    assert r["exit_ms"] - r["entry_ms"] <= 24 * HR + 60_000


@pytest.mark.parametrize("side", [1, -1])
def test_h67_h68_v1_1_old_close_position_is_not_a_flush(side):
    o, h, l, c = flush_path(side)                     # v1 shapes: H67 top-40% close / H68 bottom-40% close
    k, ctx = mk(o, h, l, c, oi=oi_with_drop(24 * 30))
    raws, notes = S3.gen_h67(k, ctx, side)
    assert notes["flush_bars"] == 0 and raws == []


# ---------------------------------------------------------------- H71
def h71_path(seed):
    rng = np.random.default_rng(seed)
    r = np.concatenate([rng.normal(0.0006, 0.01, 24 * 200), rng.normal(0, 0.0008, 24 * 15), [0.0075] * 4, rng.normal(0.001, 0.004, 24 * 10)])
    c = 100 * np.exp(np.cumsum(r))
    o = np.concatenate([[100], c[:-1]])
    sp = np.abs(rng.normal(0, 0.0005, len(c)))
    return o, np.maximum(o, c) * (1 + sp), np.minimum(o, c) * (1 - sp), c


def test_h71_squeeze_release_enters_after_4h_close_and_exits_on_a_4h_close_or_stop():
    k, ctx = mk(*h71_path(4))
    raws, notes = S3.gen_h71(k, ctx)
    assert len(raws) == 1 and notes["events"] >= 1
    r = raws[0]
    assert r["side"] == 1 and r["sig_ms"] % (4 * HR) == 0 and r["entry_ms"] >= r["sig_ms"]
    assert r["reason"] in ("bb_mid", "stop", "end_of_data")
    if r["reason"] == "bb_mid":
        assert r["exit_ms"] % (4 * HR) == 0
    assert 0.006 <= r["stop_pct"] <= 0.0983
