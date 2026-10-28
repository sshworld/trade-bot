import pytest
from h34_paper.core import MS15
from h34_paper.engine import Engine, Limits, pos_risk
from h34_paper.rules import resolve, ConfigError, IMPLEMENTED
from helpers import make_data, fire_rule, run, skips, T0

COINS4 = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")


def entries(ev):
    return [e for e in ev if e["event"] == "paper_entry"]


def test_one_position_per_coin_across_rules_and_logged():
    r1 = fire_rule("R1", 1, {"BTCUSDT": {5}})
    r2 = fire_rule("R2", -1, {"BTCUSDT": {7}})
    data = make_data(("BTCUSDT",), 40)
    eng = Engine([r1, r2], limits=Limits(), coins=("BTCUSDT",))
    tr, ev = run(eng, data, 0, 12)
    assert len(entries(ev)) == 1
    s = skips(ev, "limit_one_per_coin")
    assert len(s) == 1 and s[0]["strategy"] == "R2" and s[0]["limit"]["held_by"] == ["R1"]
    assert eng.counters["signals_skipped_limit"] == 1


def test_max_three_concurrent_and_skipped_never_enters_later():
    fire = {c: {5} for c in COINS4}
    data = make_data(COINS4, 60)
    eng = Engine([fire_rule("R1", 1, fire)], limits=Limits(), coins=COINS4)
    tr1, ev = run(eng, data, 0, 30)
    assert len(entries(ev)) == 3
    s = skips(ev, "limit_max_concurrent")
    assert len(s) == 1 and s[0]["symbol"] == "BNBUSDT"
    # slots free up after the time exits (bar 22); the skipped BNB signal is never entered afterwards
    tr2, ev2 = run(eng, data, 30, 55)
    assert not entries(ev2) and not tr2
    assert len(tr1) == 3 and all(t["symbol"] != "BNBUSDT" for t in tr1)
    assert eng.open_positions() == []


def test_open_risk_cap_6pct_blocks_fourth_even_without_concurrency_cap():
    fire = {c: {5} for c in COINS4}
    data = make_data(COINS4, 60)
    eng = Engine([fire_rule("R1", 1, fire)], limits=Limits(max_concurrent=10), coins=COINS4)
    tr, ev = run(eng, data, 0, 8)
    assert len(entries(ev)) == 3                          # 3 x 2.0% = 6.000000000000001% still allowed (float tolerance)
    s = skips(ev, "limit_open_risk")
    assert len(s) == 1
    assert sum(pos_risk(p) for p in eng.open_positions()) == pytest.approx(0.06)


def test_one_stop_loss_limit():
    r = fire_rule("R1", 1, {"BTCUSDT": {5}})
    data = make_data(("BTCUSDT",), 40)
    eng = Engine([r], limits=Limits(one_stop_loss=0.0199), coins=("BTCUSDT",))
    tr, ev = run(eng, data, 0, 10)
    assert not entries(ev) and len(skips(ev, "limit_one_stop_loss")) == 1


def test_portfolio_daily_loss_cap_blocks_new_entries_same_kst_day():
    # two losses of 2% each (stops) -> -4% <= -3% cap -> the later signal is skipped; per-rule 5% cap not reached
    over = {("BTCUSDT", 8): (100, 100.2, 99.0, 99.5), ("ETHUSDT", 8): (100, 100.2, 99.0, 99.5)}
    fire = {"BTCUSDT": {5}, "ETHUSDT": {5}, "SOLUSDT": {12}}
    data = make_data(COINS4[:3], 60, over=over)
    eng = Engine([fire_rule("R1", 1, fire)], limits=Limits(daily_loss_cap=0.03), coins=COINS4[:3])
    tr, ev = run(eng, data, 0, 20)
    assert len(tr) == 2 and all(t["exit_reason"] == "stop" for t in tr)
    s = skips(ev, "limit_portfolio_daily_5pct_kst")
    assert len(s) == 1 and s[0]["symbol"] == "SOLUSDT"
    assert s[0]["limit"]["day_pnl"] == pytest.approx(0.98 ** 2 - 1)         # compounded on the shared wallet, not -0.04 (sum)
    assert s[0]["limit"]["wallet"] == pytest.approx(0.98 ** 2)


def two_stop_losses(limits, rules):
    over = {("BTCUSDT", 8): (100, 100.2, 99.0, 99.5), ("ETHUSDT", 8): (100, 100.2, 99.0, 99.5)}
    data = make_data(COINS4[:3], 60, over=over)
    eng = Engine(rules, limits=limits, coins=COINS4[:3])
    tr, ev = run(eng, data, 0, 20)
    return eng, tr, ev


def test_daily_cap_compounds_on_shared_wallet_not_sum_of_ratios():
    # two -2% stops: summed ratios = -4.00%, compounded wallet = -3.96%. cap 3.99% sits between the two readings.
    fire = {"BTCUSDT": {5}, "ETHUSDT": {5}, "SOLUSDT": {12}}
    eng, tr, ev = two_stop_losses(Limits(daily_loss_cap=0.0399), [fire_rule("R1", 1, fire)])
    assert len(tr) == 2 and not skips(ev, "limit_portfolio_daily_5pct_kst")      # compounded -3.96% > -3.99%: still allowed
    assert eng.wallet == pytest.approx(0.98 ** 2) and eng.pday_pnl == pytest.approx(0.98 ** 2 - 1)
    eng, tr, ev = two_stop_losses(Limits(daily_loss_cap=0.0396), [fire_rule("R1", 1, fire)])
    assert len(skips(ev, "limit_portfolio_daily_5pct_kst")) == 1                  # -3.96% <= -3.96% (cap reached exactly)


