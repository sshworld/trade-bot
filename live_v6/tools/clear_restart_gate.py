"""Reset the BinHV45 restart-gate anchor and clear a gate halt. Operator tool, not the user.

The engine sets meta.restart_gate_anchor once, on the first binhv45 start, and never moves it.
A halt_on_negative halt (meta.restart_gate) stays across process restarts until this tool runs.
`python -m live_v6 resume` does not clear it.

  sudo systemctl stop live_v6-live
  sudo python3 /opt/tradebot/app/current/live_v6/tools/clear_restart_gate.py --by "Developer (TA ok <date>)"
  sudo systemctl start live_v6-live

The anchor moves to now, so trades closed before this reset are not counted. The open book's SL/TP
are not touched (this tool only edits the state file).

--state    default /var/lib/live_v6-live/mainnet.json
--by       required: who resets it
--unit     refuse while this systemd unit is active (default live_v6-live)
--dry-run  print what would change, write nothing
"""
import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone


def unit_active(unit):
    if not unit:
        return False
    r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
    return r.stdout.strip() in ("active", "activating", "reloading")


def clear(st, by, now_ms):
    m = st.setdefault("meta", {})
    if not m.get("restart_gate_anchor") and not m.get("restart_gate"):
        return None
    ent = {"t_ms": now_ms, "by": by, "sudo_user": os.environ.get("SUDO_USER") or getpass.getuser(),
           "anchor_before": m.get("restart_gate_anchor"), "halt": m.pop("restart_gate", None)}
    m["restart_gate_anchor"] = {"t_ms": now_ms, "strategy": "binhv45", "reset_by": by}
    ent["anchor_after"] = m["restart_gate_anchor"]
    m.setdefault("restart_gate_clears", []).append(ent)
    del m["restart_gate_clears"][:-50]
    return ent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="/var/lib/live_v6-live/mainnet.json")
    ap.add_argument("--by", required=True)
    ap.add_argument("--unit", default="live_v6-live")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.by.strip():
        sys.exit("--by must name who resets the gate")
    if unit_active(a.unit):
        print(f"REFUSED: {a.unit} is active -- stop it first (the running engine would overwrite the state)")
        return 2
    with open(a.state) as f:
        st = json.load(f)
    ent = clear(st, a.by.strip(), int(time.time() * 1000))
    if ent is None:
        print("no restart-gate anchor or halt -- nothing to clear")
        return 0
    print(("DRY RUN " if a.dry_run else "") + "reset restart gate: " + json.dumps(ent, ensure_ascii=False, default=str))
    if a.dry_run:
        return 0
    sb = os.stat(a.state)
    bak = f"{a.state}.bak-gateclear-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    shutil.copy2(a.state, bak)
    tmp = a.state + ".gate.tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, sb.st_mode & 0o7777)
    try:
        os.chown(tmp, sb.st_uid, sb.st_gid)
    except PermissionError:
        pass
    os.replace(tmp, a.state)
    with open(os.path.join(os.path.dirname(os.path.abspath(a.state)), "restart_gate_clears.jsonl"), "a") as f:
        f.write(json.dumps(ent, ensure_ascii=False, default=str) + "\n")
    print(f"reset; backup {bak}; anchor now {ent['anchor_after']['t_ms']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
