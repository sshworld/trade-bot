"""Safety-layer unit/integration tests (offline): breaker, heartbeat, sizing, no averaging,
ledger reconciliation, auto-halt, bar-close strategy loop, exchange adapter error mapping."""

import time
from decimal import Decimal

import httpx
import pytest

from app.trading.live_v1 import safety as S
from app.trading.live_v1.engine import LiveV1Engine, LiveV1Settings
from app.trading.live_v1.exchange import (
    BinanceExchange, ExchangeUnavailable, OrderRejected, SymbolRules, WouldTrigger,
)
from app.trading.live_v1.strategy import replay
from app.trading.schemas import PositionSide, TradeRecord

from .fake_exchange import ETH_RULES, FakeExchange, FaultyExchange

EXCHANGE_INFO = {"symbols": [
    {"symbol": "BTCUSDT", "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.10", "minPrice": "556.80"},
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
        {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "120"},
        {"filterType": "MIN_NOTIONAL", "notional": "50"}]},
    {"symbol": "ETHUSDT", "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
        {"filterType": "MIN_NOTIONAL", "notional": "20"}]},
]}

BAR = int(time.time() * 1000) // 1000 * 1000


async def _eng(fx=None, **kw):
    fx = fx or FakeExchange()
    ex = FaultyExchange(fx)
    kw.setdefault("income_interval_s", 0.0)
    kw.setdefault("breach_grace_s", 0.0)
    eng = LiveV1Engine(ex, LiveV1Settings(query_delay_s=0, **kw))
    await eng.initialize()
    return eng, ex, fx


# ── primitives ──
def test_breaker_trips_after_n_and_recovers():
    b = S.ApiErrorBreaker(n=3, window_s=60, recover=2)
    assert not b.error(0) and not b.error(1)
    assert b.error(2) and b.tripped
    assert not b.success() and b.success() and not b.tripped


def test_breaker_window_forgets_old_errors():
    b = S.ApiErrorBreaker(n=3, window_s=10)
    b.error(0); b.error(1)
    assert not b.error(100)


def test_autohalt_rules():
    D = Decimal
    assert S.autohalt_reason(D(1000), D(850), D(0), []) is not None            # −15%
    assert S.autohalt_reason(D(1000), D(1350), D(500), []) is not None         # deposit is not profit
    assert S.autohalt_reason(D(1000), D(900), D(0), []) is None
    losing = [D(-10)] * 20 + [D(10)] * 10                                      # PF 0.5 at 30
    assert "PF" in S.autohalt_reason(D(1000), D(1000), D(0), losing)
    assert S.autohalt_reason(D(1000), D(1000), D(0), losing[:29]) is None
    assert S.autohalt_reason(D(1000), D(1000), D(0), [D(-10)] * 15 + [D(13)] * 15) is None


def test_choose_leverage_keeps_stop_inside_liquidation():
    # L: 0.7×(1/L − 0.4%) → 10x 6.72%, 9x 7.50%, 5x 13.72%, 4x 17.22%, 3x 23.05%, 2x 34.72%, 1x 69.72%
    assert S.choose_leverage(0.03) == 10                 # TA cap 10x
    assert S.choose_leverage(0.07) == 9
    assert S.choose_leverage(0.1372) == 5
    assert S.choose_leverage(0.15) == 4
    assert S.choose_leverage(0.20) == 3
    assert S.choose_leverage(0.30) == 2
    assert S.choose_leverage(0.60) == 1
    assert S.choose_leverage(0.70) is None               # even 1x cannot → skip
    assert S.choose_leverage(0.01, bracket_max_leverage=3) == 3
    assert S.choose_leverage(0.066, mmr=0.01) == 9       # higher MMR → lower leverage
    for f in (0.01, 0.05, 0.12, 0.2, 0.4, 0.69):
        lev = S.choose_leverage(f)
        assert lev <= 10 and f <= 0.7 * S.liquidation_distance(lev)


