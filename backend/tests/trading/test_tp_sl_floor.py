"""S3 — 분할 TP 후 SL floor (이익 잠금) 테스트.

체결 TP 가격 위로 SL 잠금, LONG/SHORT 대칭, breakeven 하한.
"""

from decimal import Decimal

import pytest

from app.trading.engine import PaperTradingEngine
from app.trading.schemas import OrderStatus, Position, PositionSide, TrancheOrder


ENTRY = Decimal("80000")
# 5x, TP1 마진 3% → 가격 +0.6% = 80480, TP2 +1.2% = 80960
TP1 = Decimal("80480")
TP2 = Decimal("80960")


def _exit(price, qty, filled):
    return TrancheOrder(
        id=f"x{price}", position_id="p1", side=PositionSide.LONG, is_entry=False,
        target_price=Decimal(str(price)), quantity=Decimal(str(qty)),
        filled_price=Decimal(str(price)) if filled else None,
        status=OrderStatus.FILLED if filled else OrderStatus.WAITING, created_at=0,
    )


def _pos(side=PositionSide.LONG, exits=None, sl=Decimal("79000")):
    return Position(
        id="p1", side=side, leverage=5, signal_type="t", signal_strength=0.6,
        entry_tranches=[TrancheOrder(id="e1", position_id="p1", side=side, is_entry=True,
                                     target_price=ENTRY, quantity=Decimal("0.03"),
                                     filled_price=ENTRY, status=OrderStatus.FILLED, created_at=0)],
        exit_tranches=exits or [], stop_loss_price=sl,
        avg_entry_price=ENTRY, total_quantity=Decimal("0.03"),
        allocated_margin=Decimal("480"), tp_margin_pcts=[3.0, 6.0, 10.0],
        opened_at=0,
    )


@pytest.fixture
def eng():
    return PaperTradingEngine()


def test_floor_tp1_above_entry(eng):
    """TP1 체결 → SL floor ≈ entry +0.42% (체결 TP 위, 본전 위)."""
    exits = [_exit(TP1, 0.015, True), _exit(TP2, 0.009, False)]
    pos = _pos(exits=exits)
    floor = eng._tp_sl_floor(pos)
    # TP1 - (TP1-entry)*0.30 = 80480 - 480*0.3 = 80480 - 144 = 80336 (= entry+0.42%)
    assert floor == Decimal("80336.0")
    assert floor > ENTRY  # 본전 위


def test_floor_tp2_above_tp1(eng):
    """TP2 체결 → SL floor ≈ entry +0.84% (TP1 위)."""
    exits = [_exit(TP1, 0.015, True), _exit(TP2, 0.009, True)]
    pos = _pos(exits=exits)
    floor = eng._tp_sl_floor(pos)
    # best_tp=TP2=80960, 80960 - (80960-80000)*0.3 = 80960 - 288 = 80672
    assert floor == Decimal("80672.0")
    assert floor > TP1  # TP1 위


def test_trailing_after_tp1_locks_profit(eng):
    """_trailing_sl_after_tp: TP1 체결 시 SL이 체결 TP 위(이익) 로 이동."""
    exits = [_exit(TP1, 0.015, True), _exit(TP2, 0.009, False)]
    pos = _pos(exits=exits, sl=Decimal("79000"))
    eng._trailing_sl_after_tp(pos, filled_exits=1)
    assert pos.stop_loss_price == Decimal("80336.0")
    assert pos.stop_loss_price > ENTRY


def test_short_symmetry(eng):
    """SHORT: floor 가 체결 TP 아래(이익 구간)."""
    entry = Decimal("80000")
    tp1_short = Decimal("79520")  # -0.6%
    ex = TrancheOrder(id="x1", position_id="p1", side=PositionSide.SHORT, is_entry=False,
                      target_price=tp1_short, quantity=Decimal("0.015"),
                      filled_price=tp1_short, status=OrderStatus.FILLED, created_at=0)
    pos = Position(id="p1", side=PositionSide.SHORT, leverage=5, signal_type="t",
                   signal_strength=0.6,
                   entry_tranches=[TrancheOrder(id="e1", position_id="p1", side=PositionSide.SHORT,
                                                is_entry=True, target_price=entry, quantity=Decimal("0.03"),
                                                filled_price=entry, status=OrderStatus.FILLED, created_at=0)],
                   exit_tranches=[ex], stop_loss_price=Decimal("81000"),
                   avg_entry_price=entry, total_quantity=Decimal("0.03"),
                   allocated_margin=Decimal("480"), tp_margin_pcts=[3.0, 6.0, 10.0], opened_at=0)
    floor = eng._tp_sl_floor(pos)
    # 79520 + (80000-79520)*0.3 = 79520 + 144 = 79664
    assert floor == Decimal("79664.0")
    assert floor < entry  # SHORT 이익 구간(진입가 아래)


def test_floor_none_without_filled_tp(eng):
    """체결 TP 없으면 None → SL 변경 없음."""
    exits = [_exit(TP1, 0.015, False)]
    pos = _pos(exits=exits)
    assert eng._tp_sl_floor(pos) is None
    before = pos.stop_loss_price
    eng._trailing_sl_after_tp(pos, filled_exits=0)
    assert pos.stop_loss_price == before


def test_buffer_ratio_default(eng):
    assert eng.settings.tp_sl_buffer_ratio == 0.30
