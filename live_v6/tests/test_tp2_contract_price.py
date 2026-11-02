# TA 2026-11-02: TP1 + TP2 trigger on the last price (CONTRACT_PRICE); every stop stays on MARK_PRICE. Offline only.
from decimal import Decimal
from urllib.parse import parse_qs

import httpx

from live_v6.exchange import BinanceREST, TESTNET_URL

from .test_qrmtf import exit_engine, open_pos

DOGE = "DOGEUSDT"


def _algos(b, sym):
    return {o["client_id"][-2:]: o for o in b.inner.algos.values() if o["symbol"] == sym}


def test_rest_take_profit_working_type_param():
    sent = []

    def handler(req):
        sent.append({k: v[0] for k, v in parse_qs(req.url.query.decode()).items()})
        return httpx.Response(200, json={"algoId": 1, "clientAlgoId": "c", "triggerPrice": "1", "workingType": sent[-1].get("workingType")})

    r = BinanceREST(TESTNET_URL, "k", "s", transport=httpx.MockTransport(handler))
    assert r.take_profit(DOGE, "SELL", Decimal("0.2"), "v6t2", Decimal(10), working_type="CONTRACT_PRICE")["working_type"] == "CONTRACT_PRICE"
    r.take_profit(DOGE, "SELL", Decimal("0.2"), "v6t1", Decimal(10))
    r.stop(DOGE, "SELL", Decimal("0.1"), "v6s0")
    assert [(p["clientAlgoId"], p["type"], p["workingType"]) for p in sent] == [
        ("v6t2", "TAKE_PROFIT_MARKET", "CONTRACT_PRICE"), ("v6t1", "TAKE_PROFIT_MARKET", "MARK_PRICE"),
        ("v6s0", "STOP_MARKET", "MARK_PRICE")]


def test_entry_tp1_tp2_contract_sl_mark(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, side=1)
    a = _algos(offline, DOGE)
    assert a["t2"]["working_type"] == "CONTRACT_PRICE"
    assert a["t1"]["working_type"] == "CONTRACT_PRICE"
    assert [o["working_type"] for o in a.values() if o["type"] == "STOP_MARKET"] == ["MARK_PRICE"]


def test_restart_replaces_missing_tp2_on_contract_price_once(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, side=-1)
    t2 = _algos(offline, DOGE)["t2"]
    offline.inner.algos.pop(t2["id"])                          # TP2 gone while the bot was down (cancelled by hand)
    exit_engine(offline).reconcile()                           # restart
    eng3 = exit_engine(offline)
    eng3.reconcile()
    tps = [o for o in offline.inner.algos.values() if o["symbol"] == DOGE and o["client_id"].endswith("t2")]
    assert len(tps) == 1 and tps[0]["working_type"] == "CONTRACT_PRICE" and tps[0]["stop_price"] == t2["stop_price"]
    assert tps[0]["qty"] == t2["qty"]


def test_pre_deploy_mark_price_tp2_left_as_is_not_duplicated(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, side=1)
    t2 = _algos(offline, DOGE)["t2"]
    t2["working_type"] = "MARK_PRICE"                          # as placed by 0cfb9b7 before the deploy
    before = {k: dict(v) for k, v in offline.inner.algos.items()}
    eng2 = exit_engine(offline)                                # deploy restart
    eng2.reconcile()
    eng2.reconcile()
    assert {k: dict(v) for k, v in offline.inner.algos.items()} == before
    assert sum(1 for o in offline.inner.algos.values() if o["client_id"].endswith("t2")) == 1


def test_restart_replaces_missing_tp1_on_contract_price_once(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, side=1)
    t1 = _algos(offline, DOGE)["t1"]
    offline.inner.algos.pop(t1["id"])                          # TP1 gone while the bot was down, price never reached it
    eng2 = exit_engine(offline)
    eng2.reconcile()
    eng2.reconcile()
    tps = [o for o in offline.inner.algos.values() if o["symbol"] == DOGE and o["client_id"].endswith("t1")]
    assert len(tps) == 1 and tps[0]["working_type"] == "CONTRACT_PRICE" and tps[0]["stop_price"] == t1["stop_price"]
    assert tps[0]["qty"] == t1["qty"]


def test_pre_deploy_mark_price_tp1_left_as_is_not_duplicated(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, side=-1)
    a = _algos(offline, DOGE)
    a["t1"]["working_type"] = "MARK_PRICE"                     # as placed by d87da26 before the deploy
    a["t2"]["working_type"] = "MARK_PRICE"                     # and a 0cfb9b7-era TP2
    before = {k: dict(v) for k, v in offline.inner.algos.items()}
    eng2 = exit_engine(offline)                                # deploy restart
    eng2.reconcile()
    eng2.reconcile()
    assert {k: dict(v) for k, v in offline.inner.algos.items()} == before
    assert sum(1 for o in offline.inner.algos.values() if o["client_id"].endswith("t1")) == 1
