"""FE-v2.1 addendum (prereg-lock-fullentry-v2_1-addendum.md a5852ccbc9b0), replace-losers RP-v1 (prereg-lock-replace-losers-v1.md 31619c1507f2),
variant C (per-coin margin fraction, PROVISIONAL until TA locks it). Synthetic ledgers only; nothing is run on the 355 ledger. Written BEFORE the code."""
import dataclasses as dc
from decimal import Decimal as Dc

import numpy as np
import pandas as pd
import pytest

from h34_paper import sizing_full as F
from h34_paper import sizing_up as S
from tests.h34_paper.test_sizing_full import A, B, BR, COINS, RULES, T0, _rules, led, row

MIN = pd.Timedelta(minutes=1)
H = pd.Timedelta(hours=1)
COINS6 = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
RULES = {**RULES, **{c: _rules() for c in COINS6}}
BR = {**BR, **{c: [{"floor": 0.0, "cap": 1e9, "mmr": 0.004, "max_lev": 50}] for c in COINS6}}
C = F.fe2_params("C", min_stop_dist=0.004)
RP = F.rp_params()


def sim(ledger, params=A, init=1000.0, replace=None, price_at=None):
    return F.simulate_full(ledger, RULES, BR, params, init=init, replace=replace, price_at=price_at)


def prices(d):
    """price_at(sym, ts) from {(sym, hours_after_T0, extra_minutes): px}; None when missing."""
    m = {(s, T0 + h * H + mi * MIN): px for (s, h, mi), px in d.items()}
    return lambda sym, ts: m.get((sym, ts))


# ================================================================ FE-v2.1 Q7: stop vs liquidation guard
def test_lock_constants_and_guard_param():
    assert F.LOCK_FE21_SHA12 == "a5852ccbc9b0" and F.LOCK_RP_SHA12 == "31619c1507f2"
    assert A.liq_guard == B.liq_guard == C.liq_guard == 0.7


def test_stop_beyond_070_of_liq_distance_is_skipped_not_moved():
    # lev 10, mmr 0.004: 0.7 * (0.1 - 0.004) = 6.72%
    assert sim(led(row(stop=0.0672)), A)["entered"] == 1                        # exactly at the limit passes
    s = sim(led(row(stop=0.0673)), A)
    assert s["entered"] == 0 and s["skips"] == {"stop_vs_liq": 1}
    assert "6.72" in s["skip_log"][0]["detail"] and s["skip_log"][0]["idx"] == 0
    assert sim(led(row(stop=0.0673, side=-1)), B)["skips"] == {"stop_vs_liq": 1}
    t = sim(led(row(stop=0.05)), A)["trades"]
    assert t.stop_frac[0] == pytest.approx(0.05)                                 # the stop of an entered trade is the signal's


def test_guard_uses_bracket_mmr_of_the_sized_notional():
    br = {**BR, "AAAUSDT": [{"floor": 0.0, "cap": 500.0, "mmr": 0.004, "max_lev": 50}, {"floor": 500.0, "cap": 1e9, "mmr": 0.02, "max_lev": 50}]}
    # stop 6.6%: notional ~ 50/0.0677 = 738 -> tier 2 mmr 2% -> limit 0.7*0.08 = 5.6% -> skipped; tier-1 mmr would allow 6.72%
    s = F.simulate_full(led(row(stop=0.066)), RULES, br, B, init=1000.0)
    assert s["skips"] == {"stop_vs_liq": 1}


def test_guard_param_scales_and_stop_too_wide_still_first():
    assert sim(led(row(stop=0.0673)), dc.replace(A, liq_guard=1.0))["entered"] == 1
    assert sim(led(row(stop=0.10)), A)["skips"] == {"stop_too_wide": 1}


# ================================================================ FE-v2.1 Q3/Q7: Z3 = realised loss, liquidated = whole margin
def test_z3_uses_realised_net_loss_over_entry_wallet_incl_costs():
    s = sim(led(row(stop=0.01, unit=-0.0123)), A)          # unit already holds fees, slippage, funding
    t = s["trades"]
    assert t.z3_loss_frac[0] == pytest.approx(0.0123 * 1000 / 1000)
    c = F.fe_clauses(s, runs=100)
    assert c["z3_worst_loss_frac"] == pytest.approx(0.0123) and c["z3_pass"]
    big = sim(led(row(stop=0.01, unit=-0.07)), A)           # a loss beyond 5.5% (stop slipped / gap)
    assert not F.fe_clauses(big, runs=100)["z3_pass"] and F.fe_clauses(big, runs=100)["z3_worst_loss_frac"] == pytest.approx(0.07)


