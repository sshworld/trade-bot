"""FE-v2 sizing hook for the H61-H71 screens: takes the sizing-independent candidate ledger of one group and runs the TA sizing module
(h34_paper/sizing_full.py = sizing-full 1f1c05e, unmodified) for variants A/B/C x replace-losers off/on. Nothing here picks a number the locks do not give.

* Candidate-list statistics (S1-1..S1-4, S1-6) are in R units of the candidate ledger R = unit / (stop_dist + 0.0017) (unit = gross - 0.15% cost - funding) -
  the unlimited candidate list, not any limits book. S1-5 is the variant's own off-ledger (wallet MDD <= 20% and top-5%-removed mean R > 0).
* The S1 gate of replace-losers (answers R10) uses the candidate's own seed and N (H61-H71 lock: N = 74, seeds 89..99); `gate_pass` = S1-1..S1-6 all pass.
* Variant C has a per-coin f for the six coins only (lock 03a2d0898830); a ledger with any other coin runs A and B only (the new-coin addendum names A and B).
* Candidates whose coin has no exchange filters / brackets in the snapshot cannot be sized: they are removed from the sizing ledgers and counted by coin
  (`no_exchange_info`); the candidate-list statistics keep them.
* RP: replacement-window funding is not modelled (answers R4, stated as a limitation)."""
from __future__ import annotations

import math
from collections import OrderedDict

import numpy as np
import pandas as pd

from . import sizing_full as F
from . import sizing_up as S

SIZING_COLS = ("sym", "side", "entry_time", "exit_time", "entry_px", "stop_dist", "mae", "unit", "fee1", "R")
FEE_SIZING = 0.0017
S1_KEYS_BASE = ("S1-1", "S1-2", "S1-3", "S1-4", "S1-6")
# report names for the sizing-ledger RP-gate numbers (same keys / calculation; named apart from the clause lines, which use the screen's R)
RP_GATE_LABELS = {"S1-1": "gate mean R", "S1-2": "gate date-block lower bound", "S1-3": "gate 2x-cost mean (R - 0.0015/stop_dist)",
                  "S1-4": "gate halves", "S1-6": "gate best-year share"}
VARIANT_C_NOTE = ("variant C (per-coin margin fraction) is defined for BTC/ETH/SOL/BNB/XRP/DOGE only (lock 03a2d0898830; answers C2: a coin without f is an error). "
                  "The group has coins outside these six, so C was not run; the new-coin addendum names variants A and B.")


def ledger_frame(fe):
    """Sizing ledger = the candidate ledger with datetime times and R = unit / (stop_dist + 0.0017). The input is not modified."""
    L = fe.copy().reset_index(drop=True)
    L["entry_time"] = pd.to_datetime(L.entry_time)
    L["exit_time"] = pd.to_datetime(L.exit_time)
    L["R"] = L.unit / (L.stop_dist + FEE_SIZING)
    return L


def variants_for(L):
    return ("A", "B", "C") if set(L.sym) <= set(F.VARIANT_F["C"]) else ("A", "B")


def split_no_info(L, rules, brackets):
    ok = L.sym.map(lambda s: s in rules and s in brackets)
    miss = L[~ok].sym.value_counts().to_dict()
    return L[ok].reset_index(drop=True), {k: int(v) for k, v in sorted(miss.items())}


def make_price_at(open_loader, keep=12):
    """price_at(sym, ts) = open of the 1m bar starting exactly at ts, None when the bar (or the coin) is missing. Coins load lazily (LRU of `keep`)."""
    cache = OrderedDict()

    def get(sym):
        if sym in cache:
            cache.move_to_end(sym)
            return cache[sym]
        o = open_loader(sym)
        d = None if o is None else dict(zip(o.index.to_numpy().astype("datetime64[ns]"), o.to_numpy(float)))
        cache[sym] = d
        while len(cache) > keep:
            cache.popitem(last=False)
        return d

    def price_at(sym, ts):
        d = get(sym)
        return None if d is None else d.get(np.datetime64(pd.Timestamp(ts), "ns"))
    return price_at


def rp_gate(base_clauses, s15_by_variant):
    """{variant: True/False}: S1-1..S1-4 and S1-6 of the candidate list (variant independent) AND the variant's S1-5."""
    base = all(base_clauses[k]["pass"] for k in S1_KEYS_BASE)
    return {v: bool(base and s15) for v, s15 in s15_by_variant.items()}


