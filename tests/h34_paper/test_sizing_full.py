"""Full-entry sizing FE-v2 (prereg-lock-fullentry-v2.md 539c7585353b + H61-H71 addendum 9bc7869cd811), replay mode, BUILD ONLY.
notional = min(f*L*W, target_loss*W / (stop_dist + fee_rt)) floored to step; 10x; <=3 concurrent, 1 per coin, sum of open stop-losses <= 6% of wallet.
Synthetic ledgers only; never run on the 355 ledger here. Written BEFORE h34_paper/sizing_full.py (TA procedure)."""
import subprocess
from decimal import Decimal as Dc
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from h34_paper import sizing_full as F
from h34_paper import sizing_up as S

LIVE = S.live_code()
SymbolRules = LIVE[2]


def _rules(min_notional="5", step="0.001", mkt_max="100000", min_qty=None):
    mq = Dc(min_qty or step)
    return SymbolRules("X", Dc("0.01"), Dc(step), mq, Dc(min_notional), max_qty=Dc("1000000"), mkt_min_qty=mq,
                       mkt_step_size=Dc(step), mkt_max_qty=Dc(mkt_max), pct_up=Dc("1.05"), pct_down=Dc("0.95"))


COINS = ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT")
RULES = {c: _rules() for c in COINS}
RULES.update(BIGUSDT=_rules("100"), MAXUSDT=_rules(mkt_max="10"), LOWUSDT=_rules(), MINQ=_rules(min_qty="1"))
BR = {s: [{"floor": 0.0, "cap": 1e9, "mmr": 0.004, "max_lev": 50}] for s in RULES}
BR["LOWUSDT"] = [{"floor": 0.0, "cap": 1e9, "mmr": 0.004, "max_lev": 5}]
T0 = pd.Timestamp("2024-01-01")
A = F.fe2_params("A", min_stop_dist=0.004)
B = F.fe2_params("B", min_stop_dist=0.004)


def row(sym="AAAUSDT", e=0, x=4, px=100.0, stop=0.01, unit=0.02, mae=0.0, fee1=0.0005, side=1):
    return dict(sym=sym, side=side, entry_time=T0 + pd.Timedelta(hours=e), exit_time=T0 + pd.Timedelta(hours=x), entry_px=px, stop_dist=stop,
                mae=mae, unit=unit, fee1=fee1, gross_unit=unit, fee_unit=0.0, slip_unit=0.0, funding_unit=0.0)


def led(*rows):
    return pd.DataFrame(list(rows))


def sim(ledger, params=A, init=1000.0, rules=None, brackets=None):
    return F.simulate_full(ledger, rules or RULES, brackets or BR, params, init=init)


# ---------------------------------------------------------------- params: lock values, no silent defaults
def test_fe2_variants_carry_lock_values():
    for v, f in (("A", 0.10), ("B", 0.25)):
        p = F.fe2_params(v, min_stop_dist=0.004)
        assert (p.f, p.lev, p.target_loss_pct, p.fee_rt) == (f, 10, 5.0, 0.0017)
        assert (p.max_positions, p.per_coin, p.open_loss_cap_pct, p.min_stop_dist, p.min_notional_wallet) == (3, 1, 6.0, 0.004, 0.5)
    assert F.fe2_params("A", min_stop_dist=0.006).min_stop_dist == 0.006
    with pytest.raises(TypeError):
        F.fe2_params("A")                                   # min stop distance is candidate-specific: required
    with pytest.raises(ValueError):
        F.fe2_params("C", min_stop_dist=0.004)


def test_fullparams_has_no_defaults():
    with pytest.raises(TypeError):
        F.FullParams()
    with pytest.raises(TypeError):
        F.FullParams(f=0.1, lev=10, target_loss_pct=5.0)    # every field is explicit


