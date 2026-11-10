# TA protection policy v1 (2026-11-09), rulings on PR #2. Offline fakes only: no network, no Telegram.
# +3R runner is scheme E only. Legacy keeps its +2R TP2. Entry-stop failure uses the 1s/3s/10s retry.
import pytest
from decimal import Decimal as D
from urllib.parse import parse_qs

import httpx

from live_v6.exchange import TESTNET_URL, BinanceREST

from live_v6.strategies.base import enter

from .test_qrmtf import DOGE, bot_orders, legacy_engine, now_ms, open_pos

SOL = "SOLUSDT"
RETRY_S = [1.0, 3.0, 10.0]


def engine_for(b, scheme, sleep_log=None):
    real = b.engine

    def wrapped(**kw):
        eng = real(**kw)
        if sleep_log is not None:
            eng.sleep = sleep_log.append
        return eng

    b.engine = wrapped
    try:
        if scheme == "e":
            from .test_chandelier_e import Clk, e_engine
            return e_engine(b, Clk())
        return legacy_engine(b)
    finally:
        b.engine = real


def _orders(b, sym=DOGE):
    return b.inner.open_orders(sym)


def _of_type(b, kind, sym=DOGE):
    return [o for o in _orders(b, sym) if o["type"] == kind]


def _stops(b, sym=DOGE):
    return _of_type(b, "STOP_MARKET", sym)


def _tps(b, sym=DOGE):
    return _of_type(b, "TAKE_PROFIT_MARKET", sym)


def _r_px(eng, j, k):
    s = int(j.get("side", 1))
    e = D(j["entry_px"])
    r = abs(e - D(j.get("stop_px_entry") or j["stop_px"]))
    return eng.rules[DOGE].price(e + s * r * D(k), "up" if s > 0 else "down")


def _runner_px(eng, j):
    return _r_px(eng, j, 3)


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


@pytest.mark.parametrize("side", [1, -1])
def test_scheme_e_plus_3r_tp_after_tp1(offline, side):
    """Scheme E only: after TP1 the remainder carries one MARK_PRICE reduceOnly TP at entry ± 3R."""
    _assert_no_telegram(eng := engine_for(offline, "e"))
    j0 = open_pos(offline, eng, side)
    stop0 = D(j0["stop_px"])
    want = _runner_px(eng, j0)
    j = _fill_tp1(offline, eng)
    runners = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t3"]
    assert len(runners) == 1 and len(_tps(offline)) == 1, _tps(offline)
    o = runners[0]
    assert o["stop_price"] == want and o["working_type"] == "MARK_PRICE"
    assert o["reduce_only"] and not o["close_position"] and o["qty"] == abs(offline.amt(DOGE))
    assert len(_stops(offline)) == 1 and not [x for x in _tps(offline) if x["client_id"].endswith("t2")]
    assert j.get("tp1_done") and D(j["stop_px"]) != stop0


@pytest.mark.parametrize("side", [1, -1])
def test_legacy_keeps_tp2_at_2r_after_tp1(offline, side):
    """Legacy second take-profit stays at +2R. No +3R runner is added."""
    eng = engine_for(offline, "legacy")
    j0 = open_pos(offline, eng, side)
    stop0 = D(j0["stop_px"])
    want = _r_px(eng, j0, eng.cfg.tp2_r)
    j = _fill_tp1(offline, eng)
    t2 = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t2"]
    assert len(t2) == 1, _tps(offline)
    assert t2[0]["stop_price"] == want and t2[0]["working_type"] == "CONTRACT_PRICE"
    assert t2[0]["reduce_only"] and t2[0]["qty"] == abs(offline.amt(DOGE))
    assert not [o for o in _tps(offline) if o["client_id"].endswith("t3")]
    assert j["tp"]["tp3"] is None if "tp3" in j["tp"] else True
    assert "tp3" not in j["tp"]
    assert len(_stops(offline)) == 1 and j.get("tp1_done") and D(j["stop_px"]) != stop0


@pytest.mark.parametrize("side", [1, -1])
def test_scheme_e_unsplittable_qty_gets_full_3r_and_sl(offline, side):
    """Scheme E, qty that cannot be split: full size gets +3R and the SL. No 'no TP' path."""
    eng = engine_for(offline, "e")
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


