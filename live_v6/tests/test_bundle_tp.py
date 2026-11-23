# bundle_v5 exchange take-profit (user 2026-11-23: "TP 안 걸어서 손절난 게 있어"): every position gets TP1 +1R (R = entry −
# initial stop) for 50 % → SL to the fee-inclusive breakeven + 0.15 %; the strategy's trail (never looser) and time exit take
# the rest; a qty too small to split gets ONE TP for the whole qty; positions opened before TP was on get it at the next
# reconcile; nothing of ours is left on the exchange once the position is flat. Offline (FakeExchange).
from decimal import Decimal as D

from live_v6.runner import live_settings

from .test_bundle_v5 import _bundle_eng, _intent
from .test_faults import DOGE

TP = {k: getattr(live_settings("bundle_v5"), k)
      for k in ("take_profit", "tp1_r", "tp1_frac", "tp2_r", "be_offset", "be_fee", "tp_whole_if_unsplit")}


def _tps(b):
    return [o for o in b.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"]


def _stops(b):
    return [o for o in b.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")]


def _tp1_px(eng, j):
    e = D(j["entry_px"])
    return eng.rules[DOGE].price(e + (e - D(j["stop_px_entry"])), "up")


def _open(b, **kw):
    eng = _bundle_eng(b, **{**TP, **kw})
    eng.execute([_intent(eng)])
    assert b.amt(DOGE) == 100
    return eng, eng.st["pos"][DOGE]


def test_live_settings_bundle_tp_on():
    assert TP == dict(take_profit=True, tp1_r=1.0, tp1_frac=0.5, tp2_r=None, be_offset=0.0015, be_fee=0.0005,
                      tp_whole_if_unsplit=True)


def test_entry_places_tp1_half_at_plus_1r(offline):
    eng, j = _open(offline)
    [t] = _tps(offline)
    assert t["side"] == "SELL" and t["reduce_only"] and D(t["qty"]) == 50 and t["client_id"] == j["cid"] + "t1"
    assert D(t["stop_price"]) == _tp1_px(eng, j) == D(j["tp"]["tp1"]) and j["tp"]["tp2"] is None
    assert len(_stops(offline)) == 1
    assert "익절 TP1" in offline.notifiers[-1].sent[-1] or any("익절 TP1" in s for s in offline.notifiers[-1].sent)


def test_tp1_fill_moves_stop_to_breakeven_and_trail_never_below(offline):
    eng, j = _open(offline)
    offline.inner.set_price(DOGE, _tp1_px(eng, j) + D("0.00010"))  # TP1 fires on the exchange
    eng.reconcile()
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    be = eng._be_target(DOGE, j)
    assert offline.amt(DOGE) == 50 and j["tp1_done"] and D(j["qty"]) == 50 and j.get("be_done")
    [s] = _stops(offline)
    assert D(s["stop_price"]) == be == D(j["stop_px"]) > D(j["entry_px"])
    assert eng.move_stop(DOGE, be - D("0.00100")) == "not_tighter"   # the strategy trail below BE: ignored
    assert D(_stops(offline)[0]["stop_price"]) == be
    assert eng.move_stop(DOGE, be + D("0.00050")) == "ok"           # above BE: tightens as before
    offline.inner.set_price(DOGE, be)                               # remainder stopped out
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and offline.inner.open_orders(DOGE) == []


def test_stop_before_tp_leaves_no_orphan_tp(offline):
    eng, j = _open(offline)
    offline.inner.set_price(DOGE, D(j["stop_px"]) - D("0.00010"))
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and offline.inner.open_orders(DOGE) == [] and DOGE not in eng.st["pos"]


def test_strategy_exit_cancels_tp(offline):
    eng, j = _open(offline)
    eng.execute([{"type": "exit", "sym": DOGE, "reason": "time_exit"}])
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and offline.inner.open_orders(DOGE) == [] and DOGE not in eng.st["pos"]


def test_cannot_split_gets_one_tp_for_the_whole_qty(offline):
    eng, j = _open(offline)
    one = {"side": 1, "entry_px": j["entry_px"], "stop_px_entry": j["stop_px_entry"], "stop_px": j["stop_px"], "qty": "1"}
    tp1, q1, tp2, q2 = eng._tp_levels(DOGE, one)
    assert (q1, tp2, q2) == (D(1), None, D(0)) and tp1 == _tp1_px(eng, j)
    eng.cfg.tp_whole_if_unsplit = False                             # qrmtf behaviour unchanged: no TP1, no TP2 (E)
    assert eng._tp_levels(DOGE, one)[1:] == (D(0), None, D(1))


def test_whole_qty_tp_fill_closes_as_take_profit_no_orphan_stop(offline):
    eng, j = _open(offline, tp1_frac=1.0)                           # frac 1.0 cannot split → whole qty at TP1
    [t] = _tps(offline)
    assert D(t["qty"]) == 100 and not j["tp1_done"]
    offline.inner.set_price(DOGE, _tp1_px(eng, j) + D("0.00010"))
    eng.reconcile()
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and offline.inner.open_orders(DOGE) == [] and DOGE not in eng.st["pos"]
    assert any("청산" in s and "익절" in s for s in offline.notifiers[-1].sent)


def test_restart_does_not_duplicate_tp(offline):
    eng, j = _open(offline)
    eng2 = _bundle_eng(offline, **TP)                               # restart: new engine, same state file
    eng2.reconcile()
    eng2.reconcile()
    assert [o["client_id"] for o in _tps(offline)] == [j["cid"] + "t1"] and len(_stops(offline)) == 1


def test_position_opened_without_tp_gets_it_after_deploy(offline):
    old, j = _open(offline, take_profit=False)                      # opened by the version without TP
    assert "tp" not in j and _tps(offline) == []
    new = _bundle_eng(offline, **TP)                                # deploy: restart with TP on
    new.reconcile()
    jj = new.st["pos"][DOGE]
    [t] = _tps(offline)
    assert D(t["qty"]) == 50 and D(t["stop_price"]) == _tp1_px(new, jj) and jj["tp"]["tp1"] == str(t["stop_price"])
    assert any("익절 주문 추가" in s for s in offline.notifiers[-1].sent)
    new.reconcile()
    assert len(_tps(offline)) == 1 and not new.in_manual(DOGE) and len(_stops(offline)) == 1


def test_adopted_position_already_past_tp1_takes_half_at_market(offline):
    old, j = _open(offline, take_profit=False)
    offline.inner.set_price(DOGE, _tp1_px(old, j) + D("0.00200"))  # already beyond TP1 when the TP version starts
    new = _bundle_eng(offline, **TP)
    new.reconcile()
    new.reconcile()
    new.reconcile()
    jj = new.st["pos"][DOGE]
    assert offline.amt(DOGE) == 50 and D(jj["qty"]) == 50 and not new.in_manual(DOGE)
    assert len(_stops(offline)) == 1 and _tps(offline) == []