def test_z3_liquidated_trade_counts_whole_margin():
    s = sim(led(row(stop=0.01, mae=0.5, unit=0.5, fee1=0.0005)), B)
    t = s["trades"]
    assert bool(t.liquidated[0])
    assert t.z3_loss_frac[0] == pytest.approx(max(-t.ret[0], t.margin_frac[0])) and t.z3_loss_frac[0] >= 0.25 - 1e-12
    c = F.fe_clauses(s, runs=100)
    assert c["z3_worst_loss_frac"] == pytest.approx(t.z3_loss_frac[0]) and not c["z3_pass"]


def test_z3_win_is_zero_loss():
    assert sim(led(row(unit=0.02)), A)["trades"].z3_loss_frac[0] == 0.0


# ================================================================ FE-v2.1 Q9: first date the wallet path touches -25%
def test_first_touch_of_minus25_reported_not_halting():
    # init 1000: trade 1 loses 30% of its 1000 notional -> wallet 700 (<= 750) at trade 1 exit; later trades still run (no halt)
    s = sim(led(row(e=0, x=4, unit=-0.30), row(sym="BBBUSDT", e=8, x=12, unit=0.01)), A)
    assert s["entered"] == 2
    c = F.fe_clauses(s, runs=100)
    assert c["z9_first_touch_init"] == T0 + 4 * H and c["z9_first_touch_peak"] == T0 + 4 * H


def test_first_touch_from_peak_differs_from_init():
    # +500 first (wallet 1500), then notional 1500 loses 30% = -450 -> 1050: -30% from the peak, never -25% vs init
    s = sim(led(row(e=0, x=4, unit=0.5), row(sym="BBBUSDT", e=8, x=12, unit=-0.30)), A)
    c = F.fe_clauses(s, runs=100)
    assert c["z9_first_touch_init"] is None and c["z9_first_touch_peak"] == T0 + 12 * H


def test_first_touch_none_when_never():
    c = F.fe_clauses(sim(led(row(unit=0.01)), A), runs=100)
    assert c["z9_first_touch_init"] is None and c["z9_first_touch_peak"] is None


# ================================================================ FE-v2.1 Q12: annual trade count
def test_annual_trades_rounds_half_up_to_nearest_integer():
    d0, d1 = T0, T0 + pd.Timedelta(days=730.5)
    assert F.annual_trades(21, d0, d1) == 11            # 10.5 -> 11 (not banker's 10)
    assert F.annual_trades(20, d0, d1) == 10
    assert F.annual_trades(22, d0, d1) == 11
    assert F.annual_trades(5, d0, d0) == 5               # zero span: the count itself
    assert F.annual_trades(1, d0, d0 + pd.Timedelta(days=1000)) == 0              # 0.365 -> 0


def test_fe_clauses_uses_annual_trades_for_bootstrap_n():
    lg = led(*[row(e=48 * i, x=48 * i + 4, stop=0.01, unit=0.01) for i in range(30)])
    s = sim(lg, A)
    t = s["trades"]
    c = F.fe_clauses(s, runs=50)
    days = (t.exit_time.max() - t.entry_time.min()).total_seconds() / 86400
    assert c["boot_n"] == F.annual_trades(30, t.entry_time.min(), t.exit_time.max()) == int(np.floor(30 / (days / 365.25) + 0.5))
    assert c["trades_per_year"] == pytest.approx(30 / (days / 365.25))


# ================================================================ replace-losers: parameters and switch
def test_rp_params_lock_values_no_defaults():
    assert (RP.cost_rt, RP.fill_lag_minutes) == (0.0015, 1)
    with pytest.raises(TypeError):
        F.ReplaceParams()
    with pytest.raises(ValueError):
        F.ReplaceParams(cost_rt=-0.1, fill_lag_minutes=1)
    with pytest.raises(ValueError):
        F.ReplaceParams(cost_rt=0.0015, fill_lag_minutes=-1)