@pytest.mark.parametrize("side", [1, -1])
def test_legacy_unsplittable_qty_keeps_full_tp2_at_2r(offline, side):
    """Legacy cannot-split path is unchanged: one +2R TP2 on the full qty, no +3R order."""
    eng = engine_for(offline, "legacy")
    j = open_pos(offline, eng, side)
    offline.inner.pos[DOGE]["amt"] = D(side)
    j["qty"] = j["entry_qty"] = "1"
    for o in list(_tps(offline)):
        offline.inner.algos.pop(o["id"], None)
    j.pop("tp", None)
    j.pop("tp1_done", None)
    eng._place_tps(DOGE, j)
    tps = _tps(offline)
    assert len(tps) == 1 and tps[0]["client_id"] == j["cid"] + "t2"
    assert tps[0]["stop_price"] == _r_px(eng, j, eng.cfg.tp2_r) and tps[0]["qty"] == D(1)
    assert tps[0]["working_type"] == "CONTRACT_PRICE" and tps[0]["reduce_only"]
    assert len(_stops(offline)) == 1 and "tp3" not in j["tp"]
    assert offline.amt(DOGE) == D(side)


@pytest.mark.parametrize("hit", ["tp", "stop"])
def test_scheme_e_first_hit_flattens_and_cancels_the_other(offline, hit):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    j = _fill_tp1(offline, eng)
    assert any(o["client_id"] == j["cid"] + "t3" for o in _tps(offline))
    px = D(j["tp"]["tp3"]) if hit == "tp" else D(j["stop_px"])
    offline.inner.set_price(DOGE, px)
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"] and not bot_orders(offline, DOGE)


@pytest.mark.parametrize("hit", ["tp", "stop"])
def test_legacy_first_hit_is_tp2_or_stop_and_there_is_no_3r(offline, hit):
    eng = engine_for(offline, "legacy")
    open_pos(offline, eng, 1)
    j = _fill_tp1(offline, eng)
    assert not [o for o in _tps(offline) if o["client_id"].endswith("t3")]
    assert any(o["client_id"] == j["cid"] + "t2" for o in _tps(offline))
    px = D(j["tp"]["tp2"]) if hit == "tp" else D(j["stop_px"])
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
    """A missing positions row is unknown from the first read: no order is sent, and nothing is closed or cancelled."""
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
    assert [c for c in offline.fx.calls[n:] if c[0] == "take_profit"] == []
    assert sl == []
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
    if scheme == "e":
        old = _pop_cid_suffix(offline, "t3")[0]
        eng.audit_protection()
        runners = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t3"]
        assert len(runners) == 1 and runners[0]["stop_price"] == old["stop_price"] == _runner_px(eng, j)
        assert runners[0]["working_type"] == "MARK_PRICE" and runners[0]["reduce_only"]
        assert runners[0]["qty"] == abs(offline.amt(DOGE))
        assert len(_tps(offline)) == 1 and len(_stops(offline)) == 1
    else:
        assert not [o for o in _tps(offline) if o["client_id"].endswith("t3")]
        old = _pop_cid_suffix(offline, "t2")[0]
        eng.audit_protection()
        back = [o for o in _tps(offline) if o["client_id"] == j["cid"] + "t2"]
        assert len(back) == 1 and back[0]["stop_price"] == old["stop_price"] == _r_px(eng, j, eng.cfg.tp2_r)
        assert back[0]["working_type"] == "CONTRACT_PRICE" and back[0]["reduce_only"]
        assert back[0]["qty"] == abs(offline.amt(DOGE))
        assert not [o for o in _tps(offline) if o["client_id"].endswith("t3")]


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


def _fail_once(kind):
    seen = {"n": 0}

    def flaky(fn, *a, **k):
        seen["n"] += 1
        if seen["n"] == 1:
            from live_v6.exchange import ExchangeUnavailable
            raise ExchangeUnavailable(f"{kind} down once")
        return fn(*a, **k)

    return flaky


