"""S1 — SL -4509(포지션 없음) 오판 HALT 수정 테스트.

(a) -4509 → HALT 스킵: AlgoNoOpenPosition raise → return, no halt.
(b) 진짜 무방비 → HALT 유지(회귀): generic Exception 3x + positionAmt 있음 → HALT.
(c) client 단위: -4509 body → place_algo_order raises AlgoNoOpenPosition.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.trading.engine  # noqa: F401 — 순환 import 회피
from app.binance.client import AlgoNoOpenPosition, BinanceClient
from app.trading import live_engine as le_mod
from app.trading.live_engine import LiveTradingEngine
from app.trading.schemas import OrderStatus, Position, PositionSide, TrancheOrder


def _pos(*, filled=True, sl_algo_id="OLD") -> Position:
    entry = TrancheOrder(
        id="e1", position_id="p1", side=PositionSide.LONG, is_entry=True,
        target_price=Decimal("80000"), quantity=Decimal("0.01"),
        status=OrderStatus.FILLED if filled else OrderStatus.WAITING,
        filled_price=Decimal("80000") if filled else None, created_at=0,
    )
    return Position(
        id="p1", side=PositionSide.LONG, leverage=5, signal_type="t",
        signal_strength=0.6, signal_details={"sl_algo_id": sl_algo_id},
        entry_tranches=[entry], exit_tranches=[], stop_loss_price=Decimal("79680"),
        avg_entry_price=Decimal("80000"), total_quantity=Decimal("0.01"),
        allocated_margin=Decimal("160"), opened_at=0,
    )


@pytest.fixture
def eng(monkeypatch):
    e = LiveTradingEngine()
    e.open_positions.clear()
    e.trade_history.clear()
    e._last_price = Decimal("80000")
    monkeypatch.setattr(le_mod.asyncio, "sleep", AsyncMock())
    # 텔레그램 무력화
    monkeypatch.setattr(e.alert_sender, "_send_telegram_text", AsyncMock())
    return e


# ── (a) -4509 → HALT 스킵 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_4509_no_halt(eng, monkeypatch):
    """-4509 AlgoNoOpenPosition → 즉시 return, HALT 없음."""
    place_mock = AsyncMock(side_effect=AlgoNoOpenPosition("-4509"))
    monkeypatch.setattr(le_mod.binance_client, "place_algo_order", place_mock)
    monkeypatch.setattr(le_mod.binance_client, "get_position_risk",
                        AsyncMock(return_value={"positionAmt": "0"}))

    pos = _pos()
    eng.open_positions[pos.id] = pos
    await eng._place_sl_order(pos)

    assert eng.anomaly_detector.is_halted() is False
    assert eng.anomaly_detector._manual_halt is False


@pytest.mark.asyncio
async def test_4509_no_emergency_close(eng, monkeypatch):
    """-4509 → emergency_close 호출 없음."""
    monkeypatch.setattr(le_mod.binance_client, "place_algo_order",
                        AsyncMock(side_effect=AlgoNoOpenPosition("-4509")))
    monkeypatch.setattr(le_mod.binance_client, "get_position_risk",
                        AsyncMock(return_value={"positionAmt": "0"}))
    emergency_mock = AsyncMock()
    monkeypatch.setattr(eng, "_emergency_close", emergency_mock)

    pos = _pos()
    eng.open_positions[pos.id] = pos
    await eng._place_sl_order(pos)

    assert emergency_mock.await_count == 0


# ── (b) 진짜 무방비 → HALT 유지(회귀) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_real_unprotected_still_halts(eng, monkeypatch):
    """generic Exception 3x + positionAmt 존재 + read-back 0 → HALT."""
    place_mock = AsyncMock(side_effect=Exception("network err"))
    monkeypatch.setattr(le_mod.binance_client, "place_algo_order", place_mock)
    monkeypatch.setattr(le_mod.binance_client, "get_position_risk",
                        AsyncMock(return_value={"positionAmt": "0.005"}))
    monkeypatch.setattr(le_mod.binance_client, "get_open_algo_orders",
                        AsyncMock(return_value=[]))  # read-back 0

    emergency_mock = AsyncMock()
    monkeypatch.setattr(eng, "_emergency_close", emergency_mock)

    pos = _pos()
    eng.open_positions[pos.id] = pos
    await eng._place_sl_order(pos)

    assert place_mock.await_count == 3
    assert eng.anomaly_detector._manual_halt is True
    assert emergency_mock.await_count >= 1


@pytest.mark.asyncio
async def test_fallback_guard_skips_halt_when_no_position(eng, monkeypatch):
    """fallback: generic Exception 3x 후 get_position_risk → positionAmt 0 → HALT 스킵."""
    place_mock = AsyncMock(side_effect=Exception("network err"))
    monkeypatch.setattr(le_mod.binance_client, "place_algo_order", place_mock)
    monkeypatch.setattr(le_mod.binance_client, "get_position_risk",
                        AsyncMock(return_value={"positionAmt": "0"}))
    monkeypatch.setattr(le_mod.binance_client, "get_open_algo_orders",
                        AsyncMock(return_value=[]))

    emergency_mock = AsyncMock()
    monkeypatch.setattr(eng, "_emergency_close", emergency_mock)

    pos = _pos()
    eng.open_positions[pos.id] = pos
    await eng._place_sl_order(pos)

    assert eng.anomaly_detector._manual_halt is False
    assert emergency_mock.await_count == 0


# ── (c) client 단위 — -4509 body → AlgoNoOpenPosition ─────────────────────

@pytest.mark.asyncio
async def test_client_4509_raises_algo_no_open_position():
    """-4509 code body → place_algo_order raises AlgoNoOpenPosition."""
    client = BinanceClient()

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "code": -4509,
        "msg": "Time in Force GTE can only be used with open positions",
    }
    http_err = httpx.HTTPStatusError(
        "400 Bad Request",
        request=MagicMock(),
        response=fake_response,
    )

    with patch.object(client, "_retry_request", AsyncMock(side_effect=http_err)):
        with pytest.raises(AlgoNoOpenPosition):
            await client.place_algo_order(
                symbol="BTCUSDT",
                side="SELL",
                order_type="STOP_MARKET",
                trigger_price=Decimal("79680"),
                close_position=True,
            )


@pytest.mark.asyncio
async def test_client_4509_msg_fallback_raises():
    """msg 에 'can only be used with open positions' 포함 시 AlgoNoOpenPosition."""
    client = BinanceClient()

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "code": 400,
        "msg": "Time in Force GTE can only be used with open positions here",
    }
    http_err = httpx.HTTPStatusError(
        "400", request=MagicMock(), response=fake_response,
    )

    with patch.object(client, "_retry_request", AsyncMock(side_effect=http_err)):
        with pytest.raises(AlgoNoOpenPosition):
            await client.place_algo_order(
                symbol="BTCUSDT", side="SELL", order_type="STOP_MARKET",
                trigger_price=Decimal("79680"), close_position=True,
            )