def _clean(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    return x


def _row(sim, runs):
    t = sim["trades"]
    r = dict(signals=sim["signals"], entered=sim["entered"], skipped=sim["signals"] - sim["entered"], skips=dict(sorted(sim["skips"].items())),
             replace_attempts=dict(sorted(sim.get("replace_attempts", {}).items())), final_wallet=sim["final"], max_concurrent=sim["max_concurrent"],
             max_open_loss_frac=sim["max_open_loss_frac"])
    if not len(t):
        return dict(r, annual_n=0, tier=F.trade_count_tier(0), mean_hold_minutes=None, replaced_n=0, replaced_mean_R=None, z1_max_dd=None, z2_share=None,
                    z3_worst_loss_frac=None, first_touch_init=None, first_touch_peak=None, sized_by_cap=0, sized_by_loss=0, liquidated=0, mean_R=None)
    c = F.fe_clauses(sim, runs=runs)
    st = F.rp_stats(sim)
    return dict(r, annual_n=c["boot_n"], trades_per_year_unrounded=c["trades_per_year"], span_years=c["span_years"], tier=c["trade_count_tier"],
                mean_hold_minutes=st["mean_hold_minutes"], replaced_n=st["replaced_n"], replaced_mean_R=st["replaced_mean_R"],
                z1_max_dd=c["z1_max_dd"], z1_pass=c["z1_pass"], z2_share=c["z2_share"], z2_pass=c["z2_pass"], z2_seed=c["z2_seed"], z2_n=c["boot_n"],
                z3_worst_loss_frac=c["z3_worst_loss_frac"], z3_pass=c["z3_pass"],
                first_touch_init=None if c["z9_first_touch_init"] is None or pd.isna(c["z9_first_touch_init"]) else str(c["z9_first_touch_init"]),
                first_touch_peak=None if c["z9_first_touch_peak"] is None or pd.isna(c["z9_first_touch_peak"]) else str(c["z9_first_touch_peak"]),
                sized_by_cap=int((t.sized_by == "cap").sum()), sized_by_loss=int((t.sized_by == "loss").sum()), liquidated=int(t.liquidated.sum()),
                mean_R=float(t.R.mean()), mean_ret=float(t.ret.mean()))


def apply_fe_sizing(spec, gname, fe, b, *, rules_loader, open_loader, min_stop_dist, runs=10_000, price_at=None):
    """b needs sc_u (unused: kept for the report), seed (group seed) and n_cand. Returns plain data plus `sims` (the module's sim dicts)."""
    L = ledger_frame(fe) if len(fe) else fe
    out = dict(spec=spec, group=gname, n_candidates_total=int(len(L)), seed=int(b["seed"]), n_cand=int(b["n_cand"]), min_stop_dist=min_stop_dist, sims={}, rows={},
               no_exchange_info={}, variants=(), gate={}, gate_detail={}, rp_applies={}, candidate_R={}, note="", variant_c_note="")
    if not len(L):
        out["note"] = "no candidate trades: nothing to size"
        return out
    rules, brackets = rules_loader(sorted(set(L.sym)))
    keep, miss = split_no_info(L, rules, brackets)
    out["no_exchange_info"] = miss
    out["variants"] = variants_for(L)
    if out["variants"] != ("A", "B", "C"):
        out["variant_c_note"] = VARIANT_C_NOTE
    if not len(keep):
        out["note"] = "no candidate trade has exchange filters + brackets: nothing to size"
        return out
    pa = price_at or make_price_at(open_loader)
    sims = F.simulate_all(keep, rules, brackets, min_stop_dist=min_stop_dist, price_at=pa, variants=out["variants"])
    out["sims"] = sims
    for k, s in sims.items():
        out["rows"][k] = _row(s, runs)
    gd, s15 = {}, {}
    for v in out["variants"]:
        g = F.s1_gate(L, sims[f"{v}_off"], n_candidates=int(b["n_cand"]), seed=int(b["seed"]))
        gd[v] = g
        s15[v] = bool(g["S1-5"]["pass"])
    first = gd[out["variants"][0]]
    out["gate_detail"] = {v: {k: g[k] for k in (*S1_KEYS_BASE, "S1-5")} for v, g in gd.items()}
    out["gate"] = rp_gate(first, s15)
    out["gate_gate_pass_module"] = {v: bool(g["gate_pass"]) for v, g in gd.items()}
    out["rp_applies"] = F.rp_gate_flags({v: dict(gate_pass=ok) for v, ok in out["gate"].items()})
    R = L.R.to_numpy(float)
    out["candidate_R"] = dict(n=int(len(R)), mean_R=float(R.mean()), **{k: first[k] for k in S1_KEYS_BASE})
    return out


# ------------------------------------------------------------------ report
def _f(x, nd=4):
    return "n/a" if x is None else f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def _pct(x, nd=2):
    return "n/a" if x is None else f"{100 * x:.{nd}f}%"


def render_sizing(z, coins=None):
    L = [f"### FE sizing output (sizing module sizing_full.py @ 1f1c05e; start wallet {S.INIT_WALLET}; min stop {z['min_stop_dist'] * 100:.2f}%)", ""]
    m = z.get("meta")
    if m:
        L += ["Inputs: " + "; ".join(f"{k} {v}" for k, v in m.items()), ""]
    if z["note"]:
        L += [z["note"], ""]
        return L
    L += [f"Candidates {z['n_candidates_total']}; sized {z['rows'][next(iter(z['rows']))]['signals']}; variants run: {', '.join(z['variants'])}."]
    L += ["Margin fraction f per position (10x leverage): A 0.10; B 0.25; variant C " + ", ".join(f"{k} {v}" for k, v in F.VARIANT_F["C"].items()) + "."]
    if z["variant_c_note"]:
        L += [z["variant_c_note"]]
    if z["no_exchange_info"]:
        L += [f"Candidates dropped before sizing for lack of exchange filters/brackets in the snapshot: {sum(z['no_exchange_info'].values())} trades in "
              f"{len(z['no_exchange_info'])} coins ({', '.join(f'{k} {v}' for k, v in z['no_exchange_info'].items())})."]
    L += ["", "Candidate ledger columns passed to the sizing module: " + ", ".join(SIZING_COLS)
          + " (R = unit / (stop_dist + 0.0017) on the unlimited candidate list; sym/side/times/px from the candidate ledger).", ""]
    cr = z["candidate_R"]
    L += [f"Sizing-ledger RP-gate inputs on the unlimited candidate list (sizing-ledger R = unit / (stop_dist + 0.0017), n {cr['n']}, mean R {_f(cr['mean_R'])}; "
          f"seed {z['seed']}, N {z['n_cand']}, q {0.05 / z['n_cand']:.6f}; a different R definition from the clause lines above, so these are not the clause S1-3 etc. "
          "and feed only the RP gate): "
          + "; ".join(f"{RP_GATE_LABELS[k]} pass={cr[k]['pass']} value={cr[k]['value']}" for k in S1_KEYS_BASE), ""]
    L += ["RP gate (answers R10: the RP verdict applies only where S1-1..S1-6 all pass on the base ledger; otherwise reference only): "
          + ", ".join(f"{v}: {'applies' if ok else 'reference only'} (S1-5 pass={z['gate_detail'][v]['S1-5']['pass']} MDD={_pct(z['gate_detail'][v]['S1-5']['value']['max_dd'])} "
                      f"top5-removed mean R={_f(z['gate_detail'][v]['S1-5']['value']['top5_removed_mean'])})" for v, ok in z["gate"].items()), ""]
    keys = list(z["rows"])
    hdr = ["", *keys]
    rows = [("Signals sized", "signals"), ("Entered", "entered"), ("Annual n (nearest int)", "annual_n"), ("S1-0 tier", "tier"), ("Mean R (sizing, R = net / loss at stop incl. fee)", "mean_R"),
            ("Average hold (min)", "mean_hold_minutes"), ("Closed by replacement", "replaced_n"), ("Mean R of replaced", "replaced_mean_R"),
            ("Replace attempts failed", "replace_attempts"), ("Final wallet", "final_wallet"), ("Max concurrent", "max_concurrent"), ("Max open loss (fraction of wallet)", "max_open_loss_frac"),
            ("FE-Z1 real-order MDD", "z1_max_dd"), ("FE-Z2 share reaching -25% (seed 88)", "z2_share"), ("FE-Z2 n (annual)", "z2_n"), ("FE-Z3 worst trade loss/wallet", "z3_worst_loss_frac"),
            ("First -25% touch vs initial (report only)", "first_touch_init"), ("First -25% touch vs peak (report only)", "first_touch_peak"),
            ("Sized by margin cap / by loss", None), ("Liquidated", "liquidated"), ("Skips by reason", "skips")]
    L += ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for lab, key in rows:
        cells = []
        for k in keys:
            r = z["rows"][k]
            if key is None:
                cells.append(f"{r['sized_by_cap']} / {r['sized_by_loss']}")
            else:
                v = r.get(key)
                cells.append(", ".join(f"{a} {b}" for a, b in v.items()) or "none" if isinstance(v, dict) else
                             _pct(v) if key in ("z1_max_dd", "z2_share", "z3_worst_loss_frac", "max_open_loss_frac") else _f(v, 2) if key in ("final_wallet", "mean_hold_minutes") else _f(v))
        L.append(f"| {lab} | " + " | ".join(cells) + " |")
    L += ["", "Notes: _off = base ledger (no replacement); _on = replace-losers-v1 switched on (cost 0.15%, fill at the next 1m open, worst negative-unrealised-R position only, "
          "liquidated positions excluded). Replacement-window funding is not modelled (answers R4, limitation). `no_price` = no 1m bar at the needed minute, so no replacement (answers R1). "
          "The first -25% touch is a report only. Annual n = trades / (days from first entry to last exit / 365.25), nearest integer. A liquidated trade counts its margin in Z3.", ""]
    return L


def write_sizing_files(z, out, tag):
    from pathlib import Path
    out = Path(out)
    reps = []
    for k, s in z["sims"].items():
        t = s["trades"]
        t.to_csv(out / f"fe_trades_{tag}_{k}.csv", index=False)
        pd.DataFrame(s["skip_log"], columns=["idx", "sym", "entry_time", "reason", "detail", "wallet"]).to_csv(out / f"fe_skips_{tag}_{k}.csv", index=False)
        for r in s["replacements"]:
            reps.append(dict(ledger=k, **r))
    pd.DataFrame(reps).to_csv(out / f"fe_replacements_{tag}.csv", index=False)
