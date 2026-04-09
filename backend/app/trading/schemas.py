"""트레이딩 데이터 모델 + 설정.

파라미터는 2026-04-08 Buffett×Dimon 회의록 기준.
변경 시 반드시 전문가 토론 → 회의록 → 승인 후 적용.
"""

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


class TrancheOrder(BaseModel):
    id: str
    position_id: str
    side: PositionSide
    is_entry: bool
    target_price: Decimal
    quantity: Decimal
    filled_price: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: int
    filled_at: int | None = None


class Position(BaseModel):
    id: str
    symbol: str = "BTCUSDT"
    side: PositionSide
    leverage: int
    signal_type: str
    signal_strength: float
    signal_message: str = ""
    signal_details: dict | None = None

    entry_tranches: list[TrancheOrder]
    exit_tranches: list[TrancheOrder]
    stop_loss_price: Decimal

    avg_entry_price: Decimal | None = None
    total_quantity: Decimal = Decimal("0")
    allocated_quantity: Decimal = Decimal("0")
    allocated_margin: Decimal = Decimal("0")
    tp_levels: list[float] = []
    exit_split: list[float] = []
    sl_pct: float = 5.0
    timeframe: str = "1h"
    realized_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    status: str = "opening"
    opened_at: int
    closed_at: int | None = None


class TradeRecord(BaseModel):
    id: str
    symbol: str
    side: PositionSide
    leverage: int
    avg_entry_price: Decimal
    avg_exit_price: Decimal
    quantity: Decimal
    realized_pnl: Decimal
    pnl_percent: float
    signal_type: str
    signal_message: str = ""
    signal_details: dict | None = None
    close_reason: str = ""
    total_fees: Decimal = Decimal("0")
    opened_at: int
    closed_at: int
    duration_seconds: int


class AccountState(BaseModel):
    balance: Decimal = Decimal("1000")
    initial_capital: Decimal = Decimal("1000")
    equity: Decimal = Decimal("1000")
    peak_equity: Decimal = Decimal("1000")     # 고점 추적 (drawdown용)
    margin_used: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_realized_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    total_trades: int = 0
    winning_trades: int = 0
    daily_pnl: Decimal = Decimal("0")          # 금일 실현 PnL
    daily_start_balance: Decimal = Decimal("1000")  # 금일 00시 잔고
    daily_trades: int = 0                       # 금일 거래 수
    daily_replacements: int = 0                 # 금일 교체 수
    last_replacement_at: int = 0                # 마지막 교체 시각
    last_daily_reset: int = 0                   # 마지막 일일 리셋 시각


class TradeTier(str, Enum):
    WITH_TREND = "with_trend"
    COUNTER_TREND = "counter_trend"
    BLOCKED = "blocked"


class TrendContext(BaseModel):
    tf_directions: dict[str, str] = {}
    tf_strengths: dict[str, float] = {}
    updated_at: int = 0


# ── TF별 TP/SL 설정 (회의록 2026-04-08 확정) ──────────────────

class TFParams(BaseModel):
    """TF별 TP/SL/Split 파라미터. 마진 기준 %."""
    tp_levels: list[float]
    sl_pct: float
    exit_split: list[float]


# WITH_TREND TF별
TF_PARAMS_WITH_TREND: dict[str, TFParams] = {
    "30m": TFParams(tp_levels=[5.0, 10.0, 18.0], sl_pct=3.5, exit_split=[0.50, 0.30, 0.20]),
    "1h":  TFParams(tp_levels=[7.0, 14.0, 25.0], sl_pct=5.0, exit_split=[0.50, 0.30, 0.20]),
    "4h":  TFParams(tp_levels=[10.0, 20.0, 35.0], sl_pct=7.0, exit_split=[0.50, 0.30, 0.20]),
}

# COUNTER_TREND & CONSENSUS TF별
TF_PARAMS_COUNTER: dict[str, TFParams] = {
    "30m": TFParams(tp_levels=[3.5, 7.0, 12.0], sl_pct=3.0, exit_split=[0.50, 0.30, 0.20]),
    "1h":  TFParams(tp_levels=[5.0, 10.0, 18.0], sl_pct=4.0, exit_split=[0.50, 0.30, 0.20]),
    "4h":  TFParams(tp_levels=[7.0, 14.0, 25.0], sl_pct=5.5, exit_split=[0.50, 0.30, 0.20]),
}


def get_tf_params(tf: str, tier: str) -> TFParams:
    """TF + tier에 맞는 파라미터 반환."""
    if tier == "with_trend":
        return TF_PARAMS_WITH_TREND.get(tf, TF_PARAMS_WITH_TREND["1h"])
    return TF_PARAMS_COUNTER.get(tf, TF_PARAMS_COUNTER["1h"])


# ── Counter-Trend 추가 조건 ────────────────────────────────────

class CounterTrendSettings(BaseModel):
    extra_min_count: int = 1
    extra_min_score: float = 1.0
    min_strong_triggers: int = 2
    entry_offsets: list[float] = [0.0, -0.3, -0.6]
    max_counter_positions: int = 1


# ── 메인 설정 ──────────────────────────────────────────────────

class TradingSettings(BaseModel):
    initial_capital: Decimal = Decimal("1000")

    # 레버리지: 3-5x (회의록 확정)
    min_leverage: int = 3
    max_leverage: int = 5

    # 수수료
    fee_maker_pct: float = 0.02
    fee_taker_pct: float = 0.04

    # 진입 분할
    entry_offsets: list[float] = [0.0, -0.5, -1.0]
    entry_split: list[float] = [0.33, 0.33, 0.34]

    # 포지션
    max_open_positions: int = 1          # 동시 1개 (회의록 확정)
    risk_per_trade_pct: float = 2.0      # 거래당 자본 2% 리스크

    # 일일 제한
    max_daily_trades: int = 5
    daily_loss_tier1_pct: float = 3.0    # -3% → 사이즈 절반
    daily_loss_tier2_pct: float = 5.0    # -5% → 당일 거래 중단
    daily_loss_tier3_pct: float = 8.0    # -8% → 48시간 중단
    drawdown_halt_pct: float = 10.0      # 고점 대비 -10% → 중단

    # 교체
    replacement_cooldown_ms: int = 1_800_000  # 30분
    max_daily_replacements: int = 3

    # ATR 가드레일
    atr_sl_min_multiple: float = 1.5
    atr_sl_max_multiple: float = 4.0

    counter_trend: CounterTrendSettings = CounterTrendSettings()
