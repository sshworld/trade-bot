"""H46/H47 screen -- research-dependent part: loaders, coin-month coverage, the v8 engine call, raw-trade conversion.
Reuses research/v8.engine + SymPrep (the H7-T engine path) UNCHANGED; nothing from the research tree is copied except the
per-month tick estimate for symbols absent from the exchangeInfo snapshot (inline in research/v8_run.h16_symbol).
Run with /workspace/.venv-live6/bin/python; parquet reads are symbol-filtered (a full load is OOM-killed)."""
from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from . import h46 as H
from .screen import funding_ret

RESEARCH_ROOT = Path(os.environ.get("TRADE_BOT_RESEARCH", "/workspace/trade-bot-research"))
PQ = RESEARCH_ROOT / "data" / "parquet"
MEMBERSHIP = RESEARCH_ROOT / "results/ops/universe_h46_membership_mean_2026-10-28.csv"
MEMBERSHIP_SHA = "d5eb81db7c9d8cec09a281a8b5ae3502338534d2437fae9d097fce96bb7c80ad"
H16_UNIVERSE = RESEARCH_ROOT / "results/v8/universe/universe_top20_monthly_v1_1.csv"
H1_FILES = ["v7_um_1h.parquet", "h12h13_extra_1h.parquet", "h16_um_1h.parquet", "h46_um_1h.parquet"]
M1_FILES = ["h16_um_1m.parquet", "h46_um_1m.parquet"]          # non-six coins; the six use research v7_six_1m (v8.load_1m)
FUND_FILES = ["v7_um_funding.parquet", "h12h13_extra_funding.parquet", "h16_um_funding.parquet", "h16_d1_funding.parquet",
              "h46_um_funding.parquet"]
MONTHS = [f"{y}-{m:02d}" for y in range(2021, 2027) for m in range(1, 13) if (y, m) <= (2026, 9)]
H4N, H1N, M1N = np.timedelta64(4, "h"), np.timedelta64(1, "h"), np.timedelta64(1, "m")
_V8 = None


def research(replay=False):
    """import research.v8 (shim for the modules the live6 venv lacks and the engine never uses: matplotlib/requests/scipy).
    replay=True imports research.h7t_replay_0d82b19 FIRST (it re-points v8 at the live rules/sizing worktree; order matters)."""
    global _V8
    if _V8 is not None:
        return _V8
    for m in ("matplotlib", "matplotlib.pyplot", "requests", "scipy", "scipy.stats"):
        try:
            importlib.import_module(m)
        except Exception:
            sys.modules[m] = mock.MagicMock()
    if str(RESEARCH_ROOT) not in sys.path:
        sys.path.insert(0, str(RESEARCH_ROOT))
    if replay:
        importlib.import_module("research.h7t_replay_0d82b19")
    _V8 = importlib.import_module("research.v8")
    return _V8


# ------------------------------------------------------------------ loaders (symbol-filtered)
def load_1h(sym):
    v8 = research()
    if sym in v8.SIX:
        return v8.v3.data(sym)[0]
    t = v8._cat(H1_FILES, sym, ["ts", "open", "high", "low", "close", "volume"])
    t = t.drop_duplicates("ts").set_index("ts").sort_index()
    t.index = pd.DatetimeIndex(t.index).astype("datetime64[ns]")
    return t[t.index < v8.END]


def load_funding(sym):
    v8 = research()
    if sym in v8.SIX:
        return v8.v3.data(sym)[1]
    t = v8._cat(FUND_FILES, sym, ["ts", "rate"])
    s = t.drop_duplicates("ts").set_index("ts").sort_index()["rate"]
    s.index = pd.DatetimeIndex(s.index).astype("datetime64[ns]")
    return s


def load_1m(sym):
    """1m bars. Six coins: v8.load_1m (v7_six_1m). Other coins: M1_FILES (h16 + h46 downloads), symbol-filtered reads, concatenated in
    file order, duplicate ts dropped (first file wins), clipped at v8.END (2026-09-30 end clip). None when there is no data."""
    v8 = research()
    if sym in v8.SIX:
        try:
            k = v8.load_1m(sym)
        except Exception:
            return None
        return k if len(k) else None
    cols = ["ts", "open", "high", "low", "close", "volume"]
    t = v8._cat(M1_FILES, sym, cols)             # symbol-filtered per file (v8._cat reads PQ = research data/parquet)
    if not len(t):
        return None
    k = t.drop_duplicates("ts").set_index("ts").sort_index()
    k.index = pd.DatetimeIndex(k.index).astype("datetime64[ns]")
    k = k[k.index < v8.END]
    return k if len(k) else None


