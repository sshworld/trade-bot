"""Clear the peak-drawdown entry halt (meta.peak_dd) -- TEAM tool (Developer runs it after TA judges), not the user.
The engine never clears peak_dd by itself (and `python -m live_v6 resume` does not either). Stdlib only, no code change
or redeploy needed.

  sudo systemctl stop live_v6-live
  sudo python3 /opt/tradebot/app/current/live_v6/tools/clear_peak_halt.py --by "Developer (TA ok 11/04)" [--reset-peak]
  sudo systemctl start live_v6-live

--state      default /var/lib/live_v6-live/mainnet.json
--by         required: who clears it (written to the audit log with the time and the sudo user)
--reset-peak set peak_equity to the last recorded equity (otherwise the old peak stays and, if equity is still under
             80 % of it, the next reconcile halts again with a new alert)
--unit       refuse while this systemd unit is active (default live_v6-live; a running engine would overwrite the file)
--dry-run    print what would change, write nothing
Writes: a backup <state>.bak-peakclear-<UTC>, the state (atomic replace, owner/mode kept), meta.peak_dd_clears (last
50) and one line in <state dir>/peak_dd_clears.jsonl."""
import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal


def unit_active(unit):
    if not unit:
        return False
    r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
    return r.stdout.strip() in ("active", "activating", "reloading")


def clear(st, by, reset_peak, now_ms):
    m = st.setdefault("meta", {})
    pd = m.get("peak_dd")
    if not pd:
        return None
    ent = {"t_ms": now_ms, "by": by, "sudo_user": os.environ.get("SUDO_USER") or getpass.getuser(), "cleared": pd,
           "equity": m.get("equity"), "peak_before": m.get("peak_equity"), "reset_peak": bool(reset_peak)}
    m.pop("peak_dd")
    if reset_peak and m.get("equity") is not None:
        m["peak_equity"] = str(Decimal(str(m["equity"])))
    ent["peak_after"] = m.get("peak_equity")
    m.setdefault("peak_dd_clears", []).append(ent)
    del m["peak_dd_clears"][:-50]
    return ent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="/var/lib/live_v6-live/mainnet.json")
    ap.add_argument("--by", required=True)
    ap.add_argument("--reset-peak", action="store_true")
    ap.add_argument("--unit", default="live_v6-live")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.by.strip():
        sys.exit("--by must name who clears the halt")
    if unit_active(a.unit):
        print(f"REFUSED: {a.unit} is active -- stop it first (the running engine would overwrite the state)")
        return 2
    with open(a.state) as f:
        st = json.load(f)
    ent = clear(st, a.by.strip(), a.reset_peak, int(time.time() * 1000))
    if ent is None:
        print("no peak_dd halt set -- nothing to clear")
        return 0
    print(("DRY RUN " if a.dry_run else "") + "clear peak_dd: " + json.dumps(ent, ensure_ascii=False))
    if a.dry_run:
        return 0
    sb = os.stat(a.state)
    bak = f"{a.state}.bak-peakclear-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    shutil.copy2(a.state, bak)
    tmp = a.state + ".clear.tmp"
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
    with open(os.path.join(os.path.dirname(os.path.abspath(a.state)), "peak_dd_clears.jsonl"), "a") as f:
        f.write(json.dumps(ent, ensure_ascii=False) + "\n")
    print(f"cleared; backup {bak}; peak_equity now {ent['peak_after']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
