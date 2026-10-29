"""invariants every generator must satisfy on a synthetic random-walk coin (H48..H71), plus targeted rule checks."""
import numpy as np
import pandas as pd
import pytest

from h34_paper import hx_data as X
from h34_paper import hx_run as R
from h34_paper import hx_specs as S1
from hx_synth import synth_coin

HR = 3_600_000
DAY = 24 * HR
MIN = 60_000
KNOWN_REASONS = {"stop", "target", "delist", "end_of_data", "time", "signal", "signal_exit", "sched", "time_exit", "trail", "trail_stop", "max_hold", "expiry"}


def walk(seed, n=24 * 330, sig=0.008, drift=0.0, start=100.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, sig, n)
    # regime waves so that breakouts, pullbacks and sweeps occur
    r += 0.004 * np.sin(np.arange(n) / 160.0)
    c = start * np.exp(np.cumsum(r))
    o = np.concatenate([[start], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n)))
    return o, h, l, c


@pytest.fixture(scope="module")
def coin():
    o, h, l, c = walk(5)
    v = np.abs(np.random.default_rng(1).normal(6000, 2500, len(o))) + 100
    k = synth_coin(o, h, l, c, start="2021-12-01", sym="TESTUSDT", v=v)
    k.ok_m = set(k.months)
    return k


@pytest.fixture(scope="module")
def ctx(coin):
    day0 = (coin.t[0] // DAY) * DAY
    days = np.arange(day0, coin.t[-1] + DAY, DAY)
    reg = (days, np.ones(len(days)))
    cx = dict(reg=reg)
    oi_t = coin.t[::5]
    rng = np.random.default_rng(3)
    cx["oi"] = {coin.sym: (oi_t, 1e6 * np.exp(np.cumsum(rng.normal(0, 0.01, len(oi_t)))))}
    return cx


def check_raws(c, raws):
    assert raws, "generator produced nothing"
    last_exit = -1
    for r in sorted(raws, key=lambda r: r["entry_ms"]):
        assert r["entry_ms"] >= last_exit, "positions on one coin overlap"          # one position per coin
        last_exit = r["exit_ms"]
        assert r["exit_ms"] >= r["entry_ms"]
        s = r["side"]
        assert s * (r["entry_px"] - r["sl"]) > 0, "stop on the wrong side"
        assert r["stop_pct"] == pytest.approx(abs(r["entry_px"] - r["sl"]) / r["entry_px"])
        i = int(np.searchsorted(c.t, r["entry_ms"]))
        assert c.t[i] == r["entry_ms"], "entry minute exists"
        inside = c.l[i] - 1e-9 <= r["entry_px"] <= c.h[i] + 1e-9
        above_open_limit = r["side"] > 0 and c.o[i] < r["entry_px"] and r.get("tp") is not None      # H51 literal "fills at L" (counted in notes)
        assert inside or above_open_limit, "entry price inside the entry 1m bar (market: its open, limit: the limit)"
        assert r["sig_ms"] <= r["entry_ms"]
        assert r["mae"] >= 0
        if r["reason"] == "stop":
            assert r["exit_px"] * 1.0 == pytest.approx(r["sl"]) or s * (r["exit_px"] - r["sl"]) <= 1e-9, "stop fill not worse-than... "
        raw_r = H_raw_r(r)
        assert np.isfinite(raw_r)


def H_raw_r(r):
    from h34_paper import h46 as H
    return H.raw_r(r)


SPECS_ALL = ["H48", "H50", "H51", "H52", "H53", "H54", "H55", "H56", "H57", "H58", "H59", "H60", "H61", "H62", "H63", "H64", "H65", "H66",
             "H67", "H68", "H69", "H70", "H71"]


SHORT_REG = {"H57", "H58", "H60"}


@pytest.mark.parametrize("seed", [5, 2, 3])
@pytest.mark.parametrize("spec", SPECS_ALL)
def test_generator_invariants(spec, seed, ctx):
    o, h, l, c = walk(seed, sig=0.02 if seed == 3 else 0.008)
    coin = synth_coin(o, h, l, c, start="2021-12-01", sym="TESTUSDT", v=np.abs(np.random.default_rng(seed).normal(6000, 2500, len(o))) + 100)
    coin.ok_m = set(coin.months)
    ctx = dict(ctx)
    if spec in SHORT_REG:
        ctx["reg"] = (ctx["reg"][0], np.zeros(len(ctx["reg"][0])))
    ctx["oi"] = {coin.sym: ctx["oi"]["TESTUSDT"]}
    raws, notes = R._gens()[spec](coin, ctx)
    if not raws:
        pytest.skip(f"{spec}: no signal on this synthetic path (notes {notes})")
    check_raws(coin, raws)
    assert notes.get("entries", len(raws)) == len(raws)


def test_most_generators_fire_on_the_random_walk(coin, ctx):
    n = {s: len(R._gens()[s](coin, ctx)[0]) for s in SPECS_ALL}
    assert sum(1 for v in n.values() if v > 0) >= 13, n


def test_h49_stop_bar_blocks_reentry_until_the_next_4h_bar(coin, ctx, monkeypatch):
    real = X.D.research()

    class FakeV8:
        def __getattr__(self, k):
            return getattr(real, k)

        @staticmethod
        def crowd_long(sym, f):
            return pd.Series(False, index=pd.date_range("2021-12-01", periods=24 * 340, freq="h"))
    monkeypatch.setattr(X.D, "research", lambda replay=False: FakeV8())
    ev = S1.btc_events(coin, ctx)
    assert ev, "no BTC events on the synthetic path"
    cx = dict(ctx, btc_events=ev)
    raws, notes = S1.gen_h49(coin, cx)
    if len(raws) < 2:
        pytest.skip("too few H49 entries on this path")
    check_raws(coin, raws)
    H4 = 4 * HR
    rs = sorted(raws, key=lambda r: r["entry_ms"])
    for a, b in zip(rs, rs[1:]):
        if a["reason"] == "stop":
            assert b["entry_ms"] >= (a["exit_ms"] // H4) * H4 + H4


def test_h48_enters_only_on_monday_open(coin, ctx):
    raws, _ = S1.gen_h48(coin, ctx)
    if not raws:
        pytest.skip("no H48 signal")
    for r in raws:
        d = pd.Timestamp(r["entry_ms"], unit="ms")
        assert d.dayofweek == 0 and d.hour == 0 and d.minute <= 5
