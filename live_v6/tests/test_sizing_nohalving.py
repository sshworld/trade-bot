"""Same-side halving is OFF by default (TA verdict-sizing-nohalf-2026-10-29, replay branch sizing-nohalf).
`SizingParams.same_side_halving_at = None` = off; an int N keeps the old rule (risk_pct / 2 when >= N same-side positions are open).
Every other limit (portfolio_risk_cap, total_risk_cap, max_risk_pct, min-order rule, leverage 10, margin 90%) must still bind."""
from dataclasses import replace
from decimal import Decimal

import pytest

from live_v6.exchange import rules_from_info
from live_v6.sizing import SizingParams, size_entry

from .fakes import FakeExchange

RULES = rules_from_info(FakeExchange().exchange_info(), ("BTCUSDT", "DOGEUSDT", "SOLUSDT"))
BR = [{"floor": 0.0, "cap": 5e4, "mmr": 0.005, "max_lev": 50}]
DOGE, REF, SD = RULES["DOGEUSDT"], Decimal("0.15"), Decimal("0.0045")
HALVE3 = SizingParams(same_side_halving_at=3)
OFF = SizingParams()


def _open(n, frac=0.002, side=1):
    return [{"side": side, "risk_frac": frac}] * n


def _doge(open_positions=(), p=OFF, side=1, wallet=1000, available=1000, **kw):
    return size_entry(DOGE, BR, wallet, available, REF, SD, side, list(open_positions), p, mark=REF, **kw)


# ── default = off ──
def test_default_halving_is_off():
    assert SizingParams().same_side_halving_at is None
    assert SizingParams().risk_pct == 0.5


@pytest.mark.parametrize("n_open", [0, 1, 2, 3, 4, 5, 6])
def test_off_same_side_entries_get_full_risk(n_open):
    """With halving off the (n_open+1)-th same-side entry — incl. the 4th (3 open) and 5th, where the old rule halved — gets full 0.5%."""
    base = _doge()
    sz = _doge(_open(n_open))
    assert sz.skip is None and sz.risk_pct_used == 0.5
    assert sz.qty == base.qty and sz.risk_usdt == base.risk_usdt


def test_off_opposite_and_mixed_sides_unaffected():
    assert _doge(_open(4, side=-1), side=1).risk_pct_used == 0.5
    assert _doge(_open(3) + _open(3, side=-1), side=-1).risk_pct_used == 0.5


def test_explicit_none_equals_default():
    assert _doge(_open(4), p=SizingParams(same_side_halving_at=None)) == _doge(_open(4))


# ── old behavior intact when the parameter is set to 3 ──
@pytest.mark.parametrize("n_open,halved", [(0, False), (1, False), (2, False), (3, True), (4, True), (5, True)])
def test_param_3_keeps_old_rule(n_open, halved):
    full = _doge(p=HALVE3)
    sz = _doge(_open(n_open), p=HALVE3)
    assert sz.skip is None
    assert sz.risk_pct_used == (0.25 if halved else 0.5)
    if halved:
        assert sz.qty < full.qty and sz.risk_usdt <= Decimal(1000) * Decimal("0.0025")
    else:
        assert sz.qty == full.qty


def test_param_3_counts_only_same_side():
    assert _doge(_open(3, side=-1), p=HALVE3, side=1).risk_pct_used == 0.5
    assert _doge(_open(3, side=-1), p=HALVE3, side=-1).risk_pct_used == 0.25


def test_param_2_threshold_is_honored():
    assert _doge(_open(1), p=SizingParams(same_side_halving_at=2)).risk_pct_used == 0.5
    assert _doge(_open(2), p=SizingParams(same_side_halving_at=2)).risk_pct_used == 0.25


# ── every other limit still binds with halving off ──
def test_portfolio_risk_cap_still_binds_off():
    """4 open same-side at 0.55% = 2.2%: full 0.5% would reach ≈2.7% > 2.5% → skip; the old rule (halved 0.25% → ≈2.45%) would have entered."""
    op = _open(4, frac=0.0055)
    sz = _doge(op)
    assert sz.skip == "risk_cap_portfolio" and sz.cap_frac == 0.025
    old = _doge(op, p=HALVE3)
    assert old.skip is None and old.risk_pct_used == 0.25