def test_replace_needs_prices():
    with pytest.raises(ValueError):
        sim(led(row()), A, replace=RP)
    with pytest.raises(TypeError):
        sim(led(row()), A, replace="on", price_at=lambda s, t: 1.0)


def four(extra=()):
    """3 open at 0h,1h,2h (AAA, BBB, CCC, all 100 long stop 1%, exit 20h); signal at 3h on DDD is blocked by max_positions."""
    return led(row("AAAUSDT", e=0, x=20), row("BBBUSDT", e=1, x=20), row("CCCUSDT", e=2, x=20), row("DDDUSDT", e=3, x=10, unit=0.02), *extra)


def test_switch_off_is_plain_fe2_and_equals_replace_none():
    s = sim(four(), A)
    assert s["skips"] == {"max_positions": 1} and s["entered"] == 3 and s["replacements"] == []
    assert list(s["trades"].exit_kind) == ["ledger"] * 3


def test_switch_on_closes_worst_negative_and_enters_new_signal():
    pa = prices({("AAAUSDT", 3, 0): 98.0, ("BBBUSDT", 3, 0): 99.0, ("CCCUSDT", 3, 0): 101.0, ("AAAUSDT", 3, 1): 97.5})
    s = sim(four(), A, replace=RP, price_at=pa)
    t = s["trades"].set_index("idx")
    assert s["skips"] == {} and s["entered"] == 4 and len(s["replacements"]) == 1
    # AAA: R = -0.02 / (0.01 + 0.0017) is the worst; filled at the next 1m open 97.5, round-trip cost 0.15%
    a = t.loc[0]
    assert a.exit_kind == "replace" and a.exit_time == T0 + 3 * H + MIN and a.replaced_by == 3
    assert a.unit == pytest.approx(-0.025 - 0.0015) and a.net_usd == pytest.approx(1000 * (-0.0265)) and not a.liquidated
    assert a.W_exit == pytest.approx(973.5)
    assert t.loc[1].exit_kind == t.loc[2].exit_kind == "ledger"
    d = t.loc[3]                                           # new signal sized on the wallet after the realised loss
    assert d.W_entry == pytest.approx(973.5) and d.qty == pytest.approx(9.735) and d.open_before == 2
    r = s["replacements"][0]
    assert (r["closed_idx"], r["new_idx"], r["blocked_by"], r["close_px"]) == (0, 3, "max_positions", 97.5)
    assert r["unrealized_R"] == pytest.approx(-0.02 / 0.0117) and r["close_time"] == T0 + 3 * H + MIN
    assert s["final"] == pytest.approx(1000 - 26.5 + 973.5 * 0.0 + (t.loc[1].net_usd + t.loc[2].net_usd) + t.loc[3].net_usd)


def test_ledger_exit_of_replaced_trade_is_not_booked_twice():
    pa = prices({("AAAUSDT", 3, 0): 98.0, ("BBBUSDT", 3, 0): 99.0, ("CCCUSDT", 3, 0): 101.0, ("AAAUSDT", 3, 1): 97.5})
    s = sim(four(), A, replace=RP, price_at=pa)
    assert s["final"] == pytest.approx(1000 + s["trades"].net_usd.sum()) and len(s["wallet"]) == 1 + 4


def test_no_loser_means_skip_as_before():
    pa = prices({("AAAUSDT", 3, 0): 100.0, ("BBBUSDT", 3, 0): 99.0 + 3, ("CCCUSDT", 3, 0): 101.0, ("AAAUSDT", 3, 1): 100.0})
    s = sim(four(), A, replace=RP, price_at=pa)                  # AAA exactly at entry (R = 0 is not negative), others up
    assert s["skips"] == {"max_positions": 1} and s["entered"] == 3 and s["replacements"] == []
    assert s["replace_attempts"] == {"no_loser": 1}


