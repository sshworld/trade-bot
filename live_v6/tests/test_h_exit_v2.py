"""The H exit recipe is frozen at entry. No test here uses a private endpoint."""
import json
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest
from live_v6.exchange import ExchangeUnavailable

from live_v6.strategies.bundle_v5 import BundleConfig, BundleV5, EnginePort, Market, PaperPort, sizing_from_env
from live_v6.strategies.bundle_v5_core import H_EXIT_V2, H_EXIT_V2_TERMS
from .test_bundle_tp import TP, _stops, _tps
from .test_bundle_v5 import _Drv, _bundle_eng, _intent
from .test_bundle_v5_sizing import _book, _cand, _enter, _row
from .test_faults import DOGE, is_entry


def book(regime=1, enabled=True, exchange=False):
    b = _book((2, 0, 0, 9))
    b.regime = lambda _: regime
    b.h_exit_policy = H_EXIT_V2 if enabled else None
    b.exchange_exits = exchange
    return b


def candidate(comp=3, stop=80.0):
    c = _cand(comp, DOGE, 900, stop, L=1.0)
    c.cid = f"{'H' if comp == 3 else 'M'}-{DOGE}-900"
    c.info["atr"] = (c.e - stop) / 2
    return c


def open_order(eng, component="H"):
    plan = dict(H_EXIT_V2_TERMS)
    it = _intent(eng, stop="0.13", cid=f"{component}-{DOGE}-1")
    it["stop_dist"] = .02
    it["fixed"]["h_exit"] = plan
    eng.execute([it])
    return plan


def test_opt_in_through_bundle_config():
    assert BundleConfig(**sizing_from_env({})).h_exit_policy is None
    assert BundleConfig(**sizing_from_env({"LIVE_V6_BUNDLE_H_EXIT_POLICY": H_EXIT_V2})).h_exit_policy == H_EXIT_V2
    for value in ("", "unknown"):
        with pytest.raises(ValueError):
            BundleConfig(**sizing_from_env({"LIVE_V6_BUNDLE_H_EXIT_POLICY": value}))


def test_live_release_profile_applies_to_new_h_orders(monkeypatch):
    profile = Path(__file__).resolve().parents[1] / "deploy" / "ssanggeuli-live.env"
    settings = dict(line.split("=", 1) for line in profile.read_text().splitlines())
    assert set(settings) == {"LIVE_V6_BUNDLE_RISK_PCT", "LIVE_V6_BUNDLE_H_EXIT_POLICY", "LIVE_V6_BUNDLE_R_LONG_ONLY",
                             "LIVE_V6_BUNDLE_R_NOTIONAL_CAP", "LIVE_V6_BUNDLE_R_EXIT_POLICY"}
    monkeypatch.setenv("LIVE_V6_BUNDLE_MARGIN", "pooled")
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    strategy = BundleV5(market=Market())
    strategy.on_start(SimpleNamespace())
    assert strategy.cfg.risk_pct == (2, 0, 5, 18)
    b = strategy.drv.book
    assert b.margin == "pooled" and b.exchange_exits
    b.regime = lambda _: 0
    [entry] = _enter(b, [candidate(stop=70.0)])                    # 30 % stop at 1x: 18 % risk = 60 % margin
    assert entry["h_exit"] == H_EXIT_V2_TERMS
    assert entry["qty"] * entry["dist"] == pytest.approx(.18 * b.capital, rel=.01)


@pytest.mark.parametrize("regime,base_stop", [(0, 80), (-4, 60), (1, 80)])
def test_preserves_stop_quantity_leverage_and_entry_gates_in_all_regimes(regime, base_stop):
    c = candidate(stop=base_stop)
    legacy, = _enter(book(regime, False), [c])
    changed, = _enter(book(regime), [c])
    assert legacy["type"] == changed["type"] == "enter"
    assert (changed["qty"], changed["lev"]) == (legacy["qty"], legacy["lev"])
    assert changed["stop"] == legacy["stop"] == base_stop
    assert changed["h_exit"] == H_EXIT_V2_TERMS
    assert changed["qty"] * changed["dist"] == legacy["qty"] * legacy["dist"]
    port = EnginePort()
    port.handle([changed], 900, SimpleNamespace(notes=[]))
    [intent] = port.take()
    assert intent["fixed"]["h_exit"] == changed["h_exit"]
    assert intent["fixed"]["stop_px"] == base_stop and intent["fixed"]["qty"] == legacy["qty"]
    assert intent["stop_dist"] == c.e - base_stop and intent["max_age_s"] == 90


