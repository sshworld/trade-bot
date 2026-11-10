# TA protection policy v1 (2026-11-09). Offline fakes only: no exchange network, no Telegram.
# Legacy (TP2 +2R) and scheme E (chandelier, no TP2) both get the +3R reduceOnly runner.
import pytest
from decimal import Decimal as D
from urllib.parse import parse_qs

import httpx

from live_v6.exchange import TESTNET_URL, BinanceREST

from .test_qrmtf import DOGE, bot_orders, legacy_engine, open_pos

SOL = "SOLUSDT"
RETRY_S = [1.0, 3.0, 10.0]


def engine_for(b, scheme):
    if scheme == "e":
        from .test_chandelier_e import Clk, e_engine
        return e_engine(b, Clk())
    return legacy_engine(b)


def _orders(b, sym=DOGE):
    return b.inner.open_orders(sym)


def _of_type(b, kind, sym=DOGE):
    return [o for o in _orders(b, sym) if o["type"] == kind]


def _stops(b, sym=DOGE):
    return _of_type(b, "STOP_MARKET", sym)


def _tps(b, sym=DOGE):
    return _of_type(b, "TAKE_PROFIT_MARKET", sym)


def _runner_px(eng, j):
    s = int(j.get("side", 1))
    e = D(j["entry_px"])
    r = abs(e - D(j.get("stop_px_entry") or j["stop_px"]))
    return eng.rules[DOGE].price(e + s * r * D(3), "up" if s > 0 else "down")


def _fill_tp1(b, eng):
    j = eng.st["pos"][DOGE]
    b.inner.set_price(DOGE, D(j["tp"]["tp1"]))
    eng.reconcile()
    eng.reconcile()
    return eng.st["pos"][DOGE]


def _pop_cid_suffix(b, suffix, sym=DOGE):
    gone = [o for o in _orders(b, sym) if str(o["client_id"]).endswith(suffix)]
    for o in gone:
        b.inner.algos.pop(o["id"], None)
    return gone


def _sleeps(eng):
    rec = []
    eng.sleep = rec.append
    return rec


def _closes(b):
    return [c for c in b.fx.calls if c[0] == "market" and len(c[1]) > 4 and c[1][4]]


def _alerts(eng):
    return [m for m in eng.tg.sent if m.startswith("🚨")]


def _assert_no_telegram(eng):
    assert eng.tg.live is False and eng.tg.mode != "live"


@pytest.mark.parametrize("scheme", ["legacy", "e"])
@pytest.mark.parametrize("side", [1, -1])
def test_plus_3r_tp_after_tp1(offline, scheme, side):
    """After TP1 fills, the remainder carries one MARK_PRICE reduceOnly TP at entry ± 3R. The stop stays."""
    _assert_no_telegram(eng := engine_for(offline, scheme))
    j0 = open_pos(offline, eng, side)
    stop0 = D(j0["stop_px"])
    want = _runner_px(eng, j0)
    j = _fill_tp1(offline, eng)
    runners = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t3"]
    assert len(runners) == 1, _tps(offline)
    o = runners[0]
    assert o["stop_price"] == want and o["working_type"] == "MARK_PRICE"
    assert o["reduce_only"] and not o["close_position"] and o["qty"] == abs(offline.amt(DOGE))
    assert len(_stops(offline)) == 1
    assert j.get("tp1_done") and D(j["stop_px"]) != stop0  # chandelier / breakeven still moved
    if scheme == "e":
        assert not [o for o in _tps(offline) if o["client_id"].endswith("t2")]
        assert len(_tps(offline)) == 1


@pytest.mark.parametrize("scheme", ["legacy", "e"])
@pytest.mark.parametrize("side", [1, -1])
def test_unsplittable_qty_gets_full_3r_and_sl(offline, scheme, side):
    """A qty that cannot be split has no 'no TP' path: full size gets +3R and the existing SL stays."""
    eng = engine_for(offline, scheme)
    j = open_pos(offline, eng, side)
    offline.inner.pos[DOGE]["amt"] = D(side)
    j["qty"] = j["entry_qty"] = "1"
    for o in list(_tps(offline)):
        offline.inner.algos.pop(o["id"], None)
    j.pop("tp", None)
    j.pop("tp1_done", None)
    eng._place_tps(DOGE, j)
    tps = _tps(offline)
    assert len(tps) == 1 and tps[0]["client_id"] == j["cid"] + "t3"
    assert tps[0]["stop_price"] == _runner_px(eng, j) and tps[0]["qty"] == D(1)
    assert tps[0]["working_type"] == "MARK_PRICE" and tps[0]["reduce_only"] and not tps[0]["close_position"]
    assert len(_stops(offline)) == 1
    assert j["tp"].get("full") is True and not j.get("tp1_done")
    assert offline.amt(DOGE) == D(side)


