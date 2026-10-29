"""Wiring of the FE-v2 sizing hook (h34_paper/hx_sizing.py) to the TA sizing module (sizing_full.py @ sizing-full 1f1c05e). Synthetic data only. Written BEFORE the code."""
from decimal import Decimal as Dc

import numpy as np
import pandas as pd
import pytest

from h34_paper import hx_sizing as Z
from h34_paper import sizing_full as F
from live_v6.rules import SymbolRules

SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
T0 = pd.Timestamp("2022-01-03 00:00:00")
H1 = pd.Timedelta(hours=1)


def rules(sym="X"):
    return SymbolRules(symbol=sym, tick_size=Dc("0.01"), step_size=Dc("0.001"), min_qty=Dc("0.001"), min_notional=Dc("5"), max_qty=Dc("1000"))


BK = [{"floor": 0.0, "cap": 1e9, "mmr": 0.004, "max_lev": 50}]


def rl(syms):
    rs, bs = {}, {}
    for s in syms:
        if s.startswith("NOINFO"):
            continue
        rs[s], bs[s] = rules(s), list(BK)
    return rs, bs


def fe_row(sym="BTCUSDT", k=0, side=1, stop=0.02, unit=0.01, hold_h=2, entry_px=100.0, mae=0.005):
    et = T0 + k * H1
    return dict(sym=sym, side=side, entry_time=et.strftime("%Y-%m-%d %H:%M:%S"), exit_time=(et + hold_h * H1).strftime("%Y-%m-%d %H:%M:%S"), entry_px=entry_px,
                stop_dist=stop, mae=mae, unit=unit, fee1=0.00075, gross_unit=unit + 0.0015, fee_unit=0.0015, slip_unit=0.0, funding_unit=0.0)


def fe_df(rows):
    return pd.DataFrame(rows)


SC_PASS = {"S1-1": (True, 0.3), "S1-2": (True, 0.1), "S1-3": (True, 0.2), "S1-4": (True, (0.3, 0.3)), "S1-5": (False, 0.5), "S1-6": (True, 0.1), "S1-Y": (True, (0.3, 2022))}


def prices(opens):
    return lambda sym, ts: opens.get((sym, ts))


# ---------------------------------------------------------------- ledger frame
def test_ledger_frame_adds_R_and_parses_times():
    L = Z.ledger_frame(fe_df([fe_row(unit=0.0183, stop=0.02)]))
    assert L.R[0] == pytest.approx(0.0183 / (0.02 + 0.0017))
    assert pd.api.types.is_datetime64_any_dtype(L.entry_time) and pd.api.types.is_datetime64_any_dtype(L.exit_time)
    for c in Z.SIZING_COLS:
        assert c in L


def test_ledger_frame_does_not_modify_input():
    d = fe_df([fe_row()])
    before = d.copy()
    Z.ledger_frame(d)
    pd.testing.assert_frame_equal(d, before)


# ---------------------------------------------------------------- which variants
def test_variants_six_group_runs_ABC_new_group_AB_only():
    assert Z.variants_for(fe_df([fe_row(s, k) for k, s in enumerate(SIX)])) == ("A", "B", "C")
    assert Z.variants_for(fe_df([fe_row("BTCUSDT"), fe_row("AAAUSDT", 1)])) == ("A", "B")
    assert Z.variants_for(fe_df([fe_row("AAAUSDT")])) == ("A", "B")


# ---------------------------------------------------------------- missing exchange info
def test_missing_exchange_info_is_removed_and_counted():
    L = Z.ledger_frame(fe_df([fe_row("BTCUSDT", 0), fe_row("NOINFO1USDT", 1), fe_row("NOINFO1USDT", 5), fe_row("ETHUSDT", 9)]))
    keep, miss = Z.split_no_info(L, *rl(["BTCUSDT", "ETHUSDT", "NOINFO1USDT"]))
    assert list(keep.sym) == ["BTCUSDT", "ETHUSDT"] and miss == {"NOINFO1USDT": 2}


# ---------------------------------------------------------------- gate
def test_gate_takes_S1_5_from_variant_and_rest_from_candidate_list():
    g = Z.rp_gate({"S1-1": dict(**{"pass": True}), "S1-2": {"pass": True}, "S1-3": {"pass": True}, "S1-4": {"pass": True}, "S1-6": {"pass": True}}, {"A": True, "B": False, "C": True})
    assert g == {"A": True, "B": False, "C": True}
    g = Z.rp_gate({"S1-1": {"pass": True}, "S1-2": {"pass": False}, "S1-3": {"pass": True}, "S1-4": {"pass": True}, "S1-6": {"pass": True}}, {"A": True, "B": True})
    assert g == {"A": False, "B": False}


# ---------------------------------------------------------------- price_at
def test_make_price_at_lazy_exact_minute_and_missing(monkeypatch):
    calls = []

    def op(sym):
        calls.append(sym)
        if sym == "NOBAR":
            return None
        return pd.Series([1.0, 2.0, 3.0], index=pd.DatetimeIndex([T0, T0 + pd.Timedelta(minutes=1), T0 + pd.Timedelta(minutes=5)]))
    p = Z.make_price_at(op, keep=2)
    assert p("A", T0) == 1.0 and p("A", T0 + pd.Timedelta(minutes=1)) == 2.0
    assert p("A", T0 + pd.Timedelta(minutes=2)) is None            # missing minute -> None (no_price), never the previous bar
    assert p("NOBAR", T0) is None
    assert calls.count("A") == 1                                   # cached
    p("B", T0), p("C", T0), p("A", T0)
    assert calls.count("A") == 2                                   # LRU of 2 evicted it


