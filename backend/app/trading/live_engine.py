"""Live Trading Engine — 실제 Binance Futures 주문 실행.

PaperTradingEngine을 상속하여 시뮬레이션 체결을 실제 API 호출로 교체.
2026-04-09 Buffett×Dimon 실거래 회의록 기준.

핵심 차이:
  - 진입/청산 시 binance_client.place_order() 호출
  - 주기적 reconciliation으로 주문 상태 동기화
  - 시작 시 ghost position 감지 + 잔고 동기화
  - 실거래용 강화 리스크 파라미터 적용
"""

import asyncio
import logging
import time
from decimal import Decimal, ROUND_DOWN

from app.binance.client import binance_client
from app.config import settings
from app.trading.engine import PaperTradingEngine
from app.trading.schemas import (
    AccountState,
    LiveTradingSettings,
    OrderStatus,
    Position,
    PositionSide,
    TrancheOrder,
)
from app.trading.persistence import (
    save_account, load_account, save_position, delete_position,
    reset_all,
)

logger = logging.getLogger(__name__)


class LiveTradingEngine(PaperTradingEngine):
    """실거래 엔진. PaperTradingEngine 로직 + 실제 Binance 주문."""

    def __init__(self):
        super().__init__()
        self.settings = LiveTradingSettings()
        self._balance_cache: tuple[float, Decimal] | None = None
        self._initialized = False

    # ── 초기화: 잔고 동기화 + Ghost Position 감지 ──────────────

    async def initialize(self):
        """서버 시작 시 호출. 바이낸스 잔고/포지션 동기화."""
        try:
            # 1. 실제 잔고 조회
            real_balance = await binance_client.get_balance("USDT")
            logger.info(f"[LIVE] Binance USDT balance: ${real_balance}")

            # 2. Ghost position 감지
            binance_pos = await binance_client.get_position_risk("BTCUSDT")
            if binance_pos and float(binance_pos.get("positionAmt", 0)) != 0:
                pos_amt = binance_pos["positionAmt"]
                entry_price = binance_pos.get("entryPrice", "0")
                logger.warning(
                    f"[LIVE] Ghost position detected on Binance: "
                    f"{pos_amt} BTCUSDT @ {entry_price}"
                )
                # DB에 추적 중인 포지션이 없으면 HALT
                if not self.open_positions:
                    logger.critical(
                        "[LIVE] HALT: Untracked position on Binance! "
                        "Investigate before resuming."
                    )
                    await self.alert_sender._send_telegram_text(
                        "🚨 <b>LIVE ENGINE HALT</b>\n\n"
                        f"Untracked position detected on Binance:\n"
                        f"<code>{pos_amt} BTCUSDT @ ${entry_price}</code>\n\n"
                        "Bot will NOT trade until this is resolved.\n"
                        "Check Binance and close manually if needed."
                    )
                    self._halt_until = int(time.time() * 1000) + 86400_000
                    self._initialized = True
                    return

            # 3. 레버리지 설정
            try:
                await binance_client.set_leverage("BTCUSDT", self.settings.max_leverage)
                logger.info(f"[LIVE] Leverage set to {self.settings.max_leverage}x")
            except Exception as e:
                logger.warning(f"[LIVE] Set leverage failed (may already be set): {e}")

            # 4. 계좌 상태 초기화/동기화
            saved = load_account()
            if saved:
                self.account = saved
                # 잔고 차이 체크
                local_total = self.account.balance + self.account.margin_used
                diff_pct = abs(float(real_balance - local_total) / float(real_balance) * 100) if real_balance > 0 else 0
                if diff_pct > self.settings.balance_discrepancy_pct:
                    logger.warning(
                        f"[LIVE] Balance discrepancy: local=${local_total}, "
                        f"binance=${real_balance} (diff={diff_pct:.1f}%)"
                    )
            else:
                # 첫 시작: 실제 잔고로 초기화
                self.account = AccountState(
                    balance=real_balance,
                    initial_capital=real_balance,
                    equity=real_balance,
                    peak_equity=real_balance,
                    daily_start_balance=real_balance,
                )
                save_account(self.account)
                logger.info(f"[LIVE] Account initialized with ${real_balance}")

            # 5. WAITING 상태 주문 reconcile
            await self.reconcile_orders()

            self._initialized = True
            logger.info("[LIVE] Engine initialized successfully")

            await self.alert_sender._send_telegram_text(
                "🟢 <b>LIVE ENGINE STARTED</b>\n\n"
                f"💰 Balance: ${real_balance}\n"
                f"📊 Leverage: {self.settings.max_leverage}x\n"
                f"🔒 Daily loss limit: -{self.settings.daily_loss_tier2_pct}%\n"
                f"📍 Open positions: {len(self.open_positions)}"
            )

        except Exception as e:
            logger.critical(f"[LIVE] Initialization failed: {e}")
            raise

    # ── 잔고 캐시 ─────────────────────────────────────────────

    async def _get_real_balance(self) -> Decimal:
        """5초 캐시된 실잔고."""
        now = time.monotonic()
        if self._balance_cache:
            cached_time, cached_bal = self._balance_cache
            if now - cached_time < self.settings.balance_cache_ttl_sec:
                return cached_bal
        balance = await binance_client.get_balance("USDT")
        self._balance_cache = (now, balance)
        return balance

    # ── Signal → Position (실주문) ────────────────────────────

    async def on_signal(self, signal: dict, current_price: Decimal) -> Position | None:
        if not self._initialized:
            logger.info("[LIVE] on_signal skipped: not initialized")
            return None

        async with self._lock:
            now = int(time.time() * 1000)
            logger.info(f"[LIVE] on_signal: {signal.get('direction')} {signal.get('timeframe')} strength={signal.get('strength',0):.2f} @ {current_price}")

            self._check_daily_reset(now)

            if now < self._halt_until:
                logger.info("[LIVE] on_signal blocked: halt active")
                return None
            if self.anomaly_detector.is_halted():
                logger.info("[LIVE] on_signal blocked: anomaly halt")
                return None

            # drawdown 체크
            if self.account.peak_equity > 0:
                dd = (self.account.peak_equity - self.account.equity) / self.account.peak_equity * 100
                if dd >= Decimal(str(self.settings.drawdown_halt_pct)):
                    logger.warning(f"[LIVE] Drawdown halt: {dd:.1f}%")
                    today_end = (int(time.time() // 86400) + 1) * 86400 * 1000
                    self._halt_until = today_end
                    return None

            # 일일 손실 체크
            daily_base = self.account.daily_start_balance if self.account.daily_start_balance > 0 else self.account.initial_capital
            daily_loss_pct = float(-self.account.daily_pnl / daily_base * 100) if self.account.daily_pnl < 0 else 0.0
            if daily_loss_pct >= self.settings.daily_loss_tier2_pct:
                today_end = (int(time.time() // 86400) + 1) * 86400 * 1000
                self._halt_until = today_end
                logger.info(f"[LIVE] Daily loss halt: -{daily_loss_pct:.1f}%")
                return None

            # velocity brake
            recent_sl = [
                t for t in self.trade_history[-10:]
                if t.close_reason == "stop_loss" and now - t.closed_at < self.settings.velocity_window_ms
            ]
            if len(recent_sl) >= self.settings.velocity_max_consecutive_sl:
                self._halt_until = now + self.settings.velocity_pause_ms
                logger.info(f"[LIVE] REJECT: velocity brake ({len(recent_sl)} SLs in window)")
                return None

            # 시그널 스로틀 (5초, 2026-04-11 회의록)
            expired = [k for k, t in self._recent_signals.items() if now - t > 60_000]
            for k in expired:
                del self._recent_signals[k]
            sig_key = f"{signal['type']}_{signal['direction']}"
            if sig_key in self._recent_signals:
                if now - self._recent_signals[sig_key] < 5_000:
                    return None  # 5초 스로틀 — silent
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
                    logger.info(f"[LIVE] REJECT: 2 consecutive {side.value} SLs, 30min cooldown")
                    return None

            # 기존 포지션 처리
            if self.open_positions:
                pos = list(self.open_positions.values())[0]
                if pos.side == side:
                    self._tighten_sl_on_confirmation(pos, current_price)
                    return None
                else:
                    if not self._should_replace(pos, current_price, now, signal):
                        logger.info(f"[LIVE] REJECT: replacement conditions not met")
                        return None
                    # 교체: 기존 포지션 시장가 청산
                    await self._live_close_position(
                        list(self.open_positions.keys())[0], current_price, "replaced_by_signal"
                    )
                    self.account.daily_replacements += 1
                    self.account.last_replacement_at = now
                    self.anomaly_detector.record_replacement(now)

                    cascade_alert = self.anomaly_detector.check_replacement()
                    if cascade_alert:
                        asyncio.create_task(self.alert_sender.send(cascade_alert))
                        if cascade_alert.action_taken.value != "alert":
                            return None
            elif len(self.open_positions) >= self.settings.max_open_positions:
                return None

            # Tier 분류
            from app.analysis.trend_filter import classify_trade
            from app.trading.schemas import TradeTier, get_tf_atr_params

            if is_consensus:
                tier = classify_trade(signal["direction"], signal_tf, self._trend_context)
                if tier == TradeTier.BLOCKED:
                    logger.info(f"[LIVE] REJECT: BLOCKED by trend filter (consensus)")
                    return None
                tier_name = "consensus"
            else:
                tier = classify_trade(signal["direction"], signal_tf, self._trend_context)
                if tier == TradeTier.BLOCKED:
                    logger.info(f"[LIVE] REJECT: BLOCKED by trend filter ({signal['direction']} vs higher TF)")
                    return None
                tier_name = tier.value

            is_counter = tier_name in ("counter_trend", "consensus")
            logger.info(f"[LIVE] Tier: {tier_name} (counter={is_counter})")

            # Counter-trend 추가 검증
            if is_counter and not is_consensus:
                ct = self.settings.counter_trend
                details = signal.get("details", {})
                indicators = details.get("indicators", [])
                strong_triggers = sum(1 for ind in indicators if ind.get("weight", 0) >= 1.5)
                if strong_triggers < ct.min_strong_triggers:
                    logger.info(f"[LIVE] REJECT: counter-trend needs {ct.min_strong_triggers} strong triggers, got {strong_triggers}")
                    return None
                tf_threshold = details.get("threshold", {})
                net_score = details.get("net_score", 0)
                required_net = tf_threshold.get("min_net", 2.0) + ct.extra_min_score
                if net_score < required_net:
                    logger.info(f"[LIVE] REJECT: counter-trend net_score {net_score:.1f} < required {required_net:.1f}")
                    return None

            # ATR 기반 사이즈 계산
            atr_params = get_tf_atr_params(signal_tf)
            strength = signal.get("strength", 0.5)
            leverage = self._calculate_leverage(strength)

            atr = self._get_atr(signal_tf)
            if atr <= 0:
                atr = float(current_price) * 0.01

            size_multiplier = Decimal("1.0")
            if daily_loss_pct >= self.settings.daily_loss_tier1_pct:
                size_multiplier = Decimal("0.5")
                leverage = self.settings.min_leverage

            sl_distance = atr * atr_params.sl_atr
            sl_distance = max(sl_distance, atr * self.settings.atr_sl_min_multiple)
            sl_distance = min(sl_distance, atr * self.settings.atr_sl_max_multiple)

            # 순수 퍼센트 리스크 (2026-04-11 회의록: 클램프 없음)
            risk_amount = self.account.balance * Decimal(str(self.settings.risk_per_trade_pct / 100)) * size_multiplier

            if sl_distance <= 0:
                logger.info("[LIVE] REJECT: sl_distance <= 0")
                return None
            position_notional = risk_amount / Decimal(str(sl_distance / float(current_price)))
            # 슬리피지 버퍼 적용
            position_notional = position_notional * Decimal(str(self.settings.slippage_buffer))
            position_notional = position_notional.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            # Binance 최소 노셔널 체크 (자연 하한)
            if position_notional < self.settings.min_notional:
                logger.info(f"[LIVE] Notional ${position_notional} < min ${self.settings.min_notional}, skipping")
                return None

            # 실잔고 대비 마진 체크
            real_balance = await self._get_real_balance()
            margin = (position_notional / leverage).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            if margin > real_balance * Decimal("0.95"):
                logger.warning(f"[LIVE] Insufficient margin: need ${margin}, have ${real_balance}")
                return None

            total_qty = (position_notional / current_price).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
            if total_qty <= 0:
                return None

            import uuid
            pos_id = str(uuid.uuid4())[:8]

            # 레버리지 설정
            try:
                await binance_client.set_leverage("BTCUSDT", leverage)
            except Exception as e:
                logger.warning(f"[LIVE] Set leverage failed: {e}")

            # 진입 tranche 생성
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

            # SL 가격
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
                id=pos_id, side=side, leverage=leverage,
                signal_type=signal["type"], signal_strength=strength,
                signal_message=f"[{tier_label}] {signal.get('message', '')}",
                signal_details=signal_details,
                entry_tranches=entry_tranches, exit_tranches=[],
                stop_loss_price=stop_loss, allocated_quantity=total_qty,
                allocated_margin=margin,
                tp_levels=[atr_params.tp1_atr, atr_params.tp2_atr, atr_params.tp3_atr],
                exit_split=atr_params.exit_split,
                sl_atr_multiple=atr_params.sl_atr, timeframe=signal_tf,
                opened_at=now,
            )

            # ── 실주문: 첫 tranche 시장가 ──
            first = entry_tranches[0]
            binance_side = "BUY" if side == PositionSide.LONG else "SELL"
            try:
                resp = await binance_client.place_order(
                    symbol="BTCUSDT",
                    side=binance_side,
                    order_type="MARKET",
                    quantity=first.quantity,
                    client_order_id=first.id,
                )
                first.client_order_id = first.id
                first.binance_order_id = str(resp.get("orderId", ""))

                if resp.get("status") == "FILLED":
                    first.status = OrderStatus.FILLED
                    first.filled_price = Decimal(str(resp.get("avgPrice", current_price)))
                    first.filled_at = now
                    fee = self._calc_fee(first.filled_price, first.quantity, is_market=True)
                    position.total_fees += fee
                    self.account.total_fees += fee
                else:
                    first.status = OrderStatus.WAITING
                    logger.info(f"[LIVE] First tranche status: {resp.get('status')}")

            except Exception as e:
                logger.error(f"[LIVE] Order placement failed: {e}")
                await self.alert_sender._send_telegram_text(
                    f"🚨 <b>ORDER FAILED</b>\n\n"
                    f"Side: {binance_side}\n"
                    f"Qty: {first.quantity}\n"
                    f"Error: <code>{e}</code>"
                )
                return None

            # 나머지 entry tranche는 LIMIT 주문
            for tranche in entry_tranches[1:]:
                try:
                    resp = await binance_client.place_order(
                        symbol="BTCUSDT",
                        side=binance_side,
                        order_type="LIMIT",
                        quantity=tranche.quantity,
                        price=tranche.target_price,
                        client_order_id=tranche.id,
                    )
                    tranche.client_order_id = tranche.id
                    tranche.binance_order_id = str(resp.get("orderId", ""))
                    tranche.status = OrderStatus.WAITING
                except Exception as e:
                    logger.error(f"[LIVE] Limit entry order failed: {e}")
                    tranche.status = OrderStatus.CANCELLED

            # Cross margin: 잔고 차감 없음 (Binance가 관리)
            self.account.margin_used += margin
            self.open_positions[pos_id] = position

            if first.status == OrderStatus.FILLED:
                self.account.total_fees += position.total_fees
                self._recalculate_position(position)

            # 바이낸스 실잔고로 동기화
            try:
                real_bal = await self._get_real_balance()
                self.account.balance = real_bal
            except Exception:
                pass

            self.account.daily_trades += 1
            save_position(position)
            save_account(self.account)

            # SL 사전 배치 (바이낸스 STOP_MARKET)
            await self._place_sl_order(position)

            logger.info(
                f"[LIVE] Position opened [{tier_name}]: {side.value} {total_qty} "
                f"@ ~{current_price} (lev:{leverage}x, TF:{signal_tf})"
            )

            # 텔레그램 알림
            side_kr = "롱" if side == PositionSide.LONG else "숏"
            asyncio.create_task(self.alert_sender._send_telegram_text(
                f"📈 <b>POSITION OPENED</b>\n\n"
                f"Side: {side_kr.upper()} ({tier_label})\n"
                f"Size: {total_qty} BTC (${position_notional:,.0f})\n"
                f"Leverage: {leverage}x\n"
                f"Entry: ~${current_price:,.2f}\n"
                f"SL: ${stop_loss:,.2f}\n"
                f"Margin: ${margin:,.2f}"
            ))

            return position

    # ── Tick → Reconciliation 기반 체결 ───────────────────────

    async def on_price_update(self, price: Decimal) -> list[dict]:
        """Paper 엔진의 시뮬레이션 fill 대신, SL/trailing/time 체크만 수행.
        실제 체결은 reconcile_orders()에서 처리."""
        self._last_price = price
        self.anomaly_detector.record_price_update(int(time.time() * 1000))
        if not self.open_positions:
            return []

        async with self._lock:
            events: list[dict] = []
            positions_to_close: list[tuple[str, str]] = []

            for pos_id, pos in self.open_positions.items():
                old_sl = pos.stop_loss_price

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

                # SL 변경 시 바이낸스 주문 재배치
                if pos.stop_loss_price != old_sl:
                    await self._update_sl_order_if_changed(pos, old_sl)

                # SL 체크 → 시장가 청산
                if pos.avg_entry_price and pos.status in ("opening", "open"):
                    if self._should_stop_loss(pos, price):
                        filled_tp = sum(1 for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
                        reason = "breakeven" if filled_tp > 0 else "stop_loss"
                        positions_to_close.append((pos_id, reason))

            for pos_id, reason in positions_to_close:
                if pos_id in self.open_positions:
                    trade = await self._live_close_position(pos_id, price, reason)
                    if trade:
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

    # ── 실주문 청산 ───────────────────────────────────────────

    async def _live_close_position(self, pos_id: str, price: Decimal, reason: str):
        """바이낸스에서 시장가 청산 후 로컬 상태 업데이트."""
        pos = self.open_positions.get(pos_id)
        if not pos:
            return None

        # 1. SL 주문 취소
        await self._cancel_sl_order(pos)

        # 2. 미체결 주문 전부 취소
        for tranche in pos.entry_tranches + pos.exit_tranches:
            if tranche.status in (OrderStatus.PENDING, OrderStatus.WAITING):
                if tranche.client_order_id:
                    try:
                        await binance_client.cancel_order("BTCUSDT", tranche.client_order_id)
                    except Exception:
                        pass
                tranche.status = OrderStatus.CANCELLED

        # 2. 남은 수량 시장가 청산
        remaining_qty = Decimal("0")
        for t in pos.exit_tranches:
            if t.status != OrderStatus.FILLED:
                remaining_qty += t.quantity
        # entry 중 미체결도 빼기
        filled_entry_qty = sum(t.quantity for t in pos.entry_tranches if t.status == OrderStatus.FILLED)

        close_qty = filled_entry_qty - sum(
            t.quantity for t in pos.exit_tranches if t.status == OrderStatus.FILLED
        )

        actual_close_price = price
        if close_qty > 0:
            close_side = "SELL" if pos.side == PositionSide.LONG else "BUY"
            try:
                resp = await binance_client.place_order(
                    symbol="BTCUSDT",
                    side=close_side,
                    order_type="MARKET",
                    quantity=close_qty,
                    client_order_id=f"{pos_id}-close",
                )
                if resp.get("avgPrice"):
                    actual_close_price = Decimal(str(resp["avgPrice"]))
                logger.info(f"[LIVE] Close order filled @ {actual_close_price}")
            except Exception as e:
                logger.error(f"[LIVE] Close order failed: {e}")
                # 실패해도 로컬 상태는 업데이트 (다음 reconcile에서 처리)

        # 3. 로컬 상태 업데이트 (Paper 로직 재사용)
        trade = self._close_position(pos_id, actual_close_price, reason)

        # 바이낸스 실잔고로 동기화
        try:
            real_bal = await self._get_real_balance()
            self.account.balance = real_bal
            self.account.margin_used = Decimal("0")
        except Exception:
            pass

        # 4. 텔레그램 알림
        side_kr = "롱" if trade.side == PositionSide.LONG else "숏"
        reason_kr = {"take_profit": "익절", "breakeven": "본전", "stop_loss": "손절",
                     "time_exit": "시간초과", "replaced_by_signal": "교체"}.get(reason, reason)
        emoji = "💚" if trade.realized_pnl >= 0 else "🔴"
        asyncio.create_task(self.alert_sender._send_telegram_text(
            f"{emoji} <b>POSITION CLOSED — {reason_kr.upper()}</b>\n\n"
            f"Side: {side_kr}\n"
            f"Entry: ${trade.avg_entry_price:,.2f}\n"
            f"Exit: ${actual_close_price:,.2f}\n"
            f"PnL: {'+'if trade.realized_pnl >= 0 else ''}${trade.realized_pnl:.2f} "
            f"({trade.pnl_percent:+.2f}%)\n"
            f"Fees: ${trade.total_fees:.2f}\n"
            f"Duration: {trade.duration_seconds}s\n\n"
            f"Balance: ${self.account.balance:,.2f}"
        ))

        return trade

    # ── Reconciliation: 바이낸스 주문 상태 동기화 ─────────────

    async def reconcile_orders(self):
        """WAITING 상태인 주문을 바이낸스에서 조회하여 상태 동기화."""
        if not self.open_positions:
            return

        async with self._lock:
            for pos_id, pos in list(self.open_positions.items()):
                changed = False

                # Entry tranche reconciliation
                for tranche in pos.entry_tranches:
                    if tranche.status != OrderStatus.WAITING:
                        continue
                    if not tranche.client_order_id:
                        continue

                    order = await binance_client.get_order("BTCUSDT", tranche.client_order_id)
                    if not order:
                        continue

                    status = order.get("status", "")
                    if status == "FILLED":
                        tranche.status = OrderStatus.FILLED
                        tranche.filled_price = Decimal(str(order.get("avgPrice", tranche.target_price)))
                        tranche.filled_at = int(order.get("updateTime", time.time() * 1000))
                        fee = self._calc_fee(tranche.filled_price, tranche.quantity, is_market=False)
                        pos.total_fees += fee
                        self.account.balance -= fee
                        self.account.total_fees += fee
                        self._recalculate_position(pos)
                        changed = True
                        logger.info(f"[LIVE] Entry tranche filled: {tranche.id} @ {tranche.filled_price}")

                        filled_entries = sum(1 for t in pos.entry_tranches if t.status == OrderStatus.FILLED)
                        if filled_entries == len(pos.entry_tranches):
                            pos.status = "open"

                    elif status in ("CANCELED", "REJECTED", "EXPIRED"):
                        tranche.status = OrderStatus.CANCELLED
                        changed = True
                        logger.info(f"[LIVE] Entry tranche {status}: {tranche.id}")

                # Exit tranche reconciliation
                for tranche in pos.exit_tranches:
                    if tranche.status != OrderStatus.WAITING:
                        continue
                    if not tranche.client_order_id:
                        continue

                    order = await binance_client.get_order("BTCUSDT", tranche.client_order_id)
                    if not order:
                        continue

                    status = order.get("status", "")
                    if status == "FILLED":
                        tranche.status = OrderStatus.FILLED
                        tranche.filled_price = Decimal(str(order.get("avgPrice", tranche.target_price)))
                        tranche.filled_at = int(order.get("updateTime", time.time() * 1000))
                        pnl = self._calc_tranche_pnl(pos, tranche)
                        pos.realized_pnl += pnl
                        fee = self._calc_fee(tranche.filled_price, tranche.quantity, is_market=False)
                        pos.total_fees += fee
                        self.account.balance -= fee
                        self.account.total_fees += fee

                        filled_exits = sum(1 for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
                        self._trailing_sl_after_tp(pos, filled_exits)
                        changed = True
                        logger.info(f"[LIVE] Exit tranche filled: {tranche.id} @ {tranche.filled_price}")

                        # 모든 exit 체결 → 포지션 종료
                        if filled_exits == len(pos.exit_tranches):
                            trade = self._close_position(pos_id, tranche.filled_price, "take_profit")
                            side_kr = "롱" if trade.side == PositionSide.LONG else "숏"
                            asyncio.create_task(self.alert_sender._send_telegram_text(
                                f"💚 <b>TAKE PROFIT — ALL TARGETS HIT</b>\n\n"
                                f"Side: {side_kr}\n"
                                f"PnL: +${trade.realized_pnl:.2f} ({trade.pnl_percent:+.2f}%)\n"
                                f"Balance: ${self.account.balance:,.2f}"
                            ))
                            break

                    elif status in ("CANCELED", "REJECTED", "EXPIRED"):
                        tranche.status = OrderStatus.CANCELLED
                        changed = True

                if changed and pos_id in self.open_positions:
                    save_position(pos)
                    save_account(self.account)

            # 잔고 동기화 (매 reconcile 주기)
            try:
                real_bal = await self._get_real_balance()
                if self.account.balance != real_bal:
                    self.account.balance = real_bal
                    save_account(self.account)
            except Exception:
                pass

    # ── Exit tranche 실주문 발행 ──────────────────────────────

    async def _place_exit_orders(self, pos: Position):
        """Exit tranche들을 바이낸스에 LIMIT 주문으로 발행."""
        close_side = "SELL" if pos.side == PositionSide.LONG else "BUY"
        for tranche in pos.exit_tranches:
            if tranche.status != OrderStatus.PENDING:
                continue
            try:
                resp = await binance_client.place_order(
                    symbol="BTCUSDT",
                    side=close_side,
                    order_type="LIMIT",
                    quantity=tranche.quantity,
                    price=tranche.target_price,
                    client_order_id=tranche.id,
                )
                tranche.client_order_id = tranche.id
                tranche.binance_order_id = str(resp.get("orderId", ""))
                tranche.status = OrderStatus.WAITING
                logger.info(f"[LIVE] Exit order placed: {tranche.id} @ {tranche.target_price}")
            except Exception as e:
                logger.error(f"[LIVE] Exit order failed: {e}")

    # ── recalculate 오버라이드: exit tranche 생성 후 실주문 ──

    def _recalculate_position(self, pos: Position):
        """부모 로직 실행 후 exit tranche가 새로 생기면 주문 발행."""
        had_exits = len(pos.exit_tranches)
        super()._recalculate_position(pos)
        new_exits = len(pos.exit_tranches)

        if new_exits > had_exits:
            # 새 exit tranche가 생겼으면 비동기로 주문 발행
            pending_exits = [t for t in pos.exit_tranches if t.status == OrderStatus.PENDING]
            if pending_exits:
                asyncio.create_task(self._place_exit_orders(pos))

    # ── SL 사전 배치 (STOP_MARKET + reduceOnly) ─────────────

    async def _place_sl_order(self, pos: Position):
        """SL을 바이낸스 Algo API (STOP_MARKET)로 사전 배치."""
        close_side = "SELL" if pos.side == PositionSide.LONG else "BUY"

        # 기존 SL 주문 취소
        await self._cancel_sl_order(pos)

        filled_qty = sum(t.quantity for t in pos.entry_tranches if t.status == OrderStatus.FILLED)
        exited_qty = sum(t.quantity for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
        remaining = filled_qty - exited_qty
        if remaining <= 0:
            return

        try:
            result = await binance_client.place_algo_order(
                symbol="BTCUSDT",
                side=close_side,
                order_type="STOP_MARKET",
                trigger_price=pos.stop_loss_price.quantize(Decimal("0.10")),
                quantity=remaining.quantize(Decimal("0.001")),
            )
            pos.signal_details = pos.signal_details or {}
            pos.signal_details["sl_algo_id"] = str(result.get("algoId", ""))
            logger.info(f"[LIVE] SL algo order placed: {close_side} STOP_MARKET trigger={pos.stop_loss_price} qty={remaining}")
        except Exception as e:
            logger.error(f"[LIVE] SL algo order failed: {e}")

    async def _cancel_sl_order(self, pos: Position):
        """기존 SL algo 주문 취소."""
        algo_id = (pos.signal_details or {}).get("sl_algo_id")
        if algo_id:
            try:
                await binance_client.cancel_algo_order("BTCUSDT", algo_id)
                logger.info(f"[LIVE] SL algo order cancelled: {algo_id}")
            except Exception:
                pass

    async def _update_sl_order_if_changed(self, pos: Position, old_sl: Decimal):
        """SL이 0.1% 이상 변경되었으면 재배치."""
        if old_sl <= 0:
            await self._place_sl_order(pos)
            return
        change_pct = abs(float(pos.stop_loss_price - old_sl) / float(old_sl) * 100)
        if change_pct >= 0.1:
            await self._place_sl_order(pos)

    # ── Reset (DB 초기화 + 바이낸스 주문 전부 취소) ───────────

    def reset(self):
        """위험: 모든 데이터 초기화. 바이낸스 주문은 취소하지 않음."""
        logger.warning("[LIVE] Reset called — local state only")
        super().reset()