def test_short_positions_and_stop_normalisation_rank_by_R():
    # A long, stop 2%, -2% -> R = -0.02/0.0217 = -0.92 ; B long stop 1%, -2% -> R = -1.709 (worst although it lost less in %);
    # C short stop 1%, +1% (against) -> R = -0.855
    lg = led(row("AAAUSDT", e=0, x=20, stop=0.02), row("BBBUSDT", e=1, x=20, stop=0.01), row("CCCUSDT", e=2, x=20, stop=0.01, side=-1),
             row("DDDUSDT", e=3, x=10))
    pa = prices({("AAAUSDT", 3, 0): 98.0, ("BBBUSDT", 3, 0): 98.0, ("CCCUSDT", 3, 0): 101.0, ("BBBUSDT", 3, 1): 98.0})
    s = sim(lg, A, replace=RP, price_at=pa)
    assert [r["closed_idx"] for r in s["replacements"]] == [1]
    pb = prices({("AAAUSDT", 3, 0): 98.0, ("BBBUSDT", 3, 0): 99.5, ("CCCUSDT", 3, 0): 103.0, ("CCCUSDT", 3, 1): 103.0})   # short -3% -> worst
    s2 = sim(lg, A, replace=RP, price_at=pb)
    r = s2["replacements"][0]
    assert r["closed_idx"] == 2 and r["unrealized_R"] == pytest.approx(-0.03 / 0.0117)
    assert s2["trades"].set_index("idx").loc[2].unit == pytest.approx(-0.03 - 0.0015)


def test_tie_equal_R_closes_earlier_entry_then_lower_idx():
    pa = prices({("AAAUSDT", 3, 0): 98.0, ("BBBUSDT", 3, 0): 98.0, ("CCCUSDT", 3, 0): 99.0, ("AAAUSDT", 3, 1): 98.0, ("BBBUSDT", 3, 1): 98.0})
    s = sim(four(), A, replace=RP, price_at=pa)
    assert s["replacements"][0]["closed_idx"] == 0                                    # earlier entry wins the tie
    lg = led(row("AAAUSDT", e=0, x=20), row("BBBUSDT", e=0, x=20), row("CCCUSDT", e=2, x=20), row("DDDUSDT", e=3, x=10))
    pb = prices({("AAAUSDT", 3, 0): 98.0, ("BBBUSDT", 3, 0): 98.0, ("CCCUSDT", 3, 0): 99.0, ("AAAUSDT", 3, 1): 98.0, ("BBBUSDT", 3, 1): 98.0})
    s2 = sim(lg, A, replace=RP, price_at=pb)
    assert s2["replacements"][0]["closed_idx"] == 0                                   # same entry minute: lower ledger idx


def test_only_one_replacement_per_signal():
    # 5% trades: AAA 5% stop-loss open; BBB signal blocked by open_loss_cap; one close frees it. With two open 2.9% trades and a 5%-risk new one
    # one close is not enough -> skipped, nothing closed
    lg = led(row("AAAUSDT", e=0, x=20, stop=0.01), row("BBBUSDT", e=1, x=20, stop=0.01), row("CCCUSDT", e=2, x=20, stop=0.05))
    pa = prices({("AAAUSDT", 2, 0): 98.0, ("BBBUSDT", 2, 0): 98.5, ("AAAUSDT", 2, 1): 98.0})
    s = sim(lg, B, replace=RP, price_at=pa)
    assert s["entered"] == 2 and s["skips"] == {"open_loss_cap": 1} and s["replacements"] == []
    assert s["replace_attempts"] == {"still_blocked": 1}
    assert s["trades"].exit_kind.tolist() == ["ledger", "ledger"] and s["final"] == pytest.approx(1000 + s["trades"].net_usd.sum())


