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
                        apply_sizing=lambda spec, grp, df, b: dict(rows=len(df), seed=b['seed']))
    assert (tmp_path / "H61" / "fe_candidate_ledger_h61_new.csv").exists()
    assert res["H61"]["groups"]["new"]["sizing"] == dict(rows=6, seed=89)
    assert "FE sizing output" in (tmp_path / "H61" / "H61_screen_result.md").read_text()


def test_fullentry_answers_lock_is_checked_for_fe2_specs():
    for sp in ("H61", "H62", "H63", "H64", "H65", "H66", "H67", "H68", "H69", "H70", "H71"):
        assert ("answers-fullentry-R1-R10-C1-C6-2026-10-29.md", "b9c172688fee") in R.REGISTRY[sp]["locks"]
    assert R.check_files("H61") == []


def test_candidate_ledger_has_R_column_equal_to_unit_over_stop_plus_fee():
    raws = fake_gen(FakeCoin("AAAUSDT"), {})[0]
    df = R.fe_ledger(raws)
    assert R.LEDGER_COLS[-1] == "R" and "R" in df
    assert df.R.tolist() == pytest.approx((df.unit / (df.stop_dist + 0.0017)).tolist())


def test_default_sizing_hook_is_available_and_sizing_ready():
    assert R.sizing_ready()
    assert callable(R.default_apply_sizing)


def test_fe2_sizing_dict_is_rendered_as_tables(tmp_path, monkeypatch):
    from h34_paper import hx_sizing as Z
    monkeypatch.setattr(R, "preflight", lambda *a, **k: [])
    z = dict(spec="H61", group="new", n_candidates_total=0, seed=89, n_cand=74, min_stop_dist=0.006, sims={}, rows={}, no_exchange_info={}, variants=(), gate={}, gate_detail={},
             rp_applies={}, candidate_R={}, note="no candidate trades: nothing to size", variant_c_note="")
    res = R.run_session(["H61"], tmp_path, git=CLEAN, universe=UNIV, loader=loader, ctx_builder=lambda s: {}, gens={"H61": fake_gen}, log=lambda *_: None,
                        apply_sizing=lambda spec, grp, df, b: z)
    assert "no candidate trades: nothing to size" in (tmp_path / "H61" / "H61_screen_result.md").read_text()


def test_default_rules_loader_six_from_file_new_from_exchangeinfo():
    if not R.EXCHANGE_INFO.exists():
        pytest.skip("no snapshot")
    rules, br = R.default_rules_loader(["BTCUSDT", "1000BONKUSDT", "EOSUSDT"])
    assert str(rules["BTCUSDT"].min_notional) == "50" and "1000BONKUSDT" in rules and "EOSUSDT" not in rules
    assert set(rules) <= set(br)


def test_candidate_list_stats_hold_and_annual_n():
    d = 86_400_000
    led = [dict(entry_ms=T0, exit_ms=T0 + 2 * 3_600_000), dict(entry_ms=T0 + 100 * d, exit_ms=T0 + 100 * d + 4 * 3_600_000), dict(entry_ms=T0 + 200 * d, exit_ms=T0 + 200 * d + 3 * 3_600_000)]
    c = R.candidate_list_stats(led)
    assert c["n"] == 3 and c["avg_hold_h"] == pytest.approx(3.0)
    span_days = (200 * d + 3 * 3_600_000) / d
    assert c["annual_n"] == int(np.floor(3 / (span_days / 365.25) + 0.5))
    assert R.candidate_list_stats([]) == dict(n=0, avg_hold_h=None, annual_n=0)


def test_sizing_meta_is_rendered():
    from h34_paper import hx_sizing as Z
    z = dict(min_stop_dist=0.006, note="x", meta=dict(exchangeinfo_sha256="aa", brackets_sha256="bb", sizing_module="m", rules_new_coins="r", ledger_cols=["a"]))
    assert "exchangeinfo_sha256 aa" in "\n".join(Z.render_sizing(z))


# ---- lock alignment (verdict-h61-h71-2026-10-29: runner labels and S1-0 tiers must match the lock)
def test_s1_0_tiers_match_lock():
    assert R.S1_0_TIERS == (1000, 300)
    assert [R.s1_0_tier(n) for n in (0, 299, 300, 999, 1000, 5000)] == ["undecidable", "undecidable", "conditional", "conditional", "pass", "pass"]


def _old_sc(n=75):
    return {"n": n, "S1-0": (False, "x"), "S1-1": (False, -0.1), "S1-2": (False, -0.5), "S1-3": (False, -0.2), "S1-4": (False, (-0.1, -0.2, 37, 38)),
            "S1-5": (False, 0.36), "S1-6": (False, (-0.44, 4)), "S1-Y": (True, (0.3, "2021"))}


def test_lock_s1_labels_and_values():
    L = R.lock_s1(_old_sc(), "fe2")
    assert list(L) == ["S1-0", "S1-1", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6"] and "S1-Y" not in L
    assert L["S1-0"][1]["tier"] == "undecidable" and L["S1-0"][0] is False
    assert R.lock_s1(_old_sc(1000), "fe2")["S1-0"][1]["tier"] == "pass"
    assert R.lock_s1(_old_sc(500), "fe2")["S1-0"][1]["tier"] == "conditional"
    assert L["S1-5"][0] is False and L["S1-5"][1] == dict(max_dd=0.36, top5_removed_mean=-0.44, removed=4)
    assert L["S1-6"] == (True, (0.3, "2021"))      # lock S1-6 = best-year share (old 'S1-Y')
    ok = dict(_old_sc(1200), **{"S1-5": (True, 0.1), "S1-6": (True, (0.2, 3))})
    assert R.lock_s1(ok, "fe2")["S1-5"][0] is True
    assert R.lock_s1(dict(ok, **{"S1-6": (False, (-0.1, 3))}), "fe2")["S1-5"][0] is False


def test_s1_lines_use_lock_labels():
    txt = "\n".join(R.s1_lines(_old_sc(), "Limits book", "fe2"))
    assert "S1-Y" not in txt and "S1-0 trade-count tier (>= 1000 pass; 300-999 conditional; < 300 undecidable): undecidable" in txt
    assert "S1-5 MDD <= 20% and top-5%-removed mean > 0" in txt and "S1-6 best-year share of total R <= 60%" in txt
    assert "trades 75 >= " not in txt          # the old built-in 300/100 trade-count check is gone
