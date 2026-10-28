"""One-time historical screen engines for H31, H32, H31-S, H32-S, H34-A, H35, H36, H38 (research venv: pandas/numpy/pyarrow).
H34-B / H34-B-S use core.step (the recorder's code). All engines emit raw trades; `account()` applies the same sizing / daily-cap
Book as the recorder. Rules are copied from the QR files named in the results note; nothing tuned.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import core
from .core import COST, MS15, MS1H, MS1D, TICK, Book, Daily, Pos

P = "/workspace/trade-bot-research/data/parquet/"
MS4H = 4 * MS1H
COST_STOP_WORSE = 0.0017      # screen file H31/H32/H38: 0.05%x2 fee + 2bp x2 slippage (=0.14%) + 3bp on stop fills
SIX = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
INTEG = 100                   # data-integrity: signals need this many gap-free bars behind them (not a strategy parameter)


# ------------------------------------------------------------------ indicators (pandas, = research/indicators.py)
def rma(x, n):
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def atr14(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return rma(tr, n)


def adx14(df, n=14):
    up = df["high"].diff()
    dn = -df["low"].diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr14(df, n)
    pdi, ndi = 100 * rma(pdm, n) / a, 100 * rma(ndm, n) / a
    return rma(100 * (pdi - ndi).abs() / (pdi + ndi), n)


def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def ms_index(idx):
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return ((idx - pd.Timestamp("1970-01-01")) // pd.Timedelta(milliseconds=1)).to_numpy().astype("int64")


class Bars:
    """OHLC arrays + indicators for one coin/timeframe, built from a parquet frame indexed by open time."""

    def __init__(self, df, tf_ms):
        df = df[["open", "high", "low", "close"]].astype(float).sort_index()
        if os.environ.get("H34_SMOKE_FROM"):                       # smoke tests only (never set for the official run)
            df = df[df.index >= pd.Timestamp(os.environ["H34_SMOKE_FROM"], tz=df.index.tz)]
        self.tf = tf_ms
        self.ts = ms_index(df.index)
        self.o, self.h, self.l, self.c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        self.n = len(df)
        self.e20, self.e50 = ema(df.close, 20).to_numpy(), ema(df.close, 50).to_numpy()
        self.atr = atr14(df).to_numpy()
        self.adx = adx14(df).to_numpy()
        self.rsi = np.array([np.nan if v is None else v for v in core.rsi_wilder(df.close.tolist())])
        d = np.diff(self.ts)
        run = np.ones(self.n, dtype=np.int64)
        for i in range(1, self.n):
            run[i] = run[i - 1] + 1 if d[i - 1] == tf_ms else 1
        self.run = run
        self.gaps = int((d != tf_ms).sum())

    def idx_closed_at(self, t_ms):
        """index of the last bar CLOSED by t_ms (array-friendly)."""
        return np.searchsorted(self.ts, np.asarray(t_ms) - self.tf, side="right") - 1


def load_bars(sym, tf):
    t = {"1h": "v7_um_1h", "4h": "v7_um_4h"}[tf]
    d = pd.read_parquet(P + t + ".parquet", columns=["ts", "open", "high", "low", "close"], filters=[("sym", "=", sym)])
    return Bars(d.set_index("ts"), MS1H if tf == "1h" else MS4H)


def load_funding(sym):
    d = pd.read_parquet(P + "v3_um_funding.parquet", columns=["ts", "rate"], filters=[("sym", "=", sym)]).sort_values("ts")
    return ms_index(pd.DatetimeIndex(d.ts)), d.rate.to_numpy().astype(float)


def funding_ret(fund, side, entry_ms, exit_ms):
    """funding paid as a fraction of notional: sum of settled rates with entry < stamp <= exit; long pays +rate, short receives."""
    ts, r = fund
    a, b = np.searchsorted(ts, entry_ms, side="right"), np.searchsorted(ts, exit_ms, side="right")
    return float(side * r[a:b].sum())


# ------------------------------------------------------------------ generic bar engine
def run_engine(sym, B, desired, exit_fn, reverse, stop_cost, tick, long_only_cap=None):
    """Closed-bar signals -> entry at NEXT bar open +/-1 tick adverse; stop (and optional TP) intrabar, same bar -> stop first
    (stop fills at the bar open when the bar opens beyond it); signal exits and reversals execute at the next bar open; time exit
    at the close of the max_bars-th bar. desired(i) -> None | dict(side, sl_dist, tp_dist|None, min_stop_pct, max_bars, mode).
    Returns (raw trades list, skipped_small_stop count)."""
    out, skipped = [], 0
    pos = None
    pend_exit = False
    pend_entry = None
    n = B.n
    for i in range(n):
        if pend_exit and pos is not None:
            out.append(_raw(sym, pos, B.o[i], "signal_exit", B.ts[i], False, stop_cost))
            pos = None
        pend_exit = False
        if pend_entry is not None and pos is None:
            d, si = pend_entry
            px = B.o[i] + d["side"] * tick
            sld = d["sl_pct"] * px if "sl_pct" in d else d["sl_dist"]
            tpd = (d["tp_pct"] * px if "tp_pct" in d else d["tp_dist"])
            if sld / px < d["min_stop_pct"]:
                skipped += 1
            else:
                pos = dict(side=d["side"], entry_i=i, entry_ms=int(B.ts[i]), px=px, open=B.o[i], sl=px - d["side"] * sld,
                           tp=None if tpd is None else px + d["side"] * tpd, stop_pct=sld / px,
                           max_bars=d["max_bars"], mode=d.get("mode", ""), sig_ms=int(B.ts[si]), sig_close=int(B.ts[si] + B.tf), seen=0)
        pend_entry = None
        if pos is not None:
            pos["seen"] += 1
            s = pos["side"]
            o, h, l, c = B.o[i], B.h[i], B.l[i], B.c[i]
            sl_hit = (l <= pos["sl"]) if s > 0 else (h >= pos["sl"])
            tp_hit = pos["tp"] is not None and ((h >= pos["tp"]) if s > 0 else (l <= pos["tp"]))
            end = int(B.ts[i] + B.tf)
            if sl_hit:
                px = min(o, pos["sl"]) if s > 0 else max(o, pos["sl"])
                out.append(_raw(sym, pos, px, "stop", end, (o < pos["sl"]) if s > 0 else (o > pos["sl"]), stop_cost))
                pos = None
            elif tp_hit:
                out.append(_raw(sym, pos, pos["tp"], "target", end, False, stop_cost))
                pos = None
            elif pos["max_bars"] is not None and pos["seen"] >= pos["max_bars"]:
                out.append(_raw(sym, pos, c, "time", end, False, stop_cost))
                pos = None
        if i + 1 < n:
            d = desired(i)
            if pos is not None:
                if exit_fn is not None and exit_fn(i, pos["side"]):
                    pend_exit = True
                if reverse and d is not None and d["side"] != pos["side"]:
                    pend_exit, pend_entry = True, (d, i)
            elif d is not None:
                pend_entry = (d, i)
    if pos is not None:
        out.append(_raw(sym, pos, B.c[n - 1], "end_of_data", int(B.ts[n - 1] + B.tf), False, stop_cost))
    return out, skipped


def _raw(sym, pos, exit_px, reason, exit_ms, gap, stop_cost):
    cost = COST_STOP_WORSE if (stop_cost and reason == "stop") else COST
    return dict(sym=sym, side=pos["side"], entry_ms=pos["entry_ms"], exit_ms=int(exit_ms), entry_px=pos["px"], entry_open=pos["open"],
                exit_px=float(exit_px), reason=reason, stop_pct=pos["stop_pct"], cost=cost, gap_through=bool(gap),
                sig_ms=pos["sig_ms"], sig_close=pos["sig_close"], mode=pos["mode"], tp=pos["tp"], sl=pos["sl"], bars=pos["seen"])


# ------------------------------------------------------------------ accounting (same Book as the recorder)
def account(raws, strategy, fund=None, wallet0=1.0):
    """Sequential wallet / sizing / 5% KST daily cap over raw trades of ONE rule (exits before entries at equal time).
    Entries blocked by the cap are dropped (no re-simulation of the coin path). Returns (ledger list, blocked count)."""
    book = Book(1, wallet0=wallet0, strategy=strategy)
    ev = []
    for k, r in enumerate(raws):
        ev.append((r["entry_ms"], 1, k))
        ev.append((r["exit_ms"], 0, k))
    ev.sort()
    live, ledger, blocked = {}, [], 0
    for t, kind, k in ev:
        r = raws[k]
        if kind == 1:
            if book.entry_blocked(t):
                blocked += 1
                continue
            pos = Pos(strategy, r["sym"], r["side"], r["sig_ms"], r["entry_ms"], r["entry_open"], r["entry_px"],
                      r["tp"] if r["tp"] is not None else float("nan"), r["sl"], r["stop_pct"], book.size_mult(r["stop_pct"]),
                      book.wallet, 0, {}, None, r["cost"], r.get("mode", ""))
            live[k] = pos
            book.pos[(r["sym"], k)] = pos   # per-trade key: several trades may overlap (cap applies to entries only)
        else:
            pos = live.pop(k, None)
            if pos is None:
                continue
            f = 0.0 if fund is None else funding_ret(fund[r["sym"]], r["side"], r["entry_ms"], r["exit_ms"])
            pos.bars_seen = r["bars"]
            rec = book.close(pos, r["exit_px"], r["reason"], r["exit_ms"], r["gap_through"], f)
            book.pos.pop((r["sym"], k), None)
            rec["mode"] = r.get("mode", "")
            rec["rule_side"] = r["side"]
            rec["sig_ms"] = r["sig_ms"]
            ledger.append(rec)
    return ledger, blocked


# ------------------------------------------------------------------ rule definitions
def regime_fn(daily):
    return lambda t_ms: daily.regime(int(t_ms))


def make_h31(B, daily, short):
    rg = [daily.regime(int(t + B.tf)) for t in B.ts]
    nan = np.isnan

    def desired(i):
        if i < 1 or B.run[i] < INTEG or nan(B.rsi[i]) or nan(B.rsi[i - 1]) or nan(B.e50[i]) or nan(B.atr[i]):
            return None
        if not short:
            if rg[i] != 1 or not B.e20[i] > B.e50[i] or not (B.rsi[i - 1] < 40 <= B.rsi[i]):
                return None
        else:
            if not B.e20[i] < B.e50[i] or not (B.rsi[i - 1] > 60 >= B.rsi[i]):
                return None
        return dict(side=-1 if short else 1, sl_dist=2 * B.atr[i], tp_dist=None, min_stop_pct=0.004, max_bars=48)

    def exit_fn(i, side):
        if side > 0:
            return B.c[i] < B.e50[i] or B.rsi[i] > 70
        return B.c[i] > B.e50[i] or B.rsi[i] < 30
    return desired, exit_fn


def make_h32(B, daily, short):
    rg = [daily.regime(int(t + B.tf)) for t in B.ts]
    nan = np.isnan

    def desired(i):
        if i < 1 or B.run[i] < INTEG or nan(B.e50[i - 1]) or nan(B.rsi[i]) or nan(B.atr[i]):
            return None
        if not short:
            ok = rg[i] == 1 and B.e20[i] > B.e50[i] and B.e20[i - 1] <= B.e50[i - 1] and B.rsi[i] > 50
        else:
            ok = B.e20[i] < B.e50[i] and B.e20[i - 1] >= B.e50[i - 1] and B.rsi[i] < 50
        return dict(side=-1 if short else 1, sl_dist=2 * B.atr[i], tp_dist=None, min_stop_pct=0.004, max_bars=None) if ok else None

    def exit_fn(i, side):
        return (B.e20[i] < B.e50[i]) if side > 0 else (B.e20[i] > B.e50[i])
    return desired, exit_fn


def make_h35(B):
    nan = np.isnan
    state = np.where(B.e20 > B.e50, 1, -1)
    valid = ~nan(B.e50)

    def desired(i):
        if not valid[i] or B.run[i] < INTEG or nan(B.atr[i]):
            return None
        if i > 0 and valid[i - 1] and state[i] == state[i - 1]:
            return None
        return dict(side=int(state[i]), sl_dist=2 * B.atr[i], tp_dist=None, min_stop_pct=0.004, max_bars=None)
    return desired


def make_h36(B):
    hh = pd.Series(B.h).rolling(20).max().shift().to_numpy()
    ll = pd.Series(B.l).rolling(20).min().shift().to_numpy()
    nan = np.isnan

    def desired(i):
        if nan(hh[i]) or B.run[i] < INTEG or nan(B.atr[i]):
            return None
        s = 1 if B.c[i] > hh[i] else (-1 if B.c[i] < ll[i] else 0)
        return dict(side=s, sl_dist=2 * B.atr[i], tp_dist=None, min_stop_pct=0.004, max_bars=None) if s else None
    return desired


def make_h38(B15, B1h, B4h):
    """15m engine; mode by last closed 4h ADX14; direction rule per mode, evaluated each closed 15m bar when flat."""
    j1 = B1h.idx_closed_at(B15.ts + MS15)
    j4 = B4h.idx_closed_at(B15.ts + MS15)
    nan = np.isnan

    def desired(i):
        if B15.run[i] < INTEG or nan(B15.rsi[i]):
            return None
        k4 = j4[i]
        if k4 < 0 or nan(B4h.adx[k4]) or B4h.run[k4] < INTEG:
            return None
        a = B4h.adx[k4]
        px = B15.c[i]
        if a < 20:
            side = 1 if B15.rsi[i] < 50 else -1
            return dict(side=side, sl_pct=0.005, tp_pct=0.005, min_stop_pct=0.004, max_bars=16, mode="SHORT")
        if a < 30:
            k = j1[i]
            if k < 0 or nan(B1h.e50[k]) or nan(B1h.atr[k]) or B1h.run[k] < INTEG:
                return None
            side = 1 if B1h.e20[k] > B1h.e50[k] else -1
            return dict(side=side, sl_dist=1.5 * B1h.atr[k], tp_dist=2.0 * B1h.atr[k], min_stop_pct=0.004, max_bars=96, mode="MID")
        if nan(B4h.e50[k4]) or nan(B4h.atr[k4]):
            return None
        side = 1 if B4h.e20[k4] > B4h.e50[k4] else -1
        return dict(side=side, sl_dist=2.0 * B4h.atr[k4], tp_dist=3.0 * B4h.atr[k4], min_stop_pct=0.004, max_bars=480, mode="LONG")
    return desired


# ------------------------------------------------------------------ H34-A (4h, intrabar entry on 1m path)
def load_1m(sym):
    d = pd.read_parquet(P + "v7_six_1m.parquet", columns=["ts", "open", "high", "low", "close"], filters=[("sym", "=", sym)])
    d = d.set_index("ts").sort_index()
    if os.environ.get("H34_SMOKE_FROM"):
        d = d[d.index >= pd.Timestamp(os.environ["H34_SMOKE_FROM"], tz=d.index.tz)]
    return ms_index(d.index), d.open.to_numpy().astype(float), d.high.to_numpy().astype(float), d.low.to_numpy().astype(float)


def funding_flags(sym, short):
    """H7 funding filter at each funding stamp: long blocked if F3>=p95(90d) and F3>1bp; short (lock h34: same threshold magnitude, negative): F3<=-p95
    and F3<-1bp. Returns (stamp_ms, blocked bool)."""
    d = pd.read_parquet(P + "v3_um_funding.parquet", columns=["ts", "rate"], filters=[("sym", "=", sym)]).sort_values("ts")
    f = d.set_index("ts").rate.dropna()
    iv = (f.index.to_series().diff().dt.total_seconds() / 3600).round().fillna(8).clip(lower=1)
    fn = f * 8 / iv
    f3 = fn.rolling(3).mean()
    if not short:
        p = fn.rolling("90D", min_periods=100).quantile(0.95)
        crowd = (f3 >= p) & (f3.round(10) > 0.0001)
    else:
        p = fn.rolling("90D", min_periods=100).quantile(0.95)     # lock h34 L21: same threshold MAGNITUDE, negative sign
        crowd = (f3 <= -p) & (f3.round(10) < -0.0001)
    return ms_index(crowd.index), crowd.fillna(False).to_numpy(bool)


def run_h34a(sym, B4, daily, short, m1):
    t1, o1, h1, l1 = m1
    tick = TICK[sym]
    cts, cflag = funding_flags(sym, short)
    side = -1 if short else 1
    hh = pd.Series(B4.h).rolling(55).max().shift().to_numpy()
    ll = pd.Series(B4.l).rolling(55).min().shift().to_numpy()
    lo20 = pd.Series(B4.l).rolling(20).min().shift().to_numpy()
    hi20 = pd.Series(B4.h).rolling(20).max().shift().to_numpy()
    A = np.searchsorted(t1, B4.ts)
    Z = np.searchsorted(t1, B4.ts + MS4H)
    out, skip_small, n = [], 0, B4.n
    pos, pend_exit = None, False

    def crowd_at(t):
        k = np.searchsorted(cts, t, side="right") - 1
        return bool(cflag[k]) if k >= 0 else False

    def scan(m0, z, first):
        """first stop/target minute in [m0,z): stop first on the same minute. Returns (px, reason, minute_index) or None."""
        lo, hi = l1[m0:z], h1[m0:z]
        if side > 0:
            s_idx, t_idx = np.flatnonzero(lo <= pos["sl"]), np.flatnonzero(hi >= pos["tp"])
        else:
            s_idx, t_idx = np.flatnonzero(hi >= pos["sl"]), np.flatnonzero(lo <= pos["tp"])
        si = s_idx[0] if len(s_idx) else None
        ti = t_idx[0] if len(t_idx) else None
        if si is not None and (ti is None or si <= ti):
            m = m0 + si
            px = pos["sl"] if m == first else (min(o1[m], pos["sl"]) if side > 0 else max(o1[m], pos["sl"]))
            return px, "stop", m
        if ti is not None:
            return pos["tp"], "target", m0 + ti
        return None

    for i in range(n):
        a, z = A[i], Z[i]
        has1m = z > a and t1[a] == B4.ts[i] and (z - a) == 240
        if pend_exit and pos is not None:
            out.append(_raw(sym, pos, B4.o[i], "signal_exit", B4.ts[i], False, False)); pos = None
        pend_exit = False
        stopped = False
        if pos is not None:
            if has1m:
                r = scan(a, z, -1)
                end = int(t1[r[2]] + 60_000) if r else None
            else:                                    # 1m gap bar: fall back to the 4h bar (stop first), flagged
                lo, hi = B4.l[i], B4.h[i]
                sh = (lo <= pos["sl"]) if side > 0 else (hi >= pos["sl"])
                th = (hi >= pos["tp"]) if side > 0 else (lo <= pos["tp"])
                r = ((min(B4.o[i], pos["sl"]) if side > 0 else max(B4.o[i], pos["sl"])), "stop", None) if sh else \
                    ((pos["tp"], "target", None) if th else None)
                pos["gap"] = True
                end = int(B4.ts[i] + MS4H) if r else None
            if r:
                rr = _raw(sym, pos, r[0], r[1], end, False, False); rr["gap_through"] = bool(pos.get("gap")); out.append(rr)
                pos = None; stopped = True
        reg = daily.regime(int(B4.ts[i]))
        want = (reg == -1) if short else (reg == 1)
        L = ll[i] if short else hh[i]
        if pos is None and not stopped and has1m and i >= 55 and not np.isnan(L) and want and B4.run[i - 1] >= INTEG \
                and not np.isnan(B4.atr[i - 1]) and B4.atr[i - 1] > 0:
            trig = L - tick if short else L + tick
            cand = a + np.flatnonzero((l1[a:z] <= trig + 1e-12) if short else (h1[a:z] >= trig - 1e-12))
            for m in cand:
                if crowd_at(t1[m]):
                    continue
                px = (min(L, o1[m]) - tick) if short else (max(L, o1[m]) + tick)
                atr = B4.atr[i - 1]
                if atr / px < 0.0045:
                    skip_small += 1
                    continue
                pos = dict(side=side, entry_i=i, entry_ms=int(t1[m]), px=px, open=o1[m], sl=px - side * atr, tp=px + side * atr,
                           stop_pct=atr / px, max_bars=None, mode="", sig_ms=int(t1[m]), sig_close=int(t1[m]), seen=0)
                r = scan(m, z, m)
                if r:
                    out.append(_raw(sym, pos, r[0], r[1], int(t1[r[2]] + 60_000), False, False)); pos = None
                break
        if pos is not None:
            pos["seen"] += 1
            if (B4.c[i] > hi20[i]) if short else (B4.c[i] < lo20[i]):
                if not np.isnan(hi20[i] if short else lo20[i]):
                    pend_exit = True
    if pos is not None:
        out.append(_raw(sym, pos, B4.c[n - 1], "end_of_data", int(B4.ts[n - 1] + MS4H), False, False))
    return out, skip_small