def test_m_is_unchanged_and_legacy_h_does_not_adopt():
    m = candidate(comp=0, stop=98)
    before, = _enter(book(enabled=False), [m])
    after, = _enter(book(), [m])
    assert before == after and "h_exit" not in after
    old = book(enabled=False)
    _enter(old, [candidate()])
    restored = book()
    restored.__init__(weights=restored.weights, regime=restored.regime, h_exit_policy=H_EXIT_V2, state=old.state())
    assert "h_exit" not in restored.positions()[0][1]


@pytest.mark.parametrize("exit_via", ["tp2", "stop", "strategy"])
def test_actual_exchange_fills_and_restart_preserve_position_recipe(offline, exit_via):
    eng = _bundle_eng(offline, **TP)
    plan = open_order(eng)
    j = eng.st["pos"][DOGE]
    assert j["h_exit"] == plan
    entry, initial_stop = D(j["entry_px"]), D(j["stop_px_entry"])
    risk = entry - initial_stop
    target1 = eng.rules[DOGE].price(entry + risk, "up")
    target2 = eng.rules[DOGE].price(entry + 5 * risk, "up")
    assert sorted((D(o["stop_price"]), D(o["qty"])) for o in _tps(offline)) == [(target1, 25), (target2, 75)]
    offline.inner.set_price(DOGE, target1)
    replay = _bundle_eng(offline, **{**TP, "tp1_frac": .9, "tp2_r": None})
    replay.reconcile()
    replay.reconcile()
    j = replay.st["pos"][DOGE]
    assert D(j["qty"]) == offline.amt(DOGE) == 75
    assert j["tp1_done"] and j["be_done"] and len(_stops(offline)) == 1
    assert [(D(o["stop_price"]), D(o["qty"])) for o in _tps(offline)] == [(target2, 75)]
    if exit_via == "strategy":
        replay.execute([{"type": "exit", "sym": DOGE, "reason": "bundle_time"}])
    else:
        offline.inner.set_price(DOGE, target2 if exit_via == "tp2" else D(j["stop_px"]))
    replay.reconcile()
    assert offline.amt(DOGE) == 0 and not offline.inner.open_orders(DOGE)


def test_postonly_pending_recipe_survives_restart_and_anchors_to_actual_fill(offline):
    offline.inner.books = {DOGE: {"bid": D("0.1499"), "ask": D("0.1501")}}
    eng = _bundle_eng(offline, entry_mode="postonly_timeout", **TP)
    plan = open_order(eng)
    cid = eng._pending_postonly(DOGE)
    intent = eng.st["intents"][cid]
    assert intent["h_exit"] == plan
    offline.inner.fill_limit(intent["pending"]["ocid"], 100)
    restart = _bundle_eng(offline, entry_mode="postonly_timeout", **TP)
    restart.tick()
    restart.reconcile()
    j = restart.st["pos"][DOGE]
    assert j["h_exit"] == plan and D(j["entry_px"]) == D("0.1499")
    target = restart.rules[DOGE].price(2 * D(j["entry_px"]) - D(j["stop_px_entry"]), "up")
    assert D(j["tp"]["tp1"]) == target and sorted(D(o["qty"]) for o in _tps(offline)) == [25, 75]


