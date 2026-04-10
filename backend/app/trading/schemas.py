"""트레이딩 데이터 모델 + 설정.

파라미터는 2026-04-10 Buffett×Dimon 회의록 기준.
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
    WAITING = "waiting"  # Binance 주문 전송 중 (reconciliation용)


class TrancheOrder(BaseModel):
    id: str
    position_id: str
    side: PositionSide
    is_entry: bool
    target_price: Decimal
    quantity: Decimal
    filled_price: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING
    client_order_id: str | None = None
    binance_order_id: str | None = None
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
    tp_levels: list[float] = []       # ATR 배수 [1.5, 3.0, 999]
    exit_split: list[float] = []
    sl_atr_multiple: float = 2.0      # SL ATR 배수
    highest_price: Decimal | None = None  # 트레일링용 최고가 추적
    lowest_price: Decimal | None = None   # 트레일링용 최저가 추적
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
    peak_equity: Decimal = Decimal("1000")
    margin_used: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_realized_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    total_trades: int = 0
    winning_trades: int = 0
    daily_pnl: Decimal = Decimal("0")
    daily_start_balance: Decimal = Decimal("1000")
    daily_trades: int = 0
    daily_replacements: int = 0
    last_replacement_at: int = 0
    last_daily_reset: int = 0


class TradeTier(str, Enum):
    WITH_TREND = "with_trend"
    COUNTER_TREND = "counter_trend"
    BLOCKED = "blocked"


class TrendContext(BaseModel):
    tf_directions: dict[str, str] = {}
    tf_strengths: dict[str, float] = {}
    updated_at: int = 0


# ── ATR 기반 TP/SL 설정 (2026-04-10 회의록) ───────────────────

class TFATRParams(BaseModel):
    """TF별 ATR 배수 기반 TP/SL. 단타 최적화."""
    sl_atr: float
    tp1_atr: float
    tp2_atr: float
    tp3_atr: float         # 하드캡 (무한 트레일 제거)
    exit_split: list[float]


TF_ATR_PARAMS: dict[str, TFATRParams] = {
    "30m": TFATRParams(sl_atr=1.2, tp1_atr=1.0, tp2_atr=1.8, tp3_atr=3.0, exit_split=[0.50, 0.30, 0.20]),
    "1h":  TFATRParams(sl_atr=1.5, tp1_atr=1.2, tp2_atr=2.0, tp3_atr=3.5, exit_split=[0.50, 0.30, 0.20]),
    "4h":  TFATRParams(sl_atr=2.0, tp1_atr=1.5, tp2_atr=2.5, tp3_atr=4.0, exit_split=[0.50, 0.30, 0.20]),
}


def get_tf_atr_params(tf: str) -> TFATRParams:
    return TF_ATR_PARAMS.get(tf, TF_ATR_PARAMS["1h"])


# ── Counter-Trend 추가 조건 ────────────────────────────────────

class CounterTrendSettings(BaseModel):
    extra_min_count: int = 1
    extra_min_score: float = 1.0
    min_strong_triggers: int = 2
    # Counter: 2 tranche, 확인 아닌 소폭 물타기
    entry_offsets: list[float] = [0.0, -0.3]
    entry_split: list[float] = [0.60, 0.40]


# ── 메인 설정 ──────────────────────────────────────────────────

class TradingSettings(BaseModel):
    initial_capital: Decimal = Decimal("1000")

    # 레버리지: 5x 고정 (2026-04-10 회의록)
    min_leverage: int = 5
    max_leverage: int = 5

    # 수수료
    fee_maker_pct: float = 0.02
    fee_taker_pct: float = 0.04

    # 진입: 평단 최적화 (2026-04-11 회의록)
    # WITH_TREND: 50% 즉시, 30% -0.3% 역행 추가, 20% -0.6% 역행 추가
    entry_offsets: list[float] = [0.0, -0.3, -0.6]
    entry_split: list[float] = [0.50, 0.30, 0.20]

    # 포지션
    max_open_positions: int = 1
    risk_per_trade_pct: float = 2.0

    # 일일 제한 — 횟수 무제한, 손실만 제한
    daily_loss_tier1_pct: float = 3.0    # -3% → 사이즈 절반
    daily_loss_tier2_pct: float = 5.0    # -5% → 당일 중단 (다음 날 00시 복귀)
    drawdown_halt_pct: float = 10.0      # 고점 대비 -10% → 중단

    # 교체 — 무제한, 품질 게이트
    replacement_cooldown_ms: int = 1_200_000  # 20분
    replacement_min_score_diff: float = 0.5   # 새 시그널 > 기존 + 0.5
    same_signal_block_ms: int = 28_800_000    # 같은 시그널 8시간 차단

    # 속도 제한 (velocity brake)
    velocity_max_consecutive_sl: int = 3      # 60분 내 3연속 SL
    velocity_window_ms: int = 3_600_000       # 60분
    velocity_pause_ms: int = 1_800_000        # 30분 일시 중단

    # ATR 가드레일
    atr_sl_min_multiple: float = 1.5
    atr_sl_max_multiple: float = 4.0

    counter_trend: CounterTrendSettings = CounterTrendSettings()


class LiveTradingSettings(TradingSettings):
    """실거래용 리스크 파라미터 (2026-04-11 회의록 기준: 순수 % 체계)."""
    drawdown_halt_pct: float = 7.0        # Peak drawdown -7% → 당일 정지
    slippage_buffer: float = 0.95         # 계산 사이즈의 95%만 사용
    min_notional: Decimal = Decimal("100")  # Binance 최소 노셔널 (자연 하한)
    balance_cache_ttl_sec: float = 5.0    # 잔고 캐시 5초
    reconciliation_interval_sec: int = 5  # 주문 조회 주기
    balance_discrepancy_pct: float = 1.0  # 잔고 차이 1% 초과 시 경고