def test_portfolio_risk_cap_boundary_enters_off():
    sz = _doge(_open(4, frac=0.0049))             # 1.96% + ≈0.5% ≤ 2.5%
    assert sz.skip is None and sz.risk_pct_used == 0.5 and sz.cap_label == "risk_cap_portfolio"
    assert sum(o["risk_frac"] for o in _open(4, frac=0.0049)) + sz.risk_frac <= 0.025 + 1e-12


def test_portfolio_risk_cap_param_still_applies_off():
    assert _doge(_open(4, frac=0.0055), p=SizingParams(portfolio_risk_cap=0.05)).skip is None


def test_max_risk_pct_still_binds_off():
    """Stop 3%: fees add ≈3.3% to the risk. risk_pct 0.98 + fees > max_risk_pct 1.0 → risk_cap; the halved old rule (0.49%) fits."""
    kw = dict(risk_pct=0.98, max_risk_pct=1.0, portfolio_risk_cap=0.5)
    sz = _doge(_open(3, frac=0.001), p=SizingParams(**kw))
    assert sz.skip == "risk_cap" and "of" in sz.detail and "%" in sz.detail
    assert _doge(_open(3, frac=0.001), p=SizingParams(same_side_halving_at=3, **kw)).skip is None
    assert _doge(p=SizingParams(**kw)).skip == "risk_cap"            # nothing open: same cap, not a halving effect


def test_total_risk_cap_still_binds_off():
    """qty_floor path (wallet 100, BTC q0 = 0): open risk Σ + new > 5% → total_risk_cap, with 4 same-side open and halving off."""
    btc = RULES["BTCUSDT"]
    args = (btc, BR, 100, 100, 60000, 1200, 1)
    ok = size_entry(*args, _open(3, frac=0.012), OFF, mark=60000)
    assert ok.skip is None and ok.path == "qty_floor" and ok.cap_label == "total_risk_cap" and ok.cap_frac == 0.05
    sz = size_entry(*args, _open(3, frac=0.013), OFF, mark=60000)
    assert sz.skip == "total_risk_cap"
    assert size_entry(*args, _open(4, frac=0.0125), OFF, mark=60000).skip == "total_risk_cap"


def test_min_order_rule_still_applies_off():
    """q0 below the exchange minimum → the smallest allowed quantity, whatever the same-side count."""
    btc = RULES["BTCUSDT"]
    for n in (0, 3, 4):
        sz = size_entry(btc, BR, 100, 100, 60000, 1200, 1, _open(n, frac=0.001), OFF, mark=60000)
        assert sz.skip is None and sz.path == "qty_floor" and sz.qty == Decimal("0.001"), n
    # min_order_loss_cap 3% still refuses a minimum order that loses too much
    assert size_entry(btc, BR, 30, 30, 60000, 1200, 1, _open(3, frac=0.001), OFF, mark=60000).skip == "min_order_risk_over_cap"


def test_leverage_cap_10_still_applies_off():
    assert OFF.max_leverage == 10
    sz = size_entry(DOGE, BR, 1000, 1000, REF, Decimal("0.0005"), 1, _open(4), OFF, mark=REF)
    assert sz.skip is None and sz.lev == 10
    sz = size_entry(DOGE, BR, 1000, 1000, REF, Decimal("0.0005"), 1, _open(4), replace(OFF, max_leverage=3), mark=REF)
    assert sz.skip is None and sz.lev == 3


def test_margin_90pct_still_binds_off():
    assert OFF.margin_use == 0.9
    sz = _doge(_open(4), available=1)
    assert sz.skip == "margin" and "90%" in sz.detail
    base = _doge(_open(4))
    need = base.notional / base.lev + base.notional * Decimal("0.001")
    assert _doge(_open(4), available=need / Decimal("0.9") * Decimal("1.001")).skip is None
    assert _doge(_open(4), available=need / Decimal("0.9") * Decimal("0.999")).skip == "margin"
