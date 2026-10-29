# Wallet aggregation, daily returns and the end-of-data exit charge (synthetic, no real data).
import pandas as pd
import pytest

from research_h100 import data as D
from research_h100 import run as R
from research_h100.sim import Costs, Params, simulate_coin
from research_h100.tests.test_sim import make, hot_then, T0


def test_flat_wallet_and_open_position_charged_exit_fee_at_end():
    hours = pd.date_range(T0, periods=48, freq="h")
    bars, res = {}, {}
    c = Costs()
    for i, s in enumerate(D.COINS):
        b = make(48) if i == 0 else make(48).iloc[8:]
        fr = hot_then([]) if i == 0 else pd.Series(dtype=float)
        bars[s] = b
        res[s] = simulate_coin(b, fr, 1 / 6, Params(), c)
    ev = R.evaluate(res, bars, c, hours)
    X = 0.75 / 6
    rt = 2 * X * (c.spot_side + c.fut_side)
    assert ev["final_equity"] == pytest.approx(1.0 - rt)
    assert ev["end_exit_cost"] == pytest.approx(rt / 2)
    assert len(ev["daily"]) == 2
    assert ev["daily"].iloc[0] == pytest.approx(-rt / 2)
    assert ev["mdd_worst_intrabar"] == pytest.approx(-rt, rel=1e-6)
