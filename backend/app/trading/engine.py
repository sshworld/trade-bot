"""Paper Trading Engine.

파라미터는 2026-04-08 Buffett×Dimon 회의록 기준.
변경 시 반드시 전문가 토론 → 회의록 → 승인.
"""

import asyncio
import logging
import time
import uuid
from decimal import Decimal, ROUND_DOWN

from app.trading.schemas import (
    AccountState,
    OrderStatus,
    Position,
    PositionSide,
    TradeTier,
    TradeRecord,
    TradingSettings,
    TrendContext,
    TrancheOrder,
    get_tf_atr_params,
)
from app.analysis.trend_filter import classify_trade
from app.trading.persistence import (
    save_trade, load_trades, save_account, load_account,
    save_daily_snapshot, save_position, delete_position, load_positions,
    clear_positions, reset_all,
)
from app.trading.anomaly_detector import AnomalyDetector, AnomalyConfig
from app.trading.alert_sender import AlertSender
from app.config import settings

logger = logging.getLogger(__name__)


class PaperTradingEngine:
    def __init__(self):
        self.settings = TradingSettings()
        self.open_positions: dict[str, Position] = {}
        self._lock = asyncio.Lock()
        self._last_price: Decimal | None = None
        self._recent_signals: dict[str, int] = {}
        self._trend_context: TrendContext = TrendContext()
        self._halt_until: int = 0

        # 행동 이상 감지기
        self.anomaly_detector = AnomalyDetector(AnomalyConfig())
        self.alert_sender = AlertSender(
            telegram_bot_token=settings.alert_telegram_bot_token,
            telegram_chat_id=settings.alert_telegram_chat_id,
            webhook_url=settings.alert_webhook_url,
        )

        # DB에서 복원
        saved_account = load_account()
        self.account = saved_account if saved_account else AccountState()
        self.trade_history: list[TradeRecord] = load_trades()
        self.open_positions = load_positions()

        if self.open_positions:
            logger.info(f"Restored {len(self.open_positions)} open positions from DB")
        elif saved_account:
            self.account.margin_used = Decimal("0")
            self.account.unrealized_pnl = Decimal("0")
            self.account.equity = self.account.balance

    def update_trend_context(self, ctx: TrendContext):
        self._trend_context = ctx

    # ── Signal → Position ──────────────────────────────────────────

    async def on_signal(self, signal: dict, current_price: Decimal) -> Position | None:
        async with self._lock:
            now = int(time.time() * 1000)

            # ── 일일 리셋 (자정 기준) ──
            self._check_daily_reset(now)

            # ── 중단 상태 체크 ──
            if now < self._halt_until:
                return None

            # ── 행동 이상 감지기 halt 체크 ──
            if self.anomaly_detector.is_halted():
                return None

            # 고점 대비 drawdown 체크
            if self.account.peak_equity > 0:
                dd = (self.account.peak_equity - self.account.equity) / self.account.peak_equity * 100
                if dd >= Decimal(str(self.settings.drawdown_halt_pct)):
                    logger.warning(f"Drawdown halt: {dd:.1f}% from peak")
                    # 당일 중단 (다음 날 리셋)
                    today_end = (int(time.time() // 86400) + 1) * 86400 * 1000
                    self._halt_until = today_end
                    return None

            # 일일 손실 체크 (당일 00시 잔고 기준)
            daily_base = self.account.daily_start_balance if self.account.daily_start_balance > 0 else self.account.initial_capital
            daily_loss_pct = float(-self.account.daily_pnl / daily_base * 100) if self.account.daily_pnl < 0 else 0.0
            if daily_loss_pct >= self.settings.daily_loss_tier2_pct:
                today_end = (int(time.time() // 86400) + 1) * 86400 * 1000
                self._halt_until = today_end
                logger.info(f"Daily loss -{daily_loss_pct:.1f}% >= {self.settings.daily_loss_tier2_pct}%, stopped for today")
                return None

            # 속도 제한: 60분 내 3연속 SL → 30분 일시 중단
            recent_sl = [
                t for t in self.trade_history[-10:]
                if t.close_reason == "stop_loss" and now - t.closed_at < self.settings.velocity_window_ms
            ]
            if len(recent_sl) >= self.settings.velocity_max_consecutive_sl:
                self._halt_until = now + self.settings.velocity_pause_ms
                logger.info(f"Velocity brake: {len(recent_sl)} SLs in {self.settings.velocity_window_ms//60000}min, pausing {self.settings.velocity_pause_ms//60000}min")
                return None

            # 시그널 중복 방지
            expired = [k for k, t in self._recent_signals.items() if now - t > 600_000]
            for k in expired:
                del self._recent_signals[k]
            sig_key = f"{signal['type']}_{signal['direction']}"
            if sig_key in self._recent_signals:
                if now - self._recent_signals[sig_key] < 300_000:
                    return None
            self._recent_signals[sig_key] = now

            side = PositionSide.LONG if signal["direction"] == "bullish" else PositionSide.SHORT
            is_consensus = signal.get("type", "").startswith("consensus_override")
            signal_tf = signal.get("timeframe", "1h")

            # 연속 SL 쿨다운
            recent_same_dir = [
                t for t in self.trade_history[-10:]
                if t.side == side and t.close_reason == "stop_loss"
            ]
            if len(recent_same_dir) >= 2:
                if now - recent_same_dir[-1].closed_at < 1_800_000:
                    logger.info(f"Cooldown: {side.value} blocked after 2 consecutive SLs")
                    return None

            # ── 기존 포지션 처리 ──
            if self.open_positions:
                pos = list(self.open_positions.values())[0]

                if pos.side == side:
                    # 같은 방향 → SL 조정만
                    self._tighten_sl_on_confirmation(pos, current_price)
                    return None
                else:
                    # 반대 방향 → 교체 판단
                    if not self._should_replace(pos, current_price, now, signal):
                        return None
                    # 교체 실행
                    trade = self._close_position(list(self.open_positions.keys())[0], current_price, "replaced_by_signal")
                    self.account.daily_replacements += 1
                    self.account.last_replacement_at = now
                    self.anomaly_detector.record_replacement(now)
                    logger.info(f"Position replaced: {trade.side.value} PnL={trade.realized_pnl}")

                    # 교체 cascade 검사
                    cascade_alert = self.anomaly_detector.check_replacement()
                    if cascade_alert:
                        asyncio.create_task(self.alert_sender.send(cascade_alert))
                        if cascade_alert.action_taken.value != "alert":
                            return None
            elif len(self.open_positions) >= self.settings.max_open_positions:
                return None

            # ── Tier 분류 ──
            if is_consensus:
                tier = classify_trade(signal["direction"], signal_tf, self._trend_context)
                if tier == TradeTier.BLOCKED:
                    return None
                tier_name = "consensus"
            else:
                tier = classify_trade(signal["direction"], signal_tf, self._trend_context)
                if tier == TradeTier.BLOCKED:
                    logger.info(f"BLOCKED: {signal['direction']} on {signal_tf}")
                    return None
                tier_name = tier.value

            is_counter = tier_name in ("counter_trend", "consensus")

            # Counter-trend 추가 검증
            if is_counter and not is_consensus:
                ct = self.settings.counter_trend
                details = signal.get("details", {})
                indicators = details.get("indicators", [])
                strong_triggers = sum(1 for ind in indicators if ind.get("weight", 0) >= 1.5)
                if strong_triggers < ct.min_strong_triggers:
                    return None
                tf_threshold = details.get("threshold", {})
                net_score = details.get("net_score", 0)
                if net_score < (tf_threshold.get("min_net", 2.0) + ct.extra_min_score):
                    return None

            # ── TF별 파라미터 ──
            # ATR 기반 TP/SL 파라미터
            atr_params = get_tf_atr_params(signal_tf)
            strength = signal.get("strength", 0.5)
            leverage = self._calculate_leverage(strength)

            # ATR 계산
            atr = self._get_atr(signal_tf)
            if atr <= 0:
                atr = float(current_price) * 0.01  # fallback: 가격의 1%

            # 일일 손실 -3%~-5% → 사이즈 절반
            size_multiplier = Decimal("1.0")
            if daily_loss_pct >= self.settings.daily_loss_tier1_pct:
                size_multiplier = Decimal("0.5")
                leverage = self.settings.min_leverage

            # ATR 기반 SL 계산 (가격 기준)
            sl_distance = atr * atr_params.sl_atr
            # ATR 가드레일 적용
            sl_distance = max(sl_distance, atr * self.settings.atr_sl_min_multiple)
            sl_distance = min(sl_distance, atr * self.settings.atr_sl_max_multiple)

            # 리스크 기반 사이즈: 2% 리스크 역산
            risk_amount = self.account.balance * Decimal(str(self.settings.risk_per_trade_pct / 100)) * size_multiplier
            if sl_distance <= 0:
                return None
            position_notional = risk_amount / Decimal(str(sl_distance / float(current_price)))
            position_notional = position_notional.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            if position_notional < 100:
                return None

            margin = (position_notional / leverage).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            total_qty = (position_notional / current_price).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
            if total_qty <= 0:
                return None

            pos_id = str(uuid.uuid4())[:8]

            # 진입: WITH_TREND은 확인 추가, COUNTER는 소폭 물타기
            if is_counter:
                entry_offsets = self.settings.counter_trend.entry_offsets
                entry_split = self.settings.counter_trend.entry_split
            else:
                entry_offsets = self.settings.entry_offsets
                entry_split = self.settings.entry_split

            entry_tranches = self._create_entry_tranches(
                side, current_price, total_qty, pos_id, now,
                offsets_override=entry_offsets, split_override=entry_split,
            )

            # SL 가격 계산
            sl_decimal = Decimal(str(sl_distance))
            if side == PositionSide.LONG:
                stop_loss = (current_price - sl_decimal).quantize(Decimal("0.01"))
            else:
                stop_loss = (current_price + sl_decimal).quantize(Decimal("0.01"))

            signal_details = signal.get("details") or {}
            signal_details["trade_tier"] = tier_name
            signal_details["higher_tf_trend"] = dict(self._trend_context.tf_directions)

            tier_label = tier_name.upper().replace("_", " ")

            position = Position(
                id=pos_id,
                side=side,
                leverage=leverage,
                signal_type=signal["type"],
                signal_strength=strength,
                signal_message=f"[{tier_label}] {signal.get('message', '')}",
                signal_details=signal_details,
                entry_tranches=entry_tranches,
                exit_tranches=[],
                stop_loss_price=stop_loss,
                allocated_quantity=total_qty,
                allocated_margin=margin,
                tp_levels=[atr_params.tp1_atr, atr_params.tp2_atr, atr_params.tp3_atr],
                exit_split=atr_params.exit_split,
                sl_atr_multiple=atr_params.sl_atr,
                timeframe=signal_tf,
                opened_at=now,
            )

            self.account.balance -= margin
            self.account.margin_used += margin
            self.open_positions[pos_id] = position

            # 첫 tranche 즉시 체결 (taker)
            first = entry_tranches[0]
            first.status = OrderStatus.FILLED
            first.filled_price = current_price
            first.filled_at = now
            fee = self._calc_fee(current_price, first.quantity, is_market=True)
            position.total_fees += fee
            self.account.balance -= fee
            self.account.total_fees += fee
            self._recalculate_position(position)

            self.account.daily_trades += 1
            save_position(position)
            save_account(self.account)
            logger.info(
                f"Position opened [{tier_name}]: {side.value} {total_qty} @ ~{current_price} "
                f"(lev:{leverage}x, TF:{signal_tf}, SL:{tf_params.sl_pct}%, TP:{tf_params.tp_levels})"
            )
            return position

    # ── Tick → Fill Check ──────────────────────────────────────────

    async def on_price_update(self, price: Decimal) -> list[dict]:
        self._last_price = price
        self.anomaly_detector.record_price_update(int(time.time() * 1000))
        if not self.open_positions:
            return []

        async with self._lock:
            events: list[dict] = []
            positions_to_close: list[tuple[str, str]] = []

            for pos_id, pos in self.open_positions.items():
                # 진입 tranche 체결
                for tranche in pos.entry_tranches:
                    if tranche.status != OrderStatus.PENDING:
                        continue
                    if self._should_fill_entry(tranche, price):
                        tranche.status = OrderStatus.FILLED
                        tranche.filled_price = price
                        tranche.filled_at = int(time.time() * 1000)
                        fee = self._calc_fee(price, tranche.quantity, is_market=False)
                        pos.total_fees += fee
                        self.account.balance -= fee
                        self.account.total_fees += fee
                        self._recalculate_position(pos)
                        save_position(pos)

                        filled_entries = sum(1 for t in pos.entry_tranches if t.status == OrderStatus.FILLED)
                        if filled_entries == len(pos.entry_tranches):
                            pos.status = "open"

                        events.append({
                            "type": "tranche_filled",
                            "data": {
                                "position_id": pos_id,
                                "is_entry": True,
                                "filled_price": str(price),
                                "quantity": str(tranche.quantity),
                                "filled_count": filled_entries,
                                "total_count": len(pos.entry_tranches),
                                "message": f"분할매수 {filled_entries}/{len(pos.entry_tranches)} 체결 @ ${price:,.2f}",
                            },
                        })

                # 청산 tranche 체결
                for tranche in pos.exit_tranches:
                    if tranche.status != OrderStatus.PENDING:
                        continue
                    if self._should_fill_exit(tranche, price):
                        tranche.status = OrderStatus.FILLED
                        tranche.filled_price = price
                        tranche.filled_at = int(time.time() * 1000)
                        pnl = self._calc_tranche_pnl(pos, tranche)
                        pos.realized_pnl += pnl
                        fee = self._calc_fee(price, tranche.quantity, is_market=False)
                        pos.total_fees += fee
                        self.account.balance -= fee
                        self.account.total_fees += fee

                        filled_exits = sum(1 for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
                        total_exits = len(pos.exit_tranches)

                        # 트레일링 SL
                        self._trailing_sl_after_tp(pos, filled_exits)
                        save_position(pos)

                        events.append({
                            "type": "tranche_filled",
                            "data": {
                                "position_id": pos_id,
                                "is_entry": False,
                                "filled_price": str(price),
                                "quantity": str(tranche.quantity),
                                "filled_count": filled_exits,
                                "total_count": total_exits,
                                "new_sl": str(pos.stop_loss_price),
                                "message": f"분할매도 {filled_exits}/{total_exits} 익절 @ ${price:,.2f} (SL→${pos.stop_loss_price:,.2f})",
                            },
                        })

                        if filled_exits == total_exits:
                            positions_to_close.append((pos_id, "take_profit"))

                # 동적 트레일링 (TP2 이후 매 tick)
                self._update_dynamic_trailing(pos, price)

                # 시간 기반 청산
                if pos.avg_entry_price and pos.status in ("opening", "open"):
                    time_action = self._check_time_exit(pos, int(time.time() * 1000))
                    if time_action == "time_exit":
                        positions_to_close.append((pos_id, "time_exit"))
                    elif time_action == "tighten_sl":
                        be = self._breakeven_price(pos)
                        atr = self._get_atr(pos.timeframe)
                        if atr > 0:
                            bump = Decimal(str(atr * 0.5))
                            if pos.side == PositionSide.LONG:
                                new_sl = be + bump
                                if new_sl > pos.stop_loss_price:
                                    pos.stop_loss_price = new_sl.quantize(Decimal("0.01"))
                            else:
                                new_sl = be - bump
                                if new_sl < pos.stop_loss_price:
                                    pos.stop_loss_price = new_sl.quantize(Decimal("0.01"))

                # 손절 체크
                if pos.avg_entry_price and pos.status in ("opening", "open"):
                    if self._should_stop_loss(pos, price):
                        filled_tp = sum(1 for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
                        reason = "breakeven" if filled_tp > 0 else "stop_loss"
                        positions_to_close.append((pos_id, reason))

            for pos_id, reason in positions_to_close:
                if pos_id in self.open_positions:
                    trade = self._close_position(pos_id, price, reason)
                    events.append({
                        "type": "trade_closed",
                        "data": {
                            "position_id": pos_id,
                            "reason": reason,
                            "realized_pnl": str(trade.realized_pnl),
                            "pnl_percent": trade.pnl_percent,
                            "message": (
                                f"{'롱' if trade.side == PositionSide.LONG else '숏'} 포지션 종료 "
                                f"({'익절' if reason == 'take_profit' else '본전' if reason == 'breakeven' else '손절'}) "
                                f"PnL: {'+'if trade.realized_pnl >= 0 else ''}${trade.realized_pnl:.2f} ({trade.pnl_percent:+.2f}%)"
                            ),
                        },
                    })

            self._update_account(price)

            if events:
                events.append({"type": "account_update", "data": self.get_status()})

            return events

    # ── Position Close ─────────────────────────────────────────────

    def _close_position(self, pos_id: str, price: Decimal, reason: str) -> TradeRecord:
        pos = self.open_positions.pop(pos_id)
        now = int(time.time() * 1000)
        pos.status = "closed"
        pos.closed_at = now

        remaining_qty = Decimal("0")
        for t in pos.exit_tranches:
            if t.status == OrderStatus.PENDING:
                t.status = OrderStatus.CANCELLED
                remaining_qty += t.quantity
        for t in pos.entry_tranches:
            if t.status == OrderStatus.PENDING:
                t.status = OrderStatus.CANCELLED

        if remaining_qty > 0 and pos.avg_entry_price:
            pnl = self._calc_pnl(pos.side, pos.avg_entry_price, price, remaining_qty, pos.leverage)
            pos.realized_pnl += pnl
            fee = self._calc_fee(price, remaining_qty, is_market=True)
            pos.total_fees += fee
            self.account.balance -= fee
            self.account.total_fees += fee

        margin = pos.allocated_margin
        self.account.balance += margin + pos.realized_pnl
        self.account.margin_used -= margin
        self.account.total_realized_pnl += pos.realized_pnl
        self.account.daily_pnl += pos.realized_pnl
        self.account.total_trades += 1
        if pos.realized_pnl > 0:
            self.account.winning_trades += 1

        filled_exits = [t for t in pos.exit_tranches if t.status == OrderStatus.FILLED]
        if filled_exits:
            total_val = sum(t.filled_price * t.quantity for t in filled_exits)
            total_qty = sum(t.quantity for t in filled_exits)
            avg_exit = (total_val / total_qty).quantize(Decimal("0.01"))
        else:
            avg_exit = price

        if remaining_qty > 0 and pos.total_quantity > 0:
            total_val = avg_exit * (pos.total_quantity - remaining_qty) + price * remaining_qty
            avg_exit = (total_val / pos.total_quantity).quantize(Decimal("0.01"))

        pnl_margin = pos.allocated_margin if pos.allocated_margin > 0 else Decimal("1")
        pnl_pct = float(pos.realized_pnl / pnl_margin * 100)

        trade = TradeRecord(
            id=pos.id, symbol=pos.symbol, side=pos.side, leverage=pos.leverage,
            avg_entry_price=pos.avg_entry_price or price,
            avg_exit_price=avg_exit, quantity=pos.total_quantity,
            realized_pnl=pos.realized_pnl, pnl_percent=round(pnl_pct, 2),
            signal_type=pos.signal_type, signal_message=pos.signal_message,
            signal_details=pos.signal_details, close_reason=reason,
            total_fees=pos.total_fees, opened_at=pos.opened_at,
            closed_at=now, duration_seconds=int((now - pos.opened_at) / 1000),
        )
        self.trade_history.append(trade)
        # DB: 거래 기록 저장, 포지션 삭제, 계좌 저장
        save_trade(trade)
        delete_position(pos.id)
        save_account(self.account)

        # ── 행동 이상 감지: 거래 종료 후 검사 ──
        daily_volume = sum(
            abs(t.avg_entry_price * t.quantity)
            for t in self.trade_history
            if t.closed_at >= (int(time.time() // 86400) * 86400 * 1000)
        )
        post_alert = self.anomaly_detector.check_post_trade(
            trade_history=self.trade_history,
            daily_fees=self.account.total_fees,
            daily_volume=Decimal(str(daily_volume)) if daily_volume else Decimal("0"),
        )
        if post_alert:
            asyncio.create_task(self.alert_sender.send(post_alert))

        return trade

    # ── Helpers ─────────────────────────────────────────────────────

    def _check_daily_reset(self, now: int):
        """자정 리셋. 당일 시작 잔고 스냅샷."""
        today_start = int(time.time() // 86400) * 86400 * 1000
        if self.account.last_daily_reset < today_start:
            # 전일 스냅샷 저장
            if self.account.last_daily_reset > 0:
                import datetime
                yesterday = (datetime.datetime.utcfromtimestamp(self.account.last_daily_reset / 1000)).strftime("%Y-%m-%d")
                close_bal = self.account.balance + self.account.margin_used
                save_daily_snapshot(
                    yesterday,
                    str(self.account.daily_start_balance),
                    str(close_bal),
                    str(self.account.daily_pnl),
                    self.account.daily_trades,
                    str(self.account.total_fees),
                )

            # 신규 일일 리셋
            self.account.daily_start_balance = self.account.balance + self.account.margin_used
            self.account.daily_pnl = Decimal("0")
            self.account.daily_trades = 0
            self.account.daily_replacements = 0
            self.account.last_daily_reset = today_start
            save_account(self.account)

    def _should_replace(self, pos: Position, current_price: Decimal, now: int, new_signal: dict | None = None) -> bool:
        """교체 조건: PnL < 0 AND 새 시그널이 기존보다 강해야."""
        # 쿨다운 20분
        if now - self.account.last_replacement_at < self.settings.replacement_cooldown_ms:
            return False

        # 같은 시그널 패밀리 8시간 차단
        if new_signal:
            new_type = new_signal.get("type", "")
            if new_type == pos.signal_type and now - pos.opened_at < self.settings.same_signal_block_ms:
                return False

        if not pos.avg_entry_price or pos.allocated_margin <= 0:
            return True

        unrealized = self._calc_pnl(pos.side, pos.avg_entry_price, current_price, pos.total_quantity, pos.leverage)
        pnl_pct = float(unrealized / pos.allocated_margin * 100)

        # PnL < 0 (손실 중)이어야 교체 가능
        if pnl_pct >= 0:
            return False

        # 새 시그널 강도 > 기존 + 0.5
        if new_signal:
            new_strength = new_signal.get("strength", 0)
            if new_strength < pos.signal_strength + self.settings.replacement_min_score_diff:
                return False

        return True

    def _breakeven_price(self, pos: Position) -> Decimal:
        """수수료 포함 진짜 본전가 계산.

        LONG: 진입가 + 왕복 수수료 (가격 기준)
        SHORT: 진입가 - 왕복 수수료
        """
        # 진입은 첫 tranche taker, 나머지 maker. 청산(SL)은 taker.
        # 간단하게: 진입 taker + 청산 taker 로 계산 (보수적)
        entry_fee_pct = Decimal(str(self.settings.fee_taker_pct / pos.leverage / 100))
        exit_fee_pct = Decimal(str(self.settings.fee_taker_pct / pos.leverage / 100))
        total_fee_pct = entry_fee_pct + exit_fee_pct

        if pos.side == PositionSide.LONG:
            return (pos.avg_entry_price * (1 + total_fee_pct)).quantize(Decimal("0.01"))
        return (pos.avg_entry_price * (1 - total_fee_pct)).quantize(Decimal("0.01"))

    def _tighten_sl_on_confirmation(self, pos: Position, current_price: Decimal):
        """같은 방향 시그널 → SL 조임. 회의록 기준."""
        if not pos.avg_entry_price or pos.allocated_margin <= 0:
            return

        unrealized = self._calc_pnl(pos.side, pos.avg_entry_price, current_price, pos.total_quantity, pos.leverage)
        pnl_pct = float(unrealized / pos.allocated_margin * 100)

        if pnl_pct < 1.5:
            return  # 1.5% 미만이면 무시
        elif pnl_pct < 3.0:
            new_sl = self._breakeven_price(pos)  # 수수료 포함 본전
        else:
            # 50% 잠금
            if pos.side == PositionSide.LONG:
                move = current_price - pos.avg_entry_price
                new_sl = pos.avg_entry_price + move * Decimal("0.5")
            else:
                move = pos.avg_entry_price - current_price
                new_sl = pos.avg_entry_price - move * Decimal("0.5")

        new_sl = new_sl.quantize(Decimal("0.01"))
        if pos.side == PositionSide.LONG and new_sl > pos.stop_loss_price:
            pos.stop_loss_price = new_sl
        elif pos.side == PositionSide.SHORT and new_sl < pos.stop_loss_price:
            pos.stop_loss_price = new_sl

    def _trailing_sl_after_tp(self, pos: Position, filled_exits: int):
        """TP 체결 후 트레일링. TP1→본전, TP2→TP1, TP3→동적 트레일."""
        total_exits = len(pos.exit_tranches)
        if filled_exits >= total_exits:
            return

        filled_exit_list = [t for t in pos.exit_tranches if t.status == OrderStatus.FILLED]

        if filled_exits == 1:
            new_sl = self._breakeven_price(pos)
        elif filled_exits >= 2 and len(filled_exit_list) >= 2:
            sorted_prices = sorted(
                [t.filled_price for t in filled_exit_list],
                key=lambda p: p if pos.side == PositionSide.LONG else -p,
            )
            new_sl = sorted_prices[0]
        else:
            return

        new_sl = new_sl.quantize(Decimal("0.01"))
        if pos.side == PositionSide.LONG and new_sl > pos.stop_loss_price:
            pos.stop_loss_price = new_sl
        elif pos.side == PositionSide.SHORT and new_sl < pos.stop_loss_price:
            pos.stop_loss_price = new_sl

    def _update_dynamic_trailing(self, pos: Position, price: Decimal):
        """TP2 이후 남은 30% 포지션 동적 트레일링. 매 tick 호출."""
        filled_exits = sum(1 for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
        if filled_exits < 2:
            return  # TP2 전이면 동적 트레일 안 함

        atr = self._get_atr(pos.timeframe)
        if atr <= 0:
            return

        # 최고/최저가 추적
        if pos.side == PositionSide.LONG:
            if pos.highest_price is None or price > pos.highest_price:
                pos.highest_price = price
            highest = pos.highest_price

            # 수익이 5×ATR 초과면 1×ATR로 조임, 아니면 2×ATR
            profit_in_atr = float(highest - pos.avg_entry_price) / atr if pos.avg_entry_price else 0
            trail = atr * (1.0 if profit_in_atr > 5 else 2.0)
            new_sl = (highest - Decimal(str(trail))).quantize(Decimal("0.01"))

            # TP1 가격 하한
            tp1_prices = [t.filled_price for t in pos.exit_tranches if t.status == OrderStatus.FILLED]
            if tp1_prices:
                floor = min(tp1_prices)
                new_sl = max(new_sl, floor)

            if new_sl > pos.stop_loss_price:
                pos.stop_loss_price = new_sl
        else:
            if pos.lowest_price is None or price < pos.lowest_price:
                pos.lowest_price = price
            lowest = pos.lowest_price

            profit_in_atr = float(pos.avg_entry_price - lowest) / atr if pos.avg_entry_price else 0
            trail = atr * (1.0 if profit_in_atr > 5 else 2.0)
            new_sl = (lowest + Decimal(str(trail))).quantize(Decimal("0.01"))

            tp1_prices = [t.filled_price for t in pos.exit_tranches if t.status == OrderStatus.FILLED]
            if tp1_prices:
                ceiling = max(tp1_prices)
                new_sl = min(new_sl, ceiling)

            if new_sl < pos.stop_loss_price:
                pos.stop_loss_price = new_sl

        # SL보다 불리한 pending entry 취소
        for et in pos.entry_tranches:
            if et.status != OrderStatus.PENDING:
                continue
            if pos.side == PositionSide.LONG and et.target_price <= pos.stop_loss_price:
                et.status = OrderStatus.CANCELLED
            elif pos.side == PositionSide.SHORT and et.target_price >= pos.stop_loss_price:
                et.status = OrderStatus.CANCELLED

    def _calculate_leverage(self, strength: float) -> int:
        s = self.settings
        return int(s.min_leverage + strength * (s.max_leverage - s.min_leverage))

    def _calculate_position_size_risk_based(
        self, leverage: int, sl_margin_pct: float, size_mult: Decimal = Decimal("1"),
    ) -> Decimal:
        """리스크 기반 사이즈: 거래당 자본의 2% 리스크."""
        risk_amount = self.account.balance * Decimal(str(self.settings.risk_per_trade_pct / 100)) * size_mult
        # risk_amount = notional × (sl_margin_pct / leverage / 100)
        # → notional = risk_amount / (sl_margin_pct / leverage / 100)
        sl_price_pct = sl_margin_pct / leverage
        if sl_price_pct <= 0:
            return Decimal("0")
        notional = risk_amount / Decimal(str(sl_price_pct / 100))
        return notional.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    def _create_entry_tranches(
        self, side: PositionSide, base_price: Decimal, total_qty: Decimal,
        pos_id: str, now: int, offsets_override: list[float] | None = None,
        split_override: list[float] | None = None,
    ) -> list[TrancheOrder]:
        offsets = offsets_override or self.settings.entry_offsets
        splits = split_override or self.settings.entry_split
        tranches = []
        for i, (split, offset) in enumerate(zip(splits, offsets)):
            qty = (total_qty * Decimal(str(split))).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
            if i == len(splits) - 1:
                qty = total_qty - sum(t.quantity for t in tranches)
            if side == PositionSide.LONG:
                target = base_price * (1 + Decimal(str(offset / 100)))
            else:
                target = base_price * (1 - Decimal(str(offset / 100)))
            tranches.append(TrancheOrder(
                id=f"{pos_id}-e{i}", position_id=pos_id, side=side, is_entry=True,
                target_price=target.quantize(Decimal("0.01")), quantity=qty, created_at=now,
            ))
        return tranches

    def _create_exit_tranches(
        self, side: PositionSide, avg_entry: Decimal, total_qty: Decimal,
        pos_id: str, now: int, tp_atr_multiples: list[float] | None = None,
        exit_split: list[float] | None = None, leverage: int = 5,
        tf: str = "1h",
    ) -> list[TrancheOrder]:
        """ATR 기반 TP. tp_atr_multiples=[1.5, 3.0, 999.0] → 999=트레일링(매우 먼 가격)."""
        tp_multiples = tp_atr_multiples or [1.5, 3.0, 999.0]
        split = exit_split or [0.40, 0.30, 0.30]
        atr = self._get_atr(tf)
        if atr <= 0:
            atr = float(avg_entry) * 0.01

        tranches = []
        for i, (sp, tp_mult) in enumerate(zip(split, tp_multiples)):
            qty = (total_qty * Decimal(str(sp))).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
            if i == len(split) - 1:
                qty = total_qty - sum(t.quantity for t in tranches)
            tp_distance = Decimal(str(atr * tp_mult))
            if side == PositionSide.LONG:
                target = avg_entry + tp_distance
            else:
                target = avg_entry - tp_distance
            tranches.append(TrancheOrder(
                id=f"{pos_id}-x{i}", position_id=pos_id, side=side, is_entry=False,
                target_price=target.quantize(Decimal("0.01")), quantity=qty, created_at=now,
            ))
        return tranches

    def _calculate_stop_loss(
        self, side: PositionSide, entry_price: Decimal,
        sl_pct: float = 5.0, leverage: int = 5,
    ) -> Decimal:
        price_pct = Decimal(str(sl_pct / leverage / 100))
        if side == PositionSide.LONG:
            return (entry_price * (1 - price_pct)).quantize(Decimal("0.01"))
        return (entry_price * (1 + price_pct)).quantize(Decimal("0.01"))

    def _apply_atr_guardrail(
        self, side: PositionSide, entry: Decimal, sl: Decimal, tf: str, leverage: int,
    ) -> Decimal:
        """ATR 가드레일: SL이 1.5~4.0 × ATR(14) 범위 내인지 확인."""
        try:
            from app.binance.kline_store import kline_store
            df = kline_store.get_dataframe("BTCUSDT", tf)
            if df is None or len(df) < 15:
                return sl
            atr = self._calc_atr(df)
            if atr <= 0:
                return sl

            sl_distance = abs(float(entry - sl))
            min_sl = float(atr) * self.settings.atr_sl_min_multiple
            max_sl = float(atr) * self.settings.atr_sl_max_multiple

            if sl_distance < min_sl:
                sl_distance = min_sl
            elif sl_distance > max_sl:
                sl_distance = max_sl

            if side == PositionSide.LONG:
                return (entry - Decimal(str(sl_distance))).quantize(Decimal("0.01"))
            return (entry + Decimal(str(sl_distance))).quantize(Decimal("0.01"))
        except Exception:
            return sl

    def _calc_atr(self, df, period: int = 14) -> float:
        """ATR(14) 계산."""
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        tr = []
        for i in range(1, len(high)):
            tr.append(max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            ))
        if len(tr) < period:
            return sum(tr) / len(tr) if tr else 0
        return sum(tr[-period:]) / period

    def _check_time_exit(self, pos: Position, now: int) -> str | None:
        """시간 기반 청산. 평균 승리 시간의 2배→SL 조임, 4배→청산."""
        winning = [t for t in self.trade_history[-20:] if float(t.realized_pnl) > 0]
        if not winning:
            avg_dur = 3_600_000  # 1시간 기본값
        else:
            avg_dur = sum(t.duration_seconds * 1000 for t in winning) / len(winning)
        if avg_dur <= 0:
            avg_dur = 3_600_000

        age = now - pos.opened_at
        if age > 4 * avg_dur:
            return "time_exit"
        if age > 2 * avg_dur:
            return "tighten_sl"
        return None

    def _get_atr(self, tf: str) -> float:
        """KlineStore에서 ATR 계산."""
        try:
            from app.binance.kline_store import kline_store
            df = kline_store.get_dataframe("BTCUSDT", tf)
            if df is None or len(df) < 15:
                return 0
            return self._calc_atr(df)
        except Exception:
            return 0

    def _should_fill_entry(self, t: TrancheOrder, price: Decimal) -> bool:
        if t.side == PositionSide.LONG:
            return price <= t.target_price
        return price >= t.target_price

    def _should_fill_exit(self, t: TrancheOrder, price: Decimal) -> bool:
        if t.side == PositionSide.LONG:
            return price >= t.target_price
        return price <= t.target_price

    def _should_stop_loss(self, pos: Position, price: Decimal) -> bool:
        if pos.side == PositionSide.LONG:
            return price <= pos.stop_loss_price
        return price >= pos.stop_loss_price

    def _recalculate_position(self, pos: Position):
        filled = [t for t in pos.entry_tranches if t.status == OrderStatus.FILLED]
        if not filled:
            return
        total_value = sum(t.filled_price * t.quantity for t in filled)
        total_qty = sum(t.quantity for t in filled)
        pos.avg_entry_price = (total_value / total_qty).quantize(Decimal("0.01"))
        pos.total_quantity = total_qty

        # ATR 기반 SL 재계산
        atr = self._get_atr(pos.timeframe)
        if atr > 0:
            sl_distance = Decimal(str(atr * pos.sl_atr_multiple))
            sl_distance = max(sl_distance, Decimal(str(atr * self.settings.atr_sl_min_multiple)))
            sl_distance = min(sl_distance, Decimal(str(atr * self.settings.atr_sl_max_multiple)))
            if pos.side == PositionSide.LONG:
                new_sl = (pos.avg_entry_price - sl_distance).quantize(Decimal("0.01"))
            else:
                new_sl = (pos.avg_entry_price + sl_distance).quantize(Decimal("0.01"))
            pos.stop_loss_price = new_sl

        # Exit tranche 생성/재생성
        filled_exits = [t for t in pos.exit_tranches if t.status == OrderStatus.FILLED]
        filled_exit_qty = sum(t.quantity for t in filled_exits)
        remaining_qty = total_qty - filled_exit_qty
        if remaining_qty > 0:
            pos.exit_tranches = filled_exits + self._create_exit_tranches(
                pos.side, pos.avg_entry_price, remaining_qty,
                pos.id, int(time.time() * 1000),
                tp_atr_multiples=pos.tp_levels or None,
                exit_split=pos.exit_split or None,
                leverage=pos.leverage,
                tf=pos.timeframe,
            )

    def _calc_fee(self, price: Decimal, qty: Decimal, is_market: bool = False) -> Decimal:
        rate = self.settings.fee_taker_pct if is_market else self.settings.fee_maker_pct
        return (price * qty * Decimal(str(rate / 100))).quantize(Decimal("0.01"))

    def _calc_pnl(self, side: PositionSide, entry: Decimal, exit_p: Decimal, qty: Decimal, lev: int) -> Decimal:
        if side == PositionSide.LONG:
            return ((exit_p - entry) * qty).quantize(Decimal("0.01"))
        return ((entry - exit_p) * qty).quantize(Decimal("0.01"))

    def _calc_tranche_pnl(self, pos: Position, t: TrancheOrder) -> Decimal:
        return self._calc_pnl(pos.side, pos.avg_entry_price, t.filled_price, t.quantity, pos.leverage)

    def _update_account(self, price: Decimal):
        unrealized = Decimal("0")
        for pos in self.open_positions.values():
            if pos.avg_entry_price and pos.total_quantity > 0:
                unrealized += self._calc_pnl(pos.side, pos.avg_entry_price, price, pos.total_quantity, pos.leverage)
        self.account.unrealized_pnl = unrealized
        self.account.equity = self.account.balance + self.account.margin_used + unrealized
        if self.account.equity > self.account.peak_equity:
            self.account.peak_equity = self.account.equity

    # ── Query Methods ──────────────────────────────────────────────

    def get_status(self) -> dict:
        win_rate = round(self.account.winning_trades / self.account.total_trades * 100, 1) if self.account.total_trades > 0 else 0.0
        return {
            "balance": str(self.account.balance),
            "equity": str(self.account.equity),
            "unrealized_pnl": str(self.account.unrealized_pnl),
            "margin_used": str(self.account.margin_used),
            "total_fees": str(self.account.total_fees),
            "daily_pnl": str(self.account.daily_pnl),
            "daily_trades": self.account.daily_trades,
            "open_positions_count": len(self.open_positions),
            "total_trades": self.account.total_trades,
            "win_rate": win_rate,
            "anomaly": self.anomaly_detector.get_halt_info(),
        }

    def get_open_positions(self, current_price: Decimal | None = None) -> list[dict]:
        price = current_price or self._last_price or Decimal("0")
        result = []
        for pos in self.open_positions.values():
            if not pos.avg_entry_price:
                continue
            unrealized = self._calc_pnl(pos.side, pos.avg_entry_price, price, pos.total_quantity, pos.leverage)
            pnl_pct = float(unrealized / pos.allocated_margin * 100) if pos.allocated_margin > 0 else 0.0
            filled_entries = sum(1 for t in pos.entry_tranches if t.status == OrderStatus.FILLED)
            filled_exits = sum(1 for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
            result.append({
                "id": pos.id, "symbol": pos.symbol, "side": pos.side.value,
                "leverage": pos.leverage, "avg_entry_price": str(pos.avg_entry_price),
                "mark_price": str(price), "quantity": str(pos.total_quantity),
                "unrealized_pnl": str(unrealized), "pnl_percent": round(pnl_pct, 2),
                "margin": str(pos.allocated_margin), "status": pos.status,
                "filled_entries": filled_entries, "total_entries": len(pos.entry_tranches),
                "filled_exits": filled_exits, "total_exits": len(pos.exit_tranches),
                "stop_loss_price": str(pos.stop_loss_price),
                "entry_orders": [
                    {"price": str(t.target_price), "qty": str(t.quantity), "status": t.status.value,
                     "filled_price": str(t.filled_price) if t.filled_price else None}
                    for t in pos.entry_tranches
                ],
                "exit_orders": [
                    {"price": str(t.target_price), "qty": str(t.quantity), "status": t.status.value,
                     "filled_price": str(t.filled_price) if t.filled_price else None}
                    for t in pos.exit_tranches
                ],
                "signal_type": pos.signal_type, "signal_message": pos.signal_message,
                "signal_details": pos.signal_details, "opened_at": pos.opened_at,
            })
        return result

    def get_trade_history(self, limit: int = 50, offset: int = 0) -> dict:
        trades = sorted(self.trade_history, key=lambda t: t.closed_at, reverse=True)
        return {"trades": [t.model_dump(mode="json") for t in trades[offset:offset + limit]], "total": len(trades)}

    def get_daily_summary(self) -> dict:
        today_start = int(time.time() // 86400) * 86400 * 1000
        today_trades = [t for t in self.trade_history if t.closed_at >= today_start]
        today_pnl = sum(t.realized_pnl for t in today_trades)
        today_wins = sum(1 for t in today_trades if t.realized_pnl > 0)
        today_wr = round(today_wins / len(today_trades) * 100, 1) if today_trades else 0.0
        total_wr = round(self.account.winning_trades / self.account.total_trades * 100, 1) if self.account.total_trades > 0 else 0.0
        return {
            "today_pnl": str(today_pnl), "today_trades": len(today_trades), "today_win_rate": today_wr,
            "total_pnl": str(self.account.total_realized_pnl), "total_trades": self.account.total_trades,
            "overall_win_rate": total_wr,
        }

    def update_settings(self, updates: dict) -> TradingSettings:
        current = self.settings.model_dump()
        current.update({k: v for k, v in updates.items() if v is not None})
        self.settings = TradingSettings(**current)
        return self.settings

    def reset(self):
        self.account = AccountState(
            balance=self.settings.initial_capital,
            initial_capital=self.settings.initial_capital,
            equity=self.settings.initial_capital,
            peak_equity=self.settings.initial_capital,
        )
        self.open_positions.clear()
        self.trade_history.clear()
        self._recent_signals.clear()
        self._halt_until = 0
        reset_all()
        save_account(self.account)


def _create_engine() -> PaperTradingEngine:
    if not settings.binance_testnet and settings.binance_api_key:
        from app.trading.live_engine import LiveTradingEngine
        logger.info("Creating LiveTradingEngine (mainnet)")
        return LiveTradingEngine()
    logger.info("Creating PaperTradingEngine (testnet/no key)")
    return PaperTradingEngine()


trading_engine = _create_engine()
