import json
import os
from pathlib import Path

import numpy as np
import pytest

from h34_paper import hx_run as R
from h34_paper import h46 as H

DAY = 86_400_000
T0 = 1_641_168_000_000       # 2022-01-03 UTC


class FakeCoin:
    def __init__(self, sym, ok=True, member=True):
        self.sym, self.ok = sym, ok
        self.cov = [dict(sym=sym, month="2022-01", ok=ok, why="" if ok else "no data", member=member)]


def fake_gen(c, ctx):
    """3 trades per coin, one per day, +1R-ish winners alternating with losers; deterministic."""
    raws = []
    for k in range(3):
        e = T0 + k * DAY + (hash_sym(c.sym) % 50) * 60_000
        win = (k + hash_sym(c.sym)) % 2 == 0
        ep = 100.0
        xp = 103.0 if win else 98.0
        raws.append(dict(sym=c.sym, symbol=c.sym, side=1, sig_ms=e - 60_000, entry_ms=e, exit_ms=e + 3_600_000, entry_px=ep, exit_px=xp, stop_pct=0.02,
                         sl=98.0, reason="stop" if not win else "time", gap=False, bars=60, fund=0.0001, month="2022-01", group="new", in_h16=False,
                         hole_cross=False, rank=0.02 + k * 1e-4, mae=0.01, slip_r=0.0))
    return raws, dict(signals=3, entries=3)


def hash_sym(s):
    return sum(ord(x) for x in s)


UNIV = dict(six={"BTCUSDT": {"2022-01"}, "ETHUSDT": {"2022-01"}}, new={"AAAUSDT": {"2022-01"}, "BBBUSDT": {"2022-01"}, "NODATAUSDT": {"2022-01"}})


def loader(sym, months, group, h16):
    return FakeCoin(sym, ok=sym != "NODATAUSDT")


CLEAN = dict(head="abc", branch="t", dirty=False)


def test_preflight_dirty_blocked_and_unknown(tmp_path, monkeypatch):
    monkeypatch.setitem(R.REGISTRY["H48"], "blocked", "test block")
    r = R.preflight(["H48", "H99"], tmp_path, git=dict(CLEAN, dirty=True), files_ok=lambda s: [])
    assert any("dirty" in x for x in r)
    assert any("H48: BLOCKED" in x for x in r)
    assert any("H99: unknown" in x for x in r)


def test_no_spec_is_blocked_after_the_answers_and_all_locks_verify_on_disk():
    for s, sp in R.REGISTRY.items():
        assert not sp["blocked"], s
        assert R.check_files(s) == [], (s, R.check_files(s))
        assert ("answers-h48plus-questions-2026-10-29.md", "841c34b8dd7f") in sp["locks"], s


def test_h67_h68_use_the_v1_1_lock_and_rule_and_their_seeds():
    for s, seed in (("H67", 95), ("H68", 96)):
        sp = R.REGISTRY[s]
        assert ("prereg-lock-h67-h68-v1_1.md", "9ddc7ba9403c") in sp["locks"]
        assert sp["rule2"][:2] == ("hypotheses_h67_h68_v1_1.md", "29c61c0b8ef9")
        assert R.H.CFG[f"{s}-six"]["seed"] == seed and R.H.CFG[f"{s}-new"]["seed"] == seed
        assert abs(R.H.CFG[f"{s}-six"]["q"] - 0.05 / 74) < 1e-12


def test_render_states_candidate_ledger_columns_and_spec_notes():
    assert "unit" in R.LEDGER_COLS and "funding_unit" in R.LEDGER_COLS
    assert "always-true" in R.SPEC_NOTES["H59"] and "always-true" in R.SPEC_NOTES["H60"]
    assert "fill_above_open" in R.SPEC_NOTES["H51"]


def test_preflight_fe_requires_sizing(tmp_path):
    r = R.preflight(["H61"], tmp_path, git=CLEAN, files_ok=lambda s: [], sizing=False)
    assert any("sizing" in x for x in r)
    assert R.preflight(["H61"], tmp_path, git=CLEAN, files_ok=lambda s: [], sizing=True) == []


def test_preflight_sha_mismatch_detected(tmp_path, monkeypatch):
    monkeypatch.setitem(R.REGISTRY["H53"], "locks", [("prereg-lock-h53-h54.md", "000000000000")])
    assert any("expected 000000000000" in x for x in R.check_files("H53"))


def test_lock_is_exclusive(tmp_path):
    R.write_lock("H53", tmp_path, CLEAN)
    with pytest.raises(FileExistsError):
        R.write_lock("H53", tmp_path, CLEAN)
    assert R.preflight(["H53"], tmp_path, git=CLEAN, files_ok=lambda s: [])[0].startswith("H53: one-shot lock exists")


def test_cfg_values():
    c = H.CFG
    assert (c["H48-six"]["seed"], c["H48-new"]["seed"]) == (69, 70)
    assert c["H49-new"]["seed"] == 72 and c["H49-six"]["seed"] == 72
    assert [c[f"H{n}-six"]["seed"] for n in (50, 51, 52)] == [73, 74, 75] and [c[f"H{n}-new"]["seed"] for n in (50, 51, 52)] == [76, 77, 78]
    assert [c[f"H{n}-six"]["seed"] for n in range(53, 61)] == [79, 80, 81, 82, 83, 84, 85, 86]
    assert [c[f"H{n}-six"]["seed"] for n in range(61, 72)] == list(range(89, 100))
    assert abs(c["H48-six"]["q"] - 0.05 / 48) < 1e-12 and abs(c["H61-six"]["q"] - 0.05 / 74) < 1e-12
    assert (c["H53-six"]["min_trades"], c["H54-six"]["min_trades"], c["H50-six"]["min_trades"], c["H57-six"]["min_trades"]) == (200, 100, 60, 60)
    # bound percentages as printed in the locks
    for n, (nc, pct) in {"H48": (48, 99.896), "H55": (58, 99.914), "H59": (63, 99.921), "H61": (74, 99.932)}.items():
        assert round(100 * (1 - 0.05 / nc), 3) == pct


