# H100 one-shot screen runner. Refuses to run twice (one run per pre-registered spec).
import datetime as dt
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

from research_h100 import data as D
from research_h100.sim import Costs, Params, simulate_coin, block_bootstrap_lb

RES = "/workspace/trade-bot-research/results/h100"
PROG = "/workspace/trade-bot-research/results/h100_progress.md"
LOCK = "/workspace/specs/prereg-lock-h100-funding-v1_1.md"
SPEC = "/workspace/quant/hypotheses_h100_funding_v1_1.md"
SAFE = "/workspace/specs/ops-safety-rules-v1-2026-10-29.md"
EXPECT = {LOCK: "89752618a943", SPEC: "088ddd8c5c68", SAFE: "48ef505e19a6"}
WALLET_START = pd.Timestamp("2020-01-01 00:00:00")
N_TESTS = 80
ALPHA = 0.05 / N_TESTS


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def prog(msg):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")
    with open(PROG, "a") as f:
        f.write("- " + now + " " + msg + "\n")
    print(msg, flush=True)


def build_bars():
    fut = D.load_fut_1h_all()
    fr = D.load_funding_all()
    bars, notes = {}, {}
    for s in D.COINS:
        f = fut[s]
        old = pd.read_parquet(os.path.join(D.PARQ, "klines_1h.parquet" if s == "BTCUSDT" else "v2_" + s + "_1h.parquet"))
        if old.index.tz is not None:
            old.index = old.index.tz_localize(None)
        sp = D.load_spot_1h(s)
        start = max(fr[s].index.min(), f.index.min(), sp.index.min()).ceil("h")
        full = pd.date_range(start, D.END, freq="h")
        f = f.reindex(full)
        miss = f.open.isna()
        filled = int(miss.sum())
        o = old.reindex(full)
        for k in ("open", "high", "low", "close"):
            f.loc[miss, k] = o.loc[miss, k]
        sp = sp.reindex(full)
        b = pd.DataFrame(index=full)
        for k in ("open", "high", "low", "close"):
            b["f_" + k] = f[k]
            b["s_" + k] = sp[k]
        bars[s] = b
        notes[s] = dict(start=str(start), fut_filled_from_v2=filled, fut_missing_after_fill=int(b.f_open.isna().sum()),
                        spot_missing_hours=int(b.s_open.isna().sum()), funding_prints=int(len(fr[s])),
                        funding_first=str(fr[s].index.min()), funding_last=str(fr[s].index.max()))
    return bars, fr, notes


def wallet(results, hours):
    cap = 1.0 / len(D.COINS)
    close = pd.Series(0.0, index=hours)
    worst = pd.Series(0.0, index=hours)
    anypos = pd.Series(False, index=hours)
    for s, r in results.items():
        ec = r.eq_close.reindex(hours)
        ew = r.eq_worst.reindex(hours)
        pre = hours < r.eq_close.index[0]
        ec[pre] = cap
        ew[pre] = cap
        close += ec.to_numpy()
        worst += ew.to_numpy()
        anypos |= (r.fut_held | r.spot_held).reindex(hours, fill_value=False).to_numpy()
    return close, worst, anypos


def end_exit_cost(r, bars, c):
    # positions still open at 2026-09-30 23:00 are charged their exit fees at the last close (no free exit)
    if not r.in_pos_at_end:
        return 0.0
    t = r.trades[-1]
    b = bars.iloc[-1]
    q_s = t["X"] / t["spot_entry_px"]
    q_f = t["X"] / t["fut_entry_px"]
    return q_s * b.s_close * c.spot_side + q_f * b.f_close * c.fut_side


