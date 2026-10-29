"""Live trade log (TA spec v1, 2026-10-29): append-only JSONL, one file per kind — `trades` (one line per closed trade),
`skips` (one line per skipped signal), `daily` (one line per UTC day, written at 00:00 UTC).

Recording only. `write` may raise (disk full, unwritable path, …); the engine catches every error, logs it (journald)
and counts it for the daily line — a log write never blocks, retries or delays trading. No fsync: the state file stays
the source of truth; these files are for analysis."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

KINDS = ("trades", "skips", "daily")
KST = timezone(timedelta(hours=9))
SCHEMA = 1


def kst(ms) -> str | None:
    """Display time (KST) for a UTC millisecond timestamp."""
    if ms is None:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, KST).isoformat(timespec="milliseconds")


def code_commit() -> str:
    """Running code version: env LIVE_V6_COMMIT, else `git rev-parse` of the checkout, else the app directory name
    (deploys extract a tarball into /opt/tradebot/app/<sha>). Read once at start; never raises."""
    env = os.getenv("LIVE_V6_COMMIT")
    if env:
        return env
    root = Path(__file__).resolve().parents[1]
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                           timeout=2, check=False)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return root.name or "unknown"


def _default(o):
    if isinstance(o, Decimal):
        return str(o)
    return str(o)


class EventLog:
    def __init__(self, directory: str, network: str, commit: str | None = None):
        self.paths = {k: os.path.join(directory, f"{network}_{k}.jsonl") for k in KINDS}
        self.commit = commit if commit is not None else code_commit()

    def write(self, kind: str, rec: dict) -> None:
        """Append one line. Raises on any failure (the caller logs and counts it)."""
        line = json.dumps(dict(rec, v=SCHEMA), ensure_ascii=False, default=_default, separators=(",", ":"))
        with open(self.paths[kind], "a", encoding="utf-8") as f:
            f.write(line + "\n")
