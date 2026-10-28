"""H46/H47 one-time screen -- PURE part (no research imports): constants, limits book, date-block bootstrap, S1/U clauses, verdict.
Locks: /workspace/specs/prereg-lock-h46-h47-v1_2.md (TA, on top of v1.1 prereg-lock-h46-h47.md) + QR /workspace/quant/hypotheses_h46_h47.md.
Every reading of an ambiguous lock sentence is in INTERP (copied to the top of the result file) and in the Developer's numbered questions."""
from __future__ import annotations

import datetime as dt
import math
from collections import OrderedDict

import numpy as np

from . import stats
from .core import MAX_MULT, MS1D, Book, Pos

COST = 0.0015               # round trip, trade P&L (lock: 0.15%)
COST_2X = 0.0030            # S1-3
SIZE_COST = 0.0017          # lock: "사이징 비용 0.17%" -> size = RISK / (stop + 0.17%); R = net return / (stop + 0.17%)
RISK = 0.02                 # per trade
MAX_OPEN = 3                # concurrent
MAX_OPEN_RISK = 0.06        # combined open risk
DAILY_CAP = 0.05            # confirmed daily loss blocking new entries (KST day, core.Book)
N_BOOT = 10_000
CFG = {  # spec -> seed, S1-0 min trades, min months, bootstrap q (one-sided lower tail)
    "H46": dict(seed=67, min_trades=300, min_months=12, q=0.0005),
    "H47": dict(seed=68, min_trades=100, min_months=12, q=0.05 / 46),
}
HOLES = (("2022-02-26", "2022-03-01"), ("2022-04-01", "2022-04-03"))   # [start, end) UTC, lock v1.2 item 3
HOLE_MS = tuple((int(dt.datetime.fromisoformat(a).replace(tzinfo=dt.timezone.utc).timestamp() * 1000),
                 int(dt.datetime.fromisoformat(b).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)) for a, b in HOLES)
