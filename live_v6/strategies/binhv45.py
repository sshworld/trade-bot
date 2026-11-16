"""Freqtrade BinHV45 long entry (freqtrade-strategies @ 7f91ff52, published buy_params).

Closed 1m last price. Bollinger(40, 2) on close with pandas sample std (ddof=1), the same
window qtpylib uses. Thresholds are the loaded buy_params, not the unused IntParameter
defaults: bbdelta 7, closedelta 17, tail 25 (all /1000). Long only. The engine places a
post-only limit at the signal bar's close; this module only decides.
"""
from __future__ import annotations

import math
from decimal import Decimal

import pandas as pd

from .base import Strategy, enter

BB_N = 40
BB_STD = 2.0
BUY_BBDELTA = 7
BUY_CLOSEDELTA = 17
BUY_TAIL = 25


def entry_ok(prev_lower, bbdelta, closedelta, tail, close, prev_close) -> bool:
    """The six BinHV45 conditions on one closed bar. Any non-finite input is not a signal."""
    vals = (prev_lower, bbdelta, closedelta, tail, close, prev_close)
    floats = []
    for v in vals:
        if v is None:
            return False
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(f):
            return False
        floats.append(f)
    prev_lower, bbdelta, closedelta, tail, close, prev_close = floats
    return (
        prev_lower > 0.0
        and bbdelta > close * (BUY_BBDELTA / 1000.0)
        and closedelta > close * (BUY_CLOSEDELTA / 1000.0)
        and tail < bbdelta * (BUY_TAIL / 1000.0)
        and close < prev_lower
        and close <= prev_close
    )


def binhv45_hits(closes, lows) -> list[int]:
    """Bar indices whose close satisfies BinHV45. `closes` / `lows` are oldest-first."""
    c = pd.Series(list(closes), dtype="float64")
    low = pd.Series(list(lows), dtype="float64")
    mid = c.rolling(BB_N, min_periods=BB_N).mean()
    sd = c.rolling(BB_N, min_periods=BB_N).std()          # ddof=1, same as qtpylib
    lower = mid - BB_STD * sd
    bbdelta = (mid - lower).abs()
    closedelta = (c - c.shift(1)).abs()
    tail = (c - low).abs()
    prev_lower = lower.shift(1)
    prev_c = c.shift(1)
    hits = []
    for i in range(len(c)):
        if entry_ok(prev_lower.iloc[i], bbdelta.iloc[i], closedelta.iloc[i], tail.iloc[i], c.iloc[i], prev_c.iloc[i]):
            hits.append(i)
    return hits


class BinHV45(Strategy):
    name = "binhv45"
    decision_interval_ms = 60_000
    stream_intervals = ("1m",)

    def __init__(self, state=None, **_ignored):
        super().__init__(state)

    def on_bar_close(self, T, ctx, force=False):
        pending = {it.get("sym") for it in ctx.st["intents"].values()}
        out = []
        for sym in ctx.cfg.entry_order:
            if sym in ctx.st["pos"] or sym in pending:
                continue
            try:
                bars = ctx.closed_bars(sym, "1m", 80)
            except Exception:  # noqa: BLE001  this coin waits for the next minute
                continue
            if len(bars) < BB_N + 1:
                continue
            last = bars[-1]
            if int(last["open_time"]) != int(T) - 60_000:
                continue
            closes = [b["close"] for b in bars]
            lows = [b["low"] for b in bars]
            if (len(bars) - 1) not in binhv45_hits(closes, lows):
                continue
            close = Decimal(str(last["close"]))
            it = enter(sym, close * Decimal("0.0075"), int(T), side=1)
            it["limit_px"] = format(close, "f")
            it["signal_px"] = it["limit_px"]
            out.append(it)
        return out