def test_param_validation():
    base = dict(f=0.1, lev=10, target_loss_pct=5.0, fee_rt=0.0017, min_stop_dist=0.004, max_positions=3, per_coin=1, open_loss_cap_pct=6.0,
                min_notional_wallet=0.5)
    F.FullParams(**base)
    for k, v in (("f", 0), ("f", 1.01), ("lev", 0), ("lev", 11), ("target_loss_pct", 0), ("target_loss_pct", 101), ("fee_rt", -0.1),
                 ("min_stop_dist", -1), ("max_positions", 0), ("per_coin", 0), ("open_loss_cap_pct", 0), ("min_notional_wallet", -1)):
        with pytest.raises(ValueError):
            F.FullParams(**{**base, k: v})
    F.FullParams(**{**base, "f": 0.25, "lev": 5})


# ---------------------------------------------------------------- sizing: cap vs loss, both variants
def test_variant_a_cap_binds_for_narrow_stop():
    # W 1000, stop 1%: loss-sized 50/(0.0117) = 4273 > cap f*L*W = 1000 -> notional 1000, qty 10
    t = sim(led(row(stop=0.01)), A)["trades"]
    assert t.qty[0] == 10 and t.notional[0] == 1000 and t.lev[0] == 10 and t.margin[0] == 100 and t.sized_by[0] == "cap"
    assert t.margin_frac[0] == pytest.approx(0.10)
    assert t.loss_at_stop_frac[0] == pytest.approx(0.01)                         # qty * stop distance / wallet
    assert t.loss_at_stop_incl_fee_rt_frac[0] == pytest.approx(10 * 100 * 0.0117 / 1000)
    assert "q0" not in t.columns and "path" not in t.columns


def test_variant_b_cap_is_2_5x_wallet():
    t = sim(led(row(stop=0.01)), B)["trades"]
    assert t.qty[0] == 25 and t.notional[0] == 2500 and t.margin[0] == 250 and t.margin_frac[0] == pytest.approx(0.25) and t.sized_by[0] == "cap"


def test_loss_binds_for_wide_stop_and_equal_in_both_variants():
    # stop 5%: 50 / 0.0517 = 967.1 -> qty 9.671 in A and B (cap not binding in either)
    ta, tb = sim(led(row(stop=0.05)), A)["trades"], sim(led(row(stop=0.05)), B)["trades"]
    assert ta.qty[0] == tb.qty[0] == pytest.approx(9.671) and ta.sized_by[0] == "loss"
    assert ta.loss_at_stop_incl_fee_rt_frac[0] <= 0.05 + 1e-12 and ta.loss_at_stop_incl_fee_rt_frac[0] > 0.0499
    assert ta.margin[0] == pytest.approx(9.671 * 100 / 10) and ta.margin[0] < 0.10 * 1000


def test_variants_differ_where_between_caps():
    # stop 3%: loss-sized 50/0.0317 = 1577.3 -> A capped at 1000, B 1577.3 (qty 15.772 after floor)
    ta, tb = sim(led(row(stop=0.03)), A)["trades"], sim(led(row(stop=0.03)), B)["trades"]
    assert ta.qty[0] == 10 and tb.qty[0] == pytest.approx(15.772) and tb.sized_by[0] == "loss"


@pytest.mark.parametrize("params", [A, B])
@pytest.mark.parametrize("stop", [0.004, 0.0057, 0.01, 0.02, 0.0317, 0.05, 0.0817, 0.09])
@pytest.mark.parametrize("px", [37.3, 100.0, 3.37, 61.111])
def test_margin_and_loss_never_exceed_limits(params, stop, px):
    t = sim(led(row(px=px, stop=stop)), params)["trades"]
    assert len(t) == 1
    assert t.margin[0] <= params.f * 1000 + 1e-9
    assert t.loss_at_stop_incl_fee_rt_frac[0] <= 0.05 + 1e-12
    assert t.lev[0] == 10 and t.notional[0] == pytest.approx(float(t.qty[0]) * px)


def test_step_floors_never_rounds_up():
    # cap 1000 / 37.3 = 26.8096 -> 26.809
    t = sim(led(row(px=37.3, stop=0.01)), A)["trades"]
    assert t.qty[0] == pytest.approx(26.809)


