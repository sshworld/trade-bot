"""v6 H7 row strategy — pure, deterministic, incremental (one call per CLOSED 4h bar).

Spec: v4 §1 base (H4) + H7 (spec v6 §1, threshold F3 > 1bp). Reference implementation: trade-bot-research
research/v6.py `sym_trades_v6(variant="H7")` + research/sim.py `simulate` (market entry, no TP):
  * long only. Signal at 4h bar close: close > max(high of previous 55 bars)
      AND BTC regime: last COMPLETED UTC day's BTC close > SMA200 of daily closes
      AND NOT funding_crowded (H7).
  * entry = next bar open; model stop = entry_open − 2×ATR14(signal bar) (Wilder RMA = pandas ewm adjust=False)
  * stop checked inside each bar (gap-through fills at open for bars after the entry bar)
  * exit signal at bar close: close < min(low of previous 20 bars) → close at next bar open
  * while the MODEL holds a position, no new entry for that symbol — even if the live entry was skipped
    (min_notional, margin, …). This is how the backtest behaves (per-symbol sim first, sizing skips after).
H7 (funding_crowded at bar close T): fn = funding rate normalised to 8h (rate·8/interval_h);
  F3 = mean of the last 3 settled fn with stamp ≤ T; p95 = 95th pct (linear) of fn stamps in (t_k − 90d, t_k]
  (t_k = last stamp ≤ T, ≥100 stamps); crowded iff F3 ≥ p95 and round(F3, 10) > 0.0001.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import asdict, dataclass, field

NAN = float("nan")
H4_MS = 4 * 3600_000
DAY_MS = 86400_000
D90_MS = 90 * DAY_MS


@dataclass(frozen=True)
class Params:
    N: int = 55
    M: int = 20
    k: float = 2.0
    atr_n: int = 14
    sma_days: int = 200
    h7_q: float = 0.95
    h7_window_ms: int = D90_MS
    h7_min_obs: int = 100
    h7_floor: float = 0.0001


# ───────────────────────── filters (pure) ─────────────────────────
def btc_regime_ok(daily: list[tuple[int, float]], t_ms: int, n: int = 200) -> bool:
    """daily = [(day_open_ms, close)] ascending. True iff the last day COMPLETED at t_ms closed above its SMA(n)."""
    opens = [d[0] for d in daily]
    j = bisect.bisect_right(opens, t_ms - DAY_MS) - 1          # day_open + 1d ≤ t
    if j < n - 1:
        return False
    closes = [d[1] for d in daily[j - n + 1:j + 1]]
    return daily[j][1] > sum(closes) / n


def _np_round(x: float, decimals: int) -> float:
    m = 10.0 ** decimals
    return round(x * m) / m                                     # numpy.round: rint(x·10^d)/10^d (half-even)


def _pd_quantile_linear(sorted_vals: list[float], q: float) -> float:
    """pandas rolling().quantile(q, interpolation='linear')."""
    n = len(sorted_vals)
    pos = q * (n - 1)
    i = int(pos)
    if pos == i or i + 1 >= n:
        return sorted_vals[i]
    lo, hi = sorted_vals[i], sorted_vals[i + 1]
    return lo + (hi - lo) * (pos - i)


def normalise_funding(stamps: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """[(t_ms rounded to minute, rate)] → [(t, rate·8/interval_h)]; first interval assumed 8h (as research)."""
    out = []
    prev = None
    for t, r in stamps:
        iv = 8.0 if prev is None else max(1.0, float(round((t - prev) / 3600_000)))
        out.append((t, r * 8 / iv))
        prev = t
    return out


def funding_crowded(fn: list[tuple[int, float]], t_ms: int, p: Params = Params()) -> tuple[bool, dict]:
    ts = [x[0] for x in fn]
    k = bisect.bisect_right(ts, t_ms) - 1
    if k < 2:
        return False, {"why": "no_funding"}
    a, b, c = fn[k - 2][1], fn[k - 1][1], fn[k][1]
    f3 = a if a == b == c else (a + b + c) / 3
    lo = bisect.bisect_right(ts, ts[k] - p.h7_window_ms)
    win = sorted(x[1] for x in fn[lo:k + 1])
    if len(win) < p.h7_min_obs:
        return False, {"f3": f3, "why": f"p95 needs {p.h7_min_obs} stamps, have {len(win)}"}
    p95 = _pd_quantile_linear(win, p.h7_q)
    return (f3 >= p95 and _np_round(f3, 10) > p.h7_floor), {"f3": f3, "p95": p95}


# ───────────────────────── per-symbol model ─────────────────────────
@dataclass
class Model:
    sym: str
    last_open: int = -1               # open_time (ms) of the last processed closed bar
    highs: list = field(default_factory=list)   # previous bars (≤ N)
    lows: list = field(default_factory=list)
    prev_close: float | None = None
    atr: float = NAN                  # ATR14 (NaN until 14 bars)
    atr_w: float = NAN                # raw RMA state
    atr_nobs: int = 0
    pos: int = 0
    entry_px: float = 0.0
    sl: float = 0.0
    ei_open: int = -1                 # open_time of the model entry bar (= trade id)
    sd: float = 0.0
    pend_exit: bool = False
    pend_entry: int = 0
    pend_sd: float = NAN
    pend_signal_open: int = -1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Model":
        return cls(**d)


def _atr_update(m: Model, h: float, l: float, c: float, n: int):
    """pandas ewm(alpha=1/n, adjust=False, min_periods=n) recurrence, exactly (incl. constant-series shortcut)."""
    tr = h - l if m.prev_close is None else max(h - l, abs(h - m.prev_close), abs(l - m.prev_close))
    a = 1.0 / n
    if m.atr_nobs == 0:
        w = tr
    else:
        w = m.atr_w
        if w != tr:
            w = ((1.0 - a) * w + a * tr) / ((1.0 - a) + a)
    m.atr_w = w
    m.atr_nobs += 1
    m.atr = w if m.atr_nobs >= n else NAN


def step(m: Model, bar: dict, signal_ok, p: Params = Params()) -> list[dict]:
    """Advance the model by one CLOSED bar {open_time, open, high, low, close}. `signal_ok(close_ms)` → (bool, info)
    is called only on a flat breakout. Returns model events; the pending action for the NEXT bar open is left in
    m.pend_exit / m.pend_entry / m.pend_sd."""
    o, h, l, c, t = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]), int(bar["open_time"])
    if t <= m.last_open:
        return []
    ev = []
    if m.pend_exit and m.pos:
        ev.append(dict(type="model_exit", reason="signal_exit", entry_open=m.ei_open, px=o, t=t))
        m.pos = 0
    m.pend_exit = False
    if m.pend_entry and m.pos == 0:
        sd = m.pend_sd
        if sd > 0 and math.isfinite(sd):
            m.pos, m.entry_px, m.ei_open, m.sd, m.sl = 1, o, t, sd, o - sd
            ev.append(dict(type="model_entry", entry_open=t, px=o, sd=sd))
    m.pend_entry, m.pend_sd, m.pend_signal_open = 0, NAN, -1
    _atr_update(m, h, l, c, p.atr_n)
    hiN = max(m.highs[-p.N:]) if len(m.highs) >= p.N else NAN
    loM = min(m.lows[-p.M:]) if len(m.lows) >= p.M else NAN
    if m.pos:
        if l <= m.sl:
            px = min(o, m.sl) if t > m.ei_open else m.sl
            ev.append(dict(type="model_exit", reason="stop", entry_open=m.ei_open, px=px, t=t))
            m.pos = 0
        elif loM == loM and c < loM:
            m.pend_exit = True
    if m.pos == 0 and hiN == hiN and c > hiN:
        ok, info = signal_ok(t + H4_MS)
        if ok:
            m.pend_entry, m.pend_sd, m.pend_signal_open = 1, p.k * m.atr, t
        ev.append(dict(type="breakout", t=t, taken=ok, **info))
    m.highs.append(h); m.lows.append(l)
    keep = max(p.N, p.M)
    if len(m.highs) > keep:
        del m.highs[:-keep]; del m.lows[:-keep]
    m.prev_close, m.last_open = c, t
    return ev
