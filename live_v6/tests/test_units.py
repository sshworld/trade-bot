"""Unit tests: strategy primitives vs pandas/numpy (the research reference), sizing/leverage rules, guards, halts."""
import math
import os
import random
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from live_v6 import strategy as S
from live_v6.exchange import MAINNET_URL, TESTNET_URL, BinanceREST, MainnetForbidden, guard_url, mainnet_allowed
from live_v6.rules import D, SymbolRules, choose_leverage, liquidation_ok, stop_price
from live_v6.sizing import SizingParams, size_entry

from .conftest import TEST_SYMBOLS
from .fakes import FakeExchange
from live_v6.exchange import rules_from_info

RULES = rules_from_info(FakeExchange().exchange_info(), ("BTCUSDT", "DOGEUSDT", "SOLUSDT"))
BR = [{"floor": 0.0, "cap": 5e4, "mmr": 0.005, "max_lev": 50}]


# ── strategy primitives vs pandas ──
def test_quantile_matches_pandas():
    rng = random.Random(1)
    for n in (1, 2, 5, 100, 271):
        v = sorted(rng.uniform(-1e-3, 1e-3) for _ in range(n))
        for q in (0.0, 0.5, 0.95, 1.0):
            assert S._pd_quantile_linear(v, q) == pytest.approx(pd.Series(v).quantile(q), rel=0, abs=1e-18)


def test_np_round_matches_numpy():
    for x in (0.00010000000004, 0.00010000000005, 0.000100000000049, 1.5e-4, 0.25, 2.5e-10):
        assert S._np_round(x, 10) == float(np.round(x, 10))


