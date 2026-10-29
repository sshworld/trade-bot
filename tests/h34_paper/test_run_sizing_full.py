"""Smoke tests for tools/run_sizing_full.py on SYNTHETIC data only (nothing here touches the real ledger, the real lock file or results/)."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.h34_paper.test_sizing_full_v21_rp import BR, RULES, T0, led, prices, row

_spec = importlib.util.spec_from_file_location("run_sizing_full", Path(__file__).resolve().parents[2] / "tools" / "run_sizing_full.py")
RUN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RUN)


def _ledger():
    rows = []
    for k in range(12):
        rows.append(row(sym=("BTCUSDT", "ETHUSDT", "SOLUSDT")[k % 3], e=10 * k, x=10 * k + 6, stop=0.02, unit=0.04 if k % 4 else -0.02))
    L = led(*rows)
    L["R"] = np.where(L.unit > 0, 1.5, -1.0)
    return L


def test_compute_gives_six_ledgers_with_all_report_fields_and_gate(tmp_path):
    L = _ledger()
    res = RUN.compute(L, RULES, BR, prices({}), runs=200)
    assert set(res["sims"]) == set(RUN.KEYS)
    for k in RUN.KEYS:
        r = res["rows"][k]
        assert {"trades", "annual_n", "mean_R", "final_wallet", "clauses", "rp_stats", "skips_by_reason", "first_touch_m25_vs_initial"} <= set(r)
        assert {"z1_max_dd", "z2_share", "z3_worst_loss_frac"} <= set(r["clauses"])
        assert ("gated_rp_verdict_applies" in r) == k.endswith("on")
        if k.endswith("on"):
            assert r["no_price"] == r["replace_attempts"].get("no_price", 0)
    assert set(res["gate_flags"]) == {"A_on", "B_on", "C_on"}


def test_write_outputs_files_and_sha256sums(tmp_path):
    res = RUN.compute(_ledger(), RULES, BR, prices({}), runs=100)
    meta = dict(started_kst="x", git=dict(head="h", branch="b"), ledger_sha256="0" * 64, exchangeinfo_sha256="1" * 64, brackets_sha256="2" * 64, locks={"f.md": "a" * 64})
    RUN.write_outputs(res, meta, tmp_path)
    for n in ("sizing_full_result.md", "sizing_full_result.json", "SHA256SUMS", "trades_C_on.csv", "replacements_A_on.csv", "skips_B_off.csv"):
        assert (tmp_path / n).exists()
    sums = (tmp_path / "SHA256SUMS").read_text().splitlines()
    assert all(RUN.sha256_file(tmp_path / ln.split("  ")[1]) == ln.split("  ")[0] for ln in sums)
    md = (tmp_path / "sizing_full_result.md").read_text()
    assert "Funding during the replacement window is NOT modelled" in md and "no_price" in md
    json.loads((tmp_path / "sizing_full_result.json").read_text())


def test_lock_is_o_excl_and_refuses_second_take(tmp_path):
    p = tmp_path / "lock.json"
    RUN.take_lock(p, dict(a=1))
    with pytest.raises(SystemExit, match="REFUSED"):
        RUN.take_lock(p, dict(a=1))


def test_verify_locks_refuses_wrong_hash(tmp_path):
    (tmp_path / "x.md").write_text("hello")
    with pytest.raises(SystemExit, match="REFUSED"):
        RUN.verify_locks(tmp_path, {"x.md": "000000000000"})
    h = RUN.sha256_file(tmp_path / "x.md")
    assert RUN.verify_locks(tmp_path, {"x.md": h[:12]})["x.md"] == h


def test_make_price_at_exact_minute_and_missing():
    idx = pd.date_range("2024-01-01", periods=5, freq="min")
    pa = RUN.make_price_at({"BTCUSDT": pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)})
    assert pa("BTCUSDT", pd.Timestamp("2024-01-01 00:02")) == 3.0
    assert pa("BTCUSDT", pd.Timestamp("2024-01-01 00:10")) is None
    assert pa("ETHUSDT", pd.Timestamp("2024-01-01 00:02")) is None


def test_runner_paths_and_input_lock_list():
    assert RUN.MIN_STOP_DIST == 0.006
    assert RUN.LOCKFILE.parent == Path("/workspace/trade-bot-research/results/sizing_full")
    assert set(RUN.INPUT_LOCKS.values()) == {"539c7585353b", "9bc7869cd811", "a5852ccbc9b0", "31619c1507f2", "03a2d0898830", "b9c172688fee"}
