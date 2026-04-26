"""행동 이상 감지 모듈 (Behavioral Anomaly Detection).

기존 임계값 기반 보호(daily loss %, drawdown %, 연속 SL 등)로는
잡히지 않는 **봇 오작동 패턴**을 감지한다.

설계 원칙 (Buffett×Dimon):
  - 의심스러우면 일단 멈추고 돈을 지킨다
  - 자동 복구 가능한 것과 사람이 봐야 하는 것을 명확히 구분
  - 모든 halt/alert는 텔레그램으로 즉시 통보

2026-04-06 설계 / 변경 시 전문가 토론 → 회의록 → 승인.
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 설정값 (Config)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AnomalyAction(str, Enum):
    ALERT = "alert"              # 알림만 (거래 계속)
    REDUCE = "reduce"            # 사이즈 50%로 축소
    HALT_SHORT = "halt_short"    # 단기 중단 (자동복구)
    HALT_LONG = "halt_long"      # 장기 중단 (자동복구)
    HALT_MANUAL = "halt_manual"  # 수동 복구 필요 (config 변경)


@dataclass
class AnomalyConfig:
    """전체 anomaly 감지 설정. Settings에서 오버라이드 가능."""

    # ── RULE 1: Rapid-Fire Orders ──────────────────────────────
    # 짧은 시간에 주문이 너무 많이 발생 → 봇 루프 버그
    rapidfire_window_sec: int = 60          # 감시 윈도우
    rapidfire_max_orders: int = 6           # 윈도우 내 최대 주문 수
    rapidfire_action: AnomalyAction = AnomalyAction.HALT_SHORT
    rapidfire_halt_sec: int = 3600          # 1시간 중단

    # ── RULE 2: Flip-Flop (방향 전환 반복) ─────────────────────
    # LONG→SHORT→LONG→SHORT 반복 → 시그널 진동(oscillation)
    flipflop_window_sec: int = 7200         # 2시간 윈도우
    flipflop_max_flips: int = 3             # 윈도우 내 방향전환 3회
    flipflop_action: AnomalyAction = AnomalyAction.HALT_SHORT
    flipflop_halt_sec: int = 7200           # 2시간 중단

    # ── RULE 3: Fee Bleeding ───────────────────────────────────
    # PnL ≈ 0인데 수수료만 계속 나감 → 의미 없는 거래 반복
    feebleed_window_trades: int = 5         # 최근 N건 검사
    feebleed_pnl_threshold_pct: float = 0.3 # |PnL%| < 0.3%이면 near-zero
    feebleed_min_count: int = 4             # 5건 중 4건 이상 near-zero
    feebleed_action: AnomalyAction = AnomalyAction.HALT_SHORT
    feebleed_halt_sec: int = 3600           # 1시간 중단

    # ── RULE 4: Replacement Cascade ────────────────────────────
    # 포지션 열자마자 교체, 또 교체 → 시그널 무한 진동
    cascade_window_sec: int = 3600          # 1시간 윈도우
    cascade_max_replacements: int = 2       # 윈도우 내 교체 2회
    cascade_action: AnomalyAction = AnomalyAction.HALT_SHORT
    cascade_halt_sec: int = 3600            # 1시간 중단

    # ── RULE 5: Consecutive Losses (전방향) ────────────────────
    # 방향 무관하게 연속 N패 → 시장/전략 미스매치
    consec_loss_count: int = 5              # 연속 5패
    consec_loss_action: AnomalyAction = AnomalyAction.HALT_LONG
    consec_loss_halt_sec: int = 14400       # 4시간 중단

    # ── RULE 6: Abnormal Position Size ─────────────────────────
    # 포지션 크기가 잔고 대비 비정상 → 계산 버그
    abnormal_size_max_pct: float = 50.0     # 잔고의 50% 초과 마진
    abnormal_size_action: AnomalyAction = AnomalyAction.HALT_MANUAL
    # HALT_MANUAL: config에서 anomaly_manual_resume = true 설정 필요

    # ── RULE 7: Price Sanity ───────────────────────────────────
    # 진입가가 현재가에서 너무 먼 → 데이터 오류 또는 버그
    price_deviation_max_pct: float = 3.0    # 현재가 대비 ±3% 벗어남
    price_sanity_action: AnomalyAction = AnomalyAction.HALT_MANUAL

    # ── RULE 8: Winning Streak Overconfidence Guard ────────────
    # 7연승 이상 → 사이즈만 축소 (과적합/운 구간 경계)
    win_streak_threshold: int = 7
    win_streak_action: AnomalyAction = AnomalyAction.REDUCE

    # ── RULE 9: Stale Price / Exchange Disconnect ──────────────
    # 가격 업데이트가 장시간 없음 → 거래소 연결 끊김
    stale_price_max_sec: int = 120          # 2분간 가격 없음
    stale_price_action: AnomalyAction = AnomalyAction.HALT_SHORT
    stale_price_halt_sec: int = 300         # 5분 중단 (자동 재시도)

    # ── RULE 10: Daily Fee Ratio ───────────────────────────────
    # 당일 수수료가 당일 거래대금 대비 과다 → 과잉매매
    daily_fee_ratio_max_pct: float = 1.0    # 수수료/거래대금 > 1%
    daily_fee_ratio_action: AnomalyAction = AnomalyAction.ALERT

    # ── Manual Resume ──────────────────────────────────────────
    anomaly_manual_resume: bool = False     # True로 바꾸면 manual halt 해제


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 알림 메시지 구조
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class AnomalyAlert:
    """감지된 이상 행동 알림."""
    rule_name: str              # e.g. "rapid_fire"
    severity: str               # "WARNING" | "CRITICAL" | "EMERGENCY"
    action_taken: AnomalyAction
    message: str                # 사람이 읽는 설명
    details: dict               # 감지 시점의 상세 데이터
    halt_until: int = 0         # ms timestamp, 0이면 halt 아님
    requires_manual_resume: bool = False
    timestamp: int = 0          # ms timestamp


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Anomaly Detector
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AnomalyDetector:
    """봇 행동 이상 감지기.

    TradingEngine에서 매 이벤트마다 호출.
    상태는 메모리에만 유지 (재시작 시 초기화 — 의도적).
    """

    def __init__(self, config: AnomalyConfig | None = None):
        self.config = config or AnomalyConfig()

        # ── 이벤트 링버퍼 ──
        self._order_timestamps: deque[int] = deque(maxlen=100)
        self._direction_history: deque[tuple[int, str]] = deque(maxlen=50)  # (ts_ms, "long"|"short")
        self._replacement_timestamps: deque[int] = deque(maxlen=50)
        self._last_price_update_ms: int = int(time.time() * 1000)

        # ── Halt 상태 ──
        self._halt_until: int = 0               # auto-resume halt
        self._manual_halt: bool = False          # manual halt (config 변경 필요)
        self._halt_reason: str = ""
        self._size_reduction_active: bool = False

        # ── 알림 이력 (중복 방지) ──
        self._last_alert_by_rule: dict[str, int] = {}
        self._alert_cooldown_sec: int = 300      # 같은 rule 알림 5분 쿨다운

    # ────────────────────────────────────────────────────────────
    # Public API: TradingEngine이 호출
    # ────────────────────────────────────────────────────────────

    def is_halted(self) -> bool:
        """거래 가능 여부. True면 거래 금지."""
        now = int(time.time() * 1000)
        if self._manual_halt:
            if self.config.anomaly_manual_resume:
                # config에서 resume 플래그가 켜졌으면 해제
                self._manual_halt = False
                self._halt_reason = ""
                self.config.anomaly_manual_resume = False
                logger.info("Manual halt released via config flag")
                return False
            return True
        if now < self._halt_until:
            return True
        if self._halt_until > 0 and now >= self._halt_until:
            # 자동 복구 시점
            self._halt_until = 0
            self._halt_reason = ""
            logger.info("Auto-halt expired, trading resumed")
        return False

    def get_size_multiplier(self) -> Decimal:
        """현재 사이즈 축소 배율. 1.0 = 정상, 0.5 = 절반."""
        return Decimal("0.5") if self._size_reduction_active else Decimal("1.0")

    def get_halt_info(self) -> dict:
        """현재 halt 상태 정보."""
        now = int(time.time() * 1000)
        remaining_sec = max(0, (self._halt_until - now) // 1000) if self._halt_until > now else 0
        return {
            "is_halted": self.is_halted(),
            "manual_halt": self._manual_halt,
            "halt_reason": self._halt_reason,
            "halt_remaining_sec": remaining_sec,
            "size_reduction_active": self._size_reduction_active,
        }

    # ── 이벤트 수집 ──

    def record_order(self, timestamp_ms: int, direction: str):
        """주문 발생 시 호출. direction: 'long' | 'short'."""
        self._order_timestamps.append(timestamp_ms)
        self._direction_history.append((timestamp_ms, direction))

    def record_replacement(self, timestamp_ms: int):
        """포지션 교체 발생 시 호출."""
        self._replacement_timestamps.append(timestamp_ms)

    def record_price_update(self, timestamp_ms: int):
        """가격 업데이트 수신 시 호출."""
        self._last_price_update_ms = timestamp_ms

    # ── 검사 실행 ──

    def check_pre_order(
        self,
        direction: str,
        margin: Decimal,
        balance: Decimal,
        entry_price: Decimal,
        current_price: Decimal,
    ) -> AnomalyAlert | None:
        """주문 전 검사. 이상 감지 시 AnomalyAlert 반환, 정상이면 None.

        이 함수가 alert를 반환하면 주문을 거부해야 한다.
        """
        now = int(time.time() * 1000)

        # RULE 1: Rapid-Fire
        alert = self._check_rapid_fire(now)
        if alert:
            return alert

        # RULE 2: Flip-Flop
        alert = self._check_flip_flop(now, direction)
        if alert:
            return alert

        # RULE 6: Abnormal Position Size
        alert = self._check_abnormal_size(now, margin, balance)
        if alert:
            return alert

        # RULE 7: Price Sanity
        alert = self._check_price_sanity(now, entry_price, current_price)
        if alert:
            return alert

        return None

    def check_post_trade(
        self,
        trade_history: list,  # list[TradeRecord]
        daily_fees: Decimal,
        daily_volume: Decimal,
    ) -> AnomalyAlert | None:
        """거래 종료 후 검사."""
        now = int(time.time() * 1000)

        # RULE 3: Fee Bleeding — 비활성화 (2026-04-26, 불필요한 halt 유발)
        # alert = self._check_fee_bleeding(now, trade_history)
        # if alert:
        #     return alert

        # RULE 5: Consecutive Losses
        alert = self._check_consecutive_losses(now, trade_history)
        if alert:
            return alert

        # RULE 8: Win Streak
        alert = self._check_win_streak(now, trade_history)
        if alert:
            return alert

        # RULE 10: Daily Fee Ratio
        alert = self._check_daily_fee_ratio(now, daily_fees, daily_volume)
        if alert:
            return alert

        return None

    def check_replacement(self) -> AnomalyAlert | None:
        """교체 발생 후 검사."""
        now = int(time.time() * 1000)
        return self._check_replacement_cascade(now)

    def check_heartbeat(self) -> AnomalyAlert | None:
        """주기적으로 호출 (예: 매 tick). 가격 데이터 이상 감지."""
        now = int(time.time() * 1000)
        return self._check_stale_price(now)

    # ────────────────────────────────────────────────────────────
    # Rule 구현
    # ────────────────────────────────────────────────────────────

    def _check_rapid_fire(self, now: int) -> AnomalyAlert | None:
        """RULE 1: 60초 내 6건 이상 주문."""
        window_start = now - self.config.rapidfire_window_sec * 1000
        recent = [ts for ts in self._order_timestamps if ts >= window_start]
        if len(recent) >= self.config.rapidfire_max_orders:
            return self._trigger(
                rule_name="rapid_fire",
                severity="CRITICAL",
                action=self.config.rapidfire_action,
                halt_sec=self.config.rapidfire_halt_sec,
                message=(
                    f"Rapid-fire detected: {len(recent)} orders in "
                    f"{self.config.rapidfire_window_sec}s "
                    f"(limit: {self.config.rapidfire_max_orders})"
                ),
                details={
                    "order_count": len(recent),
                    "window_sec": self.config.rapidfire_window_sec,
                    "timestamps": [t for t in recent[-6:]],
                },
                now=now,
            )
        return None

    def _check_flip_flop(self, now: int, next_direction: str) -> AnomalyAlert | None:
        """RULE 2: 2시간 내 방향전환 3회 이상.

        방향전환 = 직전 거래와 반대 방향.
        현재 들어오는 주문도 포함하여 카운트.
        """
        window_start = now - self.config.flipflop_window_sec * 1000
        recent = [(ts, d) for ts, d in self._direction_history if ts >= window_start]
        # 현재 주문 추가
        recent.append((now, next_direction))

        flips = 0
        for i in range(1, len(recent)):
            if recent[i][1] != recent[i - 1][1]:
                flips += 1

        if flips >= self.config.flipflop_max_flips:
            directions = [d for _, d in recent]
            return self._trigger(
                rule_name="flip_flop",
                severity="CRITICAL",
                action=self.config.flipflop_action,
                halt_sec=self.config.flipflop_halt_sec,
                message=(
                    f"Flip-flop detected: {flips} direction changes in "
                    f"{self.config.flipflop_window_sec // 3600}h "
                    f"(limit: {self.config.flipflop_max_flips}). "
                    f"Sequence: {' → '.join(directions[-6:])}"
                ),
                details={
                    "flip_count": flips,
                    "direction_sequence": directions,
                    "window_sec": self.config.flipflop_window_sec,
                },
                now=now,
            )
        return None

    def _check_fee_bleeding(self, now: int, trade_history: list) -> AnomalyAlert | None:
        """RULE 3: 최근 5건 중 4건 이상이 |PnL%| < 0.3%.

        수수료만 까먹는 '공회전' 상태.
        """
        n = self.config.feebleed_window_trades
        if len(trade_history) < n:
            return None
        recent = trade_history[-n:]
        near_zero_count = sum(
            1 for t in recent
            if abs(t.pnl_percent) < self.config.feebleed_pnl_threshold_pct
        )
        if near_zero_count >= self.config.feebleed_min_count:
            total_fees = sum(float(t.total_fees) for t in recent)
            total_pnl = sum(float(t.realized_pnl) for t in recent)
            return self._trigger(
                rule_name="fee_bleeding",
                severity="WARNING",
                action=self.config.feebleed_action,
                halt_sec=self.config.feebleed_halt_sec,
                message=(
                    f"Fee bleeding: {near_zero_count}/{n} recent trades have "
                    f"|PnL%| < {self.config.feebleed_pnl_threshold_pct}%. "
                    f"Net PnL: ${total_pnl:.2f}, Fees paid: ${total_fees:.2f}"
                ),
                details={
                    "near_zero_count": near_zero_count,
                    "window_trades": n,
                    "total_fees": total_fees,
                    "total_pnl": total_pnl,
                    "pnl_percents": [t.pnl_percent for t in recent],
                },
                now=now,
            )
        return None

    def _check_replacement_cascade(self, now: int) -> AnomalyAlert | None:
        """RULE 4: 1시간 내 교체 2회 이상."""
        window_start = now - self.config.cascade_window_sec * 1000
        recent = [ts for ts in self._replacement_timestamps if ts >= window_start]
        if len(recent) >= self.config.cascade_max_replacements:
            return self._trigger(
                rule_name="replacement_cascade",
                severity="CRITICAL",
                action=self.config.cascade_action,
                halt_sec=self.config.cascade_halt_sec,
                message=(
                    f"Replacement cascade: {len(recent)} replacements in "
                    f"{self.config.cascade_window_sec // 60}min "
                    f"(limit: {self.config.cascade_max_replacements})"
                ),
                details={
                    "replacement_count": len(recent),
                    "window_sec": self.config.cascade_window_sec,
                },
                now=now,
            )
        return None

    def _check_consecutive_losses(self, now: int, trade_history: list) -> AnomalyAlert | None:
        """RULE 5: 방향 무관 연속 N패."""
        n = self.config.consec_loss_count
        if len(trade_history) < n:
            return None
        recent = trade_history[-n:]
        all_losses = all(t.realized_pnl < 0 for t in recent)
        if all_losses:
            total_loss = sum(float(t.realized_pnl) for t in recent)
            return self._trigger(
                rule_name="consecutive_losses",
                severity="CRITICAL",
                action=self.config.consec_loss_action,
                halt_sec=self.config.consec_loss_halt_sec,
                message=(
                    f"Consecutive losses: {n} losses in a row. "
                    f"Total loss: ${total_loss:.2f}. "
                    f"Strategy may be mismatched with current market."
                ),
                details={
                    "loss_count": n,
                    "total_loss": total_loss,
                    "losses": [
                        {"pnl": float(t.realized_pnl), "pnl_pct": t.pnl_percent, "side": t.side.value}
                        for t in recent
                    ],
                },
                now=now,
            )
        return None

    def _check_abnormal_size(
        self, now: int, margin: Decimal, balance: Decimal,
    ) -> AnomalyAlert | None:
        """RULE 6: 마진이 잔고의 50% 초과."""
        if balance <= 0:
            return None
        pct = float(margin / balance * 100)
        if pct > self.config.abnormal_size_max_pct:
            return self._trigger(
                rule_name="abnormal_position_size",
                severity="EMERGENCY",
                action=self.config.abnormal_size_action,
                halt_sec=0,  # manual halt
                message=(
                    f"ABNORMAL POSITION SIZE: margin ${margin:.2f} = "
                    f"{pct:.1f}% of balance ${balance:.2f} "
                    f"(limit: {self.config.abnormal_size_max_pct}%). "
                    f"Possible calculation bug. MANUAL REVIEW REQUIRED."
                ),
                details={
                    "margin": float(margin),
                    "balance": float(balance),
                    "margin_pct": pct,
                    "limit_pct": self.config.abnormal_size_max_pct,
                },
                now=now,
                manual=True,
            )
        return None

    def _check_price_sanity(
        self, now: int, entry_price: Decimal, current_price: Decimal,
    ) -> AnomalyAlert | None:
        """RULE 7: 진입가가 현재가에서 ±3% 이상 벗어남."""
        if current_price <= 0:
            return None
        deviation_pct = abs(float((entry_price - current_price) / current_price * 100))
        if deviation_pct > self.config.price_deviation_max_pct:
            return self._trigger(
                rule_name="price_sanity",
                severity="EMERGENCY",
                action=self.config.price_sanity_action,
                halt_sec=0,  # manual halt
                message=(
                    f"PRICE SANITY FAILURE: entry ${entry_price:.2f} is "
                    f"{deviation_pct:.1f}% away from market ${current_price:.2f} "
                    f"(limit: ±{self.config.price_deviation_max_pct}%). "
                    f"Possible data corruption. MANUAL REVIEW REQUIRED."
                ),
                details={
                    "entry_price": float(entry_price),
                    "current_price": float(current_price),
                    "deviation_pct": deviation_pct,
                    "limit_pct": self.config.price_deviation_max_pct,
                },
                now=now,
                manual=True,
            )
        return None

    def _check_win_streak(self, now: int, trade_history: list) -> AnomalyAlert | None:
        """RULE 8: 7연승 이상 → 사이즈 축소 (과적합 경계)."""
        n = self.config.win_streak_threshold
        if len(trade_history) < n:
            return None
        recent = trade_history[-n:]
        all_wins = all(t.realized_pnl > 0 for t in recent)
        if all_wins:
            self._size_reduction_active = True
            return self._trigger(
                rule_name="win_streak_overconfidence",
                severity="WARNING",
                action=self.config.win_streak_action,
                halt_sec=0,
                message=(
                    f"Win streak guard: {n}+ consecutive wins. "
                    f"Reducing position size to 50% as precaution. "
                    f"Will auto-restore after next loss."
                ),
                details={
                    "win_count": n,
                    "recent_pnls": [float(t.realized_pnl) for t in recent],
                },
                now=now,
            )
        else:
            # 연승 끊김 → 복구
            if self._size_reduction_active:
                self._size_reduction_active = False
                logger.info("Win streak guard lifted (streak broken)")
        return None

    def _check_stale_price(self, now: int) -> AnomalyAlert | None:
        """RULE 9: 2분간 가격 업데이트 없음 → 거래소 연결 문제."""
        elapsed_sec = (now - self._last_price_update_ms) / 1000
        if elapsed_sec > self.config.stale_price_max_sec:
            return self._trigger(
                rule_name="stale_price",
                severity="CRITICAL",
                action=self.config.stale_price_action,
                halt_sec=self.config.stale_price_halt_sec,
                message=(
                    f"Stale price data: no price update for "
                    f"{elapsed_sec:.0f}s (limit: {self.config.stale_price_max_sec}s). "
                    f"Exchange connection may be down."
                ),
                details={
                    "elapsed_sec": elapsed_sec,
                    "last_update_ms": self._last_price_update_ms,
                    "limit_sec": self.config.stale_price_max_sec,
                },
                now=now,
            )
        return None

    def _check_daily_fee_ratio(
        self, now: int, daily_fees: Decimal, daily_volume: Decimal,
    ) -> AnomalyAlert | None:
        """RULE 10: 당일 수수료/거래대금 비율 과다."""
        if daily_volume <= 0:
            return None
        ratio_pct = float(daily_fees / daily_volume * 100)
        if ratio_pct > self.config.daily_fee_ratio_max_pct:
            return self._trigger(
                rule_name="daily_fee_ratio",
                severity="WARNING",
                action=self.config.daily_fee_ratio_action,
                halt_sec=0,
                message=(
                    f"High fee ratio: ${daily_fees:.2f} fees on "
                    f"${daily_volume:.2f} volume = {ratio_pct:.2f}% "
                    f"(limit: {self.config.daily_fee_ratio_max_pct}%). "
                    f"Consider reducing trade frequency."
                ),
                details={
                    "daily_fees": float(daily_fees),
                    "daily_volume": float(daily_volume),
                    "ratio_pct": ratio_pct,
                },
                now=now,
            )
        return None

    # ────────────────────────────────────────────────────────────
    # 내부: trigger → halt + alert 생성
    # ────────────────────────────────────────────────────────────

    def _trigger(
        self,
        rule_name: str,
        severity: str,
        action: AnomalyAction,
        halt_sec: int,
        message: str,
        details: dict,
        now: int,
        manual: bool = False,
    ) -> AnomalyAlert:
        """이상 감지 트리거. halt 설정 + alert 객체 생성."""

        # 중복 알림 방지
        last = self._last_alert_by_rule.get(rule_name, 0)
        is_duplicate = (now - last) < self._alert_cooldown_sec * 1000

        halt_until = 0

        if action == AnomalyAction.HALT_MANUAL or manual:
            self._manual_halt = True
            self._halt_reason = f"[{rule_name}] {message}"
            logger.critical(f"MANUAL HALT: {message}")
        elif action in (AnomalyAction.HALT_SHORT, AnomalyAction.HALT_LONG):
            halt_until = now + halt_sec * 1000
            if halt_until > self._halt_until:
                self._halt_until = halt_until
                self._halt_reason = f"[{rule_name}] {message}"
            logger.warning(f"AUTO HALT ({halt_sec}s): {message}")
        elif action == AnomalyAction.REDUCE:
            self._size_reduction_active = True
            logger.warning(f"SIZE REDUCTION: {message}")
        elif action == AnomalyAction.ALERT:
            logger.warning(f"ANOMALY ALERT: {message}")

        self._last_alert_by_rule[rule_name] = now

        alert = AnomalyAlert(
            rule_name=rule_name,
            severity=severity,
            action_taken=action,
            message=message,
            details=details,
            halt_until=halt_until,
            requires_manual_resume=manual,
            timestamp=now,
        )

        if not is_duplicate:
            logger.info(f"Anomaly alert created: [{severity}] {rule_name}")

        return alert