def test_atr_matches_pandas_ewm():
    rng = random.Random(2)
    c, bars = 100.0, []
    for i in range(300):
        o = c
        c = max(1.0, o * (1 + rng.gauss(0, 0.02)))
        bars.append({"open_time": i * S.H4_MS, "open": o, "high": max(o, c) * 1.01, "low": min(o, c) * 0.99, "close": c})
    df = pd.DataFrame(bars)
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(), (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    ref = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    m = S.Model("X")
    for i, b in enumerate(bars):
        S.step(m, b, lambda t: (False, {}))
        if i >= 13:
            assert m.atr == pytest.approx(ref.iloc[i], rel=1e-12)
        else:
            assert math.isnan(m.atr)


def test_breakout_entry_and_m20_exit():
    p = S.Params()
    m = S.Model("X")
    for i in range(60):                                       # flat range
        S.step(m, {"open_time": i * S.H4_MS, "open": 100, "high": 101, "low": 99, "close": 100}, lambda t: (True, {}))
    ev = S.step(m, {"open_time": 60 * S.H4_MS, "open": 100, "high": 103, "low": 99.5, "close": 102.5}, lambda t: (True, {}))
    assert any(e["type"] == "breakout" and e["taken"] for e in ev) and m.pend_entry
    ev = S.step(m, {"open_time": 61 * S.H4_MS, "open": 102, "high": 102.5, "low": 101.5, "close": 102}, lambda t: (True, {}))
    assert ev[0]["type"] == "model_entry" and m.pos == 1
    assert m.sl == 102 - m.sd and m.sd > 0                   # sd = k·ATR of the signal bar
    sl = m.sl
    ev = S.step(m, {"open_time": 62 * S.H4_MS, "open": sl + 0.5, "high": sl + 1, "low": sl - 1, "close": sl - 0.5},
                lambda t: (True, {}))
    assert ev[0] == {"type": "model_exit", "reason": "stop", "entry_open": 61 * S.H4_MS, "px": sl, "t": 62 * S.H4_MS}
    m2 = S.Model("Y")                                        # M20 exit: close below the prior 20 lows → next open
    for i in range(60):
        S.step(m2, {"open_time": i * S.H4_MS, "open": 100, "high": 101, "low": 99, "close": 100}, lambda t: (True, {}))
    m2.pos, m2.sl, m2.ei_open = 1, 50.0, 0
    S.step(m2, {"open_time": 60 * S.H4_MS, "open": 100, "high": 100, "low": 98, "close": 98.5}, lambda t: (True, {}))
    assert m2.pend_exit and m2.pos == 1
    ev = S.step(m2, {"open_time": 61 * S.H4_MS, "open": 97, "high": 98, "low": 96, "close": 97}, lambda t: (True, {}))
    assert ev[0]["reason"] == "signal_exit" and ev[0]["px"] == 97


def test_h7_crowded_rule():
    p = S.Params()
    base = [(i * 8 * 3600_000, 0.0001) for i in range(300)]
    fn = S.normalise_funding(base)
    T = fn[-1][0]
    crowded, info = S.funding_crowded(fn, T, p)
    assert not crowded                                        # all equal at 0.0001 → round(F3,10) > 0.0001 is False
    hot = base[:-3] + [(t, 0.0009) for t, _ in base[-3:]]
    crowded, info = S.funding_crowded(S.normalise_funding(hot), T, p)
    assert crowded and info["f3"] == pytest.approx(0.0009)
    short = S.normalise_funding(base[:50])
    assert not S.funding_crowded(short, short[-1][0], p)[0]  # < 100 stamps in the window → not crowded


def test_btc_regime():
    D = S.DAY_MS
    daily = [(i * D, 100.0) for i in range(199)] + [(199 * D, 101.0)]
    assert S.btc_regime_ok(daily, 200 * D)                    # day 199 completed at 200·D, above SMA
    assert not S.btc_regime_ok(daily, 200 * D - 1)            # day 199 not completed yet
    assert not S.btc_regime_ok(daily[:150], 200 * D)


# ── sizing / leverage ──
def test_stop_rounded_toward_entry_and_qty_floor():
    r = RULES["DOGEUSDT"]
    assert stop_price(r, Decimal("0.15"), 1, Decimal("0.004567")) == Decimal("0.14544")
    sz = size_entry(r, BR, 1000, 1000, Decimal("0.15"), Decimal("0.0045"), mark=Decimal("0.15"))
    assert sz.skip is None and sz.qty == Decimal(int(5 / (Decimal("0.15") - sz.stop_px)))
    assert sz.risk_usdt <= Decimal(5)


def test_skip_order_and_reasons():
    r = RULES["BTCUSDT"]
    m = dict(mark=Decimal("0.15"))
    z = size_entry(r, BR, 100, 100, 60000, 1200, mark=60000)                          # q0 = 0 → min qty 0.001 (no floor now)
    assert z.skip is None and z.path == "qty_floor" and z.qty == Decimal("0.001")
    z = size_entry(r, BR, 300, 300, 60000, 1200, mark=60000)                          # q0 0.001 = 60 USDT ≥ exchange 50
    assert z.skip is None and z.path == "q0" and z.qty == Decimal("0.001")
    assert size_entry(RULES["DOGEUSDT"], BR, 1000, 1, Decimal("0.15"), Decimal("0.0045"), **m).skip == "margin"
    full = [{"side": 1, "risk_frac": 0.01}, {"side": 1, "risk_frac": 0.012}]
    assert size_entry(RULES["DOGEUSDT"], BR, 1000, 1000, Decimal("0.15"), Decimal("0.0045"), 1, full, **m).skip == "risk_cap_portfolio"


def test_same_side_halving():
    three = [{"side": 1, "risk_frac": 0.005}] * 3
    sz = size_entry(RULES["DOGEUSDT"], BR, 1000, 1000, Decimal("0.15"), Decimal("0.0045"), 1, three,
                    SizingParams(portfolio_risk_cap=0.05, same_side_halving_at=3), mark=Decimal("0.15"))
    assert sz.risk_pct_used == 0.25


def test_leverage_rule():
    for s in (0.005, 0.01, 0.03, 0.08, 0.2):
        L = choose_leverage(s, 10, 50, 0.005, 0.7)
        assert L is not None and 1 <= L <= 10
        assert L <= math.floor(1 / (1.5 * s + 0.005)) and liquidation_ok(s, L, 0.005, 0.7)


# ── guards ──
def test_mainnet_guard_refuses_everything_under_pytest(monkeypatch):
    monkeypatch.setenv("LIVE_V6_NETWORK", "mainnet")
    monkeypatch.setenv("LIVE_V6_MAINNET_ACK", "real-money")
    assert not mainnet_allowed()
    for u in (MAINNET_URL, "https://fapi.binance.com/", "https://api.binance.com", "https://evil.example"):
        with pytest.raises(MainnetForbidden):
            guard_url(u)
        with pytest.raises(MainnetForbidden):
            BinanceREST(u, "k", "s")
    assert guard_url(TESTNET_URL) == TESTNET_URL
    assert not os.getenv("BINANCE_API_KEY") and not os.getenv("BINANCE_API_SECRET")


def test_client_repr_never_shows_keys():
    c = BinanceREST(TESTNET_URL, "KEY-abc", "SECRET-xyz")
    assert "KEY-abc" not in repr(c) and "SECRET-xyz" not in repr(c)


# ── halts ──
def test_pf_review_is_alert_only(offline):
    eng = offline.engine()
    eng.startup()
    eng.meta["trades"] = [{"net": "-1", "closed_ms": eng.now_ms()}] * 30
    eng.check_halts()
    assert not eng.meta.get("halted") and eng.meta.get("pf_review")


# ── replay (slow; needs exported research data) ──
DATA = Path("/workspace/v6replay_data")


# the two slow replay tests moved to test_replay_v21.py (v2.1 invariants + exact match under the pre-v2.1 skip rule)


# ── §8e-2: S0, equity halt at halt_fraction (0.75) × S0, deposits / withdrawals excluded ──
def _transfer(fx, amount):
    fx.wallet += Decimal(amount)
    fx.incomes.append({"type": "TRANSFER", "amount": Decimal(amount), "time": int(__import__("time").time() * 1000) + 1,
                       "symbol": "", "tran_id": f"tr{len(fx.incomes)}"})


def _eng(offline, **kw):
    eng = offline.engine(income_interval_s=kw.pop("income_interval_s", 0), **kw)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None   # bar decisions off (covered by test_bar_close_live)
    eng.startup()
    return eng


def test_s0_recorded_once_and_persisted(offline):
    eng = _eng(offline)
    assert eng.meta["start_wallet"] == "1000"
    offline.inner.wallet = Decimal(1234)
    eng2 = offline.engine()
    eng2.startup()
    assert eng2.meta["start_wallet"] == "1000"                       # not reset by a restart


def test_withdrawal_is_not_a_loss(offline):
    eng = _eng(offline)
    _transfer(offline.inner, "-300")                                 # wallet 700 < 750, but it is a withdrawal
    eng.reconcile()
    assert D(eng.meta["net_transfers"]) == -300 and not eng.meta.get("halted")
    hit, adj, thr = eng.drawdown_breached()
    assert not hit and adj == 1000 and thr == 750


def test_withdrawal_not_yet_synced_does_not_halt(offline):
    eng = _eng(offline, income_interval_s=1e9)                      # income normally not re-read for a long time
    eng._last_income = eng.clock()
    _transfer(offline.inner, "-300")
    eng.reconcile()                                                  # breach seen → forced transfer sync → no halt
    assert not eng.meta.get("halted") and D(eng.meta["net_transfers"]) == -300


def test_deposit_does_not_hide_a_loss(offline):
    eng = _eng(offline)
    opened = eng.enter("DOGEUSDT", offline.stop_dist(), int(__import__("time").time()) * 1000)
    assert opened
    _transfer(offline.inner, "500")
    offline.inner.wallet -= Decimal(251)                             # realised loss: 1500 − 251 − 500 = 749 ≤ 750
    eng.reconcile()
    assert str(eng.meta.get("halted")).startswith("emergency") and offline.amt("DOGEUSDT") == 0


@pytest.mark.parametrize("loss, halts", [("249.99", False), ("250", True)])
def test_halt_threshold_exactly_075_s0(offline, loss, halts):
    eng = _eng(offline)
    offline.inner.wallet -= Decimal(loss)
    eng.reconcile()
    assert bool(eng.meta.get("halted")) is halts


def test_unrealised_loss_counts_as_equity(offline):
    eng = _eng(offline, sizing=SizingParams(risk_pct=0.5))
    assert eng.enter("DOGEUSDT", offline.stop_dist(), int(__import__("time").time()) * 1000)
    q = offline.amt("DOGEUSDT")
    offline.inner.stops_fire = False
    offline.inner.price["DOGEUSDT"] -= Decimal(260) / q             # −260 USDT unrealised (stop "missed")
    eng.check_halts()
    eng.reconcile()
    assert str(eng.meta.get("halted")).startswith("emergency") and offline.amt("DOGEUSDT") == 0


def test_capital_and_halt_fractions_are_config(offline):
    eng = _eng(offline, capital_fraction=0.5, halt_fraction=0.8)
    assert eng.meta["capital0"] == "500.0" and eng.capital0() == 500
    assert eng.enter("DOGEUSDT", offline.stop_dist(), int(__import__("time").time()) * 1000)
    j = eng.st["pos"]["DOGEUSDT"]
    assert Decimal(j["risk_usdt"]) <= Decimal("2.5")                 # 0.5 % of C0 = 500, not of the 1000 wallet
    eng.close("DOGEUSDT", "signal_exit")
    offline.inner.wallet = Decimal(eng.meta["start_wallet"]) - Decimal(99)
    eng.reconcile()
    assert not eng.meta.get("halted")                                # 500 − 99 = 401 > 400
    offline.inner.wallet -= Decimal(1)
    eng.reconcile()
    assert str(eng.meta.get("halted")).startswith("emergency")      # 400 ≤ 0.8 × 500


def test_margin_guard_never_exceeds_strategy_equity(offline):
    eng = _eng(offline, capital_fraction=0.02)                       # C0 = 20 USDT of a 1000 wallet
    eng.cfg.sizing = SizingParams(risk_pct=5, max_risk_pct=10, portfolio_risk_cap=1.0)
    assert not eng.enter("DOGEUSDT", Decimal("0.0003"), int(__import__("time").time()) * 1000)
    assert eng.meta["skip_log"][-1][2] == "margin"                   # 500 notional / 10x = 50 > 20 strategy equity
    assert offline.amt("DOGEUSDT") == 0


def test_single_source_of_truth_for_halt_threshold():
    src = "\n".join(p.read_text() for p in Path(__file__).resolve().parents[1].rglob("*.py") if "tests" not in p.parts)
    assert "0.85" not in src and "dd_halt_pct" not in src


def test_tie_order_is_frozen_research_list():
    """TA review item 1: the frozen README list is the default and the only order live accepts."""
    import re
    from pathlib import Path
    import pytest as _pt
    from live_v6.engine import ENTRY_ORDER, SIX, Settings
    from live_v6.runner import check_frozen
    assert ENTRY_ORDER == ("BTCUSDT", "ETHUSDT", "BNBUSDT", "DOGEUSDT", "XRPUSDT", "SOLUSDT")
    assert Settings().entry_order == ENTRY_ORDER and set(ENTRY_ORDER) == set(SIX)
    check_frozen(Settings())
    with _pt.raises(SystemExit):
        check_frozen(Settings(entry_order=SIX))
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    sec = readme.split("## Simultaneous-signal tie order (FROZEN")[1]
    assert re.search(r"\n\s+" + re.escape(", ".join(ENTRY_ORDER)) + r"\n", sec)
