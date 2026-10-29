"""Sizing-up check (prereg-lock-sizing-up-v1): params, compounding, event order, halving, caps, qty_floor, liquidation, drawdown,
bootstrap, lock file. Synthetic ledgers only; the real 355-trade computation is run once by tools/run_sizing_up.py --final."""
import hashlib
import json
from decimal import Decimal as Dc
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from h34_paper import sizing_up as S

LIVE = S.live_code()
SymbolRules = LIVE[2]
RULES = {"AAAUSDT": SymbolRules("AAAUSDT", Dc("0.01"), Dc("0.001"), Dc("0.001"), Dc("5"), max_qty=Dc("10000"),
                                 mkt_min_qty=Dc("0.001"), mkt_step_size=Dc("0.001"), mkt_max_qty=Dc("2000"), pct_up=Dc("1.05"), pct_down=Dc("0.95")),
         "BIGUSDT": SymbolRules("BIGUSDT", Dc("0.1"), Dc("0.001"), Dc("0.001"), Dc("100"), max_qty=Dc("10000"),
                                 mkt_min_qty=Dc("0.001"), mkt_step_size=Dc("0.001"), mkt_max_qty=Dc("2000"), pct_up=Dc("1.05"), pct_down=Dc("0.95"))}
BR = {s: [{"floor": 0.0, "cap": 1e9, "mmr": 0.004, "max_lev": 50}] for s in RULES}
T0 = pd.Timestamp("2024-01-01")


def row(sym="AAAUSDT", e=0, x=4, px=100.0, stop=0.04, unit=0.02, mae=0.0, fee1=0.0006, side=1):
    return dict(sym=sym, side=side, entry_time=T0 + pd.Timedelta(hours=e), exit_time=T0 + pd.Timedelta(hours=x), entry_px=px, stop_dist=stop,
                mae=mae, unit=unit, fee1=fee1, gross_unit=unit, fee_unit=0.0, slip_unit=0.0, funding_unit=0.0)


def led(*rows):
    return pd.DataFrame(list(rows))


def sim(ledger, r, init=1000.0):
    return S.simulate(ledger, RULES, BR, r, init, live=LIVE)


# ---------------------------------------------------------------- params
def test_params_linked_limits():
    d = LIVE[1]()
    for r, mx, cap in ((0.5, 1.0, 0.025), (1.0, 2.0, 0.05), (1.5, 3.0, 0.06), (2.0, 4.0, 0.06)):
        p = S.params_for(r)
        assert (p.risk_pct, p.max_risk_pct, p.portfolio_risk_cap) == (r, mx, cap)
        for f in ("max_leverage", "same_side_halving_at", "margin_use", "total_risk_cap", "min_order_loss_cap", "price_buffer", "liq_ratio",
                  "entry_slippage", "stop_slippage", "margin_fee_buffer", "mmr_fallback"):
            assert getattr(p, f) == getattr(d, f)


def test_params_only_lock_values():
    with pytest.raises(ValueError):
        S.params_for(0.7)
    with pytest.raises(ValueError):
        S.params_for(3.0)


def test_live_blobs_are_6508b51():
    assert S.LIVE_BLOBS["sizing.py"] == "69d59170b135bc439432145e6531809714e3840e"      # = git rev-parse 6508b51:live_v6/sizing.py


# ---------------------------------------------------------------- compounding
def test_single_trade_exact():
    # wallet 1000, entry 100, stop 4 -> risk 1% = 10 USDT -> qty 2.5, notional 250, lev 10, +2% on notional = +5
    s = sim(led(row()), 1.0)
    t = s["trades"]
    assert s["entered"] == 1 and s["skips"] == {}
    assert t.qty[0] == 2.5 and t.notional[0] == 250 and t.lev[0] == 10 and t.path[0] == "q0"
    assert t.risk[0] == pytest.approx(0.01) and s["final"] == pytest.approx(1005.0)
    assert t.net_usd[0] == pytest.approx(5.0) and t.ret[0] == pytest.approx(0.005) and t.R[0] == pytest.approx(0.5)