@pytest.mark.parametrize("scheme", ["legacy", "e"])
@pytest.mark.parametrize("hit", ["tp", "stop"])
def test_first_hit_flattens_and_cancels_the_other_after_confirmed_zero(offline, scheme, hit):
    eng = engine_for(offline, scheme)
    open_pos(offline, eng, 1)
    j = _fill_tp1(offline, eng)
    assert any(o["client_id"] == j["cid"] + "t3" for o in _tps(offline))
    px = D(j["tp"]["tp3"]) if hit == "tp" else D(j["stop_px"])
    offline.inner.set_price(DOGE, px)
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"] and not bot_orders(offline, DOGE)


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_tp_failure_retries_then_reduceonly_market_close(offline, scheme):
    eng = engine_for(offline, scheme)
    _assert_no_telegram(eng)
    j = open_pos(offline, eng, 1)
    qty = abs(offline.amt(DOGE))
    _pop_cid_suffix(offline, "t1")
    sl = _sleeps(eng)
    n = len(offline.fx.calls)
    offline.fx.inject("take_profit", "reject", times=4)
    eng.reconcile()
    placed = [c for c in offline.fx.calls[n:] if c[0] == "take_profit"]
    assert len(placed) == 4 and sl == RETRY_S
    alerts = _alerts(eng)
    assert sum("재시도" in m for m in alerts) == 3
    assert any("시장가 청산" in m for m in alerts)
    closes = [c for c in _closes(offline) if c[1][0] == DOGE]
    assert len(closes) == 1 and closes[0][1][4] is True and D(closes[0][1][2]) == qty
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"] and not bot_orders(offline, DOGE)
    assert j["cid"]  # journal existed; the close is of that position


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_sl_failure_retries_then_reduceonly_market_close(offline, scheme):
    eng = engine_for(offline, scheme)
    _assert_no_telegram(eng)
    open_pos(offline, eng, 1)
    qty = abs(offline.amt(DOGE))
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    sl = _sleeps(eng)
    n = len(offline.fx.calls)
    offline.fx.inject("stop", "reject", times=4)
    eng.audit_protection()
    placed = [c for c in offline.fx.calls[n:] if c[0] == "stop"]
    assert len(placed) == 4 and sl == RETRY_S
    alerts = _alerts(eng)
    assert sum("재시도" in m for m in alerts) == 3 and any("시장가 청산" in m for m in alerts)
    closes = [c for c in _closes(offline) if c[1][0] == DOGE]
    assert len(closes) == 1 and closes[0][1][4] is True and D(closes[0][1][2]) == qty
    assert offline.amt(DOGE) == 0 and not bot_orders(offline, DOGE)


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_tp_failure_does_not_close_or_cancel_when_symbol_missing(offline, scheme):
    """A missing positions row is unknown: retries still run, but there is no market close and no cancel."""
    eng = engine_for(offline, scheme)
    open_pos(offline, eng, 1)
    j = eng.st["pos"][DOGE]
    _pop_cid_suffix(offline, "t1")
    kept = {o["id"] for o in _orders(offline)}
    sl = _sleeps(eng)
    n = len(offline.fx.calls)

    def omit(fn, symbols):
        pos = fn(symbols)
        pos.pop(DOGE, None)
        return pos

    offline.fx.inject("positions", omit, times=99)
    offline.fx.inject("take_profit", "reject", times=4)
    eng._place_tp(DOGE, j, "t1", D(j["tp"]["tp1"]), D(j["tp"]["q1"]))
    assert [c for c in offline.fx.calls[n:] if c[0] == "take_profit"].__len__() == 4
    assert sl == RETRY_S
    assert not _closes(offline)
    assert {o["id"] for o in _orders(offline)} == kept
    assert offline.amt(DOGE) != 0 and not j.get("closing") and DOGE in eng.st["pos"]
    assert any("보류" in m for m in _alerts(eng))
    assert not any("시장가 청산" in m for m in _alerts(eng))


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_audit_restores_missing_sl_and_tp(offline, scheme):
    eng = engine_for(offline, scheme)
    j = open_pos(offline, eng, 1)
    t1 = _pop_cid_suffix(offline, "t1")[0]
    eng.audit_protection()
    back = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t1"]
    assert len(back) == 1 and back[0]["stop_price"] == t1["stop_price"] and back[0]["qty"] == t1["qty"]
    assert back[0]["working_type"] == "CONTRACT_PRICE" and back[0]["reduce_only"]
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    eng.audit_protection()
    assert len(_stops(offline)) == 1 and offline.amt(DOGE) != 0
    j = _fill_tp1(offline, eng)
    old = _pop_cid_suffix(offline, "t3")[0]
    eng.audit_protection()
    runners = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t3"]
    assert len(runners) == 1 and runners[0]["stop_price"] == old["stop_price"] == _runner_px(eng, j)
    assert runners[0]["working_type"] == "MARK_PRICE" and runners[0]["reduce_only"]
    assert runners[0]["qty"] == abs(offline.amt(DOGE))
    if scheme == "e":
        assert len(_tps(offline)) == 1 and len(_stops(offline)) == 1


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_audit_skips_missing_symbol_and_keeps_orders(offline, scheme):
    eng = engine_for(offline, scheme)
    open_pos(offline, eng, 1)
    open_pos(offline, eng, 1, SOL)
    kept = {o["id"] for o in _orders(offline, DOGE)}
    sol = {o["id"] for o in _orders(offline, SOL)}

    def omit_doge(fn, symbols):
        pos = fn(symbols)
        pos.pop(DOGE, None)
        return pos

    offline.fx.inject("positions", omit_doge, times=99)
    eng.audit_protection()
    assert {o["id"] for o in _orders(offline, DOGE)} == kept
    assert {o["id"] for o in _orders(offline, SOL)} == sol
    assert DOGE in eng.st["pos"] and not eng.st["pos"][DOGE].get("closing")
    assert offline.amt(DOGE) != 0 and not _closes(offline)


