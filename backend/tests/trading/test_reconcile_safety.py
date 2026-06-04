"""S5 — 안정성 보너스 테스트.

_initialized 가드, reconcile per-tranche 예외 격리(position-gone 블록 실행), heartbeat 경고.
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

import app.trading.engine  # noqa: F401
from app.trading import live_engine as le_mod
from app.trading.anomaly_detector import AnomalyAction, AnomalyConfig, AnomalyDetector
from app.trading.live_engine import LiveTradingEngine
from app.trading.schemas import OrderStatus, Position, PositionSide, TrancheOrder


def _pos():
    e = TrancheOrder(id="e1", position_id="p1", side=PositionSide.LONG, is_entry=True,
                     target_price=Decimal("80000"), quantity=Decimal("0.01"),
                     filled_price=Decimal("80000"), status=OrderStatus.FILLED, created_at=0)
    return Position(id="p1", side=PositionSide.LONG, leverage=5, signal_type="t",
                    signal_strength=0.6, signal_details={"sl_algo_id": "S1"},
                    entry_tranches=[e], exit_tranches=[], stop_loss_price=Decimal("79000"),
                    avg_entry_price=Decimal("80000"), total_quantity=Decimal("0.01"),
                    allocated_margin=Decimal("160"), opened_at=0)


@pytest.fixture
def eng(monkeypatch):
    e = LiveTradingEngine()
    e.open_positions.clear()
    monkeypatch.setattr(le_mod.asyncio, "sleep", AsyncMock())
    return e


@pytest.mark.asyncio
async def test_reconcile_guarded_by_initialized(eng, monkeypatch):
    eng._initialized = False
    pos = _pos()
    eng.open_positions[pos.id] = pos
    spy = AsyncMock()
    monkeypatch.setattr(le_mod.binance_client, "get_position_risk", spy)
    await eng.reconcile_orders()
    assert spy.await_count == 0   # 초기화 전엔 아무 것도 안 함


@pytest.mark.asyncio
async def test_on_price_update_guarded(eng):
    eng._initialized = False
    pos = _pos()
    eng.open_positions[pos.id] = pos
    events = await eng.on_price_update(Decimal("80000"))
    assert events == []           # 초기화 전 tick 무시


@pytest.mark.asyncio
async def test_position_gone_runs_despite_tranche_error(eng, monkeypatch):
    """per-tranche 처리가 예외나도 position-gone 블록은 실행돼야 함 (phantom 방지)."""
    eng._initialized = True
    # WAITING entry tranche 가 있어 reconcile 가 get_order 를 호출 → 예외 유발
    e = TrancheOrder(id="e1", position_id="p1", side=PositionSide.LONG, is_entry=True,
                     target_price=Decimal("80000"), quantity=Decimal("0.01"),
                     status=OrderStatus.WAITING, client_order_id="c1", created_at=0)
    pos = Position(id="p1", side=PositionSide.LONG, leverage=5, signal_type="t",
                   signal_strength=0.6, signal_details={"sl_algo_id": "S1"},
                   entry_tranches=[e], exit_tranches=[], stop_loss_price=Decimal("79000"),
                   avg_entry_price=Decimal("80000"), total_quantity=Decimal("0.01"),
                   allocated_margin=Decimal("160"), opened_at=0)
    eng.open_positions[pos.id] = pos
    eng.account.balance = Decimal("200")
    eng.account.daily_start_balance = Decimal("200")
    eng._last_price = Decimal("79000")

    monkeypatch.setattr(eng, "_assert_sl_armed", AsyncMock())
    # get_order 예외 → per-tranche try 가 잡아야 함
    monkeypatch.setattr(le_mod.binance_client, "get_order",
                        AsyncMock(side_effect=RuntimeError("boom")))
    # position-gone: positionAmt 0 → 청산 경로
    pos_gone = AsyncMock(return_value=None)
    monkeypatch.setattr(le_mod.binance_client, "get_position_risk", pos_gone)
    monkeypatch.setattr(le_mod.binance_client, "get_balance", AsyncMock(return_value=Decimal("195")))
    monkeypatch.setattr(eng, "_nuke_all_binance_orders", AsyncMock())
    monkeypatch.setattr(eng.alert_sender, "_send_telegram_text", AsyncMock())
    monkeypatch.setattr(le_mod.binance_client, "get_open_algo_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(le_mod.binance_client, "get_open_orders", AsyncMock(return_value=[]))

    await eng.reconcile_orders()
    # position-gone 블록이 실행되어 포지션이 청산됨 (phantom 방지)
    assert pos.id not in eng.open_positions


def test_heartbeat_warns_on_stale_price():
    ad = AnomalyDetector(AnomalyConfig())
    ad._last_price_update_ms = 0  # 아주 오래됨 → stale
    alert = ad.check_heartbeat()
    assert alert is not None
    assert alert.action_taken == AnomalyAction.ALERT   # 경고만(중단 아님)
    assert alert.severity == "WARNING"


def test_heartbeat_silent_when_fresh():
    import time
    ad = AnomalyDetector(AnomalyConfig())
    ad._last_price_update_ms = int(time.time() * 1000)  # 방금 갱신
    assert ad.check_heartbeat() is None
