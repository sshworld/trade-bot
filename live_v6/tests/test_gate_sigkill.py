"""GO-LIVE GATE (TA): with several open positions on TESTNET, SIGKILL the bot process; while it stays dead an
INDEPENDENT script (tools/verify_stops.py, stdlib only, no live_v6 import) must confirm via REST that EVERY open
position has an exchange-side STOP_MARKET (closePosition / reduceOnly qty ≥ position) on the closing side.
Evidence JSON goes to the reports_dir fixture (tmp; LIVE_V6_REPORTS_DIR=live_v6/reports to regenerate the committed evidence). Also run at the worst instant: killed right after an entry fill."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYMS = ["DOGEUSDT", "SOLUSDT", "XRPUSDT"]


def _env():
    e = {k: v for k, v in os.environ.items() if k not in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "LIVE_V6_NETWORK",
                                                       "LIVE_V6_MAINNET_ACK")}
    e["LIVE_V6_FORBID_MAINNET"] = "1"
    return e


def _verify(tag, reports_dir):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "verify_stops.py"), *SYMS], env=_env(),
                       capture_output=True, text=True, timeout=60)
    rep = json.loads(r.stdout)
    (reports_dir / f"gate_sigkill_{tag}.json").write_text(json.dumps(rep, indent=1))
    return r.returncode, rep


def _run_bot(tmp_path, args, until):
    p = subprocess.Popen([sys.executable, str(ROOT / "tests" / "bot_proc.py"), str(tmp_path / "bot.json"), ",".join(SYMS),
                          *args], env=_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines, t0 = [], time.time()
    while time.time() - t0 < 180:
        line = p.stdout.readline()
        if not line and p.poll() is not None:
            break
        lines.append(line)
        if until in line:
            return p, lines
    p.kill()
    raise AssertionError("bot did not reach " + until + ":\n" + "".join(lines[-30:]))


@pytest.mark.testnet
def test_gate_sigkill_multiple_positions_all_stops_present(backend, tmp_path, reports_dir):
    if backend.kind != "testnet":
        pytest.skip("testnet only")
    p, _ = _run_bot(tmp_path, [], "READY")
    time.sleep(6)                                        # at least one normal tick/reconcile cycle
    p.send_signal(signal.SIGKILL)
    assert p.wait(10) == -signal.SIGKILL
    time.sleep(3)                                        # bot stays dead during the check
    assert p.poll() is not None
    rc, rep = _verify("steady", reports_dir)
    assert rep["n_positions"] == 3, rep
    assert rc == 0 and rep["pass"], json.dumps(rep, indent=1)


@pytest.mark.testnet
def test_gate_sigkill_right_after_entry_fill(backend, tmp_path, reports_dir):
    if backend.kind != "testnet":
        pytest.skip("testnet only")
    p, _ = _run_bot(tmp_path, ["--kill-mid-entry", "XRPUSDT"], "KILLING-SELF")
    assert p.wait(10) == -signal.SIGKILL
    time.sleep(3)
    rc, rep = _verify("mid_entry", reports_dir)
    assert rep["n_positions"] == 3, rep                  # XRP filled, then the process died before its upgrade
    assert rc == 0 and rep["pass"], json.dumps(rep, indent=1)
