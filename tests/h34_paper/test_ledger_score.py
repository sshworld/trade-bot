import json
import os
import subprocess
import sys

import pytest

from h34_paper.core import LOCK_TS_MS, MS15
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import ledger_score as LS

DAY = 86_400_000


def trade(i, r15, rule="H34-B", sym="BTCUSDT", day_step=1):
    t = LOCK_TS_MS + 3600_000 + i * day_step * DAY
    cost_term = 0.0015 / 0.0065
    return {"_key": f"{rule}|{sym}|{i}", "strategy": rule, "symbol": sym, "side": "long", "signal_close_ms": t,
            "entry_bar_open_ms": t, "exit_ms": t + 4 * 3600_000, "exit_reason": "target" if r15 > 0 else "stop",
            "r_c015": r15, "r_c030": r15 - cost_term, "net_ret_c015": r15 * 0.0065, "net_ret_c030": (r15 - cost_term) * 0.0065,
            "size_mult": 0.02 / 0.0065, "wallet_entry": 1.0}


def test_score_numbers_and_verdict_pass():
    tr = [trade(i, 0.6 if i % 2 else -0.1) for i in range(70)]           # 70 trades on 70 days, strongly positive
    r = LS.score(tr, [], "H34-B", LOCK_TS_MS + 9 * 7 * DAY * 0 + 5 * 7 * DAY, seed=34)
    assert r["trades"] == 70 and r["trading_days"] == 70
    assert r["win_rate"] == pytest.approx(0.5)
    assert r["mean_r_c015"] == pytest.approx(0.25)
    assert r["mean_r_c030"] == pytest.approx(0.25 - 0.0015 / 0.0065)
    assert r["break_even_win_rate_015"] == pytest.approx(0.65) and r["break_even_win_rate_030"] == pytest.approx(0.80)
    assert r["minimum_met"] and r["max_dd_c015"] < 0.2
    assert r["half1_mean_r_c015"] > 0 and r["half2_mean_r_c015"] > 0
    assert r["verdict"] == "PASS", r["verdict"]


def test_pending_then_inconclusive_when_minimum_not_met():
    tr = [trade(i, 0.5) for i in range(10)]
    assert LS.score(tr, [], "H34-B", LOCK_TS_MS + 2 * 7 * DAY, seed=34)["verdict"].startswith("PENDING")
    assert LS.score(tr, [], "H34-B", LOCK_TS_MS + 9 * 7 * DAY, seed=34)["verdict"].startswith("INCONCLUSIVE")


def test_fail_names_the_criterion():
    tr = [trade(i, -0.2 if i % 3 else 0.3) for i in range(70)]
    r = LS.score(tr, [], "H34-B", LOCK_TS_MS + 5 * 7 * DAY, seed=34)
    assert r["verdict"].startswith("FAIL") and "C1" in r["verdict"]


def test_integrity_problem_is_inconclusive_not_fail():
    tr = [trade(i, -0.2) for i in range(70)]
    ev = [{"event": "missing_signal_bar", "strategy": "H34-B"}]
    assert LS.score(tr, ev, "H34-B", LOCK_TS_MS + 5 * 7 * DAY, seed=34)["verdict"].startswith("INCONCLUSIVE (C7")


def test_c5_single_week_share_over_40pct_fails():
    tr = [trade(i, 0.05) for i in range(69)] + [trade(70, 0.0)]
    tr[3]["r_c015"] = 20.0                                                # one week holds most of the profit
    tr[3]["r_c030"] = 20.0
    r = LS.score(tr, [], "H34-B", LOCK_TS_MS + 5 * 7 * DAY, seed=34)
    assert r["best_week_share"] > 0.4 and not r["criteria"]["C5 profit > 0 ex top 5 and no week > 40%"]


def test_cli_reads_ledger_dir(tmp_path):
    with open(tmp_path / "trades.jsonl", "w") as f:
        for i in range(5):
            f.write(json.dumps(trade(i, 0.3)) + "\n")
        f.write(json.dumps(trade(0, 0.3)) + "\n")                         # duplicate key is ignored
    out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "ledger_score.py"),
                          "--dir", str(tmp_path), "--asof-kst", "2026-11-01 12:00", "--boot", "200"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "trades 5" in out.stdout and "PENDING" in out.stdout