def crowd_short_mirror(f):
    """QR short mirror: skip a short if F3 <= p5 (90d, min 100 settlements) AND F3 < -0.0001 (v8.crowd_short uses F3 < 0 -> NOT used)."""
    v8 = research()
    fn = v8.funding_norm_s(f)
    f3 = fn.rolling(3).mean()
    p5 = fn.rolling("90D", min_periods=H.FUND_WARMUP_OBS).quantile(0.05)
    return (f3 <= p5) & (f3.round(10) < -0.0001)


# ------------------------------------------------------------------ coverage
def _month_counts(idx):
    m = np.asarray(idx.to_numpy()).astype("datetime64[ns]").astype("datetime64[M]")
    u, c = np.unique(m, return_counts=True)
    return {str(a): int(b) for a, b in zip(u, c)}


def month_cov(idx, step, month):
    """fraction of bars present in `month` (UTC) of the hours/minutes expected until the data end (month fully after the data end =
    full month expected -> 0). The expected window starts at max(month start, first bar) (a listing inside the month is not penalised)."""
    if idx is None or not len(idx):
        return 0.0, 0
    t0 = np.datetime64(month + "-01", "ns")
    t1 = (np.datetime64(month, "M") + np.timedelta64(1, "M")).astype("datetime64[ns]")
    first, last = idx.to_numpy()[0].astype("datetime64[ns]"), idx.to_numpy()[-1].astype("datetime64[ns]")
    a = max(t0, first)
    b = min(t1, last + step) if last + step > t0 else t1
    exp = max(int((b - a) / step), 0)
    if exp == 0:
        return 0.0, 0
    n = _month_counts(idx).get(month, 0)
    return min(n / exp, 1.0), n


def coverage_rows(sym, k1h, k1, f, intrabar):
    """per member-month coverage + the exclusion decision (reason string, '' = ok)."""
    cnt = None
    if len(f):
        fs = pd.Series(1.0, index=f.index)
        cnt = fs.rolling("90D").count()
    rows = []
    fc = _month_counts(f.index) if len(f) else {}
    for m in MONTHS:
        c1, n1 = month_cov(k1h.index, H1N, m)
        cm = None
        if intrabar == "1m":
            cm, _ = month_cov(k1.index if k1 is not None else None, M1N, m)
        nf = fc.get(m, 0)
        warm = 0
        if cnt is not None and len(cnt):
            t0 = pd.Timestamp(m + "-01")
            j = cnt.index.searchsorted(t0, side="left") - 1
            warm = int(cnt.iloc[j]) if j >= 0 else 0
        why = []
        if c1 < H.COV_MIN:
            why.append(f"1h_cov {c1:.3f}")
        if intrabar == "1m" and (cm or 0) < H.COV_MIN:
            why.append(f"1m_cov {cm or 0:.3f}")
        if nf < H.FUND_MIN_OBS:
            why.append(f"funding_obs {nf}")
        if warm < H.FUND_WARMUP_OBS:
            why.append(f"funding_warmup {warm}")
        rows.append(dict(sym=sym, month=m, h1_cov=c1, m1_cov=cm, funding_obs=nf, funding_warmup=warm, ok=not why, why="; ".join(why)))
    return rows


def has_hole(idx, step, w0, w1):
    """frame has data before the window and fewer bars inside [w0, w1) than the window holds."""
    t = idx.to_numpy().astype("datetime64[ns]")
    if not len(t) or t[0] >= w0:
        return False
    a, b = np.searchsorted(t, w0), np.searchsorted(t, w1)
    return (b - a) < int((w1 - w0) / step)


def hole_windows(sym, idx, step):
    v8 = research()
    ws = []
    for a, b in H.HOLES:
        w0, w1 = np.datetime64(a, "ns"), np.datetime64(b, "ns")
        if (sym in v8.H7T_GAPS) or has_hole(idx, step, w0, w1):
            ws.append((w0, w1))
    return ws