def test_bracket_lookup():
    br = [{"floor": 0, "cap": 50000, "mmr": 0.004, "max_lev": 125},
          {"floor": 50000, "cap": 600000, "mmr": 0.005, "max_lev": 100}]
    assert S.bracket_for(br, 1000)["mmr"] == 0.004
    assert S.bracket_for(br, 60000)["mmr"] == 0.005
    assert S.bracket_for(br, 9e9)["mmr"] == 0.005
    assert S.bracket_for([], 1) is None


async def test_mmr_from_leverage_bracket_and_fallback():
    fx = FakeExchange(wallet="100000", spread="0")
    fx.brackets = [{"floor": 0.0, "cap": 1e9, "mmr": 0.02, "max_lev": 50}]
    eng, _, _ = await _eng(fx)
    assert eng.brackets[0]["mmr"] == 0.02
    assert await eng._enter(1, Decimal("3600"), BAR)     # 6% stop: 10x fails at MMR 2% (5.6%) → 9x (6.38%)
    assert eng.pos["leverage"] == 9 and eng.pos["mmr"] == 0.02
    fx2 = FakeExchange(wallet="100000", spread="0")
    ex2 = FaultyExchange(fx2)
    ex2.inject("leverage_brackets", "reject")
    eng2 = LiveV1Engine(ex2, LiveV1Settings(query_delay_s=0, income_interval_s=0))
    await eng2.initialize()
    assert eng2.brackets == []
    assert await eng2._enter(1, Decimal("3600"), BAR)    # config fallback 0.4% → 10x ok (6% ≤ 6.72%)
    assert eng2.pos["leverage"] == 10 and eng2.pos["mmr"] == 0.004


async def test_entry_lowers_leverage_or_skips():
    eng, _, fx = await _eng(FakeExchange(wallet="100000", spread="0"))
    assert await eng._enter(1, Decimal("9000"), BAR)     # 15% stop → 4x
    assert fx.leverage == 4 and eng.pos["leverage"] == 4
    assert fx.amt * fx.price <= Decimal("100000") * 4
    eng2, _, fx2 = await _eng(FakeExchange(wallet="100000"))
    assert not await eng2._enter(1, Decimal("43000"), BAR)   # ~72% stop → skip even at 1x
    assert fx2.amt == 0


# ── engine integration ──
async def test_api_error_streak_blocks_entries_and_recovers():
    eng, ex, fx = await _eng()
    ex.network_down = True
    for _ in range(5):
        await eng.reconcile_orders()
    assert S.API_ERRORS in eng.gate.reasons and not eng.entries_allowed()
    assert any("API 오류" in a for a in eng.alerts)
    ex.network_down = False
    for _ in range(2):
        await eng.reconcile_orders()
    assert S.API_ERRORS not in eng.gate.reasons and eng.entries_allowed()


async def test_heartbeat_watches_configured_symbol_and_notifies_resume(monkeypatch):
    sent = []
    eng, _, _ = await _eng(FakeExchange(rules=ETH_RULES, price="2500"), symbol="ETHUSDT")

    async def _send(text):
        sent.append(text)
    monkeypatch.setattr(eng.alert_sender, "send_text", _send)
    eng.hb.last_price = time.time() - 600
    await eng.check_heartbeat()
    assert S.HEARTBEAT in eng.gate.reasons and any("하트비트" in a for a in eng.alerts)
    await eng.on_price_update(Decimal("60000"))                 # BTC aggTrade feed: not our heartbeat
    await eng.on_mark_price("BTCUSDT", Decimal("60000"))       # other symbol's mark: ignored
    await eng.check_heartbeat()
    assert not eng.entries_allowed()
    await eng.on_mark_price("ETHUSDT", Decimal("2500"))
    await eng.check_heartbeat()
    assert eng.entries_allowed()
    assert sent == ["✅ 신규 진입 재개 — 가격 피드 해제"]       # one line, names the cleared block


