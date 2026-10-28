"""Summary + stage-1 screen statistics. Pure stdlib. Trades are ledger dicts (see core.trade_record)."""
from __future__ import annotations

import math
import random
from collections import OrderedDict

from .core import KST_MS, MS1D


def mean(x):
    return math.fsum(x) / len(x) if x else float("nan")


def profit_factor(rs):
    g = math.fsum(r for r in rs if r > 0)
    l = -math.fsum(r for r in rs if r < 0)
    return float("inf") if l == 0 and g > 0 else (g / l if l else float("nan"))


def bootstrap_lowers(rs, seed, n_boot=10_000, qs=(0.01, 0.002)):
    """One resampling pass (random.Random(seed)); returns {q: sorted_means[floor(q*n_boot)]} -- the 99% and 99.8% one-sided
    lower bounds come from the SAME resamples (recomputation of the same raw draws, not a rerun)."""
    if not rs:
        return {q: float("nan") for q in qs}
    rng = random.Random(seed)
    k = len(rs)
    means = sorted(math.fsum(rng.choices(rs, k=k)) / k for _ in range(n_boot))
    return {q: means[int(q * n_boot)] for q in qs}


def bootstrap_lower(rs, seed, n_boot=10_000, q=0.01):
    """99% one-sided bootstrap lower bound of the mean: iid resampling of trades with random.Random(seed), n_boot resamples,
    value = sorted_means[floor(q*n_boot)] (the 1st percentile)."""
    if not rs:
        return float("nan")
    rng = random.Random(seed)
    k = len(rs)
    means = sorted(math.fsum(rng.choices(rs, k=k)) / k for _ in range(n_boot))
    return means[int(q * n_boot)]


def max_drawdown(wallets, start=1.0):
    peak, dd = start, 0.0
    for w in wallets:
        peak = max(peak, w)
        dd = max(dd, (peak - w) / peak)
    return dd


def months(trades):
    out = set()
    for t in trades:
        s = _ym(t["entry_bar_open_ms"])
        out.add(s)
    return out


def _ym(ms):
    import datetime as dt
    d = dt.datetime.fromtimestamp((ms + KST_MS) / 1000, dt.timezone.utc)
    return f"{d.year}-{d.month:02d}"


def _year(ms):
    return _ym(ms)[:4]


def kst_date(ms):
    import datetime as dt
    return dt.datetime.fromtimestamp((ms + KST_MS) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def basic(trades):
    """Descriptive numbers for a trade list (ledger order by exit)."""
    r15 = [t["r_c015"] for t in trades]
    r30 = [t["r_c030"] for t in trades]
    n = len(trades)
    wins = sum(1 for r in r15 if r > 0)
    be = None
    return OrderedDict(
        trades=n, distinct_days=len({kst_date(t["entry_bar_open_ms"]) for t in trades}),
        distinct_months=len(months(trades)),
        win_rate=wins / n if n else float("nan"),
        mean_r_c015=mean(r15), mean_r_c030=mean(r30), pf_c015=profit_factor(r15), pf_c030=profit_factor(r30),
        max_dd=max_drawdown([t["wallet_after"] for t in trades]) if n else float("nan"),
        final_wallet=trades[-1]["wallet_after"] if n else 1.0, break_even=be)


def screen(trades, seed, min_trades, min_months=6, n_boot=10_000, crit_q=0.002):
    """Stage-1 criteria S1-0..S1-6 (prereg-h34-stage1-screen.md). `trades` sorted by exit time with wallet_after."""
    out = OrderedDict()
    out["n"] = len(trades)
    b = basic(trades)
    out["basic"] = b
    ts = sorted(trades, key=lambda t: (t["entry_bar_open_ms"], t["symbol"]))
    r15 = [t["r_c015"] for t in trades]
    s10 = len(trades) >= min_trades and b["distinct_months"] >= min_months
    out["S1-0"] = (s10, f"trades {len(trades)} >= {min_trades} and months {b['distinct_months']} >= {min_months}")
    if not trades:
        return out
    out["S1-1"] = (b["mean_r_c015"] > 0, b["mean_r_c015"])
    lbs = bootstrap_lowers(r15, seed, n_boot, qs=tuple(sorted({0.01, 0.002, 0.001, crit_q}, reverse=True)))   # crit_q bound comes from the SAME resamples
    out["S1-2_99"] = (lbs[0.01] > 0, lbs[0.01])
    out["S1-2_998"] = (lbs[0.002] > 0, lbs[0.002])
    out["S1-2_999"] = (lbs[0.001] > 0, lbs[0.001])
    out["S1-2"] = (lbs[crit_q] > 0, lbs[crit_q])     # crit_q 0.002 (family-v1, 99.8%) by default; H39-H42 lock uses 0.001 (99.9%); 99/99.8/99.9 all reported
    out["S1-3"] = (b["mean_r_c030"] > 0, b["mean_r_c030"])
    # halves: chronological by entry time, equal trade counts (primary); calendar-midpoint split reported as information
    h = len(ts) // 2
    a, c = [t["r_c015"] for t in ts[:h]], [t["r_c015"] for t in ts[h:]]
    out["S1-4"] = (mean(a) > 0 and mean(c) > 0, (mean(a), mean(c), len(a), len(c)))
    mid = (ts[0]["entry_bar_open_ms"] + ts[-1]["entry_bar_open_ms"]) // 2
    a2 = [t["r_c015"] for t in ts if t["entry_bar_open_ms"] < mid]
    c2 = [t["r_c015"] for t in ts if t["entry_bar_open_ms"] >= mid]
    out["S1-4_calendar_info"] = (mean(a2), mean(c2), len(a2), len(c2))
    out["S1-5"] = (b["max_dd"] <= 0.20, b["max_dd"])
    k = math.ceil(0.05 * len(r15))
    rest = sorted(r15)[:-k] if k else r15
    out["S1-6"] = (mean(rest) > 0, (mean(rest), k))
    yr = by_year(trades)
    tot = math.fsum(r15)
    ysum = {y: n * m for y, (n, m) in yr.items()}
    share = max(ysum.values()) / tot if tot > 0 else float("nan")
    out["S1-Y"] = (not (tot > 0 and share > 0.60), (share, max(ysum, key=ysum.get) if ysum else None))
    core = ["S1-0", "S1-1", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6"]
    out["all_pass"] = all(out[x][0] for x in core)
    return out


def by_year(trades):
    d = OrderedDict()
    for t in sorted(trades, key=lambda t: t["entry_bar_open_ms"]):
        d.setdefault(_year(t["entry_bar_open_ms"]), []).append(t["r_c015"])
    return OrderedDict((y, (len(v), mean(v))) for y, v in d.items())


def by_exit_reason(trades):
    d = OrderedDict()
    for t in trades:
        d.setdefault(t["exit_reason"], []).append(t["r_c015"])
    return OrderedDict((k, (len(v), mean(v))) for k, v in d.items())
