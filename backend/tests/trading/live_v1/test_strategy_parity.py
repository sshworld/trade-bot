"""Parity: live v1 Turtle logic vs research harness strategy A (same bars → identical trades).

Uses /workspace/trade-bot-research (read-only import) when present; otherwise skipped.
Override location with TRADE_BOT_RESEARCH_DIR.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.trading.live_v1.strategy import TurtleParams, compute_signals, replay

RESEARCH = Path(os.getenv("TRADE_BOT_RESEARCH_DIR", "/workspace/trade-bot-research"))
if not (RESEARCH / "research" / "strategies.py").exists():
    pytest.skip("research harness not available", allow_module_level=True)
sys.path.insert(0, str(RESEARCH))
from research.strategies import prep_A, run_A  # noqa: E402


def _synthetic(seed: int, n: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = rng.standard_t(4, n) * 0.012 + np.sin(np.arange(n) / 250) * 0.002
    c = 30000 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.001, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame(dict(open=o, high=h, low=lo, close=c, volume=1.0),
                        index=pd.date_range("2020-01-01", periods=n, freq="4h"))


def _real() -> pd.DataFrame | None:
    f = RESEARCH / "data" / "parquet" / "klines_4h.parquet"
    try:
        df = pd.read_parquet(f)
    except Exception:
        return None
    if "open_time" in df.columns:
        df = df.set_index("open_time")
    return df[["open", "high", "low", "close"]].astype(float)


def _check(df: pd.DataFrame):
    p = TurtleParams()                                    # N55 / M20 / k2 / ATR14 (spec v2 §8)
    b = prep_A({"4h": df.copy()})
    theirs, tf = run_A(b, p.N, p.M, p.k)
    assert tf == "4h"
    bars = df.reset_index(drop=True).to_dict("records")
    st = replay(bars, p, close_at_end=True)
    mine = [(t.side, t.ei, t.xi, t.entry_px, t.exit_px, t.reason) for t in st.trades]
    ref = list(zip(theirs.side, theirs.ei, theirs.xi, theirs.entry_px, theirs.exit_px, theirs.reason))
    assert len(mine) > 10
    assert mine == ref                                    # identical entries/exits/prices/reasons
    for t, sd in zip(st.trades, theirs.stop_dist):
        assert t.stop_dist / t.entry_px == pytest.approx(sd, rel=0, abs=1e-12)
    # raw signal arrays identical too
    s = compute_signals(bars, p)
    hiN = b.high.rolling(p.N).max().shift(); loN = b.low.rolling(p.N).min().shift()
    hiM = b.high.rolling(p.M).max().shift(); loM = b.low.rolling(p.M).min().shift()
    assert s.long == list((b.close > hiN).to_numpy())
    assert s.short == list((b.close < loN).to_numpy())
    assert s.exit_long == list((b.close < loM).to_numpy())
    assert s.exit_short == list((b.close > hiM).to_numpy())
    atr = (p.k * b.atr).to_numpy()
    ok = ~np.isnan(atr)
    assert np.array_equal(np.isnan(np.array(s.stop_dist)), ~ok)
    assert np.allclose(np.array(s.stop_dist)[ok], atr[ok], rtol=1e-12, atol=0)


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_parity_synthetic(seed):
    _check(_synthetic(seed))


def test_parity_real_btc_4h():
    df = _real()
    if df is None:
        pytest.skip("research 4h parquet not readable (pyarrow missing?)")
    _check(df)
