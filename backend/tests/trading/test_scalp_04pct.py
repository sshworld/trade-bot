"""S2 — 0.4% 대칭 스캘프 전환 검증.

SL/TP = 마진 2% (가격 ±0.4% @5x) 대칭.
추매 체결 시 평단 기준 SL·TP 재계산.
진입 간격 ≤0.35% 축소.
min_sl_distance_pct = 0.0 (floor 제거).
"""

from decimal import Decimal

import pytest

from app.trading.engine import PaperTradingEngine
from app.trading.schemas import OrderStatus, Position, PositionSide, TrancheOrder


ENTRY = Decimal("60000")
LEV = 5


@pytest.fixture
def eng():
    return PaperTradingEngine()


# (a) 단일 진입 — TP/SL ±0.4%
def test_single_entry_tp_long(eng):
    """LONG 단일 진입: TP = entry × (1 + 2/100/5) = entry × 1.004."""
    tr = eng._create_exit_tranches(
        side=PositionSide.LONG, avg_entry=ENTRY,
        total_qty=Decimal("0.010"), pos_id="t1", now=0, leverage=LEV,
    )
    assert len(tr) == 1
    assert tr[0].quantity == Decimal("0.010")
    # 60000 * 1.004 = 60240.0
    assert tr[0].target_price == Decimal("60240.0")


def test_single_entry_sl_long(eng):
    """LONG 단일 진입: SL = entry × (1 - 2/100/5) = entry × 0.996."""
    sl = eng._calculate_stop_loss(PositionSide.LONG, ENTRY, 2.0, LEV)
    # 60000 * 0.996 = 59760.0
    assert sl == Decimal("59760.0")


# (b) 추매 재계산 — 새 평단 기준 SL·TP
def test_dca_recalculate(eng):
    """2회 추매 체결 후 _recalculate_position → 새 avg 기준 SL·TP."""
    price1 = Decimal("60000")
    price2 = Decimal("59760")  # 0.4% 아래
    qty = Decimal("0.005")

    e1 = TrancheOrder(
        id="p1-e0", position_id="p1", side=PositionSide.LONG, is_entry=True,
        target_price=price1, quantity=qty,
        filled_price=price1, status=OrderStatus.FILLED, created_at=0,
    )
    e2 = TrancheOrder(
        id="p1-e1", position_id="p1", side=PositionSide.LONG, is_entry=True,
        target_price=price2, quantity=qty,
        filled_price=price2, status=OrderStatus.FILLED, created_at=0,
    )
    pos = Position(
        id="p1", side=PositionSide.LONG, leverage=LEV,
        signal_type="t", signal_strength=0.6,
        entry_tranches=[e1, e2], exit_tranches=[],
        stop_loss_price=Decimal("59700"),
        allocated_margin=Decimal("600"),
        tp_margin_pcts=[2.0], tp_split=[1.0],
        opened_at=0,
    )
    eng._recalculate_position(pos)

    avg = pos.avg_entry_price
    assert avg is not None
    # avg = (60000*0.005 + 59760*0.005) / 0.010 = 59880
    assert avg == Decimal("59880.0")

    # SL ≈ avg × 0.996
    expected_sl = (avg * Decimal("0.996")).quantize(Decimal("0.1"))
    assert pos.stop_loss_price == expected_sl

    # TP ≈ avg × 1.004
    assert len(pos.exit_tranches) == 1
    expected_tp = (avg * Decimal("1.004")).quantize(Decimal("0.1"))
    assert pos.exit_tranches[0].target_price == expected_tp


# (c) 진입 간격 ≤0.35%
def test_entry_interval_max(eng):
    """모든 진입 tranche 가 base 대비 ≤0.35% 역행."""
    base = Decimal("60000")
    # atr=0 이면 offset=floor 로 동작
    tranches = eng._create_entry_tranches(
        PositionSide.LONG, base, Decimal("0.050"), "p2", 0, atr=0,
    )
    for t in tranches:
        deviation = float(base - t.target_price) / float(base)
        assert deviation <= 0.0035, f"진입 간격 초과: {deviation:.4%} > 0.35%"


# (d) floor 제거 — min_sl_distance_pct == 0.0
def test_min_sl_distance_pct_zero(eng):
    """min_sl_distance_pct == 0.0 (0.5% floor 없음)."""
    assert eng.settings.min_sl_distance_pct == 0.0


def test_sl_not_clamped_to_05pct(eng):
    """0.4% SL 이 0.5% 로 클램프되지 않음."""
    sl = eng._calculate_stop_loss(PositionSide.LONG, ENTRY, 2.0, LEV)
    # 0.4% 거리 = 240; 0.5% 거리 = 300
    sl_distance_pct = float(ENTRY - sl) / float(ENTRY)
    assert abs(sl_distance_pct - 0.004) < 1e-6, f"SL 거리가 0.4%여야 함: {sl_distance_pct:.4%}"


# (e) SHORT 대칭
def test_short_symmetry(eng):
    """SHORT: TP = entry × (1 - 0.004), SL = entry × (1 + 0.004)."""
    tr = eng._create_exit_tranches(
        side=PositionSide.SHORT, avg_entry=ENTRY,
        total_qty=Decimal("0.010"), pos_id="t3", now=0, leverage=LEV,
    )
    assert len(tr) == 1
    # 60000 * (1 - 0.004) = 59760.0
    assert tr[0].target_price == Decimal("59760.0")

    sl = eng._calculate_stop_loss(PositionSide.SHORT, ENTRY, 2.0, LEV)
    # 60000 * 1.004 = 60240.0
    assert sl == Decimal("60240.0")


# settings 검증
def test_settings_scalp_04pct(eng):
    """스캘프 0.4% 설정값 확인."""
    assert eng.settings.tp_margin_pcts == [2.0]
    assert eng.settings.tp_split == [1.0]
    assert eng.settings.sl_margin_pct == 2.0
    assert eng.settings.min_sl_distance_pct == 0.0
    assert eng.settings.entry_atr_offset_floors == [0.0, 0.1, 0.2]
    assert eng.settings.entry_atr_offset_caps == [0.0, 0.2, 0.35]
