"""skip label `qty_zero` (vs real `min_notional`) · one INFO line per completed 4h bar per model · INFO reaches stderr/journal.
Origin: live 2026-10-21 23:35:30 KST BTCUSDT skip was logged `min_notional: qty 0.000 notional 0.0000 …` although qty was 0
after step rounding; the journal showed WARNING+ only because the code emitted (almost) no INFO lines."""
import logging
import os
import subprocess
import sys
from decimal import Decimal

from live_v6 import strategy as S
from live_v6.engine import KST
from live_v6.rules import SymbolRules
from live_v6.sizing import precheck_order, size_entry
from live_v6.strategies.h7t import H7T

from .test_bar_close_live import D0, H4, M1, START, Clock, make, touch
from .test_units import BR, RULES

DOGE = "DOGEUSDT"


# ───────────── 1. label ─────────────
# (min-order rule, TA spec v2.1: q0 = 0 no longer skips by itself — the smallest exchange-allowed quantity is used when
# its loss ≤ 3% of wallet, otherwise `min_order_risk_over_cap`; `qty_zero` stays the pure gate's label for a zero qty.)
def test_qty_zero_is_the_label_of_a_zero_qty_and_q0_zero_goes_to_min_qty():
    r = RULES["BTCUSDT"]
    assert precheck_order(r, BR, 0, 60000, 10, Decimal("58800"), 100, mark=60000)[0] == "qty_zero"
    z = size_entry(r, BR, 100, 100, 60000, 1200, mark=60000)               # 0.5 USDT risk / 1200 = 0.000416 → q0 = 0
    assert z.skip is None and z.path == "qty_floor" and z.q0 == 0 and z.qty == Decimal("0.001")
    z = size_entry(r, BR, 117.46733957, 117.46733957, Decimal("84134.3"), Decimal("1562.0"), mark=Decimal("84134.3"))
    assert z.skip is None and z.path == "qty_floor" and z.qty == Decimal("0.001")         # live 10/21 23:35 BTC case


def test_incomplete_exchange_filters_skip_filter_read_failed():
    r = SymbolRules.from_exchange_info(_info_btc(), "BTCUSDT")       # no MARKET_LOT_SIZE → cannot be verified
    assert size_entry(r, BR, 117.46733957, 117.46733957, Decimal("84134.3"), Decimal("1562.0")).skip == "filter_read_failed"


def test_no_btc_floor_effective_minimum_is_exchange_minnotional():
    r = RULES["BTCUSDT"]                                                     # exchange minNotional 50 (no bot floor)
    z = size_entry(r, BR, 300, 300, 60000, 1200, mark=60000)                # qty 0.001 = 60 USDT ≥ 50
    assert z.skip is None and z.qty == Decimal("0.001") and z.path == "q0"


def test_engine_records_min_order_risk_over_cap_in_skip_log_and_daily_summary(offline):
    eng = offline.engine()
    eng.startup()
    T = int(eng.clock() * 1000)
    assert not eng.enter(DOGE, Decimal("1000"), T)                           # stop distance 1000 → q0 0, min qty loses ≫ 3%
    day = eng.now_ms()
    last = eng.meta["skip_log"][-1]
    assert last[1] == DOGE and last[2] == "min_order_risk_over_cap" and "q0=0" in last[3], last
    from datetime import datetime
    d = datetime.fromtimestamp(day / 1000, KST).strftime("%Y-%m-%d")
    assert "min_order_risk_over_cap 1" in eng.daily_summary(d) and "min_notional" not in eng.daily_summary(d)


def _info_btc():
    return {"symbols": [{"symbol": "BTCUSDT", "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
        {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
        {"filterType": "MIN_NOTIONAL", "notional": "50"}]}]}


# ───────────── 2. one INFO line per completed bar per model ─────────────
def _bar_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("bar_close ")]