def test_unknown_market_outcome_recovers_the_original_recipe(offline):
    eng = _bundle_eng(offline, **TP)
    sent = []
    def lose_reply(fn, *args, **kw):
        sent.append(fn(*args, **kw))
        raise ExchangeUnavailable("ack lost")
    def query_fails(*args, **kw):
        raise ExchangeUnavailable("pending")
    offline.fx.inject("market", lose_reply, match=is_entry)
    offline.fx.inject("get_order", query_fails, times=100, match=lambda *a, **kw: bool(sent))
    plan = open_order(eng)
    [intent] = eng.st["intents"].values()
    assert intent["h_exit"] == plan and offline.amt(DOGE) == 100
    offline.fx.clear()
    restart = _bundle_eng(offline, **TP)
    restart.reconcile()
    j = restart.st["pos"][DOGE]
    assert j["h_exit"] == plan and D(j["stop_px_entry"]) == D(".13")
    assert len(sent) == 1 and sorted(D(o["qty"]) for o in _tps(offline)) == [25, 75]


def test_recipe_cannot_be_applied_to_m(offline):
    eng = _bundle_eng(offline, **TP)
    open_order(eng, component="M")
    assert offline.amt(DOGE) == 0 and not offline.inner.open_orders(DOGE)


def test_tp2_repair_after_an_initial_rejection_and_partial_child(offline):
    eng = _bundle_eng(offline, **TP)
    offline.fx.inject("take_profit", "reject", match=lambda sym, side, px, cid, qty, **kw: cid.endswith("t2"))
    open_order(eng)
    j = eng.st["pos"][DOGE]
    assert [o["qty"] for o in _tps(offline)] == [25] and _stops(offline)
    offline.inner.set_price(DOGE, D(j["tp"]["tp1"]))
    eng.reconcile()
    eng.reconcile()
    [target] = _tps(offline)
    assert target["qty"] == 75 and j["tp1_done"] and j["be_done"]
    offline.inner.algos.pop(target["id"])
    child = offline.inner.market(DOGE, "SELL", D(15), "partial-second", reduce_only=True)
    offline.inner._algo_end(target, "FINISHED", child["id"], D(15), child["avg_price"])
    offline.inner.algo_hist[target["client_id"]]["order_status"] = "EXPIRED"
    eng.reconcile()
    restart = _bundle_eng(offline, **TP)
    restart.reconcile()
    [remaining] = _tps(offline)
    assert (remaining["client_id"], remaining["qty"]) == (target["client_id"] + "r1", 60)
    assert offline.amt(DOGE) == 60 and len(_stops(offline)) == 1
    offline.inner.set_price(DOGE, D(j["tp"]["tp2"]))
    restart.reconcile()
    assert not offline.amt(DOGE) and not offline.inner.open_orders(DOGE)


def test_sub_lot_quarter_gets_one_tp_for_whole_position(offline):
    eng = _bundle_eng(offline, **TP)
    j = dict(side=1, entry_px=".15", stop_px_entry=".13", stop_px=".13", qty="3", h_exit=H_EXIT_V2_TERMS)
    assert eng._tp_levels(DOGE, j) == (D(".17"), D(3), None, D(0))


def test_live_book_uses_only_same_journal_and_fresh_observation_to_release_risk():
    b = book(exchange=True)
    c = candidate()
    _enter(b, [c])
    s = b.positions()[0][1]
    original = s["iq"]
    reduced = original / 2
    j = dict(cid="bot123", qty=str(reduced), tp={"q1": 1}, h_exit=dict(s["h_exit"]), model_entry_open=c.i * 60000)
    obs = dict(cid="bot123", stop="100.26", qty=str(reduced), time=1)
    ctx = SimpleNamespace(st={"pos": {c.sym: j}}, protection_snapshot={c.sym: obs}, in_manual=lambda _: False,
                          now_ms=lambda: 100_000)
    BundleV5._sync_h_quantity(b, ctx)
    assert s["q"] == original
    obs.update(time=100_000, cid="another_trade")
    BundleV5._sync_h_quantity(b, ctx)
    assert s["q"] == original
    obs.update(cid="bot123", qty=str(original))
    BundleV5._sync_h_quantity(b, ctx)
    assert s["q"] == original
    obs.update(qty=str(reduced))
    BundleV5._sync_h_quantity(b, ctx)
    assert s["q"] == reduced and s["iq"] == original and s["dist"] == c.e - c.sl


