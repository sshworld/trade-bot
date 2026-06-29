"""S1 — 시장가 청산 PnL=0 회계 버그 수정 테스트.

버그: 시장가 청산(SL/시간/교체/emergency) 시 exit tranche가 (live close 직전)
CANCELLED 로 미리 바뀌어 `remaining_qty=0` → 청산 PnL 계산 블록이 skip → realized_pnl=0.

수정: 청산 PnL 을 tranche 상태가 아니라 **실제 열려있던 수량**
(total_quantity − filled_exit_qty) 기준으로 계산한다.
"""

from decimal import Decimal

import pytest

from app.trading.engine import PaperTradingEngine
from app.trading.schemas import OrderStatus, Position, PositionSide, TrancheOrder


@pytest.fixture()
def engine():
    """DB 는 conftest autouse 로 per-test 임시 파일 격리됨."""
    return PaperTradingEngine()


def _entry(avg_entry: str, qty: str, side: PositionSide) -> TrancheOrder:
    return TrancheOrder(
        id="e1", position_id="p1", side=side, is_entry=True,
        target_price=Decimal(avg_entry), quantity=Decimal(qty),
        status=OrderStatus.FILLED, filled_price=Decimal(avg_entry), created_at=0,
    )


def _exit(qty: str, side: PositionSide, status: OrderStatus,
          filled_price: str | None = None) -> TrancheOrder:
    return TrancheOrder(
        id="x1", position_id="p1", side=side, is_entry=False,
        target_price=Decimal(filled_price or "0"), quantity=Decimal(qty),
        status=status,
        filled_price=Decimal(filled_price) if filled_price else Decimal("0"),
        created_at=0,
    )


def _make_pos(engine, *, side, avg_entry, total_qty, exit_tranches,
              realized_pnl="0", margin="100") -> str:
    pos = Position(
        id="p1", side=side, leverage=5, signal_type="t",
        signal_strength=0.6, signal_details={},
        entry_tranches=[_entry(avg_entry, total_qty, side)],
        exit_tranches=exit_tranches,
        stop_loss_price=Decimal("0"),
        avg_entry_price=Decimal(avg_entry),
        total_quantity=Decimal(total_qty),
        allocated_margin=Decimal(margin),
        realized_pnl=Decimal(realized_pnl),
        status="open", opened_at=0,
    )
    engine.open_positions[pos.id] = pos
    return pos.id


def test_market_close_with_cancelled_exits_records_pnl(engine):
    """Red 핵심: exit tranche 가 CANCELLED(live close 직전 상태) 여도
    실제 열려있던 수량 기준 청산 PnL 이 기록돼야 한다."""
    pos_id = _make_pos(
        engine, side=PositionSide.SHORT, avg_entry="59500", total_qty="0.005",
        exit_tranches=[_exit("0.005", PositionSide.SHORT, OrderStatus.CANCELLED)],
    )
    trade = engine._close_position(pos_id, Decimal("59750"), "stop_loss")
    # SHORT: (59500 - 59750) * 0.005 = -1.25
    assert trade.realized_pnl == Decimal("-1.25")


def test_partial_tp_then_close_no_double_count(engine):
    """부분 TP 후 청산: 이미 적립된 FILLED exit PnL 은 중복 가산 안 하고,
    잔여 오픈 수량(total - filled)만 계산한다."""
    # FILLED exit 0.002 의 PnL 은 reconcile 에서 이미 pos.realized_pnl 에 적립됨.
    # SHORT (59500-59600)*0.002 = -0.20 이라고 가정.
    pos_id = _make_pos(
        engine, side=PositionSide.SHORT, avg_entry="59500", total_qty="0.005",
        realized_pnl="-0.20",
        exit_tranches=[
            _exit("0.002", PositionSide.SHORT, OrderStatus.FILLED, filled_price="59600"),
            _exit("0.003", PositionSide.SHORT, OrderStatus.CANCELLED),
        ],
    )
    trade = engine._close_position(pos_id, Decimal("59750"), "stop_loss")
    # 잔여 오픈 0.003: (59500-59750)*0.003 = -0.75 → 누적 -0.20 + -0.75 = -0.95
    assert trade.realized_pnl == Decimal("-0.95")


def test_paper_path_waiting_exit_regression(engine):
    """회귀: 정상 Paper 경로(exit tranche WAITING 유지)에서 청산 PnL 불변.
    새 공식(total - filled)도 WAITING 전량과 같은 값."""
    pos_id = _make_pos(
        engine, side=PositionSide.SHORT, avg_entry="59500", total_qty="0.005",
        exit_tranches=[_exit("0.005", PositionSide.SHORT, OrderStatus.WAITING)],
    )
    trade = engine._close_position(pos_id, Decimal("59750"), "stop_loss")
    assert trade.realized_pnl == Decimal("-1.25")