def evaluate(results, bars, c, hours):
    close, worst, anypos = wallet(results, hours)
    assert not close.isna().any() and not worst.isna().any()
    adj = sum(end_exit_cost(results[s], bars[s], c) for s in D.COINS)
    close.iloc[-1] -= adj
    worst.iloc[-1] -= adj
    day_close = close.resample("1D").last()
    prev = day_close.shift(1)
    prev.iloc[0] = 1.0
    daily = day_close / prev - 1.0
    peak_prev = np.maximum.accumulate(np.concatenate([[1.0], close.to_numpy()]))[:-1]
    dd_worst = worst.to_numpy() / peak_prev - 1.0
    peak_close = np.maximum.accumulate(np.concatenate([[1.0], close.to_numpy()]))[1:]
    dd_close = close.to_numpy() / peak_close - 1.0
    i_w = int(np.argmin(dd_worst))
    ndays = len(daily)
    years = ndays / 365.25
    return dict(close=close, worst=worst, anypos=anypos, daily=daily, end_exit_cost=adj,
                final_equity=float(close.iloc[-1]), ann_return=float(close.iloc[-1] ** (1 / years) - 1),
                mdd_close=float(dd_close.min()), mdd_worst_intrabar=float(dd_worst.min()),
                mdd_worst_ts=str(hours[i_w]), min_wallet_worst=float(worst.min()),
                min_wallet_worst_ts=str(hours[int(np.argmin(worst.to_numpy()))]), min_wallet_close=float(close.min()),
                start_drop_worst=float(worst.min() / 1.0 - 1.0),
                daily_mean=float(daily.mean()), daily_std=float(daily.std(ddof=1)), n_days=ndays)


def per_coin(results, bars, c):
    rows = []
    for s in D.COINS:
        r = results[s]
        ex = end_exit_cost(r, bars[s], c)
        pnl = float(r.eq_close.iloc[-1] - 1.0 / len(D.COINS) - ex)
        active = len(r.eq_close)
        inpos = int((r.fut_held | r.spot_held).sum())
        rows.append(dict(coin=s, pnl_wallet_pct=100 * pnl, funding_pct=100 * r.funding_pnl, spot_pnl_pct=100 * r.spot_pnl,
                         fut_pnl_pct=100 * r.fut_pnl, cost_pct=100 * (r.cost_pnl - ex), liq_loss_pct=100 * r.liq_loss,
                         entries=r.n_entries, sl=r.n_sl, tp=r.n_tp, liq=r.n_liq, signal_exits=r.n_signal_exits,
                         open_at_end=int(r.in_pos_at_end), one_leg_hours=r.one_leg_hours,
                         residual_violations=r.residual_violations, deferred_signal_exits=r.deferred_signal_exits,
                         skipped_entries_missing_bar=r.skipped_entries_missing_bar,
                         time_in_market_pct=100 * inpos / active, active_hours=active))
    return pd.DataFrame(rows)