def bar(high, mark_low, atr=100):
    r = _row()
    r[1], r[5], r[6], r[9] = high, high, mark_low, atr
    return lambda c, k: r


def test_paper_and_live_have_different_fill_authorities_and_restore_residual_once():
    c = candidate()
    live = book(exchange=True)
    _enter(live, [c])
    assert live.close_minute(900, bar(199, 95)) == []
    assert live.positions()[0][1]["q"] == live.positions()[0][1]["iq"]
    paper = book()
    [entry] = _enter(paper, [c])
    first, protection = paper.close_minute(900, bar(120, 95))
    assert first["leg"] == "tp1" and first["remaining"] == pytest.approx(entry["qty"] - first["qty"])
    assert protection["type"] == "stop" and protection["old"] == c.sl
    assert protection["stop"] == pytest.approx(100.26)
    assert paper.positions()[0][1]["sl"] == pytest.approx(100.26)
    snapshot = paper.state()
    paper = type(paper)(weights=paper.weights, regime=paper.regime, state=snapshot)
    paper.open_minute(901, bar(200, 110), [])
    second, done = paper.close_minute(901, bar(200, 110))
    assert second["leg"] == "tp2" and done["reason"] == "take_profit"
    qty = entry["qty"]
    expected = -qty * 100 * .0005
    for q, px in ((first["qty"], 120), (second["qty"], 200)):
        fill = px * (1 - .0002)
        expected += q * (fill - 100) - q * fill * .0005
    assert done["trade"]["net_pnl"] == pytest.approx(expected) and paper.wallet == pytest.approx(1000 + expected)
    assert not paper.positions()


def test_paper_prefers_stop_if_both_prices_are_touched_in_one_bar():
    b = book()
    _enter(b, [candidate()])
    [action] = b.close_minute(900, bar(220, 75))
    assert action["reason"] == "stop" and action["trade"]["exit_price"] == pytest.approx(80 * .9998)


def test_paper_prices_both_prearmed_targets_in_one_bar_without_a_stop_touch():
    b = book()
    [entry] = _enter(b, [candidate()])
    first, second, closed = b.close_minute(900, bar(201, 81))
    assert [leg["leg"] for leg in (first, second)] == ["tp1", "tp2"]
    assert first["price"] == pytest.approx(120 * .9998) and second["price"] == pytest.approx(200 * .9998)
    assert first["qty"] + second["qty"] == pytest.approx(entry["qty"])
    assert first["remaining"] == pytest.approx(second["qty"]) and second["remaining"] == 0
    assert closed["reason"] == "take_profit" and closed["trade"]["exit_i"] == 900 and not b.positions()


@pytest.mark.parametrize("enabled", [True, False])
def test_filled_postonly_paper_trade_identifies_repriced_h_exits_after_restart(tmp_path, enabled):
    b = book(enabled=enabled)
    c = candidate()
    [entry] = _enter(b, [c])
    drv = _Drv({900: {"l": 98, "h": 101}}, {"bid": 99, "ask": 100})
    drv.book = b
    path = tmp_path / "paper.jsonl"
    port = PaperPort(path, entry_mode="postonly_timeout")
    port._po_place(entry, c, drv)
    restored = PaperPort(path, entry_mode="postonly_timeout")
    restored.load(json.loads(json.dumps(port.state())))
    [closed] = b.close_minute(900, bar(101, 75))
    restored.handle([closed], 901, drv)
    [trade] = [r for r in map(json.loads, path.read_text().splitlines()) if r["kind"] == "po_trade"]
    q = entry["qty"]
    expected = closed["trade"]["net_pnl"] + q * (entry["entry"] - 99) + entry["fee"] - q * 99 * PaperPort.MAKER
    assert trade["net_pnl"] == pytest.approx(expected)
    if enabled:
        assert trade["h_exit"] == H_EXIT_V2_TERMS and trade["pnl_model"] == "maker_entry_repriced_market_exits"
    else:
        assert "pnl_model" not in trade and "h_exit" not in trade
