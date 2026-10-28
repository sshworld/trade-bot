#!/usr/bin/env python
"""One-time H46 / H47 screen (locks: prereg-lock-h46-h47-v1_2.md over v1.1 + QR hypotheses_h46_h47.md).

Use /workspace/.venv-live6/bin/python (symbol-filtered parquet reads only; a full load is OOM-killed).

  --replay-check --intrabar {1m,1h}   re-run the H7-T six-coin replay through the same engine call (no H46/H47 data). Expect 355 / mean R ~ +1.69 on 1m.
  --coverage --spec {h46,h47} --intrabar X   data coverage / excluded coin-months only; no trades, no outcome.
  --final --spec {h46,h47} --intrabar X      THE one run. Writes the result file. Creates lock_<spec>_final.json (O_EXCL) BEFORE computing and
                                             refuses forever after; h47 needs h46's result first. Nobody but the user-approved owner passes --final.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from h34_paper import h46 as H  # noqa: E402
from h34_paper import h46_data as D  # noqa: E402

OUT_DEFAULT = D.RESEARCH_ROOT / "results" / "h46"


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def lock_path(out, spec):
    return Path(out) / f"lock_{spec}_final.json"


def take_lock(out, spec, intrabar, git):
    """atomic create; a second --final for the same spec (even after a crash) is refused. Recovery = TA/PM deletes the file by hand."""
    Path(out).mkdir(parents=True, exist_ok=True)
    p = lock_path(out, spec)
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise SystemExit(f"REFUSED: {p} exists -> {spec.upper()} was already run (or started) at {json.loads(p.read_text()).get('started_kst')}. One run per spec.")
    with os.fdopen(fd, "w") as fh:
        json.dump(dict(spec=spec, intrabar=intrabar, started_kst=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds"),
                       pid=os.getpid(), git=git), fh, indent=1)
    return p


def coverage_only(spec, intrabar):
    import pandas as pd
    mem = D.read_membership()
    mm = D.member_months(mem, "new") if spec == "h46" else {s: set(D.MONTHS) for s in H.SIX}
    rows = []
    for k, (sym, months) in enumerate(sorted(mm.items()), 1):
        k1h, f = D.load_1h(sym), D.load_funding(sym)
        k1 = D.load_1m(sym) if intrabar == "1m" else k1h
        rows += [dict(r, member=r["month"] in months) for r in D.coverage_rows(sym, k1h, k1, f, intrabar)]
        if k % 25 == 0:
            log(f"coverage {k}/{len(mm)}")
    df = pd.DataFrame(rows)
    m = df[df.member]
    ex = m[~m.ok]
    return df, dict(coin_months=int(len(m)), excluded=int(len(ex)), share=float(len(ex) / len(m)) if len(m) else float("nan"),
                    coins_fully_excluded=int(sum(1 for s, g in m.groupby("sym") if not g.ok.any())),
                    reasons={k: int(v) for k, v in ex.why.str.split(" ").str[0].value_counts().items()})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", choices=["h46", "h47"])
    ap.add_argument("--intrabar", choices=["1m", "1h"], help="intrabar frame for entry/stop fills (REQUIRED; see question 1 in the hand-off)")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--replay-check", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    a = ap.parse_args(argv)
    if a.replay_check:
        if not a.intrabar:
            ap.error("--intrabar required")
        r = D.replay_h7t(a.intrabar)
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / f"replay_check_{a.intrabar}.json").write_text(json.dumps(r, indent=1, default=str))
        print(json.dumps({k: v for k, v in r.items() if k != "holes"}, indent=1))
        return 0
    if a.coverage:
        if not (a.spec and a.intrabar):
            ap.error("--spec and --intrabar required")
        df, s = coverage_only(a.spec, a.intrabar)
        Path(a.out).mkdir(parents=True, exist_ok=True)
        df.to_csv(Path(a.out) / f"coverage_only_{a.spec}_{a.intrabar}.csv", index=False)
        print(json.dumps(s, indent=1))
        return 0
    if not a.final:
        ap.error("nothing to do: pass --replay-check, --coverage or --final (the one-time run; not to be passed without the PM/TA go)")
    if not (a.spec and a.intrabar):
        ap.error("--spec and --intrabar required with --final")
    from h34_paper import h46_run as R
    bad = R.check_locks()
    if bad:
        raise SystemExit("REFUSED: lock/membership sha mismatch:\n" + "\n".join(bad))
    git = R.git_state()
    if git["dirty"]:
        raise SystemExit("REFUSED: runner working tree is dirty; commit first so the result names an exact commit")
    spec = a.spec.upper()
    if a.spec == "h47" and not list(Path(a.out).glob("H46_screen_result_*.md")):
        raise SystemExit("REFUSED: run order is H46 first, then H47 (no H46 result file in the output directory)")
    take_lock(a.out, a.spec, a.intrabar, git)
    log(f"{spec} final run, intrabar {a.intrabar}, {git['branch']}@{git['head'][:10]}")
    res = R.run(spec, a.intrabar, a.out, log)
    log("verdict:", res["verdict"], "->", res["result_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
