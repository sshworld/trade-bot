"""S1 — SL 배치 신뢰성 테스트.

place-before-cancel / 재시도 / 실패시 emergency_close+halt / -2021 / remaining<=0 유지 / assert_sl_armed.
네트워크 호출 없음 (binance_client monkeypatch).
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

import app.trading.engine  # noqa: F401  — engine 먼저 로드해 순환 import 회피
from app.binance.client import AlgoWouldImmediatelyTrigger
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
        entry_tranches=[entry], exit_tranches=[], stop_loss_price=Decimal("79000"),
        avg_entry_price=Decimal("80000"), total_quantity=Decimal("0.01"),
        allocated_margin=Decimal("160"), opened_at=0,
    )


@pytest.fixture
def eng(monkeypatch):
    e = LiveTradingEngine()
    e.open_positions.clear()
    e.trade_history.clear()
    e._last_price = Decimal("80000")
    # asyncio.sleep no-op (백오프 대기 제거)
    monkeypatch.setattr(le_mod.asyncio, "sleep", AsyncMock())
    return e


@pytest.mark.asyncio
async def test_place_sl_before_cancel(eng, monkeypatch):
    calls = []
    async def place(**kw):
        calls.append("place")
        return {"algoId": "NEW"}
    async def cancel(symbol, algo_id):
        calls.append(("cancel", algo_id))
        return {}
    monkeypatch.setattr(le_mod.binance_client, "place_algo_order", place)
    monkeypatch.setattr(le_mod.binance_client, "cancel_algo_order", cancel)

    pos = _pos(sl_algo_id="OLD")
    await eng._place_sl_order(pos)

    assert pos.signal_details["sl_algo_id"] == "NEW"
    # place 가 cancel 보다 먼저 (place-before-cancel)
    assert calls[0] == "place"
    assert ("cancel", "OLD") in calls


@pytest.mark.asyncio
async def test_sl_place_retry_then_emergency(eng, monkeypatch):
    place_mock = AsyncMock(return_value={})  # algoId 없음 → 매번 실패
    monkeypatch.setattr(le_mod.binance_client, "place_algo_order", place_mock)
    monkeypatch.setattr(le_mod.binance_client, "cancel_algo_order", AsyncMock(return_value={}))
    monkeypatch.setattr(le_mod.binance_client, "get_position_risk",
                        AsyncMock(return_value={"positionAmt": "0.01"}))
    market_mock = AsyncMock(return_value={"avgPrice": "79500"})
    monkeypatch.setattr(le_mod.binance_client, "place_order", market_mock)
    monkeypatch.setattr(eng, "_nuke_all_binance_orders", AsyncMock())

    pos = _pos()
    eng.open_positions[pos.id] = pos
    await eng._place_sl_order(pos)

    assert place_mock.await_count == 3            # 3회 재시도
    assert market_mock.await_count >= 1           # emergency 시장가 청산
    assert eng.anomaly_detector._manual_halt is True


@pytest.mark.asyncio
async def test_sl_would_immediately_trigger(eng, monkeypatch):
    place_mock = AsyncMock(side_effect=AlgoWouldImmediatelyTrigger("-2021"))
    monkeypatch.setattr(le_mod.binance_client, "place_algo_order", place_mock)
    monkeypatch.setattr(le_mod.binance_client, "get_position_risk",
                        AsyncMock(return_value={"positionAmt": "0.01"}))
    market_mock = AsyncMock(return_value={"avgPrice": "79000"})
    monkeypatch.setattr(le_mod.binance_client, "place_order", market_mock)
    monkeypatch.setattr(eng, "_nuke_all_binance_orders", AsyncMock())

    pos = _pos()
    eng.open_positions[pos.id] = pos
    await eng._place_sl_order(pos)

    assert place_mock.await_count == 1            # 재시도 없이 즉시 청산
    assert market_mock.await_count >= 1


@pytest.mark.asyncio
async def test_remaining_zero_keeps_existing_sl(eng, monkeypatch):
    place_mock = AsyncMock(return_value={"algoId": "NEW"})
    cancel_mock = AsyncMock(return_value={})
    monkeypatch.setattr(le_mod.binance_client, "place_algo_order", place_mock)
    monkeypatch.setattr(le_mod.binance_client, "cancel_algo_order", cancel_mock)

    pos = _pos(filled=False)  # FILLED entry 없음 → remaining 0
    await eng._place_sl_order(pos)

    assert place_mock.await_count == 0            # 배치 안 함
    assert cancel_mock.await_count == 0           # 기존 SL 취소도 안 함
    assert pos.signal_details["sl_algo_id"] == "OLD"  # 그대로 유지


@pytest.mark.asyncio
async def test_assert_sl_armed_rearm(eng, monkeypatch):
    monkeypatch.setattr(le_mod.binance_client, "get_position_risk",
                        AsyncMock(return_value={"positionAmt": "0.01"}))
    monkeypatch.setattr(le_mod.binance_client, "get_algo_order",
                        AsyncMock(return_value=None))  # algo 부재
    rearm = AsyncMock()
    monkeypatch.setattr(eng, "_place_sl_order", rearm)

    pos = _pos()
    await eng._assert_sl_armed(pos)
    assert rearm.await_count == 1                 # 재무장 호출
