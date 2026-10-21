"""deploy/heartbeat_ping.sh (external dead-man): /fail when bars stall even though the state file is fresh (live bug)."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "heartbeat_ping.sh"
H4 = 4 * 3600 * 1000


def run(tmp_path, state):
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    (b / "systemctl").write_text("#!/bin/sh\necho active\n")
    (b / "curl").write_text(f"#!/bin/sh\nfor a; do last=$a; done\necho \"$last\" >> {tmp_path}/curl.log\n")
    for f in b.iterdir():
        f.chmod(0o755)
    st = tmp_path / "state.json"
    st.write_text(json.dumps(state))
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", HEARTBEAT_URL="https://hc.example/u", HB_STATE=str(st))
    r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30)
    return r.stdout, (tmp_path / "curl.log").read_text().split()


def state(now, lbc, lo, ok=True, ht=None):
    return {"meta": {"last_bar_close": lbc, "health": {"t": ht or now, "ok": ok, "blocks": [] if ok else ["bar_close_stale"]}},
            "strategy": {"models": {s: {"last_open": lo} for s in ("BTCUSDT", "ETHUSDT")}}}


def test_ok_when_bars_current(tmp_path):
    now = int(time.time() * 1000)
    T = now // H4 * H4
    out, urls = run(tmp_path, state(now, T, T - H4))
    assert urls == ["https://hc.example/u"], out


def test_fail_when_bars_stall_although_state_fresh(tmp_path):
    now = int(time.time() * 1000)
    T = now // H4 * H4
    if now - T < 601_000:
        pytest.skip("within the grace after a boundary")
    out, urls = run(tmp_path, state(now, None, T - 6 * H4))      # = VPS state (no last_bar_close, models frozen)
    assert urls == ["https://hc.example/u/fail"] and "4h bar not committed" in out


def test_fail_when_engine_unhealthy_or_old_build(tmp_path):
    now = int(time.time() * 1000)
    T = now // H4 * H4
    _, urls = run(tmp_path, state(now, T, T - H4, ok=False))
    assert urls == ["https://hc.example/u/fail"]
    (tmp_path / "curl.log").unlink()
    s = state(now, T, T - H4)
    s["meta"].pop("health")
    _, urls = run(tmp_path, s)
    assert urls == ["https://hc.example/u/fail"]
    (tmp_path / "curl.log").unlink()
    _, urls = run(tmp_path, state(now, T, T - H4, ht=now - 400_000))
    assert urls == ["https://hc.example/u/fail"]
