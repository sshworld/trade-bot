# Same-direction cap (TA PASS 2026-11-03 23:26 KST): at most 2 open positions on the same side; total max 3 unchanged.
# A 3rd same-side signal is not entered and is logged quietly (signal log kind=skipped reason=dir_cap, no Telegram);
# opposite-side entries open normally within the total 3; the count comes from the fresh exchange positions read, so
# it holds after a restart (state-file positions and positions only the exchange knows about both count). Offline only.
import json
from decimal import Decimal

from live_v6.runner import live_settings

from .conftest import unique_T
from .test_faults import alerts
from .test_qrmtf import exit_engine

SOL, XRP, DOGE, BTC, ETH = "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BTCUSDT", "ETHUSDT"


def D(x):
    return Decimal(str(x))


def _sd(b, s):
    return D(b.inner.price[s]) * D("0.008")


def _two(b, tmp_path, side):
    eng = exit_engine(b)
    eng.strategy.log_path = tmp_path / "qrmtf_signals.jsonl"
    for s in (SOL, XRP):
        assert eng.enter(s, _sd(b, s), unique_T(), side=side), eng.meta.get("skip_log", [])[-1:]
    return eng


def _scored(eng, sym, side):
    T = unique_T()
    eng.strategy.records.append({"T": T, "sym": sym, "kind": "entry", "side": side, "total": -66.0 if side < 0 else 66.0,
                                 "big_n": 70.0, "mid": 0.5, "fast": 0.4, "tf": {"1d": {"contrib": 17.0}}})
    return T


def _sig(tmp_path):
    p = tmp_path / "qrmtf_signals.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_live_setting_same_side_cap_2_total_3():
    c = live_settings("qrmtf")
    assert c.max_same_side == 2 and c.max_positions == 3


def _third_same_side_quiet(b, tmp_path, side):
    eng = _two(b, tmp_path, side)
    T = _scored(eng, DOGE, side)
    n_tg, n_calls = len(eng.tg.sent), len(b.fx.calls)
    ok = eng.enter(DOGE, _sd(b, DOGE), T, model_id=T, side=side)
    assert not ok and b.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    assert eng.meta["skip_log"][-1][1:3] == [DOGE, "dir_cap"]
    assert eng.tg.sent[n_tg:] == [] and not alerts(eng)                    # no 🚨 / Telegram at all
    calls = [c[0] for c in b.fx.calls[n_calls:]]
    assert not [c for c in calls if c in ("submit_market", "market", "stop", "set_leverage")]
    r = _sig(tmp_path)[-1]
    assert r["kind"] == "skipped" and r["reason"] == "dir_cap" and r["sym"] == DOGE and r["side"] == side
    assert r["total"] == (-66.0 if side < 0 else 66.0) and r["tf"]["1d"]["contrib"] == 17.0
    assert r["skip_ms"] and r["skip_kst"].endswith("+09:00")


def test_third_long_skipped_quietly_logged_with_score(offline, tmp_path):
    _third_same_side_quiet(offline, tmp_path, 1)


def test_third_short_skipped_quietly_logged_with_score(offline, tmp_path):
    _third_same_side_quiet(offline, tmp_path, -1)


def test_opposite_side_opens_within_total_3(offline, tmp_path):
    eng = _two(offline, tmp_path, 1)
    n_tg = len(eng.tg.sent)
    assert eng.enter(DOGE, _sd(offline, DOGE), unique_T(), side=-1), eng.meta.get("skip_log", [])[-1:]
    assert offline.amt(DOGE) < 0 and set(eng.st["pos"]) == {SOL, XRP, DOGE}
    assert not any(m.startswith("🚨") for m in eng.tg.sent[n_tg:])


def test_total_cap_3_checked_before_dir_cap(offline, tmp_path):
    eng = _two(offline, tmp_path, 1)

    def third(fn, syms):                                                   # 2 longs + 1 short on the exchange
        p = dict(fn(syms))
        p[BTC] = dict(p[SOL], amt=D("-0.003"))
        return p
    offline.fx.inject("positions", third, times=99)
    assert not eng.enter(DOGE, _sd(offline, DOGE), unique_T(), side=-1)
    assert eng.meta["skip_log"][-1][2] == "max_positions"


def test_after_restart_open_positions_from_state_counted(offline, tmp_path):
    _two(offline, tmp_path, -1)
    eng2 = exit_engine(offline)                                            # restart: state + exchange reconcile
    eng2.strategy.log_path = tmp_path / "qrmtf_signals.jsonl"
    assert {SOL, XRP} <= set(eng2.st["pos"])
    assert not eng2.enter(DOGE, _sd(offline, DOGE), unique_T(), side=-1)
    assert eng2.meta["skip_log"][-1][2] == "dir_cap" and offline.amt(DOGE) == 0
    assert eng2.enter(DOGE, _sd(offline, DOGE), unique_T(), side=1), eng2.meta.get("skip_log", [])[-1:]


def test_after_restart_exchange_only_positions_counted(offline, tmp_path):
    eng = exit_engine(offline)                                             # fresh state, exchange shows 2 longs
    eng.strategy.log_path = tmp_path / "qrmtf_signals.jsonl"

    def two_long(fn, syms):
        p = dict(fn(syms))
        p[BTC] = dict(p[SOL], amt=D("0.003"))
        p[ETH] = dict(p[SOL], amt=D("0.05"))
        return p
    offline.fx.inject("positions", two_long, times=99)
    assert not eng.enter(DOGE, _sd(offline, DOGE), unique_T(), side=1)
    assert eng.meta["skip_log"][-1][2] == "dir_cap" and not alerts(eng)


def test_cap_off_when_unset(offline, tmp_path):
    eng = exit_engine(offline, max_same_side=None)
    for s in (SOL, XRP, DOGE):
        assert eng.enter(s, _sd(offline, s), unique_T(), side=1), eng.meta.get("skip_log", [])[-1:]
