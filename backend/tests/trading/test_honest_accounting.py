"""S1 — 수익 정직화 + phantom 재발 방지 테스트.

- _close_position(price=0) 시 total_realized_pnl 조작 안 됨 (LONG/SHORT)
- get_status()에 real_profit 키 존재, total_fees 키 부재
"""

from decimal import Decimal

import pytest

import app.trading.engine  # noqa: F401
from app.trading.engine import PaperTradingEngine
from app.trading.live_engine import LiveTradingEngine
from app.trading.schemas import OrderStatus, Position, PositionSide, TrancheOrder


def _make_pos(side: PositionSide, entry_price: Decimal = Decimal("80000")) -> Position:
    entry = TrancheOrder(
        id="e1", position_id="p1", side=side, is_entry=True,
        target_price=entry_price, quantity=Decimal("0.01"),
        filled_price=entry_price, status=OrderStatus.FILLED, created_at=0,
    )
    tp = TrancheOrder(
        id="x1", position_id="p1", side=side, is_entry=False,
        target_price=entry_price + Decimal("400"), quantity=Decimal("0.01"),
        status=OrderStatus.WAITING, created_at=0,
    )
    return Position(
        id="p1", side=side, leverage=5, signal_type="t",
        signal_strength=0.6, entry_tranches=[entry], exit_tranches=[tp],
        stop_loss_price=entry_price - Decimal("1000"),
        avg_entry_price=entry_price, total_quantity=Decimal("0.01"),
        allocated_margin=Decimal("160"), opened_at=0,
    )


def test_zero_price_long_does_not_accumulate_total_realized_pnl():
    """LONG: price=0 청산 시 total_realized_pnl 변하지 않아야 함."""
    eng = LiveTradingEngine()
    eng.open_positions.clear()
    eng.trade_history.clear()
    pos = _make_pos(PositionSide.LONG)
    eng.open_positions[pos.id] = pos
    before = eng.account.total_realized_pnl

    trade = eng._close_position(pos.id, Decimal("0"), "emergency")

    assert eng.account.total_realized_pnl == before
    assert trade.realized_pnl == Decimal("0")


def test_zero_price_short_does_not_accumulate_total_realized_pnl():
    """SHORT: price=0 청산 시 total_realized_pnl 변하지 않아야 함."""
    eng = LiveTradingEngine()
    eng.open_positions.clear()
    eng.trade_history.clear()
    pos = _make_pos(PositionSide.SHORT, Decimal("80000"))
    pos.id = "p2"
    for t in pos.entry_tranches + pos.exit_tranches:
        t.position_id = "p2"
    eng.open_positions[pos.id] = pos
    before = eng.account.total_realized_pnl

    trade = eng._close_position(pos.id, Decimal("0"), "emergency")

    assert eng.account.total_realized_pnl == before
    assert trade.realized_pnl == Decimal("0")


def test_get_status_has_real_profit():
    """get_status()에 real_profit 키가 있어야 함."""
    eng = PaperTradingEngine()
    status = eng.get_status()
    assert "real_profit" in status
    assert "real_profit_pct" in status
    assert "initial_capital" in status


def test_get_status_no_total_fees():
    """get_status()에 total_fees 키가 없어야 함 (수수료 개념 폐기)."""
    eng = PaperTradingEngine()
    status = eng.get_status()
    assert "total_fees" not in status


def test_get_status_real_profit_value():
    """real_profit = balance - initial_capital."""
    eng = PaperTradingEngine()
    eng.account.balance = Decimal("210")
    eng.account.initial_capital = Decimal("200")
    status = eng.get_status()
    assert Decimal(status["real_profit"]) == Decimal("10")
    assert status["real_profit_pct"] == 5.0
    assert Decimal(status["initial_capital"]) == Decimal("200")


def test_get_daily_summary_total_pnl_is_real_profit():
    """get_daily_summary()의 total_pnl은 balance - initial_capital (신뢰불가 total_realized_pnl 아님)."""
    eng = PaperTradingEngine()
    eng.account.balance = Decimal("180")
    eng.account.initial_capital = Decimal("200")
    eng.account.total_realized_pnl = Decimal("633")  # 부풀려진 값
    summary = eng.get_daily_summary()
    assert Decimal(summary["total_pnl"]) == Decimal("-20")  # real_profit
