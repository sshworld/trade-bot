"""2026-06-08 회의록: 풀물량 단일 TP 8% 전환 검증.

- 분할(3/6/10@50/30/20) 폐기 → 단일 TP 8% @ 100%
- exit_tranches 1개, 전량, 목표가 = entry ± 8%/leverage
- SL 최소거리 0.5%
"""

from decimal import Decimal

from app.trading.engine import PaperTradingEngine
from app.trading.schemas import PositionSide


def test_settings_single_tp():
    eng = PaperTradingEngine()
    assert eng.settings.tp_margin_pcts == [2.0]   # S2: 8% → 2%
    assert eng.settings.tp_split == [1.0]
    assert eng.settings.min_sl_distance_pct == 0.0  # S2: floor 제거
    assert eng.settings.sl_balance_risk_pct == 2.0


def test_exit_tranches_single_full_long():
    eng = PaperTradingEngine()
    tr = eng._create_exit_tranches(
        side=PositionSide.LONG, avg_entry=Decimal("60000"),
        total_qty=Decimal("0.010"), pos_id="t1", now=0, leverage=5,
    )
    assert len(tr) == 1, "단일 TP 여야 함 (러너 없음)"
    assert tr[0].quantity == Decimal("0.010"), "전량 익절"
    # S2: target = 60000 * (1 + 2/100/5) = 60000 * 1.004 = 60240.0
    assert tr[0].target_price == Decimal("60240.0")


def test_exit_tranches_single_full_short():
    eng = PaperTradingEngine()
    tr = eng._create_exit_tranches(
        side=PositionSide.SHORT, avg_entry=Decimal("60000"),
        total_qty=Decimal("0.010"), pos_id="t2", now=0, leverage=5,
    )
    assert len(tr) == 1
    assert tr[0].quantity == Decimal("0.010")
    # S2: target = 60000 * (1 - 0.004) = 59760.0
    assert tr[0].target_price == Decimal("59760.0")