def test_step_rounds_down():
    s = sim(led(row(px=100.0, stop=0.0333)), 1.0)           # 10 / 3.33 = 3.003 -> 3.003 allowed at step .001 ; use odd wallet
    s = sim(led(row(px=100.0, stop=0.07)), 1.0, init=1000.0)  # 10 / 7 = 1.428571 -> 1.428
    assert s["trades"].qty[0] == pytest.approx(1.428) and s["trades"].risk[0] < 0.01


def test_wallet_compounds_between_sequential_trades():
    s = sim(led(row(e=0, x=4, unit=0.02), row(e=8, x=12, unit=0.02)), 1.0)
    t = s["trades"]
    assert t.W_entry[0] == 1000 and t.W_entry[1] == pytest.approx(1005.0)
    assert t.qty[1] == pytest.approx(2.512)                 # 10.05 / 4 = 2.5125 -> floor .001
    assert s["wallet"][0] == 1000 and len(s["wallet"]) == 3


def test_exit_before_entry_same_minute():
    # A exits at hour 4 exactly when B enters: B must see the wallet after A's pnl
    s = sim(led(row(e=0, x=4, unit=0.10), row(e=4, x=8, unit=0.0)), 1.0)
    assert s["trades"].W_entry[1] == pytest.approx(1025.0)


def test_exit_at_entry_minute_after_entry():
    s = sim(led(row(e=0, x=0, unit=0.1)), 1.0)
    assert s["entered"] == 1


def test_fee_funding_come_from_ledger_unit():
    s = sim(led(row(unit=-0.0123)), 1.0)
    assert s["trades"].net_usd[0] == pytest.approx(250 * -0.0123)


def test_liquidation_unit():
    s = sim(led(row(mae=0.5, unit=0.5, fee1=0.001)), 1.0)
    lev = s["trades"].lev[0]
    assert bool(s["trades"].liquidated[0]) and s["trades"].net_usd[0] == pytest.approx(250 * (-1 / lev - 0.001))


# ---------------------------------------------------------------- limits
def test_same_side_halving_from_third():
    s = sim(led(*[row(e=0, x=20) for _ in range(4)]), 0.5, init=100000.0)
    assert list(s["trades"].risk_pct_used) == [0.5, 0.5, 0.5, 0.25]


def test_open_risk_cap_skips_at_0_5():
    # 0.5% each, 3 full + halves: 0.5*3 = 1.5%, then 0.25% steps -> 2.5% reached after 7 positions; the 8th is risk_cap_portfolio
    s = sim(led(*[row(e=0, x=20) for _ in range(9)]), 0.5, init=100000.0)
    assert s["entered"] == 7 and s["skips"] == {"risk_cap_portfolio": 2}
    assert s["max_open_risk"] == pytest.approx(0.025, abs=1e-6)


def test_open_risk_cap_scales_2pct_is_6pct_not_10():
    s = sim(led(*[row(e=0, x=20) for _ in range(9)]), 2.0, init=100000.0)
    assert s["max_open_risk"] <= 0.06 + 1e-12 and s["skips"].get("risk_cap_portfolio", 0) > 0
    assert s["entered"] == 3                                   # 2+2+2 = 6% -> the 4th (halved 1%) would be 7%


def test_open_risk_cap_1pct_is_5pct():
    s = sim(led(*[row(e=0, x=20) for _ in range(9)]), 1.0, init=100000.0)
    assert s["max_open_risk"] <= 0.05 + 1e-12 and s["entered"] == 7   # 1+1+1+.5+.5+.5+.5 = 5.0%; the 8th (.5) would be 5.5%


def test_fee_inclusive_cap_binds_when_stop_is_tight():
    # stop 0.1% of price: fees (0.1% round trip) are as big as the stop loss -> risk incl. fees 2x > 2x? cap = 2*risk -> equal; use 0.05%
    s = sim(led(row(stop=0.0004)), 1.0, init=100000.0)
    assert s["entered"] == 0 and "risk_cap" in s["skips"]


def test_available_balance_limits_margin():
    s = sim(led(row(px=100.0, stop=0.04), row(px=100.0, stop=0.04, e=1)), 2.0, init=100.0)   # tiny wallet: lev 10, notional 50 -> margin 5
    assert s["entered"] >= 1