def main():
    os.makedirs(RES, exist_ok=True)
    if os.path.exists(os.path.join(RES, "summary.json")):
        sys.exit("results/h100/summary.json exists: H100 is one-shot, refusing a second run")
    for p, pre in EXPECT.items():
        h = sha(p)
        if not h.startswith(pre):
            sys.exit("sha mismatch " + p + " " + h[:12] + " != " + pre)
    prog("H100 one-shot start; lock 89752618a943, QR 088ddd8c5c68, safety 48ef505e19a6 verified")
    bars, fr, notes = build_bars()
    prog("data built: " + json.dumps({s: notes[s]["start"] for s in D.COINS}))
    hours = pd.date_range(WALLET_START, D.END, freq="h")
    p = Params()
    runs = {}
    for mult in (1.0, 2.0):
        c = Costs(mult=mult)
        res = {s: simulate_coin(bars[s], fr[s], 1.0 / len(D.COINS), p, c) for s in D.COINS}
        runs[mult] = (c, res, evaluate(res, bars, c, hours))
        prog("sim done cost x%g: final equity %.6f" % (mult, runs[mult][2]["final_equity"]))
    c1, res1, ev1 = runs[1.0]
    c2, res2, ev2 = runs[2.0]
    d1 = ev1["daily"].to_numpy()
    lb = block_bootstrap_lb(d1, 7, 10000, 102, ALPHA)
    prog("bootstrap done: LB %.3e" % lb)
    half = len(d1) // 2
    h1, h2 = float(d1[:half].mean()), float(d1[half:].mean())
    pc = per_coin(res1, bars, c1)
    pc2 = per_coin(res2, bars, c2)
    tot = lambda k: int(sum(getattr(r, k) for r in res1.values()))
    slot_hours = sum(len(r.eq_close) for r in res1.values())
    slot_inpos = sum(int((r.fut_held | r.spot_held).sum()) for r in res1.values())
    days_in_pos = int(ev1["anypos"].resample("1D").max().sum())
    crit = {
        "C1a_liquidations_model": dict(value=tot("n_liq"), rule="== 0", pass_=tot("n_liq") == 0),
        "C1b_one_leg_intervals_hours": dict(value=tot("one_leg_hours"), rule="== 0", pass_=tot("one_leg_hours") == 0),
        "C1c_worst_intrabar_dd_from_start_or_peak": dict(value=ev1["mdd_worst_intrabar"], rule="> -0.25", pass_=ev1["mdd_worst_intrabar"] > -0.25),
        "C2a_mean_daily_net_1x": dict(value=ev1["daily_mean"], rule="> 0", pass_=ev1["daily_mean"] > 0),
        "C2b_mean_daily_net_2x": dict(value=ev2["daily_mean"], rule="> 0", pass_=ev2["daily_mean"] > 0),
        "C3_block_bootstrap_LB_99.9375": dict(value=lb, rule="> 0", pass_=lb > 0),
        "C4a_first_half_mean": dict(value=h1, rule="> 0", pass_=h1 > 0),
        "C4b_second_half_mean": dict(value=h2, rule="> 0", pass_=h2 > 0),
        "C5_residual_order_or_position_violations": dict(value=tot("residual_violations"), rule="== 0", pass_=tot("residual_violations") == 0),
    }
    daily = pd.DataFrame({"ret_1x": ev1["daily"], "ret_2x": ev2["daily"],
                          "equity_1x": ev1["close"].resample("1D").last(), "equity_2x": ev2["close"].resample("1D").last(),
                          "worst_intrabar_1x": ev1["worst"].resample("1D").min(),
                          "in_position_any": ev1["anypos"].resample("1D").max().astype(int)})
    trades = []
    for s, r in res1.items():
        for t in r.trades:
            t = {k: v for k, v in t.items() if not k.startswith("_")}
            t["coin"] = s
            trades.append(t)
    trades = pd.DataFrame(trades)
    n_days = ev1["n_days"]
    summary = dict(
        hypothesis="H100 funding carry v1.1", lock="prereg-lock-h100-funding-v1_1.md 89752618a943",
        spec="hypotheses_h100_funding_v1_1.md 088ddd8c5c68", safety="ops-safety-rules-v1-2026-10-29.md 48ef505e19a6",
        run_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S KST"),
        window=dict(start=str(WALLET_START.date()), end="2026-09-30", n_days=n_days, half_split_after_day=str(daily.index[half - 1].date())),
        criteria={k: dict(value=v["value"], rule=v["rule"], passes=bool(v["pass_"])) for k, v in crit.items()},
        counts=dict(entries=tot("n_entries"), sl_exits=tot("n_sl"), tp_exits=tot("n_tp"), liquidations=tot("n_liq"),
                    signal_exits=tot("n_signal_exits"), open_at_end=sum(int(r.in_pos_at_end) for r in res1.values()),
                    one_leg_hours=tot("one_leg_hours"), residual_violations=tot("residual_violations"),
                    deferred_signal_exits=tot("deferred_signal_exits"), skipped_entries_missing_bar=tot("skipped_entries_missing_bar")),
        x1=dict({k: v for k, v in ev1.items() if not isinstance(v, (pd.Series,))},
                time_in_market_slot_hours_pct=100 * slot_inpos / slot_hours,
                time_in_market_wallet_any_pct=100 * float(ev1["anypos"].mean()), days_with_position=days_in_pos),
        x2={k: v for k, v in ev2.items() if not isinstance(v, (pd.Series,))},
        bootstrap=dict(block=7, resamples=10000, seed=102, one_sided_level=1 - ALPHA, N=N_TESTS, lower_bound=lb),
        halves=dict(first_mean=h1, second_mean=h2, first_n=half, second_n=len(d1) - half),
        data=notes,
        inputs_sha256={os.path.basename(f): sha(f) for f in [os.path.join(D.PARQ, "v3_um_funding.parquet"),
                                                               os.path.join(D.PARQ, "v7_um_1h.parquet")]},
    )
    with open(os.path.join(RES, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    pc.to_csv(os.path.join(RES, "per_coin_1x.csv"), index=False)
    pc2.to_csv(os.path.join(RES, "per_coin_2x.csv"), index=False)
    daily.to_csv(os.path.join(RES, "daily.csv"))
    trades.to_csv(os.path.join(RES, "trades_1x.csv"), index=False)
    prog("results written")
    return summary


if __name__ == "__main__":
    main()