def test_daily_cap_wallet_is_shared_across_rules():
    # R1 and R2 each lose 2% on the same KST day on different coins; the shared wallet is down 3.96% -> a third rule's signal is blocked
    r1 = fire_rule("R1", 1, {"BTCUSDT": {5}})
    r2 = fire_rule("R2", 1, {"ETHUSDT": {5}})
    r3 = fire_rule("R3", 1, {"SOLUSDT": {12}})
    eng, tr, ev = two_stop_losses(Limits(daily_loss_cap=0.03), [r1, r2, r3])
    assert len(tr) == 2
    s = skips(ev, "limit_portfolio_daily_5pct_kst")
    assert len(s) == 1 and s[0]["strategy"] == "R3"
    assert eng.wallet == pytest.approx(0.98 ** 2)
    # each rule keeps its own book wallet (per-rule ledger), the portfolio cap reads only the shared one
    assert sorted(round(b.wallet, 6) for b in eng.books) == [0.98, 0.98, 1.0]


def test_shared_wallet_day_start_rolls_with_kst_day_and_survives_restart():
    fire = {"BTCUSDT": {5}, "ETHUSDT": {5}}
    eng, tr, ev = two_stop_losses(Limits(daily_loss_cap=0.05), [fire_rule("R1", 1, fire)])
    st = eng.to_state()
    assert st["wallet"] == pytest.approx(0.98 ** 2) and st["pday_start_wallet"] == pytest.approx(1.0)
    eng2 = Engine.from_state(st, [fire_rule("R1", 1, fire)], limits=Limits(daily_loss_cap=0.05), coins=COINS4[:3])
    assert eng2.wallet == pytest.approx(0.98 ** 2) and eng2.pday == eng.pday and eng2.pday_pnl == pytest.approx(0.98 ** 2 - 1)
    eng2._roll(eng.pday and (T0 + 3 * 24 * 3600 * 1000))                           # a later KST day: day-start wallet = current wallet
    assert eng2.pday_start_wallet == pytest.approx(0.98 ** 2) and eng2.pday_pnl == pytest.approx(0.0)
    legacy = {k: v for k, v in st.items() if k not in ("wallet", "pday_start_wallet")}
    legacy["pday_pnl"] = -0.03
    eng3 = Engine.from_state(legacy, [fire_rule("R1", 1, fire)], coins=COINS4[:3])
    assert eng3.wallet == pytest.approx(0.97) and eng3.pday_pnl == pytest.approx(-0.03)


def test_per_rule_daily_cap_5pct_still_applies_with_limits_off():
    over = {(c, 8): (100, 100.2, 99.0, 99.5) for c in COINS4}
    fire = {c: {5} for c in COINS4}
    fire["SOLUSDT"] = {5}
    late = {"BNBUSDT": {12}}
    r = fire_rule("R1", 1, {**{c: {5} for c in COINS4[:3]}, **late})
    data = make_data(COINS4, 60, over={(c, 8): (100, 100.2, 99.0, 99.5) for c in COINS4})
    eng = Engine([r], limits=Limits.off(), coins=COINS4)
    tr, ev = run(eng, data, 0, 20)
    assert len(tr) == 3                                   # -6% total confirmed loss >= 5% cap
    assert any(e["event"] == "signal_skipped" and e["reason"] == "daily_cap_5pct_kst" for e in ev)


def test_limits_off_equals_core_step_without_gate():
    fire = {c: {5} for c in COINS4}
    a = Engine([fire_rule("R1", 1, fire)], limits=Limits.off(), coins=COINS4)
    data = make_data(COINS4, 60)
    tr, ev = run(a, data, 0, 40)
    assert len(tr) == 4 and not skips(ev)


def test_rule_registry_fail_closed_and_pluggable():
    on, off = resolve([{"name": "H34-B", "enabled": True}, {"name": "H34-B-S", "enabled": False}, {"name": "H32", "enabled": False}])
    assert [r.name for r in on] == ["H34-B"] and off == ["H34-B-S", "H32"]
    with pytest.raises(ConfigError):
        resolve([{"name": "H32", "enabled": True}])           # planned, no live detector yet
    with pytest.raises(ConfigError):
        resolve([{"name": "H99", "enabled": True}])
    with pytest.raises(ConfigError):
        resolve([{"name": "H34-B", "enabled": True}, {"name": "H34-B", "enabled": False}])
    assert set(IMPLEMENTED) == {"H34-B", "H34-B-S"}


def test_rule_switched_off_keeps_open_position_and_stops_new_entries():
    r1, r2 = fire_rule("H34-B", 1, {"BTCUSDT": {5, 30}}), fire_rule("H34-B-S", -1, {})
    data = make_data(("BTCUSDT",), 80)
    eng = Engine([r1, r2], limits=Limits(), coins=("BTCUSDT",))
    run(eng, data, 0, 8)
    assert len(eng.open_positions()) == 1
    st = eng.to_state()
    import h34_paper.rules as R
    old = dict(R.IMPLEMENTED)
    try:
        R.IMPLEMENTED["H34-B"] = r1
        eng2 = Engine.from_state(st, [r2], ["H34-B"], Limits(), ("BTCUSDT",))
    finally:
        R.IMPLEMENTED.update(old)
    assert eng2.winding_down == {"H34-B"}
    tr, ev = run(eng2, data, 8, 60)
    assert len(tr) == 1                                   # the open trade ran to its exit ...
    assert not entries(ev)                                # ... and the bar-30 signal was not entered (rule is off)
    assert "H34-B" in eng2.to_state()["books"]                # its wallet/day state is parked, not lost
    assert eng2.winding_down == set()