# ---------------------------------------------------------------- the hook end to end (synthetic, real module)
def hook(rows, sc=None, group="six", seed=89, runs=200, price=None, n_cand=74):
    return Z.apply_fe_sizing("H61", group, fe_df(rows), dict(sc_u=sc or SC_PASS, seed=seed, n_cand=n_cand), rules_loader=rl,
                             open_loader=(lambda s: None), min_stop_dist=0.006, runs=runs, price_at=price)


def many(n=30):
    rows = []
    for k in range(n):
        rows.append(fe_row(SIX[k % 6], k * 6, unit=0.02 if k % 3 else -0.015, stop=0.02, hold_h=2))
    return rows


def test_hook_returns_all_ledgers_and_fields():
    z = hook(many(), price=prices({}))
    assert set(z["sims"]) == {"A_off", "A_on", "B_off", "B_on", "C_off", "C_on"}
    r = z["rows"]["A_off"]
    for k in ("signals", "entered", "annual_n", "tier", "mean_hold_minutes", "replaced_n", "replaced_mean_R", "skips", "z1_max_dd", "z2_share", "z3_worst_loss_frac",
              "first_touch_init", "first_touch_peak", "final_wallet", "max_concurrent", "sized_by_cap", "sized_by_loss", "liquidated"):
        assert k in r, k
    assert z["rows"]["A_off"]["signals"] == 30 and z["no_exchange_info"] == {}
    assert z["variants"] == ("A", "B", "C")
    assert set(z["gate"]) == {"A", "B", "C"} and "S1-5" in z["gate_detail"]["A"]
    assert z["rp_applies"].keys() == {"A_on", "B_on", "C_on"}


def test_hook_new_group_runs_AB_and_no_C():
    rows = [fe_row("AAAUSDT", k * 6, unit=0.02 if k % 3 else -0.015) for k in range(30)]
    z = hook(rows, group="new", seed=89, price=prices({}))
    assert set(z["sims"]) == {"A_off", "A_on", "B_off", "B_on"} and z["variants"] == ("A", "B")
    assert "C" in z["variant_c_note"]


def test_hook_uses_group_seed_and_candidates_in_gate():
    z = hook(many(), seed=93, price=prices({}))
    assert z["gate_detail"]["A"]["S1-2"]["seed"] == 93 and z["gate_detail"]["A"]["S1-2"]["n_candidates"] == 74


def test_hook_unlimited_candidate_R_statistics_listed():
    z = hook(many(), price=prices({}))
    st = z["candidate_R"]
    assert st["n"] == 30 and "S1-1" in st and "S1-3" in st and "S1-4" in st and "S1-6" in st


def test_hook_empty_ledger():
    z = Z.apply_fe_sizing("H61", "new", fe_df([]), dict(sc_u={}, seed=89, n_cand=74), rules_loader=rl, open_loader=lambda s: None, min_stop_dist=0.006, runs=50,
                          price_at=prices({}))
    assert z["sims"] == {} and z["note"].startswith("no candidate")


def test_hook_does_not_mutate_fe_ledger():
    d = fe_df(many())
    before = d.copy()
    Z.apply_fe_sizing("H61", "six", d, dict(sc_u=SC_PASS, seed=89, n_cand=74), rules_loader=rl, open_loader=lambda s: None, min_stop_dist=0.006, runs=50, price_at=prices({}))
    pd.testing.assert_frame_equal(d, before)


def test_hook_no_info_symbols_counted_and_not_simulated():
    rows = many(12) + [fe_row("NOINFO1USDT", 200)]
    z = hook(rows, group="new", price=prices({}))
    assert z["no_exchange_info"] == {"NOINFO1USDT": 1}
    assert z["rows"]["A_off"]["signals"] == 12 and z["n_candidates_total"] == 13


# ---------------------------------------------------------------- replace needs a price; no bar -> no_price
def test_replace_no_price_is_reported():
    # three open positions block a 4th (max_positions); no 1m bars -> every attempt is no_price
    rows = [fe_row(SIX[k], k, hold_h=50, unit=0.01, stop=0.01) for k in range(3)] + [fe_row(SIX[3], 3, hold_h=1, stop=0.01)]
    z = hook(rows, price=prices({}))
    assert z["rows"]["A_off"]["skips"].get("max_positions", 0) == 1
    assert z["rows"]["A_on"]["replace_attempts"].get("no_price", 0) == 1
    assert z["rows"]["A_on"]["replaced_n"] == 0


# ---------------------------------------------------------------- render
def test_render_contains_required_report_items():
    z = hook(many(), price=prices({}))
    txt = "\n".join(Z.render_sizing(z, coins=SIX))
    for s in ("Annual n", "Average hold", "Skips by reason", "replaced", "no_price", "Candidate ledger columns", "variant C", "S1-5", "funding", "RP gate"):
        assert s.lower() in txt.lower(), s


def test_write_csvs(tmp_path):
    z = hook(many(), price=prices({}))
    Z.write_sizing_files(z, tmp_path, "h61_six")
    for v in ("A_off", "A_on", "B_off", "B_on", "C_off", "C_on"):
        assert (tmp_path / f"fe_trades_h61_six_{v}.csv").exists() and (tmp_path / f"fe_skips_h61_six_{v}.csv").exists()
    assert (tmp_path / "fe_replacements_h61_six.csv").exists()
