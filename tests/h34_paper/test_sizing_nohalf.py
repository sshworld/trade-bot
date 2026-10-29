"""Sizing no-halving check (prereg-lock-sizing-nohalf-v1, ba8c1bae2705): the ONE flag `halving` of the sizing-up replay
(same_side_halving_at off), the open-risk-sum counter (Z5), the run-once runner. Synthetic ledgers; the real 355-trade run
with halving off is done once by tools/run_sizing_nohalf.py --final (never here). Only the known baseline (halving on) is
reproduced against the real ledger."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from h34_paper import sizing_up as S
from test_sizing_up import BR, LIVE, RULES, led, row, sim  # noqa: F401  (synthetic rules / helpers of the sizing-up tests)

RES = Path("/workspace/trade-bot-research")
REAL_LEDGER = RES / "results/sizing_up/ledger_355.csv"
needs_inputs = pytest.mark.skipif(not (RES / "results/exchangeinfo_2026-10-26.json").exists() or not (RES / "results/v4/extra/brackets_snapshot.json").exists()
                                  or not REAL_LEDGER.exists(), reason="research inputs not available")


def simh(ledger, r, halving, init=100000.0):
    return S.simulate(ledger, RULES, BR, r, init, live=LIVE, halving=halving)


# ---------------------------------------------------------------- the flag in the params
def test_default_halving_is_on_and_unchanged():
    assert S.params_for(0.5).same_side_halving_at == LIVE[1]().same_side_halving_at == 3
    assert S.params_for(0.5, halving=True) == S.params_for(0.5)


def test_halving_off_changes_only_that_field():
    on, off = S.params_for(0.5), S.params_for(0.5, halving=False)
    assert off.same_side_halving_at > 10 ** 6
    d_on, d_off = on.__dict__.copy(), off.__dict__.copy()
    d_on.pop("same_side_halving_at"), d_off.pop("same_side_halving_at")
    assert d_on == d_off                                   # risk 0.5, max_risk 1.0, cap 2.5%, leverage 10, margin 0.9 ... unchanged
    assert (off.risk_pct, off.max_risk_pct, off.portfolio_risk_cap) == (0.5, 1.0, 0.025)


def test_halving_flag_still_only_lock_risk_values():
    with pytest.raises(ValueError):
        S.params_for(0.7, halving=False)


# ---------------------------------------------------------------- flag on / off in the simulation
def test_on_halves_from_third_off_does_not():
    L = led(*[row(e=0, x=20) for _ in range(4)])
    assert list(simh(L, 0.5, True)["trades"].risk_pct_used) == [0.5, 0.5, 0.5, 0.25]
    assert list(simh(L, 0.5, False)["trades"].risk_pct_used) == [0.5, 0.5, 0.5, 0.5]
    assert list(simh(L, 0.5, False)["trades"].same_open) == [0, 1, 2, 3]
    assert list(simh(L, 0.5, True)["trades"].same_open) == [0, 1, 2, 3]


def test_default_equals_halving_on():
    L = led(*[row(e=0, x=20) for _ in range(4)])
    a, b = S.simulate(L, RULES, BR, 0.5, 100000.0, live=LIVE), simh(L, 0.5, True)
    assert a["final"] == b["final"] and list(a["trades"].qty) == list(b["trades"].qty)


def test_flag_off_identical_when_never_three_same_side():
    L = led(row(e=0, x=20), row(e=1, x=20), row(e=40, x=60), row(e=41, x=60, side=-1), row(e=42, x=60))
    on, off = simh(L, 0.5, True), simh(L, 0.5, False)
    assert off["final"] == on["final"] and list(off["trades"].qty) == list(on["trades"].qty) and off["skips"] == on["skips"]
    assert S.size_changed(on, off)["same_state_would_halve"] == 0 and S.size_changed(on, off)["qty_differs"] == 0


def test_opposite_side_positions_do_not_count_toward_halving():
    L = led(row(e=0, x=20), row(e=0, x=20, side=-1), row(e=0, x=20), row(e=0, x=20, side=-1))
    assert list(simh(L, 0.5, True)["trades"].risk_pct_used) == [0.5] * 4


def test_size_changed_counts():
    L = led(*[row(e=0, x=20) for _ in range(4)])
    on, off = simh(L, 0.5, True), simh(L, 0.5, False)
    c = S.size_changed(on, off)
    assert c["same_state_would_halve"] == 1 and c["qty_differs"] == 1 and c["baseline_halved"] == 1
    assert off["trades"].qty[3] == pytest.approx(2 * on["trades"].qty[3])


def test_off_cap_still_binds_at_2_5pct():
    # 0.5% each, 9 simultaneous same-side: five fit (2.5%), the sixth would be 3.0% -> risk_cap_portfolio; halving off, so no 0.25% steps
    s = simh(led(*[row(e=0, x=20) for _ in range(9)]), 0.5, False)
    assert s["entered"] == 5 and s["skips"] == {"risk_cap_portfolio": 4}
    assert s["max_open_risk"] == pytest.approx(0.025, abs=1e-6) and s["open_risk_over"] == 0 and s["max_concurrent"] == 5
    on = simh(led(*[row(e=0, x=20) for _ in range(9)]), 0.5, True)
    assert on["entered"] == 7 and on["open_risk_over"] == 0


# ---------------------------------------------------------------- open-risk-sum counter (Z5)
def test_open_risk_counter_counts_entries_that_push_the_sum_over_2_5pct():
    # 2.0% runs under the 6% cap: sums 2%, 4%, 6% -> two over 2.5%
    s = simh(led(*[row(e=0, x=20) for _ in range(3)]), 2.0, False)
    assert s["open_risk_over"] == 2 and s["max_open_risk"] == pytest.approx(0.06, abs=1e-6)


def test_open_risk_counter_exactly_at_limit_is_not_over():
    s = simh(led(*[row(e=0, x=20) for _ in range(5)]), 0.5, False)
    assert s["max_open_risk"] == pytest.approx(0.025, abs=1e-6) and s["open_risk_over"] == 0


def test_open_risk_sum_released_on_exit():
    L = led(*[row(e=0, x=10) for _ in range(5)], *[row(e=10, x=30) for _ in range(5)])      # exits before entries at the same minute
    s = simh(L, 0.5, False)
    assert s["entered"] == 10 and s["open_risk_over"] == 0 and s["max_concurrent"] == 5


def test_z5_clause():
    s = simh(led(*[row(e=0, x=20) for _ in range(5)]), 0.5, False)
    assert S.z5(s) == dict(max_open_risk=s["max_open_risk"], over=0, limit=0.025, z5_pass=True, skipped_by_cap=0)
    s2 = simh(led(*[row(e=0, x=20) for _ in range(3)]), 2.0, False)
    assert S.z5(s2)["z5_pass"] is False and S.z5(s2)["over"] == 2
    s3 = simh(led(*[row(e=0, x=20) for _ in range(9)]), 0.5, False)
    assert S.z5(s3)["skipped_by_cap"] == 4 and S.z5(s3)["z5_pass"]


# ---------------------------------------------------------------- the known baseline on the real ledger (halving on; not the locked run)
@needs_inputs
def test_baseline_reproduces_922_355_and_ledger_mean_R():
    ledger = pd.read_csv(REAL_LEDGER, parse_dates=["entry_time", "exit_time"])
    assert hashlib.sha256(REAL_LEDGER.read_bytes()).hexdigest().startswith("2a147ab723f5")
    assert len(ledger) == 355 and round(float(ledger.R.mean()), 5) == 1.68850
    rules = S.load_rules(RES / "results/exchangeinfo_2026-10-26.json", LIVE[2])
    br = S.load_brackets(RES / "results/v4/extra/brackets_snapshot.json")
    b = S.simulate(ledger, rules, br, 0.5, S.INIT_WALLET, live=LIVE)
    assert b["entered"] == 355 and round(b["final"], 2) == 922.02
    assert S.simulate(ledger, rules, br, 0.5, S.INIT_WALLET, live=LIVE, halving=True)["final"] == b["final"]
    assert int((b["trades"].risk_pct_used < 0.5 - 1e-12).sum()) == 101 and b["max_concurrent"] == 6 and b["open_risk_over"] == 0


# ---------------------------------------------------------------- runner: lock, run-once, outputs
def _runner():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_sizing_nohalf", Path(__file__).resolve().parents[2] / "tools" / "run_sizing_nohalf.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_runner_constants():
    m = _runner()
    assert m.LOCK_SHA12 == "ba8c1bae2705" and m.LOCK.name == "prereg-lock-sizing-nohalf-v1.md" and m.LEDGER_SHA12 == "2a147ab723f5"
    assert m.OUT == RES / "results" / "sizing_nohalf" and m.LOCK_FILE == "lock_sizing_nohalf_final.json" and m.BASE_FINAL == 922.02


def test_runner_refuses_wrong_lock(tmp_path, monkeypatch):
    m = _runner()
    p = tmp_path / "x.md"
    p.write_text("not the lock")
    monkeypatch.setattr(m, "OUT", tmp_path / "out")
    monkeypatch.setattr(m, "LOCK", p)
    with pytest.raises(SystemExit, match="REFUSED"):
        m.final()
    assert not (tmp_path / "out" / m.LOCK_FILE).exists()


@needs_inputs
def test_runner_smoke_and_run_once(tmp_path, monkeypatch):
    m = _runner()
    rng = np.random.default_rng(5)
    coins = list(S.COINS)
    px = dict(BTCUSDT=60000.0, ETHUSDT=3000.0, SOLUSDT=150.0, BNBUSDT=600.0, XRPUSDT=0.5, DOGEUSDT=0.15)
    rows = []
    for i in range(355):
        c = coins[i % 6]
        unit = float(rng.normal(0.01, 0.06))
        r = row(sym=c, e=i * 9, x=i * 9 + 30, px=px[c], stop=float(rng.uniform(0.02, 0.06)), unit=unit)
        r.update(R=unit / 0.04, W_entry=100.0, risk=0.005)
        rows.append(r)
    out = tmp_path / "out"
    out.mkdir()
    pd.DataFrame(rows).to_csv(tmp_path / "ledger.csv", index=False)
    monkeypatch.setattr(m, "OUT", out)
    monkeypatch.setattr(m, "LEDGER", tmp_path / "ledger.csv")
    monkeypatch.setattr(m, "git_state", lambda: dict(head="x" * 40, branch="t", dirty=False))
    monkeypatch.setattr(m, "LEDGER_SHA12", "")
    lock_file = tmp_path / "lock.md"
    lock_file.write_text("lock")
    monkeypatch.setattr(m, "LOCK", lock_file)
    monkeypatch.setattr(S, "verify_lock", lambda p, sha12=None: hashlib.sha256(Path(p).read_bytes()).hexdigest())
    assert m.final() == 0
    res = json.loads((out / "sizing_nohalf_result.json").read_text())
    for k in ("z1", "z2", "z3", "z3_direct", "z4", "z5"):
        assert k in res["clauses"]
    assert {"max_concurrent", "max_open_risk", "open_risk_over", "skips"} <= set(res["off"]) and "qty_differs" in res["changed"]
    assert (out / "sizing_nohalf_result.md").read_text().startswith("# Sizing no-halving check result") and (out / "trades_nohalf_risk_0.5.csv").exists()
    with pytest.raises(SystemExit, match="REFUSED"):
        m.final()