def test_qty_floor_path_when_budget_below_min_notional():
    # wallet 200, risk 0.5% = 1 USDT; stop 4 -> q0 = 0.25 -> notional 25 < min 100 -> floor qty 1.021, loss ~4.26 = 2.1% of wallet <= 3%
    s = sim(led(row(sym="BIGUSDT", px=100.0, stop=0.04)), 0.5, init=200.0)
    t = s["trades"]
    assert s["entered"] == 1 and t.path[0] == "qty_floor" and t.qty[0] >= 1.02
    assert t.risk_frac[0] > t.risk[0]                                           # live: qty_floor open risk includes fees/slippage


def test_qty_floor_refused_over_3pct():
    s = sim(led(row(sym="BIGUSDT", px=100.0, stop=0.04)), 0.5, init=100.0)      # 1.02 qty * (4 + fees) ~ 4.3 USDT = 4.3% of 100
    assert s["entered"] == 0 and s["skips"] == {"min_order_risk_over_cap": 1}


def test_margin_skip_label_counted():
    s = sim(led(row(px=100.0, stop=0.04, e=0, x=20), row(px=100.0, stop=0.04, e=1, x=20)), 2.0, init=100.0)
    assert sum(s["skips"].values()) + s["entered"] == 2


def test_ledger_not_mutated_and_deterministic():
    L = led(row(), row(e=8, x=12))
    c = L.copy()
    a, b = sim(L, 1.5), sim(L, 1.5)
    pd.testing.assert_frame_equal(L, c)
    assert a["final"] == b["final"]


def test_check_ledger():
    L = led(row())
    with pytest.raises(ValueError):
        S.check_ledger(L)                                       # wrong count
    S.check_ledger(L, n=1)
    with pytest.raises(ValueError):
        S.check_ledger(L.drop(columns=["mae"]), n=1)


# ---------------------------------------------------------------- metrics
def test_max_drawdown():
    assert S.max_drawdown([100, 120, 90, 110]) == pytest.approx(0.25)
    assert S.max_drawdown([100, 101, 102]) == 0.0
    assert S.max_drawdown([100]) == 0.0


def test_bootstrap_degenerate():
    assert S.bootstrap_dd([0.01] * 10, runs=200)["share"] == 0.0
    b = S.bootstrap_dd([-0.3] * 10, runs=200)
    assert b["share"] == 1.0 and b["n"] == 124


def test_bootstrap_matches_naive_loop():
    r = np.array([0.05, -0.04, 0.02, -0.10, 0.20])
    got = S.bootstrap_dd(r, n=6, runs=40, seed=71, thresh=0.08, chunk=17)
    rng = np.random.default_rng(71)
    idx = np.concatenate([rng.integers(0, 5, size=(17, 6)), rng.integers(0, 5, size=(17, 6)), rng.integers(0, 5, size=(6, 6))])
    dds = []
    for row_ in idx:
        w = [1.0]
        for k in row_:
            w.append(w[-1] * (1 + r[k]))
        dds.append(S.max_drawdown(w))
    assert got["share"] == pytest.approx(np.mean(np.array(dds) >= 0.08 - 1e-12)) and got["mean_dd"] == pytest.approx(np.mean(dds))


def test_bootstrap_seeded_repeatable():
    r = np.random.default_rng(1).normal(0.003, 0.03, 200)
    assert S.bootstrap_dd(r) == S.bootstrap_dd(r)
    assert S.bootstrap_dd(r, seed=72) != S.bootstrap_dd(r)


def test_clauses_numbers():
    L = led(row(e=0, x=4, unit=0.02), row(e=8, x=12, unit=-0.08), row(e=16, x=20, unit=0.02))
    s = sim(L, 1.0)
    c = S.clauses(s, base_final=1000.0, boot=dict(share=0.03))
    t = s["trades"]
    assert c["z1_max_dd"] == pytest.approx(S.max_drawdown(s["wallet"])) and c["z1_max_dd"] > 0.019
    assert c["z2_share"] == 0.03 and c["z2_pass"]
    assert c["z3_worst_R"] == pytest.approx(t.R.min()) and c["z3"] == pytest.approx(abs(t.R.min()) * t.risk[1])
    assert c["z3_direct"] == pytest.approx(-t.ret.min())
    assert c["z4_pass"] == (s["final"] > 1000.0)