async def test_sizing_uses_fresh_exchange_balance_and_risk():
    eng, _, fx = await _eng(FakeExchange(wallet="1000", spread="0"))
    eng.account.balance = Decimal("999999")              # stale local cache must be ignored
    fx.wallet = Decimal("2000")
    sd = Decimal("1200")
    assert await eng._enter(1, sd, BAR)
    assert fx.amt == Decimal("0.008")                    # 2000*0.5% / 1200 = 0.00833 → 0.008
    assert Decimal(eng.pos["risk_usdt"]) <= Decimal("10")


async def test_leverage_cap_10x():
    eng, _, fx = await _eng(FakeExchange(wallet="1000", spread="0"), max_risk_pct=2.0)
    assert await eng._enter(1, Decimal("10"), BAR)       # tiny stop → risk sizing would be 0.5 BTC
    assert fx.leverage == 10 and fx.amt * fx.price <= Decimal("10000")


async def test_no_averaging_or_second_position():
    eng, _, fx = await _eng()
    assert await eng._enter(1, Decimal("1800"), BAR)
    q = fx.amt
    fx.set_price(fx.price - 500)                         # position now losing
    assert not await eng._enter(1, Decimal("1800"), BAR + 1)
    assert not await eng._enter(-1, Decimal("1800"), BAR + 2)
    assert fx.amt == q


async def test_ledger_transfer_ok_but_unexplained_change_halts():
    eng, _, fx = await _eng()
    fx.transfer("500")                                   # deposit via income TRANSFER → consistent
    await eng.reconcile_orders(); await eng.reconcile_orders()
    assert eng.ledger_vs_exchange_balance_diff == 0.0 and eng.entries_allowed()
    fx.wallet -= Decimal("50")                           # unexplained balance change
    await eng.reconcile_orders(); await eng.reconcile_orders()
    assert S.LEDGER in eng.gate.reasons and eng.anomaly_detector.is_halted()
    assert eng.ledger_vs_exchange_balance_diff == -50.0


async def test_autohalt_on_drawdown():
    eng, _, fx = await _eng()
    fx.wallet -= Decimal("200")
    fx.incomes.append({"type": "REALIZED_PNL", "amount": Decimal("-200"), "time": fx._now(),
                       "symbol": "BTCUSDT", "tran_id": "x", "trade_id": "x"})
    await eng.reconcile_orders()
    assert eng.anomaly_detector.is_halted() and any("자동 중단" in a for a in eng.alerts)


async def test_autohalt_on_pf_after_30_trades():
    eng, _, _ = await _eng()
    now = int(time.time() * 1000)
    for i in range(30):
        eng.trade_history.append(TradeRecord(
            id=f"t{i}", symbol="BTCUSDT", side=PositionSide.LONG, leverage=5,
            avg_entry_price=Decimal(1), avg_exit_price=Decimal(1), quantity=Decimal(1),
            realized_pnl=Decimal(-10 if i < 20 else 10), pnl_percent=0, signal_type="turtle_v1",
            opened_at=now, closed_at=now + 1, duration_seconds=0))
    await eng._check_autohalt()
    assert eng.anomaly_detector.is_halted()


def _bars(closes, start=0, wicks=None):
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        w = wicks[i] if wicks else 5
        out.append({"open_time": start + i * 14_400_000, "open": o, "high": max(o, c) + w,
                    "low": min(o, c) - w, "close": c, "close_time": start + (i + 1) * 14_400_000 - 1})
    return out