@pytest.mark.parametrize("scheme", ["legacy", "e"])
@pytest.mark.parametrize("stage", ["entry", "after_tp1"])
def test_restart_replaces_missing_sl_and_tp_via_retry_procedure(offline, scheme, stage):
    """After restart, a missing SL or TP is re-placed by the 1s/3s/10s procedure. Both schemes."""
    eng = engine_for(offline, scheme)
    j = open_pos(offline, eng, 1)
    if stage == "after_tp1":
        j = _fill_tp1(offline, eng)
    tp_suffix = "t3" if scheme == "e" and stage == "after_tp1" else ("t2" if scheme == "legacy" else "t1")
    if scheme == "legacy" and stage == "entry":
        tp_suffix = "t2"  # the legacy order the audit must keep restoring
    want_px = _runner_px(eng, j) if tp_suffix == "t3" else D(j["tp"]["tp2"] if tp_suffix == "t2" else j["tp"]["tp1"])
    for o in list(_orders(offline)):
        if o["type"] == "STOP_MARKET" or str(o["client_id"]).endswith(tp_suffix):
            offline.inner.algos.pop(o["id"], None)
    assert not _stops(offline) and not [o for o in _tps(offline) if o["client_id"].endswith(tp_suffix)]
    sleeps = []
    offline.fx.inject("stop", _fail_once("stop"), times=1)
    offline.fx.inject("take_profit", _fail_once("tp"), times=1)
    eng2 = engine_for(offline, scheme, sleep_log=sleeps)  # startup reconcile is the restart
    assert DOGE in eng2.st["pos"] and not eng2.st["pos"][DOGE].get("closing")
    assert sleeps[:2] == [1.0, 1.0], sleeps  # item 2's first gap, not the old 3s window
    restored = [o for o in _tps(offline) if o["client_id"] == j["cid"] + tp_suffix]
    assert len(restored) == 1 and restored[0]["stop_price"] == want_px and restored[0]["reduce_only"]
    if tp_suffix == "t3":
        assert restored[0]["working_type"] == "MARK_PRICE"
    else:
        assert restored[0]["working_type"] == "CONTRACT_PRICE"
    assert len(_stops(offline)) == 1
    assert not _closes(offline)
    if scheme == "legacy":
        assert not [o for o in _tps(offline) if o["client_id"].endswith("t3")]


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_restart_missing_symbol_is_not_cancelled_or_closed(offline, scheme):
    """A symbol absent from the positions read on restart is unknown: SL/TP stay, no market close."""
    eng = engine_for(offline, scheme)
    open_pos(offline, eng, 1)
    kept = {o["id"] for o in _orders(offline)}
    assert kept and offline.amt(DOGE) != 0

    def omit(fn, symbols):
        pos = fn(symbols)
        pos.pop(DOGE, None)
        return pos

    offline.fx.inject("positions", omit, times=99)
    eng2 = engine_for(offline, scheme)
    assert {o["id"] for o in _orders(offline)} == kept
    assert offline.amt(DOGE) != 0 and DOGE in eng2.st["pos"]
    assert not eng2.st["pos"][DOGE].get("closing") and not _closes(offline)


def _enter(eng):
    px = D(str(eng.ex.inner.price[DOGE])) if hasattr(eng.ex, "inner") else D("0.15")
    # FaultEx wraps the fake; price lives on the fake.
    px = D(str(eng.ex.inner.price[DOGE]))
    t = now_ms()
    eng.execute([dict(enter(DOGE, px * D("0.008"), t, side=1), model_id=t, max_age_s=20)])


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_entry_stop_upgrade_retries_1s_3s_10s_and_keeps_live_prearm(offline, scheme):
    """ClosePosition upgrade fails, the pre-arm stop is still live: retry on the new schedule, do not flatten."""
    eng = engine_for(offline, scheme)
    _assert_no_telegram(eng)
    sl = _sleeps(eng)

    def fail_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            from live_v6.exchange import ExchangeUnavailable
            raise ExchangeUnavailable("down")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("stop", fail_cp, times=20)
    open_pos(offline, eng, 1)
    cp = [c for c in offline.fx.calls if c[0] == "stop" and not str(c[1][3]).endswith("p")]
    assert len(cp) == 4 and sl == RETRY_S
    assert sum("재시도" in m for m in _alerts(eng)) == 3
    assert not _closes(offline) and offline.amt(DOGE) != 0 and _stops(offline)


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_entry_stop_unconfirmed_retries_then_reduceonly_market_close(offline, scheme):
    """No confirmed stop after the entry fill: 1s, 3s, 10s, then one reduceOnly market close and a 🚨 alert."""
    eng = engine_for(offline, scheme)
    _assert_no_telegram(eng)
    sl = _sleeps(eng)

    def hide(fn, sym):
        rows = fn(sym)
        entered = any(c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls)
        if not entered:
            return rows
        return [o for o in rows if not str(o.get("client_id", "")).endswith("p")]

    def fail_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            from live_v6.exchange import ExchangeUnavailable
            raise ExchangeUnavailable("down")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", hide, times=1000)
    offline.fx.inject("stop", fail_cp, times=20)
    _enter(eng)
    cp = [c for c in offline.fx.calls if c[0] == "stop" and not str(c[1][3]).endswith("p")]
    assert len(cp) == 4 and sl == RETRY_S
    assert sum(m.startswith("🚨 보호 주문 실패 — 재시도") for m in _alerts(eng)) == 3
    assert any("시장가 청산" in m for m in _alerts(eng))
    closes = [c for c in _closes(offline) if c[1][0] == DOGE]
    assert len(closes) == 1 and closes[0][1][4] is True
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]


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
