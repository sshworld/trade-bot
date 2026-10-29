#!/workspace/.venv-live6/bin/python
"""One-shot hx screens (H48..H71).  Usage: run_screen_hx.py --final H61 H62 ...   (refuses a dirty tree, a rerun, a blocked spec, missing sizing)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from h34_paper import hx_run as R  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--final", action="store_true", help="the real, one-time run (writes the O_EXCL lock files first)")
    ap.add_argument("--out", default=str(R.RESULTS_ROOT))
    a = ap.parse_args()
    if not a.final:
        bad = R.preflight(a.specs, a.out)
        print("preflight:", "OK" if not bad else "\n".join(bad))
        return 0 if not bad else 1
    res = R.run_session(a.specs, a.out, apply_sizing=R.default_apply_sizing)
    for s, r in res.items():
        print(s, r["result_path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