async def test_bar_close_breakout_enters_with_research_stop():
    eng, _, fx = await _eng(FakeExchange(wallet="5000", spread="0"))
    closes = [60000 + (i % 7) * 10 for i in range(80)] + [60500]      # range then breakout up
    bars = _bars(closes)
    st = replay(bars, eng.v1.params)
    assert st.pend_entry == 1
    await eng.on_bar_close(bars, now=bars[-1]["close_time"] + 1000)
    assert fx.amt > 0 and fx.live_stop_for_position()
    expected_stop = Decimal(str(fx.entry)) - Decimal(str(st.pend_stop_dist))
    assert abs(Decimal(eng.pos["stop_px"]) - expected_stop) <= Decimal("0.1")


async def test_long_only_skips_shorts_and_late_bars():
    eng, _, fx = await _eng(direction="long_only")
    closes = [60000 + (i % 7) * 10 for i in range(80)] + [59500]      # breakout down
    bars = _bars(closes)
    await eng.on_bar_close(bars, now=bars[-1]["close_time"] + 1000)
    assert fx.amt == 0
    eng2, _, fx2 = await _eng(FakeExchange(wallet="5000"))
    up = _bars([60000 + (i % 7) * 10 for i in range(80)] + [60500])
    await eng2.on_bar_close(up, now=up[-1]["close_time"] + 3600_000)  # 1h late → skip entry
    assert fx2.amt == 0


async def test_signal_exit_closes_position():
    eng, _, fx = await _eng(FakeExchange(wallet="5000", spread="0"))
    closes = [60000 + (i % 7) * 10 for i in range(80)] + [60500]
    bars = _bars(closes)
    await eng.on_bar_close(bars, now=bars[-1]["close_time"] + 1000)
    assert fx.amt > 0
    more = _bars(closes + [60600, 60700, 59000])                       # close below 20-bar low
    await eng.on_bar_close(more, now=more[-1]["close_time"] + 1000)
    # the 59000 bar hits the (tight, ATR≈20) model stop intrabar while the fake price never moved,
    # so the exchange stop did not fire → engine syncs to the model (closes); 59000 also breaks
    # the 55-bar low → reverse short at next open, protected by a new exchange stop.
    st = replay(more, eng.v1.params)
    assert st.trades[-1].reason == "stop" and st.pend_entry == -1
    assert eng.trade_history[-1].close_reason == "model_sync" and eng.trade_history[-1].side == PositionSide.LONG
    assert fx.amt < 0 and fx.live_stop_for_position()


async def test_signal_exit_on_channel_break():
    eng, _, fx = await _eng(FakeExchange(wallet="5000", spread="0"))
    closes = [60000 + (i % 5) * 10 for i in range(80)] + [60700]       # tight closes, wide wicks
    wicks = [600] * 80 + [5]                                            # → ATR≈1200, 20-bar low≈59400
    bars = _bars(closes, wicks=wicks)
    await eng.on_bar_close(bars, now=bars[-1]["close_time"] + 1000)
    assert fx.amt > 0
    more = _bars(closes + [60000, 59380], wicks=wicks + [5, 5])         # close < 20-bar low, > stop
    st = replay(more, eng.v1.params)
    assert st.pend_exit, st.trades[-1:]                                 # (also a 55-bar low → reverse)
    await eng.on_bar_close(more, now=more[-1]["close_time"] + 1000)
    assert eng.trade_history[-1].close_reason == "signal_exit"
    assert fx.amt <= 0 and fx.live_stop_for_position()


async def test_legacy_signal_path_disabled():
    eng, _, fx = await _eng()
    assert await eng.on_signal({"direction": "bullish", "type": "confluence_x"}, Decimal("60000")) is None
    assert fx.amt == 0


async def test_status_compatible():
    eng, _, _ = await _eng()
    assert await eng._enter(1, Decimal("1800"), BAR)
    s = eng.get_status()
    assert s["open_positions_count"] == 1 and "v1" in s
    assert eng.get_open_positions()[0]["stop_loss_price"]