def test_one_info_line_per_bar_close_with_decisions(offline, caplog):
    caplog.set_level(logging.INFO, logger="live_v6.engine")
    clk = Clock(START)
    eng, strat = make(offline, clk)
    eng.tick()                                                               # startup + bar 08:00 close (decided at 12:00 UTC? no: 04:00 bar)
    first = _bar_lines(caplog)
    assert len(first) == 1
    assert first[0].startswith("bar_close model=h7t bar_open=2026-10-20 13:00 KST ")        # bar 04:00 UTC = 13:00 KST
    for s in eng.cfg.symbols:
        assert f"{s}=no_signal" in first[0]
    eng.tick(force_reconcile=False)
    assert len(_bar_lines(caplog)) == 1                                      # no repeat for the same bar (no flooding)
    clk.ms = D0 + 12 * 3600_000 + 5000
    eng.tick(force_reconcile=False)
    assert len(_bar_lines(caplog)) == 2 and "bar_open=2026-10-20 17:00 KST" in _bar_lines(caplog)[1]
    # entry inside bar 12:00 UTC, then its close at 16:00 UTC
    trig = strat.trigger(DOGE, eng)
    clk.ms = D0 + 12 * 3600_000 + 30 * M1
    eng.tick(force_reconcile=False)
    touch(eng, DOGE, trig * 1.0005, clk.ms)
    assert DOGE in eng.st["pos"]
    assert any(r.getMessage().startswith(f"entered {DOGE} long qty ") for r in caplog.records if r.levelno == logging.INFO)
    clk.ms = D0 + 16 * 3600_000 + 5000
    eng.tick(force_reconcile=False)
    last = _bar_lines(caplog)[-1]
    assert "bar_open=2026-10-20 21:00 KST" in last and f"{DOGE}=entered" in last, last
    text = " ".join(r.getMessage() for r in caplog.records)
    for secret in ("BINANCE", "SECRET", "apiKey", "signature", "TOKEN"):
        assert secret not in text


def test_bar_close_line_reports_sizing_skip_with_reason(offline, caplog):
    caplog.set_level(logging.INFO, logger="live_v6.engine")
    clk = Clock(START)
    eng, strat = make(offline, clk)
    eng.tick()
    clk.ms = D0 + 12 * 3600_000 + 5000
    eng.tick(force_reconcile=False)
    trig = strat.trigger(DOGE, eng)
    clk.ms = D0 + 12 * 3600_000 + 30 * M1
    eng.tick(force_reconcile=False)
    strat.state["models"][DOGE]["atr"] = 1000.0                              # absurd stop distance → qty 0 at the touch
    touch(eng, DOGE, trig * 1.0005, clk.ms)
    assert DOGE not in eng.st["pos"] and eng.meta["skip_log"][-1][2] == "min_order_risk_over_cap"
    clk.ms = D0 + 16 * 3600_000 + 5000
    eng.tick(force_reconcile=False)
    assert f"{DOGE}=skip:min_order_risk_over_cap" in _bar_lines(caplog)[-1]


def test_decisions_hook_in_position_and_m20_exit_words():
    st = H7T(params=S.Params(h7_min_obs=10 ** 9))
    st.state["models"]["AAAUSDT"] = {"pos": 1}
    st.state["models"]["BBBUSDT"] = {"pos": 0}

    class Ctx:
        cfg = type("C", (), {"symbols": ["AAAUSDT", "BBBUSDT", "CCCUSDT"]})()
        meta = {"skip_log": []}
    before = {"models": {"AAAUSDT": {"pos": 1}}, "bar": {}}
    d = st.bar_decisions(H4 * 10, Ctx, before, [{"type": "exit", "sym": "CCCUSDT", "reason": "signal_exit"}])
    assert d == {"AAAUSDT": "in_position", "BBBUSDT": "no_signal", "CCCUSDT": "exit:signal_exit"}


# ───────────── 3. INFO reaches stderr (= journald) without third-party flood ─────────────
def test_setup_logging_emits_info_to_stderr_and_mutes_http_libs():
    code = ("import logging; from live_v6.runner import setup_logging; setup_logging(); "
            "logging.getLogger('live_v6.engine').info('hello_info'); logging.getLogger('httpx').info('HTTP Request spam'); "
            "logging.getLogger('websockets').info('ws spam'); logging.getLogger('live_v6.engine').warning('hello_warn')")
    env = {k: v for k, v in os.environ.items() if k != "LIVE_V6_LOG"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    assert r.returncode == 0, r.stderr
    assert " INFO live_v6.engine hello_info" in r.stderr and " WARNING live_v6.engine hello_warn" in r.stderr
    assert "spam" not in r.stderr
    env["LIVE_V6_LOG"] = "WARNING"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    assert "hello_info" not in r.stderr and "hello_warn" in r.stderr
