"""S4 — 수수료 제거 + 회계 일원화 테스트.

account.total_fees 미누적, per-trade fee 보존, Live _close_position 로컬 balance 가감 무효화.
"""

from decimal import Decimal

import pytest

import app.trading.engine  # noqa: F401
from app.trading import live_engine as le_mod
from app.trading.engine import PaperTradingEngine
from app.trading.live_engine import LiveTradingEngine
from app.trading.schemas import OrderStatus, Position, PositionSide, TrancheOrder


def _open_pos(eng_account_margin=Decimal("160")):
    entry = TrancheOrder(id="e1", position_id="p1", side=PositionSide.LONG, is_entry=True,
                         target_price=Decimal("80000"), quantity=Decimal("0.01"),
                         filled_price=Decimal("80000"), status=OrderStatus.FILLED, created_at=0)
    tp = TrancheOrder(id="x1", position_id="p1", side=PositionSide.LONG, is_entry=False,
                      target_price=Decimal("80480"), quantity=Decimal("0.01"),
                      status=OrderStatus.WAITING, created_at=0)
    return Position(id="p1", side=PositionSide.LONG, leverage=5, signal_type="t",
                    signal_strength=0.6, entry_tranches=[entry], exit_tranches=[tp],
                    stop_loss_price=Decimal("79000"), avg_entry_price=Decimal("80000"),
                    total_quantity=Decimal("0.01"), allocated_margin=eng_account_margin,
                    realized_pnl=Decimal("5"), opened_at=0)


def test_paper_close_no_account_total_fees_accumulation():
    """Paper 청산 후 account.total_fees 누적 안 됨 (개념 제거)."""
    eng = PaperTradingEngine()
    eng.open_positions.clear()
    pos = _open_pos()
    eng.open_positions[pos.id] = pos
    before = eng.account.total_fees
    trade = eng._close_position(pos.id, Decimal("80480"), "take_profit")
    assert eng.account.total_fees == before        # 누적 0
    assert trade.total_fees >= 0                    # per-trade fee 는 기록됨


def test_live_close_does_not_mutate_balance():
    """Live _close_position 은 로컬 balance 를 가감하지 않음 (실잔고 sync 권위)."""
    eng = LiveTradingEngine()
    eng.open_positions.clear()
    eng.account.balance = Decimal("200")
    pos = _open_pos()
    eng.open_positions[pos.id] = pos
    eng._close_position(pos.id, Decimal("80480"), "take_profit")
    assert eng.account.balance == Decimal("200")    # 변동 없음 (super 가감 되돌림)


def test_resync_after_close_daily_pnl_real_based():
    """_resync_after_close: daily_pnl = real_bal - daily_start_balance."""
    eng = LiveTradingEngine()
    eng.account.daily_start_balance = Decimal("200")
    eng._resync_after_close(Decimal("207"))
    assert eng.account.balance == Decimal("207")
    assert eng.account.margin_used == Decimal("0")
    assert eng.account.daily_pnl == Decimal("7")    # 실잔고 기반


def test_status_no_total_fees_has_real_profit():
    """get_status 에 total_fees 키 없음(수수료 개념 폐기), real_profit 키 존재."""
    eng = PaperTradingEngine()
    eng.open_positions.clear()
    eng.trade_history.clear()
    status = eng.get_status()
    assert "total_fees" not in status                # 수수료 개념 폐기
    assert "real_profit" in status                   # 실수익 권위 지표


def test_account_total_fees_field_never_accumulates():
    """청산해도 account.total_fees 필드는 불변 (누적 개념 제거)."""
    eng = PaperTradingEngine()
    eng.open_positions.clear()
    before = eng.account.total_fees
    pos = _open_pos()
    eng.open_positions[pos.id] = pos
    eng._close_position(pos.id, Decimal("80480"), "take_profit")
    assert eng.account.total_fees == before