# ------------------------------------------------------------------ engine
def tick_info(sym, k1, bt):
    """tick (float or per-4h-bar array) like research/v8_run.h16_symbol: exchangeInfo tick when TRADING, else the per-month price step."""
    v8 = research()
    if not v8.delisted(sym):
        return float(v8.rules_for(sym).tick_size)
    ticks = {}
    for m, g in k1.groupby(k1.index.strftime("%Y-%m")):
        px = np.unique(np.round(np.concatenate([g.open, g.high, g.low, g.close]), 10))
        dd = np.diff(px)
        dd = dd[dd > 1e-12]
        ticks[m] = float(np.round(dd.min(), 12)) if len(dd) else np.nan
    tk = np.array([ticks.get(x, np.nan) for x in bt.strftime("%Y-%m")])
    return pd.Series(tk).ffill().bfill().to_numpy()


def engine_raw(sym, side, months_ok, intrabar, k1h=None, f=None, k1=None, blackout=True, coverage=True):
    """ONE coin through research/v8.engine. months_ok: set of 'YYYY-MM' where entries are allowed (None = all months), further limited by
    coverage when coverage=True. Returns dict(raw DataFrame, k1h, f, cov rows, holes, dl, ...)."""
    v8 = research()
    k1h = load_1h(sym) if k1h is None else k1h
    f = load_funding(sym) if f is None else f
    if intrabar == "1m":
        k1 = load_1m(sym) if k1 is None else k1
    else:
        k1 = k1h
    out = dict(sym=sym, raw=pd.DataFrame(), k1h=k1h, f=f, cov=[], holes=[], dl=None, tick=None, note="")
    if not len(k1h) or k1 is None or not len(k1):
        out["note"] = "no intrabar data"
        out["cov"] = [dict(sym=sym, month=m, h1_cov=0.0, m1_cov=0.0, funding_obs=0, funding_warmup=0, ok=False, why="no data") for m in MONTHS]
        return out
    cov = coverage_rows(sym, k1h, k1, f, intrabar) if coverage else []
    out["cov"] = cov
    ok_m = {r["month"] for r in cov if r["ok"]} if coverage else set(MONTHS)
    if months_ok is not None:
        ok_m &= set(months_ok)
    P = v8.SymPrep(sym, k1h, f, side=side)
    if side < 0:
        P.crowd = crowd_short_mirror(f)
    bt = P.b.index
    # months_ok=None (H47 / replay): warm-up months before 2021-01 stay open exactly as in the reference path (a position opened in
    # 2020-12 can still block a January entry there); entries before 2021-01-01 are dropped from the ledger afterwards.
    pre_ok = months_ok is None
    allow = np.array([(x in ok_m) or (pre_ok and x < "2021-01") for x in bt.strftime("%Y-%m")])
    step = H1N if intrabar == "1h" else M1N
    opts = dict(allow=allow)
    # D4 gap_all stays OFF for every coin (TA 17:3x, lock v1.3 item 7 literal: same setting as the H7-T replay, six and new coins alike)
    vol = k1.volume.to_numpy()
    pos = np.flatnonzero(vol > 0)
    if sym not in v8.SIX and len(pos):
        last_tr = k1.index[pos[-1]]
        end_bar = pd.Timestamp("2026-09-30 23:59" if intrabar == "1m" else "2026-09-30 23:00")
        if v8.delisted(sym) or last_tr < end_bar:
            opts["delist_ix"] = int(pos[-1])
            out["dl"] = str(last_tr)
    if blackout:
        ws = sorted(hole_windows(sym, k1.index, step))
        if ws:
            opts["blackout"] = (np.array([a for a, _ in ws], "datetime64[ns]"), np.array([b for _, b in ws], "datetime64[ns]"))
            out["holes"] = [(str(a), str(b)) for a, b in ws]
    tick = tick_info(sym, k1, bt)
    out["tick"] = tick if np.isscalar(tick) else "per-month"
    out["raw"] = v8.engine(sym, k1, P, tick, opts)
    return out


