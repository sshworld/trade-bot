"""TA R4 — ops tool: adopt an UNKNOWN exchange position (st["unknown"], i.e. not in the state file) into the bot's
state file so the bot manages it from its next start. DRY-RUN by default; nothing is sent to the exchange.

    # 1) stop the bot (the running bot rewrites the state file and would overwrite the change)
    sudo systemctl stop live_v6-live
    # 2) dry run (default) — shows exactly what would be written
    sudo -u tradebot /opt/tradebot/.venv/bin/python -m live_v6.tools.adopt_position \
         --state /var/lib/live_v6-live/mainnet.json --sym DOGEUSDT --unit live_v6-live
    # 3) apply (refused while the unit is active; a backup <state>.bak-adopt-<UTC> is written first)
    ... same command ... --apply
    # 4) start the bot; its first reconcile checks qty against the exchange (exchange wins) and the stop

Rules: long positions only (H7-T is long-only — a short must be closed by hand); the unknown entry must have a
confirmed exchange stop (stop_px recorded by the bot); never adopts a symbol already in the state file.
model_entry_open: `auto` (default) = the model's current entry bar if the model holds this coin, else none. With
none, the strategy treats the position as not its own trade and CLOSES it at the next 4h close (model_sync) — the
dry run prints this warning; adopting is ops' explicit decision. Run from the release directory (…/app/current) so
`live_v6` imports, or with PYTHONPATH set. Prints no secrets (the state file holds none)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from decimal import Decimal


def unit_active(unit: str) -> bool:
    r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, check=False)
    return r.stdout.strip() in ("active", "activating", "reloading", "deactivating")


def build(state: dict, sym: str, model_entry_open: str, cid_prefix: str, now_ms: int) -> tuple[dict, list[str]]:
    unknown, pos = state.get("unknown") or {}, state.get("pos") or {}
    if sym in pos:
        raise SystemExit(f"{sym} is already in the state file (pos) — nothing to adopt")
    u = unknown.get(sym)
    if not u:
        raise SystemExit(f"{sym} is not an unknown position in this state file (st['unknown'] has: {sorted(unknown)})")
    if int(u.get("side", 0)) != 1:
        raise SystemExit(f"{sym} is a SHORT ({u.get('amt')}) — the strategy is long-only: close it by hand instead")
    if not u.get("stop_px") or u.get("unprotected"):
        raise SystemExit(f"{sym} has no confirmed exchange stop yet — not adoptable (wait for the bot to place it)")
    qty, entry, stop = Decimal(u["qty"]), Decimal(u["entry_px"]), Decimal(u["stop_px"])
    model = ((state.get("strategy") or {}).get("models") or {}).get(sym) or {}
    notes = []
    if model_entry_open == "auto":
        meo = model.get("ei_open") if model.get("pos") else None
    elif model_entry_open == "none":
        meo = None
    else:
        meo = int(model_entry_open)
    if meo is None or meo != model.get("ei_open") or not model.get("pos"):
        notes.append(f"WARNING: the model does not hold this trade (model pos={model.get('pos')} ei_open={model.get('ei_open')}, "
                     f"adopted model_entry_open={meo}) → the bot will CLOSE {sym} at the next 4h close (model_sync).")
    sd = entry - stop
    j = {"cid": f"{cid_prefix}{sym.removesuffix('USDT')}a{now_ms // 1000}", "side": 1, "qty": str(qty),
         "entry_px": str(entry), "stop_px": str(stop), "stop_dist": str(sd), "risk_usdt": str(max(sd, Decimal(0)) * qty),
         "risk_frac": u.get("risk_frac"), "lev": None, "mmr": None, "model_entry_open": meo, "opened_ms": now_ms,
         "adopted": True, "adopted_from_unknown": {k: u.get(k) for k in ("detected_ms", "stop_src", "stop_cid")},
         "stop_seq": int(u.get("stop_seq", 0)) + 1, "exit_seq": 0}
    if sd <= 0:
        notes.append(f"NOTE: stop {stop} is not below the entry {entry} (risk recorded as 0).")
    return j, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Adopt an unknown exchange position into the live_v6 state file (TA R4).")
    ap.add_argument("--state", required=True, help="state file, e.g. /var/lib/live_v6-live/mainnet.json")
    ap.add_argument("--sym", required=True)
    ap.add_argument("--unit", help="systemd unit of that bot; --apply is refused while it is active")
    ap.add_argument("--model-entry-open", default="auto", help="auto (default) | none | <ms>")
    ap.add_argument("--cid-prefix", default="v6")
    ap.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    a = ap.parse_args(argv)
    with open(a.state) as f:
        state = json.load(f)
    j, notes = build(state, a.sym, a.model_entry_open, a.cid_prefix, int(time.time() * 1000))
    print(json.dumps({"adopt": a.sym, "journal_entry": j, "remove_from_unknown": state["unknown"][a.sym]}, indent=2, default=str))
    for n in notes:
        print(n)
    if not a.apply:
        print("DRY RUN — nothing written. Re-run with --apply (bot unit stopped) to write.")
        return 0
    if not a.unit:
        raise SystemExit("--apply needs --unit <systemd unit of this bot> (checked to be stopped)")
    if unit_active(a.unit):
        raise SystemExit(f"{a.unit} is active — stop it first (the running bot would overwrite the state file)")
    bak = f"{a.state}.bak-adopt-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    shutil.copy2(a.state, bak)
    state.setdefault("pos", {})[a.sym] = j
    state["unknown"].pop(a.sym, None)
    st = os.stat(a.state)
    tmp = f"{a.state}.adopt-tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, default=str)
        f.flush()
        os.fsync(f.fileno())
    if os.geteuid() == 0:
        os.chown(tmp, st.st_uid, st.st_gid)
    os.chmod(tmp, st.st_mode & 0o777)
    os.replace(tmp, a.state)
    print(f"APPLIED: {a.sym} moved from unknown to pos in {a.state} (backup {bak}). Start the bot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