def test_leverage_param_scales_cap_and_is_hard_max_10():
    p = F.FullParams(f=0.10, lev=5, target_loss_pct=5.0, fee_rt=0.0017, min_stop_dist=0.004, max_positions=3, per_coin=1,
                     open_loss_cap_pct=6.0, min_notional_wallet=0.5)
    t = sim(led(row(stop=0.01)), p)["trades"]
    assert t.lev[0] == 5 and t.notional[0] == 500 and t.margin[0] == 100
    with pytest.raises(ValueError):
        F.FullParams(**{**p.__dict__, "lev": 11})


def test_bracket_max_leverage_skips_not_shrinks():
    s = sim(led(row(sym="LOWUSDT", stop=0.01)), A)       # bracket allows 5x only
    assert s["entered"] == 0 and s["skips"] == {"bracket": 1}


def test_max_qty_skip_no_splitting():
    s = sim(led(row(sym="MAXUSDT", stop=0.01)), A)       # qty 10 ... market max 10 -> ok; B qty 25 > 10
    assert s["entered"] == 1
    assert sim(led(row(sym="MAXUSDT", stop=0.01)), B)["skips"] == {"max_qty": 1}


# ---------------------------------------------------------------- skips: too wide, min stop, min notional, min qty
def test_stop_plus_fee_over_10pct_skipped():
    s = sim(led(row(stop=0.10)), A)                      # 0.10 + 0.0017 > 0.10 -> notional < 0.5 W
    assert s["entered"] == 0 and s["skips"] == {"stop_too_wide": 1}
    assert "0.1017" in s["skip_log"][0]["detail"] or "10.17" in s["skip_log"][0]["detail"]
    assert sim(led(row(stop=0.098)), A)["entered"] == 1  # 0.0997 <= 0.10: notional 501.5 >= 0.5 W


def test_notional_below_half_wallet_boundary_uses_param():
    p = F.FullParams(**{**A.__dict__, "min_notional_wallet": 0.0})
    assert sim(led(row(stop=0.10)), p)["entered"] == 1


def test_min_stop_distance_skip_and_param():
    s = sim(led(row(stop=0.003)), A)
    assert s["entered"] == 0 and s["skips"] == {"stop_too_tight": 1} and s["skip_log"][0]["sym"] == "AAAUSDT"
    assert sim(led(row(stop=0.004)), A)["entered"] == 1                              # exactly 0.40% passes
    assert sim(led(row(stop=0.0039)), A)["skips"] == {"stop_too_tight": 1}
    assert sim(led(row(stop=0.005, side=-1)), A)["entered"] == 1
    c = F.fe2_params("A", min_stop_dist=0.006)                                      # H61-H71: 0.60%
    assert sim(led(row(stop=0.005)), c)["skips"] == {"stop_too_tight": 1} and sim(led(row(stop=0.006)), c)["entered"] == 1
    assert sim(led(row(stop=0.003, side=-1)), A)["skips"] == {"stop_too_tight": 1}


def test_min_notional_skip_logged_and_counted():
    # BIG min notional 100, A: cap = wallet 10 -> notional 10 < 100 -> skip; wallet 1000 -> 1000 ok
    s = sim(led(row(sym="BIGUSDT", stop=0.01)), A, init=10.0)
    assert s["entered"] == 0 and s["skips"] == {"below_min_notional": 1}
    e = s["skip_log"][0]
    assert e["reason"] == "below_min_notional" and e["idx"] == 0 and e["sym"] == "BIGUSDT" and "100" in e["detail"]
    assert sim(led(row(sym="BIGUSDT", stop=0.01)), A, init=1000.0)["entered"] == 1
    assert s["skips_below_min_size"] == 1


def test_btc_min_notional_50_from_live_exchangeinfo():
    p = Path("/workspace/trade-bot-research/results/exchangeinfo_2026-10-26.json")
    if not p.exists():
        pytest.skip("exchangeInfo snapshot not present")
    rules = S.load_rules(p, SymbolRules)
    assert rules["BTCUSDT"].min_notional == 50
    br = {"BTCUSDT": [{"floor": 0.0, "cap": 1e9, "mmr": 0.004, "max_lev": 125}]}
    lg = led(row(sym="BTCUSDT", px=1000.0, stop=0.01))
    assert sim(lg, A, init=50.0, rules=rules, brackets=br)["entered"] == 1               # cap 50 >= 50
    assert sim(lg, A, init=49.0, rules=rules, brackets=br)["skips"] == {"below_min_notional": 1}


