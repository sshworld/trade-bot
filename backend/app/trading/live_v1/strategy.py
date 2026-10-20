"""A-fixed: 4h Donchian/Turtle breakout — pure functions, parity with research harness.

Mirrors trade-bot-research `strategies.run_A` + `sim.simulate` (market mode, no TP):
  - signal at bar close: long  = close > max(high[i-N:i]); short = close < min(low[i-N:i])
  - exit at bar close:   long  = close < min(low[i-M:i]);  short = close > max(high[i-M:i])
  - orders execute at the NEXT bar open; stop distance = k * ATR(atr_n) of the signal bar
    (ATR = Wilder RMA, identical recurrence to pandas ewm(alpha=1/n, adjust=False, min_periods=n))
  - stop is checked intrabar (SL-first); a signal exit is only taken when the stop did not hit.

Live usage: `model_state(bars)` replays the same state machine over closed bars and returns what
must happen at the next bar open. Direction "long_only" = the bidirectional model with short
trades not executed (= research's long-only split); the model still "holds" virtual shorts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

NAN = float("nan")


@dataclass(frozen=True)
class TurtleParams:
    N: int = 55          # entry channel
    M: int = 20          # exit channel
    k: float = 2.0       # stop = k * ATR
    atr_n: int = 14      # spec v2 §2/§8: ATR(14)


def atr_rma(high: list[float], low: list[float], close: list[float], n: int) -> list[float]:
    """Wilder ATR exactly like research indicators.atr (pandas ewm adjust=False, min_periods=n)."""
    a = 1.0 / n
    old_wt_factor = 1.0 - a
    out: list[float] = []
    w = NAN
    nobs = 0
    for i in range(len(close)):
        if i == 0:
            tr = high[0] - low[0]
        else:
            pc = close[i - 1]
            tr = max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc))
        if i == 0:
            w = tr
        elif w != tr:
            w = (old_wt_factor * w + a * tr) / (old_wt_factor + a)
        nobs += 1
        out.append(w if nobs >= n else NAN)
    return out


def _rolling_prev(vals: list[float], n: int, fn) -> list[float]:
    """fn(vals[i-n:i]) — i.e. rolling(n).fn().shift(1)."""
    return [fn(vals[i - n:i]) if i >= n else NAN for i in range(len(vals))]


@dataclass
class Signals:
    long: list[bool]
    short: list[bool]
    exit_long: list[bool]
    exit_short: list[bool]
    stop_dist: list[float]


def compute_signals(bars: list[dict], p: TurtleParams = TurtleParams()) -> Signals:
    h = [float(b["high"]) for b in bars]
    l = [float(b["low"]) for b in bars]
    c = [float(b["close"]) for b in bars]
    hiN = _rolling_prev(h, p.N, max)
    loN = _rolling_prev(l, p.N, min)
    hiM = _rolling_prev(h, p.M, max)
    loM = _rolling_prev(l, p.M, min)
    atr = atr_rma(h, l, c, p.atr_n)
    gt = lambda x, y: (y == y) and x > y   # NaN compare → False (pandas semantics)
    lt = lambda x, y: (y == y) and x < y
    return Signals(
        long=[gt(c[i], hiN[i]) for i in range(len(c))],
        short=[lt(c[i], loN[i]) for i in range(len(c))],
        exit_long=[lt(c[i], loM[i]) for i in range(len(c))],
        exit_short=[gt(c[i], hiM[i]) for i in range(len(c))],
        stop_dist=[p.k * x for x in atr],
    )


@dataclass
class ModelTrade:
    side: int
    ei: int
    xi: int
    entry_px: float
    exit_px: float
    reason: str          # stop | signal_exit | end_of_data
    stop_dist: float     # absolute price distance


@dataclass
class ModelState:
    """State after processing the last closed bar (index n-1)."""
    pos: int = 0
    entry_px: float = 0.0
    sl: float = 0.0
    ei: int = -1
    pend_exit: bool = False          # → close at next bar open
    pend_entry: int = 0              # +1/-1 → enter at next bar open
    pend_stop_dist: float = NAN      # absolute stop distance for pend_entry
    pend_signal_bar: int = -1
    trades: list[ModelTrade] = field(default_factory=list)


def replay(bars: list[dict], p: TurtleParams = TurtleParams(), close_at_end: bool = False) -> ModelState:
    """Port of research sim.simulate(entry_mode='market', no TP/max_hold)."""
    s = compute_signals(bars, p)
    o = [float(b["open"]) for b in bars]
    h = [float(b["high"]) for b in bars]
    l = [float(b["low"]) for b in bars]
    c = [float(b["close"]) for b in bars]
    n = len(o)
    st = ModelState()
    pos = 0; entry_px = sl = 0.0; ei = 0; sdist = 0.0
    pend_entry = 0; pend_i = -1; pend_exit = False
    for i in range(n):
        if pend_exit and pos != 0:
            st.trades.append(ModelTrade(pos, ei, i, entry_px, o[i], "signal_exit", sdist))
            pos = 0
        pend_exit = False
        if pend_entry != 0 and pos == 0:
            j = pend_i; side = pend_entry
            sd = s.stop_dist[j]
            if sd > 0 and math.isfinite(sd):
                pos = side; entry_px = o[i]; ei = i; sdist = sd
                sl = entry_px - side * sd
        pend_entry = 0
        if pos != 0:
            hit = None
            if pos > 0 and l[i] <= sl:
                hit = min(o[i], sl) if i > ei else sl
            elif pos < 0 and h[i] >= sl:
                hit = max(o[i], sl) if i > ei else sl
            if hit is not None:
                st.trades.append(ModelTrade(pos, ei, i, entry_px, hit, "stop", sdist))
                pos = 0
            elif (pos > 0 and s.exit_long[i]) or (pos < 0 and s.exit_short[i]):
                pend_exit = True
        if (pos == 0 or pend_exit) and i + 1 < n:
            if s.long[i] and pos != 1:
                pend_entry, pend_i = 1, i
            elif s.short[i] and pos != -1:
                pend_entry, pend_i = -1, i
        elif (pos == 0 or pend_exit) and i + 1 == n:
            # live: the last closed bar may schedule an action for the (not yet existing) next bar
            if s.long[i] and pos != 1:
                pend_entry, pend_i = 1, i
            elif s.short[i] and pos != -1:
                pend_entry, pend_i = -1, i
    if close_at_end and pos != 0:
        st.trades.append(ModelTrade(pos, ei, n - 1, entry_px, c[n - 1], "end_of_data", sdist))
        pos = 0; pend_exit = False; pend_entry = 0
    st.pos, st.entry_px, st.sl, st.ei = pos, entry_px, sl, ei
    st.pend_exit, st.pend_entry, st.pend_signal_bar = pend_exit, pend_entry, pend_i if pend_entry else -1
    st.pend_stop_dist = s.stop_dist[pend_i] if pend_entry else NAN
    return st


def allowed_side(side: int, direction: str) -> bool:
    return side > 0 or direction == "both"
