"""H34-B / H34-B-S rules, indicators and paper-fill accounting. Pure stdlib, no I/O, no clock, no network.

Rule source: /workspace/quant/hypotheses_h34.md (sha256 e13a4c3af5b2…) + TA lock /workspace/specs/prereg-lock-h34.md
(sha256 f9a4a992fb50…). Every number below is copied from those files; nothing is tuned.

Bars are tuples (t_open_ms, open, high, low, close). All times UTC ms.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

MS15 = 900_000
MS1H = 3_600_000
MS1D = 86_400_000
KST_MS = 9 * 3_600_000

# ---- locked constants (hypotheses_h34.md v3 / prereg-lock-h34.md) -------------------------------------------------
COINS = ("BTCUSDT", "ETHUSDT")
RSI_N, RSI_LONG_LEVEL, RSI_SHORT_LEVEL = 14, 30.0, 70.0
EMA_FAST, EMA_SLOW = 20, 50
SMA_DAYS = 200
TARGET = 0.005
STOP = 0.005
MAX_BARS = 16
COST = 0.0015                 # round trip, fees + fill error (TA 0.15%)
COST_2X = 0.0030
RISK = 0.02                   # loss per stop incl. cost (TA: size = 2% / (stop + cost))
DAILY_CAP = 0.05              # confirmed loss per KST day that blocks new entries until 00:00 KST
MAX_MULT = 9.0                # exchange/margin ceiling (TA: margin 90% x 10x). Never binds for stop >= 0.45%.
TICK = {"BTCUSDT": 0.10, "ETHUSDT": 0.01, "SOLUSDT": 0.01, "BNBUSDT": 0.01, "XRPUSDT": 0.0001, "DOGEUSDT": 0.00001}
# data-integrity (NOT strategy) thresholds: a signal needs this many gap-free bars behind it (Wilder/EMA memory < 0.1-0.3%)
INTEGRITY_15M = 100
INTEGRITY_1H = 150
LOCK_TS_MS = 1_793_167_380_000  # 2026-10-28 15:03 KST = 06:03 UTC: only bars CLOSED after this count
STRATEGY = {1: "H34-B", -1: "H34-B-S"}


def kst_day(ts_ms: int) -> int:
    return (ts_ms + KST_MS) // MS1D


# ---- indicators (match research/indicators.py: pandas ewm adjust=False, min_periods=n) ---------------------------
def ema(values, span):
    """pandas ewm(span, adjust=False, min_periods=span): None until `span` valid points."""
    a = 2.0 / (span + 1.0)
    out = [None] * len(values)
    y = None
    for i, x in enumerate(values):
        y = x if y is None else (1.0 - a) * y + a * x
        if i + 1 >= span:
            out[i] = y
    return out


def rsi_wilder(closes, n=RSI_N):
    """Wilder RSI exactly as research indicators.rsi: rma = ewm(alpha=1/n, adjust=False, min_periods=n) of the gains / losses of
    close.diff(). up/0 -> RSI 100 (pandas inf); 0/0 -> None."""
    a = 1.0 / n
    out = [None] * len(closes)
    up = dn = None
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        u, w = (d if d > 0 else 0.0), (-d if d < 0 else 0.0)
        up = u if up is None else (1 - a) * up + a * u
        dn = w if dn is None else (1 - a) * dn + a * w
        if i >= n:                       # i valid diffs seen (1..i)
            if dn == 0.0:
                out[i] = None if up == 0.0 else 100.0
            else:
                out[i] = 100.0 - 100.0 / (1.0 + up / dn)
    return out


def cross_up(prev, cur, level):
    """long trigger: previous closed bar RSI < level and last closed bar RSI >= level."""
    return prev is not None and cur is not None and prev < level and cur >= level


def cross_down(prev, cur, level):
    """short trigger: previous closed bar RSI > level and last closed bar RSI <= level."""
    return prev is not None and cur is not None and prev > level and cur <= level


# ---- data containers ----------------------------------------------------------------------------------------------
def contiguous(bars, step, n):
    """True if the last n bars exist with exact spacing `step` (no missing bar)."""
    if len(bars) < n:
        return False
    return bars[-1][0] - bars[-n][0] == step * (n - 1) and all(
        bars[i + 1][0] - bars[i][0] == step for i in range(len(bars) - n, len(bars) - 1))


class Series:
    """Bars of one timeframe + indicator arrays, rebuilt by `rebuild()`. Gaps are detected, never filled."""

    def __init__(self, step):
        self.step = step
        self.bars = []
        self.ts = []

    def set_bars(self, bars):
        self.bars = sorted({b[0]: b for b in bars}.values())
        self.ts = [b[0] for b in self.bars]

    def idx(self, t_open):
        i = bisect.bisect_left(self.ts, t_open)
        return i if i < len(self.ts) and self.ts[i] == t_open else None

    def max_ts(self):
        return self.ts[-1] if self.ts else None

    def run_len_to(self, i, cap=100000):
        """number of consecutive (exact-step) bars ending at index i (counted up to `cap`)."""
        n = 1
        while n < cap and i - n >= 0 and self.ts[i - n + 1] - self.ts[i - n] == self.step:
            n += 1
        return n


class SymData:
    """15m bars + RSI, 1h bars + EMA20/EMA50 for one coin."""

    def __init__(self):
        self.s15 = Series(MS15)
        self.s1h = Series(MS1H)
        self.rsi = []
        self.e20 = []
        self.e50 = []

    def rebuild(self, bars15, bars1h):
        self.s15.set_bars(bars15)
        self.s1h.set_bars(bars1h)
        self.rsi = rsi_wilder([b[4] for b in self.s15.bars])
        c1 = [b[4] for b in self.s1h.bars]
        self.e20, self.e50 = ema(c1, EMA_FAST), ema(c1, EMA_SLOW)


class Daily:
    """BTC UTC daily bars + SMA200 of closes (last COMPLETED day as of a time; gaps -> None)."""

    def __init__(self, bars=()):
        self.set_bars(bars)

    def set_bars(self, bars):
        self.bars = sorted({b[0]: b for b in bars}.values())
        self.ts = [b[0] for b in self.bars]
        c = [b[4] for b in self.bars]
        self.sma = [None] * len(c)
        run = 0
        s = 0.0
        for i in range(len(c)):
            run = run + 1 if i and self.ts[i] - self.ts[i - 1] == MS1D else 1
            s += c[i]
            if i >= SMA_DAYS:
                s -= c[i - SMA_DAYS]
            if run >= SMA_DAYS:
                self.sma[i] = s / SMA_DAYS
        # recompute sums exactly (avoid drift) only where valid
        for i in range(len(c)):
            if self.sma[i] is not None:
                self.sma[i] = math.fsum(c[i - SMA_DAYS + 1:i + 1]) / SMA_DAYS

    def regime(self, t_ms):
        """+1 if last completed UTC day close > SMA200, -1 if <, 0 if equal, None if unavailable (history/gap)."""
        j = bisect.bisect_right(self.ts, t_ms - MS1D) - 1       # day open <= t - 1d  <=> day completed by t
        if j < 0 or self.sma[j] is None:
            return None
        c = self.bars[j][4]
        return 1 if c > self.sma[j] else (-1 if c < self.sma[j] else 0)


def htf_trend(sd, t_ms):
    """coin 1h EMA20 vs EMA50 on the last 1h bar CLOSED by t_ms: +1 (20>50), -1 (20<50), 0 equal, None unavailable."""
    j = bisect.bisect_right(sd.s1h.ts, t_ms - MS1H) - 1
    if j < 0 or sd.e50[j] is None:
        return None
    a, b = sd.e20[j], sd.e50[j]
    return 1 if a > b else (-1 if a < b else 0)


def detect(side, sd, daily, i):
    """Signal on the CLOSED 15m bar at index i. Returns (signal_dict | None, reason_if_none). Pure.

    long : BTC regime +1 and coin 1h EMA20>EMA50 and RSI14[i-1] < 30 <= RSI14[i]
    short: BTC regime -1 and coin 1h EMA20<EMA50 and RSI14[i-1] > 70 >= RSI14[i]
    """
    s = sd.s15
    if i < 1 or s.ts[i] - s.ts[i - 1] != MS15:
        return None, "gap_prev_bar"
    p, c = sd.rsi[i - 1], sd.rsi[i]
    trig = cross_up(p, c, RSI_LONG_LEVEL) if side > 0 else cross_down(p, c, RSI_SHORT_LEVEL)
    if not trig:
        return None, None
    t_close = s.ts[i] + MS15
    # warm-up integrity: RSI / EMA history must be contiguous (a gap makes the recursion unreliable) -> log, don't guess
    if s.run_len_to(i, INTEGRITY_15M) < INTEGRITY_15M:
        return None, "gap_15m_history"
    j = bisect.bisect_right(sd.s1h.ts, t_close - MS1H) - 1
    if j < 0 or sd.s1h.run_len_to(j, INTEGRITY_1H) < INTEGRITY_1H:
        return None, "gap_1h_history"
    reg = daily.regime(t_close)
    if reg is None:
        return None, "regime_unavailable"
    tr = htf_trend(sd, t_close)
    if tr is None:
        return None, "trend_unavailable"
    if reg != side or tr != side:
        return None, "filter_regime" if reg != side else "filter_trend"
    return {"rsi_prev": p, "rsi": c, "regime": reg, "ema20": sd.e20[j], "ema50": sd.e50[j],
            "btc_day_close": daily.bars[bisect.bisect_right(daily.ts, t_close - MS1D) - 1][4]}, None


# ---- paper position ------------------------------------------------------------------------------------------------
@dataclass
class Pos:
    strategy: str
    sym: str
    side: int
    signal_ms: int
    entry_bar_ms: int
    entry_open: float
    entry_px: float
    tp: float
    sl: float
    stop_pct: float
    size_mult: float
    wallet_entry: float
    bars_seen: int = 0
    sig: dict = field(default_factory=dict)
    recorded_after_close_s: float | None = None
    cost: float = COST            # round-trip cost used for this trade (0.15%; screen rules H31/H32/H38 use the worse-of rule)
    mode: str = ""

    def key(self):
        return f"{self.strategy}|{self.sym}|{self.signal_ms}"


def manage_bar(pos, bar, max_bars=MAX_BARS):
    """Apply one CLOSED bar (the entry bar first) to an open position. Returns None or
    (exit_px, exit_reason, exit_ms, gap_through). Same bar target+stop -> stop. Time exit at the close of the 16th bar."""
    t, o, h, lo, c = bar
    pos.bars_seen += 1
    gap = False
    if pos.side > 0:
        stop_hit, tp_hit = lo <= pos.sl, h >= pos.tp
        gap = o < pos.sl and t > pos.entry_bar_ms
    else:
        stop_hit, tp_hit = h >= pos.sl, lo <= pos.tp
        gap = o > pos.sl and t > pos.entry_bar_ms
    if stop_hit:
        # STOP_MARKET: a bar that OPENS beyond the stop fills at the open (worse), otherwise at the stop price
        px = min(o, pos.sl) if pos.side > 0 else max(o, pos.sl)
        return px, "stop", t + MS15, gap
    if tp_hit:
        return pos.tp, "target", t + MS15, False
    if pos.bars_seen >= max_bars:
        return c, "time", t + MS15, False
    return None


def trade_record(pos, exit_px, reason, exit_ms, gap_through, wallet_after, pnl_wallet, funding=0.0):
    gross = pos.side * (exit_px - pos.entry_px) / pos.entry_px
    den = pos.stop_pct + COST
    return {
        "id": pos.key(), "strategy": pos.strategy, "symbol": pos.sym, "side": "long" if pos.side > 0 else "short",
        "signal_bar_open_ms": pos.signal_ms, "signal_close_ms": pos.signal_ms + MS15,
        "entry_bar_open_ms": pos.entry_bar_ms, "entry_open": pos.entry_open, "entry_px": pos.entry_px,
        "tp": pos.tp, "sl": pos.sl, "stop_pct": pos.stop_pct, "size_mult": pos.size_mult, "wallet_entry": pos.wallet_entry,
        "exit_ms": exit_ms, "exit_px": exit_px, "exit_reason": reason, "bars_held": pos.bars_seen,
        "gross_ret": gross, "cost_rt": pos.cost, "funding_ret": funding,
        "net_ret_c015": gross - pos.cost - funding, "net_ret_c030": gross - 2 * pos.cost - funding,
        "r_c015": (gross - pos.cost - funding) / den, "r_c030": (gross - 2 * pos.cost - funding) / den,
        "pnl_wallet_frac": pnl_wallet, "wallet_after": wallet_after, "stop_gap_through": gap_through,
        "signal": pos.sig, "recorded_after_close_s": pos.recorded_after_close_s,
    }


# ---- rule plug-in point -----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    """What step() needs to know about one entry rule: its side, its bar-level detector and its exit parameters.
    `detect(side, sd, daily, i) -> (signal_dict | None, reason_if_none)` must be pure and use CLOSED bars only.
    The H34-B values are the locked ones; a new rule is added by registering another Rule (see h34_paper/rules.py)."""
    name: str
    side: int
    detect: object
    target: float = TARGET
    stop: float = STOP
    max_bars: int = MAX_BARS


H34B_RULES = {1: Rule("H34-B", 1, detect), -1: Rule("H34-B-S", -1, detect)}


# ---- book: wallet, sizing, daily cap (one per direction; long and short are judged separately) ----------------------
class Book:
    def __init__(self, side, wallet0=1.0, strategy=None, risk=RISK, daily_cap=DAILY_CAP, max_mult=MAX_MULT, rule=None):
        self.side = side
        self.strategy = strategy or STRATEGY[side]
        self.rule = rule or H34B_RULES[side]
        self.wallet = wallet0
        self.risk, self.daily_cap, self.max_mult = risk, daily_cap, max_mult
        self.day = None
        self.day_start_wallet = wallet0
        self.day_pnl = 0.0           # confirmed realised pnl (wallet units) on the current KST day
        self.pos = {}                # sym -> Pos
        self.done = set()            # trade ids already closed (idempotency)

    # sizing: notional multiple of wallet = risk / (stop width + cost)
    def size_mult(self, stop_pct):
        return min(self.risk / (stop_pct + COST), self.max_mult)

    def _roll(self, ts_ms):
        d = kst_day(ts_ms)
        if d != self.day:
            self.day, self.day_start_wallet, self.day_pnl = d, self.wallet, 0.0

    def entry_blocked(self, ts_ms):
        """True when the KST day's confirmed (realised) net loss has reached the cap (>= 5% of the day-start wallet)."""
        self._roll(ts_ms)
        return self.day_pnl <= -self.daily_cap * self.day_start_wallet

    def open(self, pos):
        self.pos[pos.sym] = pos

    def close(self, pos, exit_px, reason, exit_ms, gap, funding=0.0):
        """Realise: pnl = size_mult * wallet_entry * net_ret. Returns the ledger record."""
        self._roll(exit_ms)
        gross = pos.side * (exit_px - pos.entry_px) / pos.entry_px
        pnl = pos.size_mult * pos.wallet_entry * (gross - pos.cost - funding)
        self.wallet += pnl
        self.day_pnl += pnl
        self.pos.pop(pos.sym, None)
        self.done.add(pos.key())
        return trade_record(pos, exit_px, reason, exit_ms, gap, self.wallet, pnl / pos.wallet_entry, funding)

    # ---- state (JSON-safe) for restart safety
    def to_state(self):
        return {"side": self.side, "wallet": self.wallet, "day": self.day, "day_start_wallet": self.day_start_wallet,
                "day_pnl": self.day_pnl, "pos": {k: _pos_to_dict(p) for k, p in self.pos.items()},
                "done": sorted(self.done)}

    @classmethod
    def from_state(cls, d, **kw):
        b = cls(d["side"], wallet0=d["wallet"], **kw)
        b.day, b.day_start_wallet, b.day_pnl = d["day"], d["day_start_wallet"], d["day_pnl"]
        b.pos = {k: Pos(**v) for k, v in d["pos"].items()}
        b.done = set(d["done"])
        return b