def test_qty_zero_and_below_min_qty():
    assert sim(led(row(px=100000.0, stop=0.01)), A, init=1.0)["skips"] == {"qty_zero": 1}     # 1 / 100000 = 0.00001 -> 0
    s = sim(led(row(sym="MINQ", px=100.0, stop=0.01)), A, init=50.0)                          # notional 50 -> qty 0.5 < minQty 1
    assert s["skips"] == {"below_min_qty": 1}
    assert s["skips_below_min_size"] == 1


# ---------------------------------------------------------------- concurrency
def test_one_position_per_coin():
    s = sim(led(row(e=0, x=10), row(e=5, x=8), row(sym="BBBUSDT", e=6, x=9)), A)
    assert s["entered"] == 2 and s["skips"] == {"coin_open": 1} and s["skip_log"][0]["idx"] == 1


def test_max_three_concurrent():
    lg = led(*[row(sym=c, e=i, x=20, stop=0.004) for i, c in enumerate(COINS)])
    s = sim(lg, A)
    assert s["entered"] == 3 and s["skips"] == {"max_positions": 1} and s["max_concurrent"] == 3 and s["skip_log"][0]["sym"] == "DDDUSDT"


def test_sum_of_open_stop_losses_cap_6pct():
    # B, stop 1%: notional 2500, fee-incl loss 29.25 = 2.925% each (cap-bound). two = 5.85% <= 6; third = 8.775% > 6 -> skip
    lg = led(*[row(sym=c, e=i, x=20, stop=0.01) for i, c in enumerate(COINS[:3])])
    s = sim(lg, B)
    assert s["entered"] == 2 and s["skips"] == {"open_loss_cap": 1}
    assert s["max_open_loss_frac"] == pytest.approx(0.0585)
    e = s["skip_log"][0]
    assert e["reason"] == "open_loss_cap" and "8.7" in e["detail"] and "6" in e["detail"]


def test_5pct_loss_trades_cannot_coexist_skip_not_shrink():
    lg = led(row(sym="AAAUSDT", e=0, x=20, stop=0.05), row(sym="BBBUSDT", e=1, x=20, stop=0.05))
    s = sim(lg, A)
    assert s["entered"] == 1 and s["skips"] == {"open_loss_cap": 1} and list(s["trades"].idx) == [0]


def test_open_loss_cap_exact_boundary_allowed():
    p = F.FullParams(**{**A.__dict__, "open_loss_cap_pct": 1.17 * 2})        # two A trades at stop 1%: 1.17% each
    s = sim(led(row(sym="AAAUSDT", e=0, x=20), row(sym="BBBUSDT", e=1, x=20)), p)
    assert s["entered"] == 2


def test_open_loss_uses_current_wallet():
    # after A wins big, wallet grows; the open loss of the next trade is measured against the wallet at ITS entry
    s = sim(led(row(e=0, x=4, unit=0.5), row(sym="BBBUSDT", e=8, x=12)), A)
    t = s["trades"]
    assert t.W_entry[1] == pytest.approx(1000 + 1000 * 0.5)
    assert t.loss_at_stop_frac[1] == pytest.approx(float(t.qty[1]) * 1.0 / t.W_entry[1])


def test_skipped_signal_not_reentered_and_exit_frees_slot_same_minute():
    # coin AAA busy 0-10: signal at 5 skipped, signal at 10 (exit minute) allowed
    s = sim(led(row(e=0, x=10), row(e=5, x=8), row(e=10, x=12)), A)
    assert list(s["trades"].idx) == [0, 2] and s["skips"] == {"coin_open": 1}


def test_margin_sum_never_above_wallet():
    lg = led(*[row(sym=c, e=i, x=20, stop=0.004) for i, c in enumerate(COINS[:3])])
    s = sim(lg, B)
    assert (s["trades"].margin.sum()) <= 1000