EXCL_REF_ONLY = 0.10        # lock v1.2: excluded coin-months > 10% of new-coin coin-months -> verdict "reference only"
U4_MIN_TRADES = 100
SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
TEST_WALLETS = (100.0, 300.0)
COV_MIN = 0.98              # coin-month data-coverage threshold (1h bars, intrabar frame bars, funding)
FUND_MIN_OBS = 60           # funding settlements in the month
FUND_WARMUP_OBS = 100       # = v8.crowd p95 min_periods (90D window) at month start
S1_KEYS = ("S1-0", "S1-1", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6", "S1-Y")

INTERP = [
    "**Rule (H7-T long / H47 mirror, QR file)**: the existing research engine `research/v8.engine` (generalised h7t.engine, the same code that reproduces the live H7-T replay 355 trades / mean R +1.69 at $100) is called unchanged. Entry intrabar on the first tick >= prior-55-closed-4h-bar high + 1 tick (short: <= 55-bar low - 1 tick); BTC prior-UTC-day close > SMA200 (short: not above; ties never occur); stop entry -/+ 2*ATR14(4h) fixed; exit when a 4h close is below the prior 20-bar low (short: above the prior 20-bar high) at the NEXT 4h open; one entry per coin per 4h bar; no re-entry in the stop bar.",
    "**Funding filter**: long skip if F3 >= p95 (90 calendar days, min 100 settlements, 8h-normalised) AND F3 > 0.0001 (v8.crowd_long). Short (H47) skip if F3 <= p5 (same window) AND F3 < -0.0001 (the QR mirror; NOT v8.crowd_short, which uses F3 < 0). Evaluated at the touch minute from the last settled value.",
    "**Costs / R**: round-trip cost 0.15% on every trade (0.30% for S1-3, same trades), actual funding (settlements with entry < stamp <= exit, long pays), size = 2% / (stop width + 0.17%), R = (gross - cost - funding) / (stop width + 0.17%).",
    "**Limits book (primary)**: 3 concurrent, open risk 6% (3 x 2%), 2% per trade, one position per coin, new entries blocked for the rest of a KST day once the day's CONFIRMED loss reaches 5% of the day-start wallet (core.Book). Signals blocked by a limit are skipped and recorded; the coin's path is NOT re-simulated (a skipped signal is not re-entered). Ties at the same entry minute: coin symbol order. **Unlimited book (report only)**: same trades, same sizing, no concurrency / risk / daily-cap limit.",
    "**Bootstrap**: 'UTC date block bootstrap' = research/h7t.date_boot_p resampling scheme: the trades' UTC ENTRY dates are the clusters (draw as many dates as there are distinct dates, with replacement; mean = sum R / count of trades in the drawn dates), numpy default_rng(seed), 10,000 resamples. Lower bound = sorted bootstrap means [floor(q*10000)] (H46 q = 0.0005 -> index 5; H47 q = 0.05/46 -> index 10). S1-2 passes when the bound > 0. The iid-trade 99% / 99.8% bounds of h34_paper.stats and the date-block 99% / 99.8% bounds are reported as information.",
    "**Months, halves, years, daily cap** follow the H43-H45 screen code (h34_paper.stats): KST calendar months / years of the entry time, halves = equal trade counts in entry order, MDD from the ledger wallet (exit order), top-5% trades removed for S1-6, S1-Y = no year > 60% of total R.",
    "**S1 pass**: S1-0 (H46: >= 300 trades and >= 12 months; H47: >= 100 and >= 12), S1-1 mean > 0, S1-2, S1-3 (0.30% cost mean > 0), S1-4 (both halves > 0), S1-5 (MDD <= 20%), S1-6 (top-5%-removed mean > 0) AND S1-Y. Judged on the limits book; the unlimited book is shown for information only.",
    "**H46 universe**: new coins only (membership file group == 'new'), pooled; entries are allowed only in the months in which the coin is in the point-in-time top 40 (file `universe_h46_membership_mean_2026-10-28.csv`, sha256 d5eb81db...). The median list is not used. Months from 2021-01 to 2026-09 (entry window as H16/H7-T: 2021-01-01 <= entry < 2026-10-01; the file's 2026-10 rows are outside the window and ignored). Open positions are managed after the member month ends.",
    "**H46 on the six existing coins (report only)**: same long rule on the group == 'orig6' rows (the months they ranked in the top 40), same limits book, shown separately; it is not part of any H46 judgment.",
    "**H47**: BTC/ETH/SOL/BNB/XRP/DOGE, short mirror, every month 2021-01..2026-09 (no membership filter), seed 68.",
    f"**Data coverage / exclusions**: a coin-month (member month) is EXCLUDED from the judgment (no entries; counted and reported) when, in that month, the 1h bars cover < {COV_MIN:.0%} of the hours until the data end, or (1m intrabar mode) the 1m bars cover < {COV_MIN:.0%} of the minutes, or the funding series has < {FUND_MIN_OBS} settlements or fewer than {FUND_WARMUP_OBS} settlements in the 90 days before the month start (the p95 filter would be off). Share of excluded new-coin coin-months > {EXCL_REF_ONLY:.0%} -> verdict 'reference only' (lock v1.2 item 3).",
    "**Holes 2022-02-26..28 and 2022-04-01..02**: a symbol has a hole if its 1h or intrabar frame has missing bars inside either window while it has data before the window (SOL and XRP always, from the research hole list). For these symbols touch minutes inside the windows give no signal (engine blackout windows); trades open across a window stay in the book and are listed separately (lock: 'listed separately', not removed).",
    "**H46 group-U**: U1 coins with >= 10 trades (limits book): share with mean R > 0 must be >= 2/3. U2: no coin's R-sum > 35% of the total R-sum (total <= 0 -> U2 fails). U3: mean R > 0 after removing all trades of the coin with the largest R-sum. U4 (lock v1.2): a trade belongs to 'H16' if its coin was in the H16 top-20 universe (results/v8/universe/universe_top20_monthly_v1_1.csv) in its entry UTC month; the H16-absent side needs mean R > 0 if it has >= 100 trades (else FAIL); with < 100 trades the best verdict is 'conditional PASS' (live only with 성헌 OK and a stop on the first-30-trade mean R <= 0). H16 (v8, H7-T on the top-20 universe) FAILED -> cited as prior negative evidence in the result file.",
    "**Report-only**: signals skipped by the limits (by reason, with their unsized mean R), min-order skip share per coin at $100 and $300 wallets (min notional from the run-time exchangeInfo snapshot: BTC $100 team floor, ETH $20, others $5; quantity step / min qty when the symbol is in the snapshot; size 2%/(stop+0.17%) x wallet, no compounding), same-4h-bar signal overlap, unlimited book, per-coin positive counts, file hashes.",
]


# ------------------------------------------------------------------ book
def utc_date(ms):
    return int(ms // MS1D)


def utc_month(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m")


class Book46(Book):
    """core.Book with the lock's sizing cost (stop + 0.17%) and R = net / (stop + 0.17%)."""

    def size_mult(self, stop_pct):
        return min(self.risk / (stop_pct + SIZE_COST), self.max_mult)

    def close(self, pos, exit_px, reason, exit_ms, gap, funding=0.0):
        rec = super().close(pos, exit_px, reason, exit_ms, gap, funding)
        den = pos.stop_pct + SIZE_COST
        rec["r_c015"] = (rec["gross_ret"] - pos.cost - funding) / den
        rec["r_c030"] = (rec["gross_ret"] - 2 * pos.cost - funding) / den
        return rec


def raw_r(r):
    """unsized R of a raw trade (0.15% cost, actual funding, 0.17% denominator)."""
    gross = r["side"] * (r["exit_px"] - r["entry_px"]) / r["entry_px"]
    return (gross - COST - r["fund"]) / (r["stop_pct"] + SIZE_COST)


def simulate_book(raws, strategy, limits=True, wallet0=1.0):
    """Event simulation of raw trades (dicts: sym, side, sig_ms, entry_ms, exit_ms, entry_px, exit_px, stop_pct, reason, gap, bars, fund,
    + free extras) in ONE wallet. Exits before entries at equal time (a trade that exits in its own entry minute: entry, then exit).
    limits=True: max 3 open, open risk <= 6%, daily-loss cap; otherwise none. Returns (ledger, skips)."""
    book = Book46(1, wallet0=wallet0, strategy=strategy, risk=RISK, daily_cap=DAILY_CAP if limits else float("inf"))
    ev = []
    for k, r in enumerate(raws):
        ev.append((r["entry_ms"], 1, r["sym"], k))
        ev.append((r["exit_ms"], 0 if r["entry_ms"] < r["exit_ms"] else 2, r["sym"], k))
    ev.sort()
    live, ledger, skips = {}, [], []
    for t, kind, _, k in ev:
        r = raws[k]
        if kind == 1:
            why = None
            if limits:
                if any(raws[j]["sym"] == r["sym"] for j in live):
                    why = "coin_busy"
                elif len(live) >= MAX_OPEN:
                    why = "max_concurrent"
                elif (len(live) + 1) * RISK > MAX_OPEN_RISK + 1e-12:
                    why = "open_risk_6pct"
                elif book.entry_blocked(t):
                    why = "daily_loss_cap"
            if why:
                skips.append(dict(sym=r["sym"], entry_ms=r["entry_ms"], sig_ms=r["sig_ms"], reason=why, r=raw_r(r)))
                continue
            live[k] = Pos(strategy, r["sym"], r["side"], r["sig_ms"], r["entry_ms"], r["entry_px"], r["entry_px"], float("nan"),
                          r["sl"], r["stop_pct"], book.size_mult(r["stop_pct"]), book.wallet, 0, {}, None, COST, "")
        else:
            pos = live.pop(k, None)
            if pos is None:
                continue
            pos.bars_seen = r.get("bars", 0)
            rec = book.close(pos, r["exit_px"], r["reason"], r["exit_ms"], r.get("gap", False), r["fund"])
            for key in ("sig_ms", "month", "in_h16", "hole_cross", "gap", "entry_ms", "group"):
                if key in r:
                    rec[key] = r[key]
            rec["entry_bar_open_ms"] = r["entry_ms"]       # stats.* use this key for months / halves / years
            ledger.append(rec)
    return ledger, skips


# ------------------------------------------------------------------ bootstrap
def boot_index(q, n_boot=N_BOOT):
    return int(math.floor(q * n_boot + 1e-9))


def date_block_bounds(rs, dates, seed, qs, n_boot=N_BOOT, chunk=500):
    """UTC-date block bootstrap of the mean (research/h7t.date_boot_p scheme). Returns {q: sorted_means[floor(q*n_boot)]}."""
    if not len(rs):
        return {q: float("nan") for q in qs}
    d = np.asarray(dates)
    u, inv = np.unique(d, return_inverse=True)
    s = np.bincount(inv, weights=np.asarray(rs, float))
    c = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    k = len(u)
    out = []
    for a in range(0, n_boot, chunk):
        i = rng.integers(0, k, (min(chunk, n_boot - a), k))
        out.append(s[i].sum(1) / c[i].sum(1))
    bm = np.sort(np.concatenate(out))
    return {q: float(bm[boot_index(q, n_boot)]) for q in qs}


def s1(ledger, spec, n_boot=N_BOOT):
    """S1 for one ledger with the lock's date-block S1-2 (stats.screen supplies everything else)."""
    cfg = CFG[spec]
    sc = stats.screen(ledger, cfg["seed"], cfg["min_trades"], cfg["min_months"], n_boot, crit_q=cfg["q"])
    sc["S1-2_iid_info"] = sc.get("S1-2")
    if ledger:
        rs = [t["r_c015"] for t in ledger]
        lb = date_block_bounds(rs, [utc_date(t["entry_ms"]) for t in ledger], cfg["seed"], (0.01, 0.002, cfg["q"]), n_boot)
        sc["S1-2"] = (lb[cfg["q"]] > 0, lb[cfg["q"]])
        sc["S1-2_date_99"] = lb[0.01]
        sc["S1-2_date_998"] = lb[0.002]
        sc["boot_index"] = boot_index(cfg["q"], n_boot)
        sc["all_pass"] = all(sc[k][0] for k in S1_KEYS)
    else:
        sc["all_pass"] = False
    return sc


# ------------------------------------------------------------------ group U (H46)
def per_coin(ledger):
    d = OrderedDict()
    for t in ledger:
        d.setdefault(t["symbol"], []).append(t["r_c015"])
    return OrderedDict((s, dict(n=len(v), mean=stats.mean(v), rsum=math.fsum(v))) for s, v in sorted(d.items()))


def u_clauses(ledger):
    pc = per_coin(ledger)
    out = OrderedDict()
    el = [s for s, v in pc.items() if v["n"] >= 10]
    pos = [s for s in el if pc[s]["mean"] > 0]
    out["U1"] = (bool(el) and len(pos) / len(el) >= 2 / 3 - 1e-12, dict(coins_ge10=len(el), positive=len(pos),
                                                                         share=len(pos) / len(el) if el else float("nan")))
    tot = math.fsum(v["rsum"] for v in pc.values())
    best = max(pc, key=lambda s: pc[s]["rsum"]) if pc else None
    share = pc[best]["rsum"] / tot if best and tot > 0 else float("nan")
    out["U2"] = (bool(best) and tot > 0 and share <= 0.35 + 1e-12, dict(best=best, share=share, total_r=tot))
    rest = [t["r_c015"] for t in ledger if t["symbol"] != best]
    out["U3"] = (bool(rest) and stats.mean(rest) > 0, dict(dropped=best, mean=stats.mean(rest) if rest else float("nan"), n=len(rest)))
    return out


def u4(ledger):
    """split by H16-universe membership of the coin in the entry month. Returns dict side -> (n, mean, coins) + verdict parts."""
    res = {}
    for name, flag in (("H16", True), ("not_H16", False)):
        tr = [t for t in ledger if bool(t.get("in_h16")) == flag]
        res[name] = dict(n=len(tr), mean=stats.mean([t["r_c015"] for t in tr]) if tr else float("nan"), coins=len({t["symbol"] for t in tr}))
    a = res["not_H16"]
    enough = a["n"] >= U4_MIN_TRADES
    res["enough"] = enough
    res["pass"] = (a["mean"] > 0) if enough else None
    return res


def verdict_h46(sc, u, u4r, excl_share):
    fails = [k for k in S1_KEYS if k not in sc or not sc[k][0]]
    fails += [k for k, v in u.items() if not v[0]]
    if u4r["enough"] and not u4r["pass"]:
        fails.append("U4")
    if fails:
        v = "FAIL (" + ", ".join(fails) + ")"
    elif not u4r["enough"]:
        v = "conditional PASS (U4: H16-absent trades < 100; live only with 성헌 OK and a stop on first-30-trade mean R <= 0)"
    else:
        v = "PASS"
    if excl_share > EXCL_REF_ONLY:
        v += f" -- REFERENCE ONLY (excluded coin-months {excl_share:.1%} > 10%)"
    return v, fails


def verdict_h47(sc, excl_share=0.0):
    fails = [k for k in S1_KEYS if k not in sc or not sc[k][0]]
    v = "PASS" if not fails else "FAIL (" + ", ".join(fails) + ")"
    if excl_share > EXCL_REF_ONLY:
        v += f" -- REFERENCE ONLY (excluded {excl_share:.1%} > 10%)"
    return v, fails


# ------------------------------------------------------------------ report-only helpers
def skip_summary(skips):
    d = OrderedDict()
    for s in skips:
        x = d.setdefault(s["reason"], [])
        x.append(s["r"])
    return OrderedDict((k, dict(n=len(v), mean_r=stats.mean(v))) for k, v in d.items())


def overlap_rate(raws):
    """share of signals (entries) whose 4h signal bar also holds a signal of ANOTHER coin."""
    by = {}
    for r in raws:
        by.setdefault(r["sig_ms"], set()).add(r["sym"])
    n = len(raws)
    shared = sum(1 for r in raws if len(by[r["sig_ms"]]) >= 2)
    return dict(signals=n, shared=shared, rate=shared / n if n else float("nan"),
                max_same_bar=max((len(v) for v in by.values()), default=0))


def min_order_skips(raws, rules, wallet):
    """per coin: (signals, skipped, share). rules: sym -> (min_notional, step|None, min_qty|None); unknown -> $5, no step."""
    out = {}
    for r in raws:
        mn, step, mq = rules.get(r["sym"]) or (5.0, None, None)
        notional = min(RISK / (r["stop_pct"] + SIZE_COST), MAX_MULT) * wallet
        qty = notional / r["entry_px"]
        if step:
            qty = math.floor(qty / step + 1e-9) * step
        skip = (mq is not None and qty < mq - 1e-12) or qty * r["entry_px"] < mn - 1e-9
        a = out.setdefault(r["sym"], [0, 0])
        a[0] += 1
        a[1] += int(bool(skip))
    return {s: dict(signals=a, skipped=b, share=b / a) for s, (a, b) in out.items()}
