"""Live v1 on an XRP-like symbol (tick 0.0001, step 0.1, minNotional $5): nothing BTC/ETH-specific."""

import time
from decimal import Decimal

import httpx

from app.binance.ws_consumer import BinanceWSConsumer
from app.config import Settings
from app.trading.live_v1.engine import LiveV1Engine, LiveV1Settings
from app.trading.live_v1.exchange import BinanceExchange, SymbolRules
from app.trading.schemas import PositionSide
from app.trading.tg_format import fmt_entry, fmt_exit

from .fake_exchange import XRP_RULES, FakeExchange, FaultyExchange

BAR = int(time.time() * 1000) // 1000 * 1000
XRP_BRACKETS = [{"floor": 0.0, "cap": 10000.0, "mmr": 0.005, "max_lev": 75},
                {"floor": 10000.0, "cap": 100000.0, "mmr": 0.01, "max_lev": 50}]
XRP_INFO = {"symbols": [{"symbol": "XRPUSDT", "filters": [
    {"filterType": "PRICE_FILTER", "tickSize": "0.0001000", "minPrice": "0.0143"},
    {"filterType": "LOT_SIZE", "stepSize": "0.1", "minQty": "0.1", "maxQty": "10000000"},
    {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]}


def _xrp(wallet="1000"):
    fx = FakeExchange(wallet=wallet, price="0.5", spread="0.0002", rules=XRP_RULES)   # bid 0.4999 / ask 0.5001
    fx.brackets = [dict(b) for b in XRP_BRACKETS]
    return fx


async def _eng(fx, **kw):
    ex = FaultyExchange(fx)
    eng = LiveV1Engine(ex, LiveV1Settings(symbol="XRPUSDT", query_delay_s=0, income_interval_s=0,
                                          breach_grace_s=0, **kw))
    await eng.initialize()
    return eng, ex


def test_default_symbol_is_xrpusdt(monkeypatch):
    monkeypatch.delenv("LIVE_V1_SYMBOL", raising=False)
    assert Settings(_env_file=None).live_v1_symbol == "XRPUSDT"
    assert LiveV1Settings().symbol == "XRPUSDT"


def test_rules_parsed_from_exchange_info_not_hardcoded():
    r = SymbolRules.from_exchange_info(XRP_INFO, "XRPUSDT")
    assert (r.tick_size, r.step_size, r.min_qty, r.min_notional) == \
        (Decimal("0.0001"), Decimal("0.1"), Decimal("0.1"), Decimal("5"))
    assert r.floor_qty(Decimal("325.3099")) == Decimal("325.3")
    assert r.price(Decimal("0.48473"), "up") == Decimal("0.4848")
    assert r.price(Decimal("0.51527"), "down") == Decimal("0.5152")


async def test_xrp_long_sizing_rounding_and_stop():
    fx = _xrp()
    eng, ex = await _eng(fx)
    assert eng.rules == XRP_RULES and eng.brackets[0]["mmr"] == 0.005
    assert await eng._enter(1, Decimal("0.01537"), BAR)           # ~3.07% stop
    # risk 0.5% × 1000 = 5 USDT → 5/0.01537 = 325.309… → floor to step 0.1
    assert fx.amt == Decimal("325.3")
    assert eng.pos["entry_px"] == "0.5001"
    assert eng.pos["stop_px"] == "0.4848"                         # 0.48473 rounded UP to tick (toward entry)
    assert fx.lev == 10 and eng.pos["mmr"] == 0.005               # tier for 325.3 × 0.5001 ≈ $162.7
    assert [s["stop_price"] for s in fx.stops.values()] == [Decimal("0.4848")]
    assert Decimal(eng.pos["risk_usdt"]) == Decimal("4.98")       # 325.3 × 0.0153


async def test_xrp_short_stop_rounds_down_toward_entry():
    fx = _xrp()
    eng, _ = await _eng(fx)
    assert await eng._enter(-1, Decimal("0.01537"), BAR)
    assert fx.amt == Decimal("-325.3") and eng.pos["entry_px"] == "0.4999"
    assert eng.pos["stop_px"] == "0.5152"                         # 0.51527 rounded DOWN


async def test_xrp_min_notional_5_boundary():
    eng, _ = await _eng(_xrp(wallet="30.5"))                      # qty 9.92 → 9.9 → $4.95 < $5
    assert not await eng._enter(1, Decimal("0.01537"), BAR)
    assert list(eng.skip_counts(__import__("app.trading.tg_format", fromlist=["x"]).kst_date())) == ["min_notional"]
    fx = _xrp(wallet="31")                                        # qty 10.08 → 10.0 → $5.001 ≥ $5
    eng2, _ = await _eng(fx)
    assert await eng2._enter(1, Decimal("0.01537"), BAR) and fx.amt == Decimal("10.0")


async def test_xrp_heartbeat_and_breach_use_configured_symbol():
    fx = _xrp()
    eng, _ = await _eng(fx)
    assert await eng._enter(1, Decimal("0.01537"), BAR)
    fx.stops.clear()
    fx.price = Decimal("0.4800")
    await eng.on_mark_price("BTCUSDT", Decimal("60000"))          # other symbol: ignored
    assert eng._breach_task is None and fx.amt != 0
    await eng.on_mark_price("XRPUSDT", Decimal("0.4800"))
    await eng._breach_task
    assert fx.amt == 0 and eng.trade_history[-1].close_reason == "stop_breach"
    assert eng.trade_history[-1].avg_exit_price == Decimal("0.4799")   # 4-dec price kept (not 0.48)


def test_ws_streams_include_configured_mark_price():
    c = BinanceWSConsumer(manager=None)
    assert c.build_streams("XRPUSDT").endswith("/xrpusdt@markPrice@1s")
    assert "markPrice" not in c.build_streams(None)


def test_telegram_formats_4_decimal_prices():
    t = fmt_entry(PositionSide.LONG, Decimal("0.5001"), Decimal("0.4848"), None, Decimal("4.98"))
    assert "0.5001" in t and "0.4848" in t and "$4.98" in t
    t = fmt_entry(PositionSide.SHORT, Decimal("60000.5"), Decimal("61800.5"), None, Decimal("5"))
    assert "60,000.5" in t and "61,800.5" in t


async def test_binance_order_params_xrp_precision():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.url.path == "/fapi/v1/exchangeInfo":
            return httpx.Response(200, json=XRP_INFO)
        if req.url.path == "/fapi/v1/order":
            return httpx.Response(200, json={"orderId": 1, "clientOrderId": req.url.params["newClientOrderId"],
                                             "status": "FILLED", "avgPrice": "0.5001",
                                             "executedQty": req.url.params["quantity"], "updateTime": 1})
        if req.url.path == "/fapi/v1/algoOrder":
            return httpx.Response(200, json={"algoId": 9, "clientAlgoId": req.url.params["clientAlgoId"],
                                             "orderType": "STOP_MARKET", "side": req.url.params["side"],
                                             "triggerPrice": req.url.params["triggerPrice"],
                                             "closePosition": True, "algoStatus": "NEW"})
        return httpx.Response(404, json={"code": -1, "msg": "?"})

    ex = BinanceExchange("https://testnet.binancefuture.com", "k", "s", symbol="XRPUSDT",
                         transport=httpx.MockTransport(handler))
    o = await ex.market("BUY", Decimal("325.3099"), "v1xL")
    q = seen[-1].url.params
    assert q["symbol"] == "XRPUSDT" and q["quantity"] == "325.3" and o["executed_qty"] == Decimal("325.3")
    await ex.market("SELL", Decimal("12000"), "v1yS")
    assert seen[-1].url.params["quantity"] == "12000.0"           # no scientific notation
    s = await ex.stop("SELL", Decimal("0.4848"), "v1xLs1")       # engine passes tick-rounded stops
    q = seen[-1].url.params
    assert q["triggerPrice"] == "0.4848" and q["workingType"] == "MARK_PRICE" and q["closePosition"] == "true"
    assert s["stop_price"] == Decimal("0.4848")
    await ex.stop("BUY", Decimal("0.5152"), "v1yS1")
    assert seen[-1].url.params["triggerPrice"] == "0.5152"
    await ex.stop("SELL", Decimal("0.484739"), "v1zLs1")         # off-tick input is still snapped to tick
    assert seen[-1].url.params["triggerPrice"] == "0.4847"
    assert sum(r.url.path == "/fapi/v1/exchangeInfo" for r in seen) == 1   # rules cached