# ---------------------------------------------------------------- loss-at-stop numbers
def test_loss_at_stop_price_fee_rt_and_fee1_models():
    # A, stop 1%, qty 10, px 100: price loss 10 (1%); fee_rt model 1000*0.0117 = 11.7; fee1 model: entry 0.5 + exit 990*0.0005 = 0.995
    t = sim(led(row(stop=0.01)), A)["trades"]
    assert t.stop_dist_px[0] == pytest.approx(1.0) and t.stop_frac[0] == pytest.approx(0.01)
    assert t.loss_at_stop_usd[0] == pytest.approx(10.0)
    assert t.fees_at_stop_usd[0] == pytest.approx(0.5 + 0.495)
    assert t.loss_at_stop_incl_fees_frac[0] == pytest.approx((10 + 0.995) / 1000)
    assert t.loss_at_stop_incl_fee_rt_usd[0] == pytest.approx(11.7)


def test_loss_at_stop_short_uses_larger_exit_notional():
    t = sim(led(row(stop=0.01, side=-1)), A)["trades"]
    assert t.fees_at_stop_usd[0] == pytest.approx(0.5 + 1010 * 0.0005) and t.loss_at_stop_frac[0] == pytest.approx(0.01)


# ---------------------------------------------------------------- fee/PnL model identical to sizing-up
def test_pnl_is_notional_times_ledger_unit_and_liquidation_as_sizing_up():
    s = sim(led(row(unit=-0.0123)), A)
    assert s["trades"].net_usd[0] == pytest.approx(1000 * -0.0123) and s["final"] == pytest.approx(1000 - 12.3)
    t = sim(led(row(mae=0.5, unit=0.5, fee1=0.001)), A)["trades"]
    assert bool(t.liquidated[0]) and t.net_usd[0] == pytest.approx(1000 * (-1 / 10 - 0.001))


def test_wallet_compounds():
    s = sim(led(row(e=0, x=4, unit=0.02), row(sym="BBBUSDT", e=8, x=12, unit=0.02)), A)
    t = s["trades"]
    assert t.W_entry[0] == 1000 and t.W_entry[1] == pytest.approx(1020.0) and len(s["wallet"]) == 3
    assert t.ret[0] == pytest.approx(0.02 * 1000 / 1000)


# ---------------------------------------------------------------- clause helpers (numbers only; thresholds are the lock's)
def test_clause_numbers():
    lg = led(*[row(sym="AAAUSDT", e=48 * i, x=48 * i + 4, stop=0.01, unit=(0.05 if i % 2 else -0.0117)) for i in range(40)])
    s = sim(lg, A)
    c = F.fe_clauses(s, runs=200)
    assert set(c) >= {"z1_max_dd", "z2_share", "z2_seed", "z3_worst_loss_frac", "entered", "trades_per_year"}
    assert c["z2_seed"] == 88 and c["entered"] == 40
    assert c["z3_worst_loss_frac"] == pytest.approx(-float(s["trades"].ret.min()))
    assert F.FE_Z_THRESH == dict(z1=0.20, z2_share=0.05, z2_dd=0.25, z3=0.055)


def test_trade_count_tiers():
    assert [F.trade_count_tier(n) for n in (1000, 5000, 999, 300, 299, 0)] == ["ok", "ok", "conditional", "conditional", "undecidable", "undecidable"]


# ---------------------------------------------------------------- risk mode untouched, no lock
def test_risk_mode_untouched():
    blob = subprocess.check_output(["git", "hash-object", str(S.REPO / "h34_paper" / "sizing_up.py")], text=True).strip()
    assert blob == "d22b81aa9a388e5562e3e16e9b6ca92895ad8e1e"       # = git rev-parse b038708:h34_paper/sizing_up.py
    assert F.__dict__.get("size_entry") is None


def test_ledger_355_file_still_reproduces_if_present():
    p = Path("/workspace/trade-bot-research/results/sizing_up/ledger_355.csv")
    if not p.exists():
        pytest.skip("ledger file not present")
    lg = pd.read_csv(p)
    assert len(lg) == 355 and round(float(lg.R.mean()), 5) == 1.68850


def test_module_has_no_lock_or_run_entry_points():
    assert not hasattr(F, "take_lock") and not hasattr(F, "main")
    assert "O_EXCL" not in Path(F.__file__).read_text()