def test_open_loss_cap_block_replaced_and_risk_sum_after_replace_within_cap():
    # B, stop 1%: 2 open at 2.925% each; third blocked (8.775% > 6). Close AAA at -1% (loss 2500*0.0115 = 28.75): wallet 971.25,
    # remaining open loss 29.25 + new 0.02925*971.25 = 57.66 <= 0.06 * 971.25 = 58.275 -> enters
    lg = led(row("AAAUSDT", e=0, x=20, stop=0.01), row("BBBUSDT", e=1, x=20, stop=0.01), row("CCCUSDT", e=2, x=20, stop=0.01))
    pa = prices({("AAAUSDT", 2, 0): 99.0, ("BBBUSDT", 2, 0): 100.0, ("AAAUSDT", 2, 1): 99.0})
    s = sim(lg, B, replace=RP, price_at=pa)
    assert s["entered"] == 3 and s["skips"] == {} and s["replacements"][0]["blocked_by"] == "open_loss_cap"
    t = s["trades"].set_index("idx")
    assert t.loc[0].W_exit == pytest.approx(971.25) and t.loc[2].W_entry == pytest.approx(971.25)
    open_loss_usd = t.loc[1].loss_at_stop_incl_fee_rt_usd + t.loc[2].loss_at_stop_incl_fee_rt_usd
    assert open_loss_usd <= 0.06 * 971.25 + 1e-9 and s["max_open_loss_frac"] <= 0.06 + 1e-12


def test_replacement_not_used_for_non_slot_non_risk_blocks():
    lg = led(row("AAAUSDT", e=0, x=20), row("AAAUSDT", e=3, x=10), row("BBBUSDT", e=4, x=10, stop=0.003))   # coin_open; stop_too_tight
    pa = prices({("AAAUSDT", 3, 0): 90.0, ("AAAUSDT", 3, 1): 90.0, ("AAAUSDT", 4, 0): 90.0, ("AAAUSDT", 4, 1): 90.0})
    s = sim(lg, A, replace=RP, price_at=pa)
    assert s["skips"] == {"coin_open": 1, "stop_too_tight": 1} and s["replacements"] == []


def test_missing_price_means_no_replacement():
    pa = prices({("AAAUSDT", 3, 0): 98.0, ("BBBUSDT", 3, 0): 99.0, ("CCCUSDT", 3, 0): 101.0})          # no fill bar for AAA
    s = sim(four(), A, replace=RP, price_at=pa)
    assert s["skips"] == {"max_positions": 1} and s["replace_attempts"] == {"no_price": 1}


def test_liquidation_flagged_open_position_is_not_a_candidate():
    lg = led(row("AAAUSDT", e=0, x=20, mae=0.5, unit=0.5), row("BBBUSDT", e=1, x=20), row("CCCUSDT", e=2, x=20), row("DDDUSDT", e=3, x=10))
    pa = prices({("AAAUSDT", 3, 0): 90.0, ("BBBUSDT", 3, 0): 99.0, ("CCCUSDT", 3, 0): 101.0, ("BBBUSDT", 3, 1): 99.0})
    s = sim(lg, A, replace=RP, price_at=pa)
    assert s["replacements"][0]["closed_idx"] == 1


def test_replace_that_hits_liquidation_distance_is_booked_liquidated():
    pa = prices({("AAAUSDT", 3, 0): 91.0, ("BBBUSDT", 3, 0): 99.9, ("CCCUSDT", 3, 0): 101.0, ("AAAUSDT", 3, 1): 90.0})   # -10% >= 0.1 - 0.004
    s = sim(four(), A, replace=RP, price_at=pa)
    a = s["trades"].set_index("idx").loc[0]
    assert bool(a.liquidated) and a.unit == pytest.approx(-0.1 - 0.0005)


def test_off_and_on_identical_when_nothing_is_blocked():
    lg = led(row("AAAUSDT", e=0, x=4), row("BBBUSDT", e=8, x=12, unit=-0.01))
    off = sim(lg, A)
    on = sim(lg, A, replace=RP, price_at=lambda s, t: 100.0)
    assert off["final"] == on["final"] and off["trades"].drop(columns=["exit_kind"]).equals(on["trades"].drop(columns=["exit_kind"]))


def test_rp_stats_report_fields():
    pa = prices({("AAAUSDT", 3, 0): 98.0, ("BBBUSDT", 3, 0): 99.0, ("CCCUSDT", 3, 0): 101.0, ("AAAUSDT", 3, 1): 97.5})
    s = sim(four(), A, replace=RP, price_at=pa)
    st = F.rp_stats(s)
    t = s["trades"].set_index("idx")
    assert st["replaced_n"] == 1 and st["replaced_mean_R"] == pytest.approx(t.loc[0].R)
    assert st["mean_hold_minutes"] == pytest.approx(np.mean([(r.exit_time - r.entry_time).total_seconds() / 60 for r in s["trades"].itertuples()]))
    assert F.rp_stats(sim(four(), A))["replaced_n"] == 0 and F.rp_stats(sim(four(), A))["replaced_mean_R"] is None