def _pos_to_dict(p):
    return {k: getattr(p, k) for k in p.__dataclass_fields__}


# ---- one global step per closed-bar time T -------------------------------------------------------------------------
def step(T, books, data, daily, emit, recorded_at_ms=None, gate=None, coins=COINS):
    """Process the closed 15m bar that OPENED at T for every book/coin. Deterministic: same inputs -> same outputs.

    phase 1: manage open positions with bar T (exit at its close). phase 2: detect on bar T, enter at the NEXT bar's open
    (T+15m) +/- 1 tick adverse, unless a position is open for that coin, the daily cap is hit, or the next bar is missing.
    emit(kind, key, record): kind in {'trade','event'}; the sink must be idempotent on key."""
    t_close = T + MS15
    for b in books:
        for sym in sorted(b.pos):
            pos = b.pos[sym]
            i = data[sym].s15.idx(T)
            if i is None:
                emit("event", f"gap_pos|{b.strategy}|{sym}|{T}",
                     {"event": "missing_bar_while_position_open", "strategy": b.strategy, "symbol": sym, "bar_open_ms": T,
                      "trade_id": pos.key()})
                continue                       # never guess the exit: position stays open, flagged
            r = manage_bar(pos, data[sym].s15.bars[i], b.rule.max_bars)
            if r is not None:
                rec = b.close(pos, *r[:3], r[3])
                emit("trade", rec["id"], rec)
    for b in books:
        for sym in coins:
            sd = data[sym]
            i = sd.s15.idx(T)
            if i is None:
                emit("event", f"gap_bar|{b.strategy}|{sym}|{T}",
                     {"event": "missing_signal_bar", "strategy": b.strategy, "symbol": sym, "bar_open_ms": T})
                continue
            sig, why = b.rule.detect(b.side, sd, daily, i)
            if sig is None:
                if why and why.startswith(("gap", "regime_un", "trend_un")):
                    emit("event", f"skip|{b.strategy}|{sym}|{T}|{why}",
                         {"event": "signal_skipped_integrity", "reason": why, "strategy": b.strategy, "symbol": sym,
                          "signal_bar_open_ms": T})
                continue
            base = {"strategy": b.strategy, "symbol": sym, "signal_bar_open_ms": T, "signal_close_ms": t_close, "signal": sig}
            if sym in b.pos:
                emit("event", f"skip|{b.strategy}|{sym}|{T}|open_position",
                     {**base, "event": "signal_skipped", "reason": "open_position"})
                continue
            j = sd.s15.idx(t_close)
            if j is None:
                emit("event", f"skip|{b.strategy}|{sym}|{T}|no_entry_bar",
                     {**base, "event": "signal_skipped", "reason": "next_bar_missing"})
                continue
            if b.entry_blocked(t_close):
                emit("event", f"skip|{b.strategy}|{sym}|{T}|daily_cap",
                     {**base, "event": "signal_skipped", "reason": "daily_cap_5pct_kst",
                      "day_pnl": b.day_pnl, "day_start_wallet": b.day_start_wallet})
                continue
            o = sd.s15.bars[j][1]
            tick = TICK[sym]
            px = o + b.side * tick                       # next-bar open, 1 tick adverse (TA lock)
            tp, sl = px * (1 + b.side * b.rule.target), px * (1 - b.side * b.rule.stop)
            pos = Pos(b.strategy, sym, b.side, T, t_close, o, px, tp, sl, b.rule.stop, b.size_mult(b.rule.stop), b.wallet, 0, sig,
                      None if recorded_at_ms is None else (recorded_at_ms - t_close) / 1000.0)
            if gate is not None:                       # portfolio limits (engine layer); None = screen behaviour
                why = gate(b, pos, t_close)
                if why is not None:
                    emit("event", f"skip|{b.strategy}|{sym}|{T}|{why['reason']}",
                         {**base, "event": "signal_skipped", "reason": why["reason"], "limit": why, "would_be_entry_px": px,
                          "would_be_size_mult": pos.size_mult})
                    continue
            b.open(pos)
            emit("event", f"entry|{b.strategy}|{sym}|{T}",
                 {**base, "event": "paper_entry", "entry_bar_open_ms": t_close, "entry_open": o, "entry_px": px, "tp": tp,
                  "sl": sl, "size_mult": pos.size_mult, "wallet_entry": b.wallet,
                  "recorded_after_close_s": pos.recorded_after_close_s})