# ── exchange adapter error mapping ──
async def test_binance_adapter_error_mapping():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        path = req.url.path
        if path == "/fapi/v1/exchangeInfo":
            return httpx.Response(200, json=EXCHANGE_INFO)
        if path == "/fapi/v1/order" and req.method == "POST":
            return httpx.Response(503, text="busy")
        if path == "/fapi/v1/order" and req.method == "GET":
            return httpx.Response(400, json={"code": -2013, "msg": "Order does not exist."})
        if path == "/fapi/v1/algoOrder" and req.method == "POST":
            return httpx.Response(400, json={"code": -2021, "msg": "Order would immediately trigger."})
        if path == "/fapi/v2/positionRisk":
            return httpx.Response(400, json={"code": -1007, "msg": "Timeout waiting for response"})
        return httpx.Response(400, json={"code": -1102, "msg": "bad"})

    ex = BinanceExchange("https://testnet.binancefuture.com", "k", "s", transport=httpx.MockTransport(handler))
    with pytest.raises(ExchangeUnavailable):
        await ex.market("BUY", Decimal("0.0019"), "v1abc")
    assert await ex.get_order("v1abc") is None
    with pytest.raises(WouldTrigger):
        await ex.stop("SELL", Decimal("59999.99"), "v1abcs0")
    with pytest.raises(ExchangeUnavailable):
        await ex.position()
    with pytest.raises(OrderRejected):
        await ex.account()
    post = [c for c in calls if c.url.path == "/fapi/v1/order" and c.method == "POST"][0].url.params
    assert post["newClientOrderId"] == "v1abc" and post["quantity"] == "0.001" and "signature" in post
    algo = [c for c in calls if c.url.path == "/fapi/v1/algoOrder"][0].url.params
    assert algo["closePosition"] == "true" and algo["triggerPrice"] == "59999.9" and algo["clientAlgoId"] == "v1abcs0"
    await ex.close()


# ── exchangeInfo-driven symbol rules ──
def test_symbol_rules_from_exchange_info():
    btc = SymbolRules.from_exchange_info(EXCHANGE_INFO, "BTCUSDT")
    eth = SymbolRules.from_exchange_info(EXCHANGE_INFO, "ETHUSDT")
    assert (btc.tick_size, btc.step_size, btc.min_qty, btc.min_notional) == \
        (Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal("50"))
    assert (eth.tick_size, eth.min_notional) == (Decimal("0.01"), Decimal("20"))
    assert btc.floor_qty("0.0019") == Decimal("0.001") and btc.floor_qty("1.23456") == Decimal("1.234")
    assert btc.price("60000.07", "down") == Decimal("60000.0") and btc.price("60000.01", "up") == Decimal("60000.1")
    with pytest.raises(Exception):
        SymbolRules.from_exchange_info(EXCHANGE_INFO, "SOLUSDT")


async def test_adapter_reads_rules_once_and_formats_eth():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path == "/fapi/v1/exchangeInfo":
            return httpx.Response(200, json=EXCHANGE_INFO)
        if req.url.path == "/fapi/v1/order":
            return httpx.Response(200, json={"orderId": 1, "clientOrderId": "c", "status": "FILLED",
                                             "avgPrice": "2500.12", "executedQty": "0.123"})
        return httpx.Response(200, json={"algoId": 2, "clientAlgoId": "s", "orderType": "STOP_MARKET",
                                         "side": "SELL", "triggerPrice": "2400.01", "closePosition": True})

    ex = BinanceExchange("https://testnet.binancefuture.com", "k", "s", symbol="ETHUSDT",
                         transport=httpx.MockTransport(handler))
    o = await ex.market("BUY", Decimal("0.12345"), "c")
    s = await ex.stop("SELL", Decimal("2400.019"), "s")
    assert o["executed_qty"] == Decimal("0.123") and s["close_position"]
    assert calls.count("/fapi/v1/exchangeInfo") == 1
    await ex.close()