def test_stat4_and_risk_report():
    L = led(row(e=0, x=4), row(sym="BIGUSDT", e=8, x=12), row(e=16, x=20))
    s = sim(L, 0.5, init=1000.0)
    rep = S.risk_report(s)
    assert rep["overall"]["n"] == s["entered"] and set(rep["by_coin"]) <= {"AAAUSDT", "BIGUSDT"}
    assert rep["overall"]["min"] <= rep["overall"]["median"] <= rep["overall"]["max"]
    assert sum(rep["paths"].values()) == s["entered"]


def test_static_risk_has_no_open_positions():
    L = led(row(), row(), row())
    d = S.static_risk(L, RULES, BR, 0.5, wallet=1000.0, live=LIVE)
    assert list(d.risk.round(6)) == [0.005] * 3 and set(d.path) == {"q0"}


def test_ledger_facts():
    et = [T0 + pd.Timedelta(days=d) for d in (0, 10, 30, 31)]
    f = S.ledger_facts([10, 1, 1, 1, -1, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5], et * 5, et * 5)
    assert f["top5pct_n"] == 1 and f["top5pct_share_of_total_R"] == pytest.approx(10 / 19.5)
    assert f["longest_entry_gap_days"] == 20.0


# ---------------------------------------------------------------- lock file / sha
def test_verify_lock_sha(tmp_path):
    p = tmp_path / "l.md"
    p.write_text("hello")
    h = hashlib.sha256(b"hello").hexdigest()
    assert S.verify_lock(p, h[:12]) == h
    with pytest.raises(SystemExit):
        S.verify_lock(p, "000000000000")


def test_take_lock_refuses_second_run(tmp_path):
    S.take_lock(tmp_path, dict(x=1))
    assert json.loads((tmp_path / "lock_sizing_up_final.json").read_text())["x"] == 1
    with pytest.raises(SystemExit, match="REFUSED"):
        S.take_lock(tmp_path, dict(x=2))
    assert json.loads((tmp_path / "lock_sizing_up_final.json").read_text())["x"] == 1


# ---------------------------------------------------------------- runner smoke (synthetic 355-trade ledger, tmp output, real exchange filters)
RES = Path("/workspace/trade-bot-research")
needs_inputs = pytest.mark.skipif(not (RES / "results/exchangeinfo_2026-10-26.json").exists() or not (RES / "results/v4/extra/brackets_snapshot.json").exists(),
                                  reason="research inputs not available")


@needs_inputs
def test_runner_smoke_and_run_once(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_sizing_up", Path(__file__).resolve().parents[2] / "tools" / "run_sizing_up.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
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
    ledger = pd.DataFrame(rows)
    out = tmp_path / "out"
    out.mkdir()
    ledger.to_csv(out / "ledger_355.csv", index=False)
    (out / "ledger_meta.json").write_text(json.dumps(dict(trades=355, mean_R=1.0, sha256=S.sha256_file(out / "ledger_355.csv"))))
    monkeypatch.setattr(m, "OUT", out)
    monkeypatch.setattr(m, "LEDGER", out / "ledger_355.csv")
    monkeypatch.setattr(m, "META", out / "ledger_meta.json")
    monkeypatch.setattr(m, "git_state", lambda: dict(head="x" * 40, branch="t", dirty=False))
    lock_file = tmp_path / "lock.md"
    lock_file.write_text("lock")
    monkeypatch.setattr(m, "LOCK", lock_file)
    monkeypatch.setattr(S, "verify_lock", lambda p, sha12=None: hashlib.sha256(Path(p).read_bytes()).hexdigest())
    assert m.final() == 0
    res = json.loads((out / "sizing_up_result.json").read_text())
    assert set(res["clauses"]) == {"1.0", "1.5", "2.0", "0.5"} and (out / "sizing_up_result.md").read_text().startswith("# Sizing-up check result")
    assert (out / "trades_risk_2.0.csv").exists() and res["risk"]["0.5"]["overall"]["n"] > 100
    with pytest.raises(SystemExit, match="REFUSED"):
        m.final()