def to_raws(eng, side, in_h16=None, group=""):
    """engine DataFrame -> raw trade dicts for h46.simulate_book (unsized, 0.15% cost applied later; actual funding)."""
    v8 = research()
    raw = eng["raw"]
    if raw is None or not len(raw):
        return []
    raw = raw[(raw.entry_time >= v8.OOS_START) & (raw.entry_time < v8.END)]
    f = eng["f"].dropna()
    fund = ((f.index.astype("datetime64[ns]").asi8 // 10 ** 6).astype(np.int64), f.to_numpy(float))
    holes = [(int(pd.Timestamp(a).value // 10 ** 6), int(pd.Timestamp(b).value // 10 ** 6)) for a, b in eng["holes"]]
    out = []
    for r in raw.itertuples():
        e_ms = int(pd.Timestamp(r.entry_time).value // 10 ** 6)
        x_ms = int(pd.Timestamp(r.exit_time).value // 10 ** 6)
        mon = H.utc_month(e_ms)
        out.append(dict(
            sym=eng["sym"], symbol=eng["sym"], side=side, sig_ms=int(pd.Timestamp(r.sig_bar_time).value // 10 ** 6), entry_ms=e_ms, exit_ms=x_ms,
            entry_px=float(r.entry_px), exit_px=float(r.exit_px), stop_pct=float(r.stop_dist),
            sl=float(r.entry_px) * (1 - side * float(r.stop_dist)), reason=str(r.reason), gap=bool(r.gap), bars=int(r.bars_held),
            fund=funding_ret(fund, side, e_ms, x_ms), month=mon, group=group,
            in_h16=bool(in_h16 and (eng["sym"], mon) in in_h16),
            hole_cross=any(e_ms < w1 and x_ms > w0 for w0, w1 in holes)))
    return out


# ------------------------------------------------------------------ membership / H16
def read_membership():
    df = pd.read_csv(MEMBERSHIP)
    return df[df.month.isin(MONTHS)]


def member_months(df, group):
    d = {}
    for r in df[df.group == group].itertuples():
        d.setdefault(r.symbol, set()).add(r.month)
    return d


def h16_set():
    u = pd.read_csv(H16_UNIVERSE)
    return {(r.sym, r.month) for r in u.itertuples()}


def exchange_rules():
    """sym -> (min_notional, step, min_qty) from the run-time exchangeInfo snapshot (BTC $100 floor)."""
    v8 = research()
    out = {}
    for s in v8.EXS:
        try:
            r = v8.rules_for(s) if not v8.delisted(s) else v8.SymbolRules.from_exchange_info(v8.EXI, s)
            out[s] = (float(r.min_notional) if s != "BTCUSDT" else 100.0, float(r.step_size), float(r.min_qty))
        except Exception:
            pass
    return out


# ------------------------------------------------------------------ H7-T six-coin replay through the SAME engine call (no H46/H47 data)
def replay_h7t(intrabar="1m", blackout=True, init=100.0):
    """The reference H7-T replay (research/h7t_replay_0d82b19: live rules/sizing at $100): engine_raw() -> cost_book -> portfolio.
    Expected 355 trades, mean R about +1.69 with intrabar='1m'. Touches only the six existing coins' H7-T long rule."""
    v8 = research(replay=True)
    rp = importlib.import_module("research.h7t_replay_0d82b19")
    from research.v3 import END, OOS_START, closes_all
    rules = {s: v8.rules_for(s) for s in v8.SIX}
    parts, nraw, holes = [], {}, {}
    for s in v8.SIX:
        e = engine_raw(s, 1, None, intrabar, coverage=False, blackout=blackout)
        nraw[s] = len(e["raw"])
        holes[s] = e["holes"]
        parts.append(v8.cost_book(e["raw"], rp.CMS["base"], e["k1h"], e["f"], v8.BRACKETS[s][0]["mmr"]))
        del e
    book = pd.concat(parts, ignore_index=True)
    book = book[(book.entry_time >= OOS_START) & (book.entry_time < END)].reset_index(drop=True)
    t = v8.portfolio(book, closes_all(), init, rules=rules)[0]
    return dict(intrabar=intrabar, blackout=blackout, trades=int(len(t)), mean_R=float(t.R.mean()) if len(t) else float("nan"),
                raw_per_coin=nraw, holes=holes)