async def test_entry_skipped_below_min_notional():
    eng, _, fx = await _eng(FakeExchange(wallet="300", spread="0"))      # risk $1.5 / $1800 stop
    assert not await eng._enter(1, Decimal("1800"), BAR)                # 0.00083 → 0.000 < minQty
    assert fx.amt == 0 and not fx.orders
    eng2, _, fx2 = await _eng(FakeExchange(wallet="1000", price="40000", spread="0"))
    assert not await eng2._enter(1, Decimal("10000"), BAR)              # 0.0005 → 0 → skip
    assert fx2.amt == 0


async def test_entry_skipped_when_risk_after_rounding_exceeds_max():
    eng, _, fx = await _eng(FakeExchange(wallet="1000", spread="0"), max_risk_pct=0.3)
    # tiny stop → leverage-capped notional ≈ $5000 → round-trip fees alone ≈ 0.5% of wallet
    assert not await eng._enter(1, Decimal("5"), BAR)
    assert fx.amt == 0
    assert eng.skip_counts(__import__("app.trading.tg_format", fromlist=["x"]).kst_date()) == {"risk_cap": 1}
    eng2, _, fx2 = await _eng(FakeExchange(wallet="1000", spread="0"))  # default max 1.0%
    assert await eng2._enter(1, Decimal("1800"), BAR)                   # normal stop → allowed


async def test_eth_symbol_configurable():
    fx = FakeExchange(wallet="1000", price="2500", spread="0", rules=ETH_RULES)
    eng, _, _ = await _eng(fx, symbol="ETHUSDT")
    assert eng.rules.symbol == "ETHUSDT" and eng.rules.min_notional == Decimal("20")
    assert await eng._enter(1, Decimal("75.003"), BAR)                  # risk $5 / $75 = 0.0666 ETH
    assert fx.amt == Decimal("0.066")
    assert eng.pos["stop_px"] == "2425.00"                              # 2500 − 75.003 → tick UP (toward entry)
    assert fx.live_stop_for_position()
    assert await eng._exit("signal_exit")
    assert eng.trade_history[-1].symbol == "ETHUSDT"


async def test_rules_cached_and_refreshed_daily():
    eng, ex, _ = await _eng()
    n = ex.calls["symbol_rules"]
    await eng._enter(1, Decimal("1800"), BAR)
    assert ex.calls["symbol_rules"] == n                                # cached
    eng._rules_at -= 86401
    await eng.reconcile_orders()
    assert ex.calls["symbol_rules"] == n + 1                            # refreshed after a day


async def test_adapter_leverage_brackets_signed_and_mark_price():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.url.path == "/fapi/v1/leverageBracket":
            return httpx.Response(200, json=[{"symbol": "ETHUSDT", "brackets": [
                {"bracket": 1, "initialLeverage": 125, "notionalCap": 10000, "notionalFloor": 0,
                 "maintMarginRatio": 0.005, "cum": 0},
                {"bracket": 2, "initialLeverage": 100, "notionalCap": 100000, "notionalFloor": 10000,
                 "maintMarginRatio": 0.0065, "cum": 15}]}])
        if req.url.path == "/fapi/v1/premiumIndex":
            return httpx.Response(200, json={"symbol": "ETHUSDT", "markPrice": "2501.25"})
        return httpx.Response(404, json={"code": -1, "msg": "?"})

    ex = BinanceExchange("https://testnet.binancefuture.com", "k", "s", symbol="ETHUSDT",
                         transport=httpx.MockTransport(handler))
    br = await ex.leverage_brackets()
    assert br == [{"floor": 0.0, "cap": 10000.0, "mmr": 0.005, "max_lev": 125},
                  {"floor": 10000.0, "cap": 100000.0, "mmr": 0.0065, "max_lev": 100}]
    q = seen[0].url.params
    assert q["symbol"] == "ETHUSDT" and "signature" in q and seen[0].headers["X-MBX-APIKEY"] == "k"
    assert await ex.mark_price() == Decimal("2501.25")