def test_session_end_to_end(tmp_path):
    gens = {"H53": fake_gen, "H50": fake_gen}
    res = R.run_session(["H53", "H50"], tmp_path, git=CLEAN, universe=UNIV, loader=loader, ctx_builder=lambda s: {}, gens=gens, h7t=None, log=lambda *_: None)
    # H53: six only; H50: six + new
    assert list(res["H53"]["groups"]) == ["six"]
    b = res["H50"]["groups"]["new"]
    assert b["coins"] == ["AAAUSDT", "BBBUSDT"] and b["n_coins"] == 2 and b["nodata"] == ["NODATAUSDT"] and b["n_nodata"] == 1
    assert res["H50"]["groups"]["six"]["n_coins"] == 2
    d = tmp_path / "H50"
    for fn in ("RUN_LOCK_H50.json", "H50_screen_result.md", "summary_numbers.md", "coin_list_h50_new.csv", "coins_no_data_h50_new.csv", "skipped_signals_h50_six.csv"):
        assert (d / fn).exists(), fn
    md = (d / "H50_screen_result.md").read_text()
    assert "Coin list (2 coins with data): AAAUSDT, BBBUSDT" in md and "NO DATA: 1: NODATAUSDT" in md
    assert "seed 76" in md and "seed 73" in md and "verdict is TA's" in md
    assert json.loads((d / "RUN_LOCK_H50.json").read_text())["seeds"]["H50-new"] == 76
    # rerun refused
    with pytest.raises(SystemExit):
        R.run_session(["H50"], tmp_path, git=CLEAN, universe=UNIV, loader=loader, ctx_builder=lambda s: {}, gens=gens, log=lambda *_: None)


def test_lock_written_before_compute(tmp_path):
    seen = {}

    def boom(c, ctx):
        seen["lock"] = (tmp_path / "H53" / "RUN_LOCK_H53.json").exists()
        raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        R.run_session(["H53"], tmp_path, git=CLEAN, universe=UNIV, loader=loader, ctx_builder=lambda s: {}, gens={"H53": boom}, log=lambda *_: None)
    assert seen["lock"] is True
    # lock stays: a rerun after the crash is refused
    assert any("one-shot lock exists" in x for x in R.preflight(["H53"], tmp_path, git=CLEAN, files_ok=lambda s: []))


def test_books_are_the_h46_books(tmp_path):
    res = R.run_session(["H53"], tmp_path, git=CLEAN, universe=UNIV, loader=loader, ctx_builder=lambda s: {}, gens={"H53": fake_gen}, log=lambda *_: None)
    b = res["H53"]["groups"]["six"]
    # 2 coins x 3 trades, all entries within the same minutes -> 3-concurrent / one-per-coin limits apply, unlimited keeps all
    assert b["n_raw"] == 6 and len(b["ledger_u"]) == 6 and len(b["ledger"]) <= 6
    assert all(t["r_c015"] == pytest.approx((0.03 - 0.0015 - 0.0001) / 0.0217) or t["r_c015"] == pytest.approx((-0.02 - 0.0015 - 0.0001) / 0.0217) for t in b["ledger_u"])
    assert b["sc"]["S1-1"][1] == pytest.approx(np.mean([t["r_c015"] for t in b["ledger"]]))


def test_fe_ledger_columns_and_values():
    raws = fake_gen(FakeCoin("AAAUSDT"), {})[0]
    df = R.fe_ledger(raws)
    assert list(df.columns) == R.LEDGER_COLS and len(df) == 3
    r = raws[0]
    row = df.iloc[0]
    assert row.stop_dist == r["stop_pct"] and row.fee_unit == 0.0015 and row.slip_unit == 0
    assert row.funding_unit == pytest.approx(-0.0001)
    assert row.unit == pytest.approx(row.gross_unit - 0.0015 + row.funding_unit)
    assert row.entry_time.startswith("2022-01-03")


def test_overlap_h7t():
    led = [dict(symbol="AAA", entry_ms=T0), dict(symbol="BBB", entry_ms=T0 + 20 * DAY)]
    h7 = dict(sym=np.array(["AAA", "CCC"]), ms=np.array([T0 + 3_600_000, T0 + 20 * DAY + 1000]))
    o = R.overlap_h7t(led, h7)
    assert o["day"]["any"] == 1.0 and o["day"]["same_coin"] == 0.5


def test_fe2_group_writes_candidate_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "preflight", lambda *a, **k: [])
    res = R.run_session(["H61"], tmp_path, git=CLEAN, universe=UNIV, loader=loader, ctx_builder=lambda s: {}, gens={"H61": fake_gen}, log=lambda *_: None,
                        apply_sizing=lambda spec, grp, df: dict(rows=len(df)))
    assert (tmp_path / "H61" / "fe_candidate_ledger_h61_new.csv").exists()
    assert res["H61"]["groups"]["new"]["sizing"] == dict(rows=6)
    assert "FE sizing output" in (tmp_path / "H61" / "H61_screen_result.md").read_text()