# ================================================================ variant C: per-coin margin fraction (PROVISIONAL)
def test_variant_c_map_and_uniform_maps_for_a_b():
    assert C.f_for("BTCUSDT") == 0.5 and all(C.f_for(c) == 0.1 for c in COINS6[1:])
    assert all(A.f_for(c) == 0.10 and B.f_for(c) == 0.25 for c in COINS6)
    assert (C.lev, C.target_loss_pct, C.fee_rt, C.max_positions, C.per_coin, C.open_loss_cap_pct) == (10, 5.0, 0.0017, 3, 1, 6.0)
    assert A.f == 0.10 and B.f == 0.25                                           # uniform maps stay scalars


def test_per_coin_f_has_no_silent_default_and_validation():
    with pytest.raises(ValueError):
        sim(led(row("AAAUSDT", stop=0.01)), C)                                    # AAAUSDT not in the map: error, no fallback
    with pytest.raises(ValueError):
        dc.replace(A, f={"BTCUSDT": 0.0})
    with pytest.raises(ValueError):
        dc.replace(A, f={"BTCUSDT": 1.5})
    with pytest.raises(ValueError):
        dc.replace(A, f={})
    hash(C)                                                                       # frozen + hashable


def test_c_btc_gets_50pct_others_10pct_with_loss_cap_still_binding():
    # stop 0.5%: loss-sized 50/0.0067 = 7462 > cap: BTC cap 5000 (margin 500 = 50%), ETH cap 1000 (margin 100 = 10%)
    t = sim(led(row("BTCUSDT", e=0, x=20, stop=0.005), row("ETHUSDT", e=1, x=20, stop=0.005)), C)["trades"]
    assert t.notional[0] == 5000 and t.margin_frac[0] == pytest.approx(0.5) and t.sized_by[0] == "cap" and t.qty[0] == 50
    assert t.notional[1] == pytest.approx(1000, rel=0.002) and t.margin_frac[1] == pytest.approx(0.1, rel=0.002)
    assert t.sized_by[1] == "cap"
    # stop 2%: BTC loss-sized 50/0.0217 = 2304 < cap 5000 -> loss binds, 5% loss; ETH capped at 1000
    u = sim(led(row("BTCUSDT", stop=0.02)), C)["trades"]
    assert u.sized_by[0] == "loss" and u.loss_at_stop_incl_fee_rt_frac[0] <= 0.05 + 1e-12 and u.notional[0] == pytest.approx(2304.147, abs=0.2)


def test_c_btc_min_stop_distance_unchanged_by_f():
    assert sim(led(row("BTCUSDT", stop=0.003)), C)["skips"] == {"stop_too_tight": 1}
    assert sim(led(row("BTCUSDT", stop=0.004)), C)["entered"] == 1
    assert sim(led(row("ETHUSDT", stop=0.003)), C)["skips"] == {"stop_too_tight": 1}


def test_c_open_loss_sum_and_max3_limits_unchanged():
    # BTC at 0.5% stop: 5000 * 0.0067 = 33.5 = 3.35% ; ETH 1000*0.0067 = 0.67% each -> 3.35 + 0.67 + 0.67 = 4.69% <= 6, 3 open ok, 4th blocked by slots
    lg = led(row("BTCUSDT", e=0, x=20, stop=0.005), row("ETHUSDT", e=1, x=20, stop=0.005), row("SOLUSDT", e=2, x=20, stop=0.005),
             row("BNBUSDT", e=3, x=20, stop=0.005))
    s = sim(lg, C)
    assert s["entered"] == 3 and s["skips"] == {"max_positions": 1} and s["max_open_loss_frac"] == pytest.approx(0.0335 + 2 * 0.0067)
    # BTC 3.35% + a 3.35%-loss second BTC-like trade cannot coexist: BTC (3.35%) then SOL at stop 1% (1000*0.0117 = 1.17%) -> 4.52% ok; add DOGE with 5% stop -> blocked by cap
    lg2 = led(row("BTCUSDT", e=0, x=20, stop=0.005), row("ETHUSDT", e=1, x=20, stop=0.05))
    s2 = sim(lg2, C)
    assert s2["skips"] == {"open_loss_cap": 1}                                    # 3.35% + ~4.95% > 6%