def test_audit_is_one_positions_and_one_open_orders_all(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    open_pos(offline, eng, 1, SOL)
    n = len(offline.fx.calls)
    eng.audit_protection()
    delta = [c[0] for c in offline.fx.calls[n:]]
    assert delta.count("positions") == 1 and delta.count("open_orders_all") == 1
    assert "open_orders" not in delta


def test_audit_runs_from_reconcile_once_per_minute(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    n = len(offline.fx.calls)
    eng.reconcile()
    assert not [c for c in offline.fx.calls[n:] if c[0] == "open_orders_all"]
    eng._protect_audit_at = eng.clock() - 60
    n = len(offline.fx.calls)
    eng.reconcile()
    assert sum(c[0] == "open_orders_all" for c in offline.fx.calls[n:]) == 1
    n = len(offline.fx.calls)
    eng.reconcile()
    assert not [c for c in offline.fx.calls[n:] if c[0] == "open_orders_all"]


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_restart_restores_sl_and_3r_runner(offline, scheme):
    eng = engine_for(offline, scheme)
    open_pos(offline, eng, 1)
    j = _fill_tp1(offline, eng)
    want = _runner_px(eng, j)
    assert [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t3"]
    for o in list(_orders(offline)):
        if o["client_id"] == j["cid"] + "t3" or o["type"] == "STOP_MARKET":
            offline.inner.algos.pop(o["id"], None)
    assert not _stops(offline) and not [o for o in _tps(offline) if o["client_id"].endswith("t3")]
    eng2 = engine_for(offline, scheme)  # startup reconcile is the restart recovery
    assert DOGE in eng2.st["pos"]
    runners = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t3"]
    assert len(runners) == 1 and runners[0]["stop_price"] == want and runners[0]["working_type"] == "MARK_PRICE"
    assert runners[0]["reduce_only"] and runners[0]["qty"] == abs(offline.amt(DOGE))
    assert len(_stops(offline)) == 1 and D(eng2.st["pos"][DOGE]["stop_px"]) == _stops(offline)[0]["stop_price"]


def test_open_orders_all_queries_without_a_symbol():
    sent = []

    def handler(req):
        q = {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}
        sent.append((req.url.path, q.get("symbol")))
        return httpx.Response(200, json=[])

    rest = BinanceREST(TESTNET_URL, "k", "s", transport=httpx.MockTransport(handler))
    try:
        assert rest.open_orders_all() == []
    finally:
        rest.close()
    assert sent == [("/fapi/v1/openOrders", None), ("/fapi/v1/openAlgoOrders", None)]
