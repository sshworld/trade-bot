"""S2 — 손절 직후 같은 방향 재진입 차단 (reentry cooldown) 테스트.

1. 쿨다운 이내 같은 방향 SL 직후 → 차단(return None, 포지션 미생성).
2. 쿨다운 경과 후 → 가드 통과(_get_real_balance 호출됨).
3. 반대 방향 → 가드 통과.
4. 직전 청산이 take_profit → 차단 안 함.
"""

import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

import app.trading.engine  # noqa: F401 — 순환 import 회피
from app.trading import live_engine as le_mod
from app.trading.live_engine import LiveTradingEngine
from app.trading.schemas import PositionSide, TradeRecord


def _sl_record(*, side: PositionSide, closed_at: int, close_reason: str = "stop_loss") -> TradeRecord:
    return TradeRecord(
        id="t1",
        symbol="BTCUSDT",
        side=side,
        leverage=5,
        avg_entry_price=Decimal("80000"),
        avg_exit_price=Decimal("79680"),
        quantity=Decimal("0.01"),
        realized_pnl=Decimal("-3.2"),
        pnl_percent=-2.0,
        signal_type="bearish_1h",
        close_reason=close_reason,
        opened_at=closed_at - 10_000,
        closed_at=closed_at,
        duration_seconds=10,
    )


@pytest.fixture
def eng(monkeypatch):
    e = LiveTradingEngine()
    e._initialized = True
    e.open_positions.clear()
    e.trade_history.clear()
    e._last_price = Decimal("80000")
    monkeypatch.setattr(e.alert_sender, "_send_telegram_text", AsyncMock())
    return e


def _bearish_signal():
    return {
        "type": "bearish_1h",
        "direction": "bearish",
        "timeframe": "1h",
        "strength": 1.0,
        "details": {},
    }


def _bullish_signal():
    return {
        "type": "bullish_1h",
        "direction": "bullish",
        "timeframe": "1h",
        "strength": 1.0,
        "details": {},
    }


# ── 1. 쿨다운 이내 같은 방향 SL → 차단 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_reentry_blocked_within_cooldown(eng, monkeypatch):
    """SL 후 쿨다운(5분) 이내 같은 방향 시그널 → return None, 포지션 미생성."""
    now = int(time.time() * 1000)
    eng.trade_history.append(_sl_record(side=PositionSide.SHORT, closed_at=now - 1_000))

    # _get_real_balance 가 호출되면 가드 통과 의미이므로, 호출 여부를 감시
    balance_mock = AsyncMock(return_value=Decimal("200"))
    monkeypatch.setattr(eng, "_get_real_balance", balance_mock)

    result = await eng.on_signal(_bearish_signal(), Decimal("80000"))

    assert result is None
    assert len(eng.open_positions) == 0
    # 가드가 차단했으므로 _get_real_balance 에 도달하지 않아야 함
    assert balance_mock.await_count == 0


# ── 2. 쿨다운 경과 후 → 가드 통과 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reentry_allowed_after_cooldown(eng, monkeypatch):
    """SL 후 쿨다운(5분) 경과 → 가드 통과(_get_real_balance 도달)."""
    now = int(time.time() * 1000)
    eng.trade_history.append(_sl_record(side=PositionSide.SHORT, closed_at=now - 400_000))

    # 가드 이후 단계에서 중단: _get_real_balance 에서 예외 → 가드 통과 확인
    balance_mock = AsyncMock(side_effect=RuntimeError("stop-here"))
    monkeypatch.setattr(eng, "_get_real_balance", balance_mock)

    with pytest.raises(RuntimeError, match="stop-here"):
        await eng.on_signal(_bearish_signal(), Decimal("80000"))

    assert balance_mock.await_count >= 1


# ── 3. 반대 방향 → 가드 통과 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reentry_opposite_direction_not_blocked(eng, monkeypatch):
    """직전 SL이 SHORT인데 새 시그널이 bullish(LONG) → 가드 통과."""
    now = int(time.time() * 1000)
    eng.trade_history.append(_sl_record(side=PositionSide.SHORT, closed_at=now - 1_000))

    balance_mock = AsyncMock(side_effect=RuntimeError("stop-here"))
    monkeypatch.setattr(eng, "_get_real_balance", balance_mock)

    with pytest.raises(RuntimeError, match="stop-here"):
        await eng.on_signal(_bullish_signal(), Decimal("80000"))

    assert balance_mock.await_count >= 1


# ── 4. 직전 청산 take_profit → 차단 안 함 ────────────────────────────────────

@pytest.mark.asyncio
async def test_reentry_not_blocked_after_tp(eng, monkeypatch):
    """직전 청산이 take_profit → 쿨다운 이내라도 차단 안 함."""
    now = int(time.time() * 1000)
    eng.trade_history.append(
        _sl_record(side=PositionSide.SHORT, closed_at=now - 1_000, close_reason="take_profit")
    )

    balance_mock = AsyncMock(side_effect=RuntimeError("stop-here"))
    monkeypatch.setattr(eng, "_get_real_balance", balance_mock)

    with pytest.raises(RuntimeError, match="stop-here"):
        await eng.on_signal(_bearish_signal(), Decimal("80000"))

    assert balance_mock.await_count >= 1