def test_c_margin_sum_within_wallet_with_btc_50pct():
    lg = led(row("BTCUSDT", e=0, x=20, stop=0.005), row("ETHUSDT", e=1, x=20, stop=0.005), row("SOLUSDT", e=2, x=20, stop=0.005))
    t = sim(lg, C)["trades"]
    assert t.margin_frac.sum() == pytest.approx(0.7) and t.margin.sum() <= 1000


def test_c_replace_closes_loser_and_resizes_on_new_wallet():
    lg = led(row("BTCUSDT", e=0, x=20, stop=0.01), row("ETHUSDT", e=1, x=20, stop=0.01), row("SOLUSDT", e=2, x=20, stop=0.01),
             row("BNBUSDT", e=3, x=10, stop=0.01))
    pa = prices({("BTCUSDT", 3, 0): 99.0, ("ETHUSDT", 3, 0): 100.0, ("SOLUSDT", 3, 0): 100.0, ("BTCUSDT", 3, 1): 99.0})
    s = sim(lg, C, replace=RP, price_at=pa)
    t = s["trades"].set_index("idx")
    assert s["replacements"][0]["closed_idx"] == 0 and t.loc[0].notional == pytest.approx(4273.5) and t.loc[0].sized_by == "loss"     # BTC: 4273 < cap 5000, loss binds
    assert t.loc[3].W_entry == pytest.approx(t.loc[0].W_exit)


# ================================================================ one call -> A/B/C x switch off/on
def test_simulate_all_emits_six_ledgers_from_one_trade_list():
    lg = led(row("BTCUSDT", e=0, x=20, stop=0.01), row("ETHUSDT", e=1, x=20, stop=0.01), row("SOLUSDT", e=2, x=20, stop=0.01),
             row("BNBUSDT", e=3, x=10, stop=0.01))
    pa = prices({("BTCUSDT", 3, 0): 99.0, ("ETHUSDT", 3, 0): 100.0, ("SOLUSDT", 3, 0): 100.0, ("BTCUSDT", 3, 1): 99.0})
    before = lg.copy(deep=True)
    out = F.simulate_all(lg, RULES, BR, min_stop_dist=0.004, price_at=pa, init=1000.0)
    assert set(out) == {"A_off", "A_on", "B_off", "B_on", "C_off", "C_on"}
    pd.testing.assert_frame_equal(lg, before)                                      # trade list untouched
    for k, v in out.items():
        var, sw = k.split("_")
        assert v["params"].f == F.fe2_params(var, min_stop_dist=0.004).f
        assert (len(v["replacements"]) > 0) if sw == "on" and var in "AB" else True
        assert v["signals"] == 4
    ref = F.simulate_full(lg, RULES, BR, F.fe2_params("B", min_stop_dist=0.004), init=1000.0)
    assert out["B_off"]["final"] == ref["final"] and out["B_off"]["trades"].equals(ref["trades"]) and out["B_off"]["replacements"] == []
    on = F.simulate_full(lg, RULES, BR, F.fe2_params("C", min_stop_dist=0.004), init=1000.0, replace=RP, price_at=pa)
    assert out["C_on"]["final"] == on["final"] and out["C_on"]["trades"].equals(on["trades"])
    assert out["A_on"]["replace_params"] == RP and out["A_off"]["replace_params"] is None


def test_simulate_all_variants_subset_and_min_stop_per_candidate():
    lg = led(row("BTCUSDT", stop=0.005))
    out = F.simulate_all(lg, RULES, BR, min_stop_dist=0.006, price_at=lambda s, t: 100.0, init=1000.0, variants=("A",))
    assert set(out) == {"A_off", "A_on"} and out["A_off"]["skips"] == {"stop_too_tight": 1}
    with pytest.raises(ValueError):
        F.simulate_all(lg, RULES, BR, min_stop_dist=0.006, price_at=lambda s, t: 100.0, variants=("Z",))
