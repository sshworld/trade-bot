"""S1 — SL 청산 사유 분류 버그 수정 테스트.

TP tranche가 FILLED 여도 SL<평단(LONG) 이면 "stop_loss" 를 반환해야 한다.
"""

from decimal import Decimal

import pytest

import app.trading.engine  # noqa: F401  — engine 먼저 로드해 순환 import 회피
from app.trading.live_engine import LiveTradingEngine
from app.trading.schemas import OrderStatus, Position, PositionSide, TrancheOrder


def _make_pos(
    *,
    side: PositionSide,
    avg_entry: str,
    sl_price: str,
    filled_tp_count: int = 0,
) -> Position:
    entry = TrancheOrder(
        id="e1", position_id="p1", side=side, is_entry=True,
        target_price=Decimal(avg_entry), quantity=Decimal("0.01"),
        status=OrderStatus.FILLED,
        filled_price=Decimal(avg_entry), created_at=0,
    )
    exit_tranches = []
    for i in range(filled_tp_count):
        t = TrancheOrder(
            id=f"tp{i}", position_id="p1", side=side, is_entry=False,
            target_price=Decimal(avg_entry), quantity=Decimal("0.001"),
            status=OrderStatus.FILLED,
            filled_price=Decimal(avg_entry), created_at=0,
        )
        exit_tranches.append(t)

    return Position(
        id="p1", side=side, leverage=5, signal_type="t",
        signal_strength=0.6, signal_details={},
        entry_tranches=[entry], exit_tranches=exit_tranches,
        stop_loss_price=Decimal(sl_price),
        avg_entry_price=Decimal(avg_entry),
        total_quantity=Decimal("0.01"),
        allocated_margin=Decimal("100"),
        status="open",
        opened_at=0,
    )


@pytest.fixture()
def engine(tmp_path):
    import app.trading.live_engine as le_mod
    from unittest.mock import MagicMock, AsyncMock

    eng = LiveTradingEngine.__new__(LiveTradingEngine)
    eng.settings = MagicMock()
    eng.settings.leverage = 5
    return eng


# ── LONG ──────────────────────────────────────────────────────────────────────

def test_long_sl_below_avg_is_stop_loss(engine):
    """핵심 회귀: TP tranche 1개 FILLED + SL < 평단(LONG) → stop_loss."""
    pos = _make_pos(side=PositionSide.LONG, avg_entry="80000", sl_price="79000", filled_tp_count=1)
    assert engine._sl_exit_reason(pos) == "stop_loss"


def test_long_sl_above_avg_is_take_profit(engine):
    """SL > 평단(LONG, 이익 트레일 상황) → take_profit."""
    pos = _make_pos(side=PositionSide.LONG, avg_entry="80000", sl_price="81000")
    assert engine._sl_exit_reason(pos) == "take_profit"


def test_long_sl_equal_avg_is_breakeven(engine):
    """SL == 평단(LONG) → breakeven."""
    pos = _make_pos(side=PositionSide.LONG, avg_entry="80000", sl_price="80000")
    assert engine._sl_exit_reason(pos) == "breakeven"


# ── SHORT ─────────────────────────────────────────────────────────────────────

def test_short_sl_above_avg_is_stop_loss(engine):
    """SHORT: SL > 평단 → stop_loss."""
    pos = _make_pos(side=PositionSide.SHORT, avg_entry="80000", sl_price="81000")
    assert engine._sl_exit_reason(pos) == "stop_loss"


def test_short_sl_below_avg_is_take_profit(engine):
    """SHORT: SL < 평단 → take_profit."""
    pos = _make_pos(side=PositionSide.SHORT, avg_entry="80000", sl_price="79000")
    assert engine._sl_exit_reason(pos) == "take_profit"


# ── avg_entry_price=None guard ────────────────────────────────────────────────

def test_no_avg_entry_defaults_to_stop_loss(engine):
    """avg_entry_price 없으면 stop_loss 반환."""
    pos = _make_pos(side=PositionSide.LONG, avg_entry="80000", sl_price="79000")
    pos.avg_entry_price = None
    assert engine._sl_exit_reason(pos) == "stop_loss"
