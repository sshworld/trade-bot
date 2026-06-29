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

from app.binance.client import AlgoConflictClosePosition, AlgoNoOpenPosition, AlgoWouldImmediatelyTrigger, binance_client
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
                # 잔고를 바이낸스 기준으로 동기화
                self.account.balance = real_balance
                self.account.margin_used = Decimal("0")
                self.account.equity = real_balance
                # peak_equity가 실잔고보다 비정상적으로 높으면 보정
                if self.account.peak_equity > real_balance * Decimal("1.1"):
                    logger.warning(
                        f"[LIVE] Peak equity ${self.account.peak_equity} > "
                        f"balance ${real_balance} * 1.1, resetting to balance"
                    )
                    self.account.peak_equity = real_balance
                save_account(self.account)
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

            # 5. 기존 Algo 주문 전부 취소 후 재배치 (중복 방지)
            if self.open_positions:
                await self._cancel_all_binance_algo_orders()
                for pos in list(self.open_positions.values()):
                    await self._place_sl_order(pos)
                    await self._place_exit_orders(pos)
                    await self._assert_sl_armed(pos)
                logger.info(f"[LIVE] SL/TP re-placed for {len(self.open_positions)} positions")

            # 6. WAITING 상태 주문 reconcile
            await self.reconcile_orders()

            self._initialized = True
            logger.info("[LIVE] Engine initialized successfully")

            await self.alert_sender._send_telegram_text(
                "🟢 <b>LIVE ENGINE STARTED</b>\n\n"
                f"💰 Balance: ${real_balance}\n"
                f"📊 Leverage: {self.settings.max_leverage}x\n"
                f"🔒 SL/TP: ±{self.settings.sl_margin_pct}% margin (0.4% @{self.settings.max_leverage}x) | DD Halt: {self.settings.drawdown_halt_pct}%\n"
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

            # ── 적응형 필터 (2026-04-13 회의록) ──
            from app.trading.schemas import FilterState
            daily_base = self.account.daily_start_balance if self.account.daily_start_balance > 0 else self.account.initial_capital
            daily_pnl_pct = float(self.account.daily_pnl / daily_base * 100) if daily_base > 0 else 0.0
            s = self.settings

            # Drawdown 체크
            if self.account.peak_equity > 0:
                dd = float((self.account.peak_equity - self.account.equity) / self.account.peak_equity * 100)
                if dd >= s.drawdown_halt_pct:
                    logger.warning(f"[LIVE] Drawdown halt: {dd:.1f}%")
                    today_end = (int(time.time() // 86400) + 1) * 86400 * 1000
                    self._halt_until = today_end
                    self._filter_state = FilterState.STOP
                    return None

            # 필터 상태 결정
            prev_state = self._filter_state
            if daily_pnl_pct <= -s.filter_stop_pnl_pct:
                self._filter_state = FilterState.STOP
                today_end = (int(time.time() // 86400) + 1) * 86400 * 1000
                self._halt_until = today_end
                if prev_state != FilterState.STOP:
                    logger.info(f"[LIVE] STOP: PnL {daily_pnl_pct:+.1f}%")
                return None
            elif daily_pnl_pct <= -s.filter_critical_pnl_pct:
                self._filter_state = FilterState.CRITICAL
            elif daily_pnl_pct <= -s.filter_caution_pnl_pct:
                self._filter_state = FilterState.CAUTION
            elif daily_pnl_pct >= s.filter_boost_pnl_pct:
                self._filter_state = FilterState.BOOST
            else:
                self._filter_state = FilterState.NORMAL

            if self._filter_state != prev_state:
                logger.info(f"[LIVE] Filter: {prev_state.value} → {self._filter_state.value} (PnL {daily_pnl_pct:+.1f}%)")

            min_strength = {
                FilterState.BOOST: s.filter_boost_strength,
                FilterState.NORMAL: s.filter_normal_strength,
                FilterState.CAUTION: s.filter_caution_strength,
                FilterState.CRITICAL: s.filter_critical_strength,
            }[self._filter_state]

            # velocity brake: strength +0.15
            recent_sl = [
                t for t in self.trade_history[-10:]
                if t.close_reason == "stop_loss" and now - t.closed_at < s.velocity_window_ms
            ]
            if len(recent_sl) >= s.velocity_max_consecutive_sl:
                if self._velocity_bump_until < now:
                    self._velocity_bump_until = now + s.velocity_bump_duration_ms
                    logger.info(f"[LIVE] Velocity bump: +{s.velocity_strength_bump}")
            if now < self._velocity_bump_until:
                min_strength += s.velocity_strength_bump

            signal_strength = signal.get("strength", 0)
            if signal_strength < min_strength:
                logger.info(f"[LIVE] REJECT: strength {signal_strength:.2f} < min {min_strength:.2f} (filter={self._filter_state.value})")
                return None

            # 시그널 스로틀
            expired = [k for k, t in self._recent_signals.items() if now - t > 60_000]
            for k in expired:
                del self._recent_signals[k]
            sig_key = f"{signal['type']}_{signal['direction']}"
            if sig_key in self._recent_signals:
                if now - self._recent_signals[sig_key] < 5_000:
                    return None
            self._recent_signals[sig_key] = now

            side = PositionSide.LONG if signal["direction"] == "bullish" else PositionSide.SHORT
            is_consensus = signal.get("type", "").startswith("consensus_override")
            signal_tf = signal.get("timeframe", "1h")

            # 손절 직후 같은 방향 재진입 쿨다운 (churn 방지)
            cooldown_ms = self.settings.reentry_cooldown_after_sl_ms
            if cooldown_ms > 0 and self.trade_history:
                last = self.trade_history[-1]
                last_dir_side = PositionSide.LONG if last.side == PositionSide.LONG else PositionSide.SHORT
                if (last.close_reason == "stop_loss"
                        and last_dir_side == side
                        and now - last.closed_at < cooldown_ms):
                    logger.info(f"[LIVE] REJECT: reentry cooldown after SL ({(now-last.closed_at)/1000:.0f}s < {cooldown_ms/1000:.0f}s)")
                    return None

            # 기존 포지션 처리
            if self.open_positions:
                pos = list(self.open_positions.values())[0]
                if pos.side == side:
                    old_sl = pos.stop_loss_price
                    self._tighten_sl_on_confirmation(pos, current_price)
                    if pos.stop_loss_price != old_sl:
                        await self._update_sl_order_if_changed(pos, old_sl)
                        save_position(pos)
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

            # ── 최저 운영 잔고 체크 ──
            if self.account.balance < self.settings.min_operating_balance:
                logger.info(f"[LIVE] Balance ${self.account.balance} < min ${self.settings.min_operating_balance}")
                return None

            strength = signal.get("strength", 0.5)
            leverage = self._calculate_leverage(strength)

            # ATR (물타기 offset 전용)
            atr = self._get_atr(signal_tf)
            if atr <= 0:
                atr = float(current_price) * 0.01

            # ── % 기반 포지션 사이징 (사이즈 100%, 적응형 필터가 진입 품질 제어) ──
            real_balance = await self._get_real_balance()
            max_margin = real_balance * Decimal(str(self.settings.margin_cap_pct / 100))
            margin = max_margin.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            position_notional = margin * leverage
            position_notional = position_notional * Decimal(str(self.settings.slippage_buffer))
            position_notional = position_notional.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

            if position_notional < self.settings.min_notional:
                logger.info(f"[LIVE] Notional ${position_notional} < min ${self.settings.min_notional}")
                return None

            total_qty = (position_notional / current_price).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
            if total_qty <= 0:
                return None

            # 마진 재계산 (슬리피지 적용 후)
            margin = (position_notional / leverage).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

            import uuid
            pos_id = str(uuid.uuid4())[:8]

            # 레버리지 설정
            try:
                await binance_client.set_leverage("BTCUSDT", leverage)
            except Exception as e:
                logger.warning(f"[LIVE] Set leverage failed: {e}")

            # 진입 tranche 생성 (ATR 기반 물타기 offset)
            entry_tranches = self._create_entry_tranches(
                side, current_price, total_qty, pos_id, now, atr=atr,
            )

            # SL 가격: 마진 % 기반 (S2)
            stop_loss = self._calculate_stop_loss(side, current_price, self.settings.sl_margin_pct, leverage)

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
                tp_margin_pcts=list(self.settings.tp_margin_pcts),
                tp_split=list(self.settings.tp_split),
                timeframe=signal_tf,
                opened_at=now,
            )

            # ── 진입 전 clean book 검증 (고아 주문 위 진입 방지) ──
            if not await self._ensure_clean_book():
                logger.warning("[LIVE] on_signal aborted: book not clean after nuke")
                return None

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
                self._recalculate_position(position)

            # Exit tranche 주문 발행 (await로 확실히 처리)
            if (position.signal_details or {}).get("_pending_exit_placement"):
                await self._place_exit_orders(position)
                position.signal_details.pop("_pending_exit_placement", None)

            # SL 사전 배치 (바이낸스 STOP_MARKET)
            await self._place_sl_order(position)

            # 바이낸스 실잔고로 동기화
            try:
                real_bal = await self._get_real_balance()
                self.account.balance = real_bal
            except Exception:
                pass

            self.account.daily_trades += 1
            save_position(position)
            save_account(self.account)

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
        if not self._initialized:
            return []  # 초기화 race 방지 (initialize 변이 중 tick 차단)
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
                                    pos.stop_loss_price = new_sl.quantize(Decimal("0.1"))
                            else:
                                new_sl = be + bump  # SHORT: SL을 진입가 쪽으로 조임
                                if new_sl < pos.stop_loss_price:
                                    pos.stop_loss_price = new_sl.quantize(Decimal("0.1"))

                # SL 변경 시 바이낸스 주문 재배치
                if pos.stop_loss_price != old_sl:
                    await self._update_sl_order_if_changed(pos, old_sl)

                # SL 체크 → 시장가 청산
                if pos.avg_entry_price and pos.status in ("opening", "open"):
                    if self._should_stop_loss(pos, price):
                        positions_to_close.append((pos_id, self._sl_exit_reason(pos)))

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

    # ── 실주문 청산 (원샷 전체 정리) ─────────────────────────

    async def _live_close_position(self, pos_id: str, price: Decimal, reason: str):
        """바이낸스 원샷 전체 정리: 주문 전부 취소 → 포지션 청산 → 잔존 확인."""
        pos = self.open_positions.get(pos_id)
        if not pos:
            return None

        # ── STEP 1: 바이낸스 주문 전부 취소 (개별이 아닌 일괄) ──
        await self._nuke_all_binance_orders()

        # 로컬 tranche 상태도 정리
        for t in pos.entry_tranches + pos.exit_tranches:
            if t.status in (OrderStatus.PENDING, OrderStatus.WAITING):
                t.status = OrderStatus.CANCELLED

        # ── STEP 2: 바이낸스 실제 포지션 청산 ──
        actual_close_price = price
        try:
            binance_pos = await binance_client.get_position_risk("BTCUSDT")
            if binance_pos and float(binance_pos.get("positionAmt", 0)) != 0:
                amt = Decimal(binance_pos["positionAmt"])
                close_side = "SELL" if amt > 0 else "BUY"
                close_qty = abs(amt).quantize(Decimal("0.001"))
                resp = await binance_client.place_order(
                    symbol="BTCUSDT", side=close_side, order_type="MARKET",
                    quantity=close_qty,
                )
                if resp.get("avgPrice"):
                    actual_close_price = Decimal(str(resp["avgPrice"]))
                logger.info(f"[LIVE] Position closed: {close_side} {close_qty} @ {actual_close_price}")
        except Exception as e:
            logger.error(f"[LIVE] Close order failed: {e}")

        # ── STEP 3: 잔존 확인 (2차 시도) ──
        try:
            check = await binance_client.get_position_risk("BTCUSDT")
            if check and float(check.get("positionAmt", 0)) != 0:
                leftover = abs(Decimal(check["positionAmt"]))
                close_side2 = "SELL" if Decimal(check["positionAmt"]) > 0 else "BUY"
                await binance_client.place_order(
                    symbol="BTCUSDT", side=close_side2, order_type="MARKET",
                    quantity=leftover.quantize(Decimal("0.001")),
                )
                logger.warning(f"[LIVE] Leftover force-closed: {leftover}")
        except Exception:
            pass

        # 4. 로컬 상태 업데이트 (Paper 로직 재사용)
        trade = self._close_position(pos_id, actual_close_price, reason)

        # 바이낸스 실잔고로 동기화 + daily_pnl 실잔고 기반 재계산
        try:
            self._balance_cache = None  # 캐시 무효화
            real_bal = await self._get_real_balance()
            self._resync_after_close(real_bal)
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
            f"Duration: {trade.duration_seconds}s\n\n"
            f"Balance: ${self.account.balance:,.2f}"
        ))

        return trade

    # ── Reconciliation: 바이낸스 주문 상태 동기화 ─────────────

    async def reconcile_orders(self):
        """WAITING 상태인 주문을 바이낸스에서 조회하여 상태 동기화."""
        if not getattr(self, "_initialized", False):
            return  # 초기화 race 방지
        if not self.open_positions:
            return

        async with self._lock:
            for pos_id, pos in list(self.open_positions.items()):
                try:
                    changed = False

                    # SL 존재 검증 (무방비 포지션 방지, 매 사이클)
                    await self._assert_sl_armed(pos)

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
                            # balance는 바이낸스 잔고 동기화에서 처리 (직접 차감 안 함)
                            self._recalculate_position(pos)

                            # 추매 체결 → 평단 변경 → WAITING TP algo 취소 후 새 평단으로 재배치
                            for et in pos.exit_tranches:
                                if et.status == OrderStatus.WAITING and et.binance_order_id:
                                    await binance_client.cancel_algo_order("BTCUSDT", et.binance_order_id)
                                    et.status = OrderStatus.PENDING
                            await self._place_exit_orders(pos)
                            (pos.signal_details or {}).pop("_pending_exit_placement", None)

                            # SL 항상 재배치 (평단/수량 변경)
                            await self._place_sl_order(pos)
                            changed = True

                            filled_entries = sum(1 for t in pos.entry_tranches if t.status == OrderStatus.FILLED)
                            if filled_entries == len(pos.entry_tranches):
                                pos.status = "open"

                            logger.info(f"[LIVE] Entry tranche filled: {tranche.id} @ {tranche.filled_price}")

                            # 텔레그램 알림
                            side_kr = "롱" if pos.side == PositionSide.LONG else "숏"
                            await self.alert_sender._send_telegram_text(
                                f"📥 <b>추매 체결 ({filled_entries}/{len(pos.entry_tranches)})</b>\n\n"
                                f"Side: {side_kr}\n"
                                f"Price: ${tranche.filled_price:,.2f}\n"
                                f"Qty: {tranche.quantity}\n"
                                f"평단: ${pos.avg_entry_price:,.2f}\n"
                                f"총수량: {pos.total_quantity}\n"
                                f"새 SL: ${pos.stop_loss_price:,.2f}"
                            )

                        elif status in ("CANCELED", "REJECTED", "EXPIRED"):
                            tranche.status = OrderStatus.CANCELLED
                            changed = True
                            logger.info(f"[LIVE] Entry tranche {status}: {tranche.id}")

                    # Exit tranche reconciliation (Algo API)
                    for tranche in pos.exit_tranches:
                        if tranche.status != OrderStatus.WAITING:
                            continue
                        algo_id = tranche.binance_order_id
                        if not algo_id:
                            continue

                        try:
                            algo = await binance_client.get_algo_order("BTCUSDT", algo_id)
                            if not algo:
                                continue
                            algo_status = algo.get("algoStatus", "")
                        except Exception:
                            continue

                        # Binance Futures Algo terminal states:
                        #   NEW / WORKING — 트리거 대기
                        #   FINISHED — 트리거 + 시장가 체결 완료 (actualQty>0)
                        #   CANCELLED / EXPIRED / FAILED — 미체결 종료
                        if algo_status == "FINISHED":
                            actual_qty = Decimal(str(algo.get("actualQty") or "0"))
                            if actual_qty <= 0:
                                # 비정상: FINISHED 인데 체결량 0 → 다음 cycle 재시도
                                logger.warning(f"[LIVE] TP algo FINISHED but actualQty=0: {tranche.id}")
                                continue
                            tranche.status = OrderStatus.FILLED
                            tranche.filled_price = Decimal(str(algo.get("triggerPrice", tranche.target_price)))
                            tranche.filled_at = int(algo.get("triggerTime", time.time() * 1000))
                            pnl = self._calc_tranche_pnl(pos, tranche)
                            pos.realized_pnl += pnl
                            fee = self._calc_fee(tranche.filled_price, tranche.quantity, is_market=True)
                            pos.total_fees += fee

                            filled_exits = sum(1 for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
                            self._trailing_sl_after_tp(pos, filled_exits)
                            changed = True
                            logger.info(f"[LIVE] TP algo filled: {tranche.id} @ {tranche.filled_price}")

                            # SL 재배치 (수량 + 가격 변경)
                            await self._place_sl_order(pos)
                            logger.info(f"[LIVE] SL updated after TP{filled_exits}: SL={pos.stop_loss_price}")

                            # 텔레그램 알림
                            side_kr = "롱" if pos.side == PositionSide.LONG else "숏"
                            asyncio.create_task(self.alert_sender._send_telegram_text(
                                f"💰 <b>TP{filled_exits} HIT</b>\n\n"
                                f"Side: {side_kr}\n"
                                f"Price: ${tranche.filled_price:,.2f}\n"
                                f"Qty: {tranche.quantity}\n"
                                f"PnL: {'+'if pnl >= 0 else ''}${pnl:.2f}\n"
                                f"New SL: ${pos.stop_loss_price:,.2f}"
                            ))

                            # 모든 exit 체결 → 포지션 종료 (고아 방지: 전체 nuke)
                            if filled_exits == len(pos.exit_tranches):
                                await self._nuke_all_binance_orders()
                                trade = self._close_position(pos_id, tranche.filled_price, "take_profit")
                                asyncio.create_task(self.alert_sender._send_telegram_text(
                                    f"💚 <b>ALL TPs HIT</b>\n\n"
                                    f"Side: {side_kr}\n"
                                    f"PnL: +${trade.realized_pnl:.2f} ({trade.pnl_percent:+.2f}%)\n"
                                    f"Balance: ${self.account.balance:,.2f}"
                                ))
                                break

                        elif algo_status in ("CANCELLED", "EXPIRED", "FAILED"):
                            tranche.status = OrderStatus.CANCELLED
                            changed = True
                        elif algo_status not in ("NEW", "WORKING"):
                            logger.warning(
                                f"[LIVE] Unknown algoStatus {algo_status!r} for tranche {tranche.id} "
                                f"(algoId={algo_id}); treating as still WAITING"
                            )

                    if changed and pos_id in self.open_positions:
                        save_position(pos)
                        save_account(self.account)
                except Exception as e:
                    logger.error(f"[RECONCILE] per-position {pos_id} error: {e}")
                    continue

            # 바이낸스 포지션 소멸 감지 (SL/TP가 바이낸스에서 실행된 경우)
            if self.open_positions:
                try:
                    binance_pos = await binance_client.get_position_risk("BTCUSDT")
                    has_binance_pos = binance_pos and float(binance_pos.get("positionAmt", 0)) != 0
                    if not has_binance_pos:
                        # 바이낸스에서 포지션 없어짐 → SL/TP가 바이낸스에서 체결됨
                        for pos_id in list(self.open_positions.keys()):
                            pos = self.open_positions[pos_id]
                            real_bal = await binance_client.get_balance("USDT")
                            old_bal = self.account.balance
                            pnl = real_bal - old_bal
                            reason = "stop_loss" if pnl < 0 else "take_profit"

                            # 체결 가격 추정: 현재 ticker 또는 last_price
                            close_price = self._last_price
                            if not close_price:
                                try:
                                    ticker = await binance_client.get_ticker("BTCUSDT")
                                    close_price = ticker.price
                                except Exception:
                                    close_price = pos.avg_entry_price or Decimal("0")

                            logger.info(f"[LIVE] Binance position gone! {reason} PnL≈${pnl:.2f} @ ~${close_price}")

                            # 잔존 주문 전부 nuke (고아 방지: pos-scoped 대신 전체 + read-back)
                            await self._nuke_all_binance_orders()

                            trade = self._close_position(pos_id, close_price, reason)

                            self._resync_after_close(real_bal)
                            save_account(self.account)

                            side_kr = "롱" if trade.side == PositionSide.LONG else "숏"
                            reason_kr = "익절" if pnl >= 0 else "손절"
                            emoji = "💚" if pnl >= 0 else "🔴"
                            await self.alert_sender._send_telegram_text(
                                f"{emoji} <b>POSITION CLOSED (Binance) — {reason_kr.upper()}</b>\n\n"
                                f"Side: {side_kr}\n"
                                f"PnL: {'+'if pnl >= 0 else ''}${pnl:.2f}\n"
                                f"Balance: ${real_bal:,.2f}\n\n"
                                f"<i>Binance SL/TP 자동 체결</i>"
                            )
                            break
                except Exception as e:
                    logger.error(f"[RECONCILE] Position check failed: {e}")

            # 잔고 동기화 (매 reconcile 주기) — Binance가 source of truth
            try:
                real_bal = await self._get_real_balance()
                changed = False
                if self.account.balance != real_bal:
                    self.account.balance = real_bal
                    self.account.equity = real_bal + self.account.unrealized_pnl
                    changed = True
                # peak_equity도 실잔고 기준 갱신
                if self.account.equity > self.account.peak_equity:
                    self.account.peak_equity = self.account.equity
                    changed = True
                if changed:
                    save_account(self.account)
            except Exception:
                pass

    # ── Exit tranche 실주문 발행 (Algo TAKE_PROFIT_MARKET) ────

    async def _place_exit_orders(self, pos: Position):
        """Exit tranche들을 바이낸스 Algo API (TAKE_PROFIT_MARKET)로 발행."""
        close_side = "SELL" if pos.side == PositionSide.LONG else "BUY"
        for tranche in pos.exit_tranches:
            if tranche.status not in (OrderStatus.PENDING, OrderStatus.WAITING):
                continue
            try:
                result = await binance_client.place_algo_order(
                    symbol="BTCUSDT",
                    side=close_side,
                    order_type="TAKE_PROFIT_MARKET",
                    trigger_price=tranche.target_price.quantize(Decimal("0.1")),
                    quantity=tranche.quantity.quantize(Decimal("0.001")),
                    client_order_id=tranche.id,
                )
                tranche.client_order_id = tranche.id
                tranche.binance_order_id = str(result.get("algoId", ""))
                tranche.status = OrderStatus.WAITING
                logger.info(f"[LIVE] TP algo order placed: {tranche.id} trigger={tranche.target_price} qty={tranche.quantity}")
            except Exception as e:
                logger.error(f"[LIVE] TP algo order failed: {e} — will be managed by engine tick")
                # 배치 실패해도 PENDING 유지 → 엔진이 on_price_update에서 직접 관리

    # _sl_exit_reason 은 PaperTradingEngine(부모)에서 상속

    # ── recalculate 오버라이드: exit tranche 생성 후 실주문 ──

    def _recalculate_position(self, pos: Position):
        """부모 로직 실행 후 exit tranche가 새로 생기면 주문 발행 예약."""
        had_exits = len(pos.exit_tranches)
        super()._recalculate_position(pos)
        new_exits = len(pos.exit_tranches)

        if new_exits > had_exits:
            pending_exits = [t for t in pos.exit_tranches if t.status == OrderStatus.PENDING]
            if pending_exits:
                # 발행 예약 (on_signal에서 await로 호출)
                pos.signal_details = pos.signal_details or {}
                pos.signal_details["_pending_exit_placement"] = True

    # ── SL 사전 배치 (STOP_MARKET + reduceOnly) ─────────────

    async def _nuke_all_binance_orders(self):
        """바이낸스 모든 주문 일괄 취소 + read-back 검증 (고아 주문 제거).

        정책 (2026-06-04 회의록 안건2):
          - _retry_request 경유 (raw httpx 금지)
          - 취소 후 openAlgoOrders + openOrders 재조회, 비워질 때까지 최대 3회
          - 3회 후에도 더러우면 HALT + 텔레그램 alert
        """
        for attempt in range(3):
            algos = await binance_client.get_open_algo_orders("BTCUSDT")
            for a in algos:
                try:
                    await binance_client.cancel_algo_order("BTCUSDT", str(a.get("algoId", "")))
                except Exception:
                    pass
            await binance_client.cancel_all_open_orders("BTCUSDT")

            # read-back 검증
            algos_left = await binance_client.get_open_algo_orders("BTCUSDT")
            orders_left = await binance_client.get_open_orders("BTCUSDT")
            if not algos_left and not orders_left:
                logger.info(f"[LIVE] All Binance orders nuked & verified (attempt {attempt+1})")
                return
            logger.warning(
                f"[LIVE] Nuke read-back dirty (attempt {attempt+1}/3): "
                f"algos={len(algos_left)} orders={len(orders_left)}"
            )
            await asyncio.sleep(0.5)

        # 3회 후에도 잔존 → HALT + alert
        logger.critical("[LIVE] Nuke failed to clear orders after 3 attempts → HALT")
        self.anomaly_detector.set_manual_halt("orphan orders persist after nuke")
        try:
            await self.alert_sender._send_telegram_text(
                "🆘 <b>CRITICAL: 고아 주문 제거 실패</b>\n\n"
                "3회 시도 후에도 잔존 주문이 있습니다. 거래 HALT. 수동 확인 필요."
            )
        except Exception:
            pass

    async def _cancel_all_binance_algo_orders(self):
        """하위 호환용."""
        await self._nuke_all_binance_orders()

    async def _ensure_clean_book(self) -> bool:
        """새 진입 전 clean book 검증. 잔존 주문 있으면 nuke 선행.

        Returns: True = 진입 가능(clean), False = 정리 실패(진입 보류).
        """
        algos = await binance_client.get_open_algo_orders("BTCUSDT")
        orders = await binance_client.get_open_orders("BTCUSDT")
        if not algos and not orders:
            return True
        logger.warning(f"[LIVE] Dirty book before entry: algos={len(algos)} orders={len(orders)} → nuke")
        await self._nuke_all_binance_orders()
        # nuke 후 재확인
        algos = await binance_client.get_open_algo_orders("BTCUSDT")
        orders = await binance_client.get_open_orders("BTCUSDT")
        return not algos and not orders

    async def _place_sl_order(self, pos: Position):
        """SL을 바이낸스 Algo API (STOP_MARKET, closePosition=True)로 사전 배치.

        신뢰성 정책 (2026-06-04 회의록 안건1):
          - place-before-cancel: 새 SL 을 먼저 배치/확인한 뒤에만 기존 SL 취소 (무방비 윈도우 제거)
          - algoId 미확인 시 3회 재시도 (0.5s 백오프)
          - 전부 실패 → 즉시 시장가 청산 + HALT + 텔레그램 CRITICAL
          - -2021 (would immediately trigger) → SL 이미 돌파 → 즉시 청산(stop_loss)
          - remaining <= 0 이면 취소도 보류 (기존 SL 유지)

        closePosition=True: 트리거 시 Binance 가 잔여 포지션 전체를 시장가 청산 → over-close 없음.
        """
        close_side = "SELL" if pos.side == PositionSide.LONG else "BUY"

        filled_qty = sum(t.quantity for t in pos.entry_tranches if t.status == OrderStatus.FILLED)
        exited_qty = sum(t.quantity for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
        remaining = filled_qty - exited_qty
        if remaining <= 0:
            # 청산할 수량 없음 → 기존 SL 그대로 유지 (취소 금지)
            return

        pos.signal_details = pos.signal_details or {}
        old_algo_id = str(pos.signal_details.get("sl_algo_id") or "").strip()

        new_algo_id = ""
        for attempt in range(3):
            try:
                result = await binance_client.place_algo_order(
                    symbol="BTCUSDT",
                    side=close_side,
                    order_type="STOP_MARKET",
                    trigger_price=pos.stop_loss_price.quantize(Decimal("0.1")),
                    close_position=True,
                )
                new_algo_id = str(result.get("algoId", "") or "").strip()
                if new_algo_id:
                    break
                logger.warning(f"[LIVE] SL place returned no algoId (attempt {attempt+1}/3)")
            except AlgoNoOpenPosition as e:
                logger.warning(f"[LIVE] SL place -4509: 포지션 이미 청산됨 → HALT 스킵, position-gone reconciler가 청산 처리: {e}")
                return
            except AlgoWouldImmediatelyTrigger as e:
                logger.error(f"[LIVE] SL would immediately trigger → emergency close: {e}")
                await self._emergency_close(pos, reason="stop_loss")
                return
            except AlgoConflictClosePosition as e:
                # -4130: 기존 closePosition SL 이 포지션 보호 중 → 충돌분 취소 후 즉시 1회 재시도 (백오프 0)
                logger.warning(f"[LIVE] SL -4130 conflict → cancel-then-replace recovery: {e}")
                await self._cancel_conflicting_sl(close_side, old_algo_id)
                # 충돌분(old_algo_id 포함)은 이미 취소됨 → 아래 place-before-cancel 블록의
                # 중복 DELETE(-2011 "Unknown order sent" 노이즈) 방지를 위해 클리어
                old_algo_id = ""
                try:
                    result = await binance_client.place_algo_order(
                        symbol="BTCUSDT", side=close_side, order_type="STOP_MARKET",
                        trigger_price=pos.stop_loss_price.quantize(Decimal("0.1")),
                        close_position=True,
                    )
                    new_algo_id = str(result.get("algoId", "") or "").strip()
                    if new_algo_id:
                        break
                except AlgoWouldImmediatelyTrigger as e2:
                    logger.error(f"[LIVE] SL would immediately trigger (post-4130) → emergency close: {e2}")
                    await self._emergency_close(pos, reason="stop_loss")
                    return
                except Exception as e2:
                    logger.error(f"[LIVE] SL -4130 recovery retry failed: {e2}")
                # 재시도 실패 → 루프 빠져나가 fallback read-back 분기로
                break
            except Exception as e:
                logger.error(f"[LIVE] SL algo place failed (attempt {attempt+1}/3): {e}")
            await asyncio.sleep(0.5)

        if not new_algo_id:
            # 포지션이 이미 청산됐으면 무방비가 아님 → HALT 금지 (position-gone reconciler가 청산)
            try:
                bpos = await binance_client.get_position_risk("BTCUSDT")
                if not bpos or float(bpos.get("positionAmt", 0)) == 0:
                    logger.warning("[LIVE] SL place failed but no open position on Binance → already closed, skip HALT")
                    return
            except Exception:
                pass
            # read-back: 방향 내 closePosition SL 이 실제 살아있는지 확인 후 분기 (합의 #3)
            protected = None  # None=확인불가
            try:
                cp = await self._count_closeposition_sl(close_side)
                protected = cp >= 1
            except Exception as e:
                logger.error(f"[LIVE] SL read-back failed (treat as unprotected): {e}")
                protected = None
            if protected:
                # 기존 SL 이 포지션 보호 중 → 청산/HALT 안 함, 다음 사이클 재시도
                logger.warning("[LIVE] SL re-place failed but existing closePosition SL alive → keep, retry next cycle")
                try:
                    await self.alert_sender._send_telegram_text(
                        "⚠️ <b>SL 재배치 실패 — 기존 SL 보호 유지</b>\n\n"
                        f"Side: {pos.side.value} | trigger=${pos.stop_loss_price}\n다음 사이클 재시도."
                    )
                except Exception:
                    pass
                return
            # 무방비(0개) 또는 확인불가(None) → emergency_close + HALT (기존 동작)
            logger.critical("[LIVE] SL placement failed → no live SL confirmed → emergency close + HALT")
            self.anomaly_detector.set_manual_halt("SL place failed 3x")
            await self.alert_sender._send_telegram_text(
                "🆘 <b>CRITICAL: SL 배치 실패 (무방비/확인불가)</b>\n\n"
                "포지션을 즉시 시장가 청산하고 거래를 HALT 합니다.\n"
                f"Side: {pos.side.value} | trigger=${pos.stop_loss_price}"
            )
            await self._emergency_close(pos, reason="sl_place_failed")
            return

        # 새 SL 확인됨 → 이제서야 기존 SL 취소 (place-before-cancel)
        pos.signal_details["sl_algo_id"] = new_algo_id
        if old_algo_id and old_algo_id != new_algo_id:
            try:
                await binance_client.cancel_algo_order("BTCUSDT", old_algo_id)
            except Exception:
                pass
        logger.info(f"[LIVE] SL algo placed: {close_side} STOP_MARKET trigger={pos.stop_loss_price} closePosition=true algoId={new_algo_id}")
        # read-back: 방향 내 closePosition SL 이 정확히 1개인지 검증 (초과분 방어 취소)
        try:
            await self._dedupe_closeposition_sl(close_side, keep_algo_id=new_algo_id)
        except Exception:
            pass

    def _is_closeposition_stop(self, o: dict, close_side: str) -> bool:
        t = str(o.get("type", "") or o.get("orderType", "")).upper()
        side = str(o.get("side", "")).upper()
        cp = o.get("closePosition")
        cp_true = cp is True or str(cp).lower() == "true"
        return "STOP" in t and side == close_side and cp_true

    async def _count_closeposition_sl(self, close_side: str) -> int:
        orders = await binance_client.get_open_algo_orders("BTCUSDT")
        return sum(1 for o in orders if self._is_closeposition_stop(o, close_side))

    async def _cancel_conflicting_sl(self, close_side: str, old_algo_id: str):
        """충돌하는 기존 closePosition SL 취소: old_algo_id 우선, 없으면 방향 스캔."""
        cancelled = False
        if old_algo_id:
            try:
                await binance_client.cancel_algo_order("BTCUSDT", old_algo_id)
                cancelled = True
            except Exception:
                pass
        try:
            orders = await binance_client.get_open_algo_orders("BTCUSDT")
            for o in orders:
                if self._is_closeposition_stop(o, close_side):
                    aid = str(o.get("algoId", "") or "").strip()
                    if aid:
                        await binance_client.cancel_algo_order("BTCUSDT", aid)
                        cancelled = True
        except Exception:
            pass
        return cancelled

    async def _dedupe_closeposition_sl(self, close_side: str, keep_algo_id: str):
        """방향 내 closePosition SL 이 2개 이상이면 keep 제외 초과분 취소 (방어)."""
        orders = await binance_client.get_open_algo_orders("BTCUSDT")
        for o in orders:
            if self._is_closeposition_stop(o, close_side):
                aid = str(o.get("algoId", "") or "").strip()
                if aid and aid != str(keep_algo_id):
                    try:
                        await binance_client.cancel_algo_order("BTCUSDT", aid)
                        logger.info(f"[LIVE] dedupe extra closePosition SL: {aid}")
                    except Exception:
                        pass

    async def _emergency_close(self, pos: Position, reason: str):
        """SL 배치 불가/돌파 시 즉시 시장가 청산 (무방비 포지션 제거)."""
        logger.critical(f"[LIVE] EMERGENCY CLOSE: pos={pos.id} reason={reason}")
        close_price = self._last_price or pos.avg_entry_price or Decimal("0")
        try:
            binance_pos = await binance_client.get_position_risk("BTCUSDT")
            if binance_pos and float(binance_pos.get("positionAmt", 0)) != 0:
                amt = Decimal(str(binance_pos["positionAmt"]))
                close_side = "SELL" if amt > 0 else "BUY"
                resp = await binance_client.place_order(
                    symbol="BTCUSDT", side=close_side, order_type="MARKET",
                    quantity=abs(amt).quantize(Decimal("0.001")),
                )
                if resp.get("avgPrice"):
                    close_price = Decimal(str(resp["avgPrice"]))
        except Exception as e:
            logger.error(f"[LIVE] Emergency market close failed: {e}")
        # 잔존 주문 전부 취소
        try:
            await self._nuke_all_binance_orders()
        except Exception:
            pass
        # 로컬 청산 기록
        if pos.id in self.open_positions:
            try:
                self._close_position(pos.id, close_price, reason)
            except Exception as e:
                logger.error(f"[LIVE] Emergency local close failed: {e}")
        try:
            await self.alert_sender._send_telegram_text(
                f"🆘 <b>EMERGENCY CLOSE — {reason}</b>\n\n"
                f"Side: {pos.side.value}\nClose: ~${close_price}"
            )
        except Exception:
            pass

    async def _assert_sl_armed(self, pos: Position):
        """열린 포지션에 live STOP algo 가 실재하는지 검증. 없으면 1회 재무장, 실패 시 비상청산."""
        try:
            binance_pos = await binance_client.get_position_risk("BTCUSDT")
        except Exception:
            return  # 조회 실패 시 이번 사이클은 건너뜀 (다음 사이클 재시도)
        if not binance_pos or float(binance_pos.get("positionAmt", 0)) == 0:
            return  # 포지션 없음 → SL 불필요

        algo_id = str((pos.signal_details or {}).get("sl_algo_id") or "").strip()
        armed = False
        if algo_id:
            try:
                algo = await binance_client.get_algo_order("BTCUSDT", algo_id)
                if algo and algo.get("algoStatus", "") in ("NEW", "WORKING"):
                    armed = True
            except Exception:
                armed = False
        if not armed:
            logger.warning(f"[LIVE] SL not armed for open position → re-arming (algo_id={algo_id!r})")
            await self._place_sl_order(pos)

    async def _cancel_sl_order(self, pos: Position):
        """기존 SL algo 주문 취소."""
        algo_id = (pos.signal_details or {}).get("sl_algo_id")
        if algo_id and str(algo_id).strip():
            try:
                await binance_client.cancel_algo_order("BTCUSDT", str(algo_id))
                logger.info(f"[LIVE] SL algo order cancelled: {algo_id}")
                pos.signal_details["sl_algo_id"] = ""
            except Exception:
                pass

    async def _cancel_all_exit_orders(self, pos: Position):
        """모든 exit tranche의 Algo 주문 취소."""
        for tranche in pos.exit_tranches:
            if tranche.status in (OrderStatus.PENDING, OrderStatus.WAITING):
                if tranche.binance_order_id and str(tranche.binance_order_id).strip():
                    try:
                        await binance_client.cancel_algo_order("BTCUSDT", str(tranche.binance_order_id))
                        logger.info(f"[LIVE] TP algo cancelled: {tranche.binance_order_id}")
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

    # ── 청산 회계 오버라이드 (실잔고 기반 일원화, 2026-06-04 회의록 안건5) ─────

    def _close_position(self, pos_id: str, price: Decimal, reason: str):
        """Live: trade record/통계는 super 재사용하되 로컬 balance 가감은 무효화.

        Live 잔고는 Binance 실잔고 동기화가 권위 (caller 가 self.account.balance = real_bal).
        super()._close_position 의 balance ±(fee/margin/pnl) 를 되돌려, 실잔고 sync 실패 시에도
        로컬 추정치로 오염되지 않게 한다. daily_pnl 은 청산 후 caller 가 실잔고 기준으로 재계산.

        price <= 0 (emergency 등 가격 불명): total_realized_pnl 에 garbage 가 누적되지 않도록
        super 가 더한 realized_pnl 을 되돌리고 trade.realized_pnl=0 으로 무효화.
        """
        bal_before = self.account.balance
        pnl_before = self.account.total_realized_pnl
        trade = super()._close_position(pos_id, price, reason)
        # super 의 로컬 balance 가감 되돌림 (실잔고 sync 가 권위)
        self.account.balance = bal_before
        # price <= 0: 계산된 PnL 은 신뢰불가 → total_realized_pnl 오염 방지
        if price <= Decimal("0") and trade is not None:
            self.account.total_realized_pnl = pnl_before
            trade.realized_pnl = Decimal("0")
        return trade

    def _resync_after_close(self, real_bal: Decimal):
        """청산 후 실잔고 동기화 + daily_pnl 실잔고 기반 재계산."""
        self.account.balance = real_bal
        self.account.margin_used = Decimal("0")
        base = self.account.daily_start_balance
        if base and base > 0:
            self.account.daily_pnl = real_bal - base

    def _check_daily_reset(self, now: int):
        """Live: daily_start_balance 는 실잔고만 (cross margin — margin_used 더하지 않음)."""
        mu = self.account.margin_used
        self.account.margin_used = Decimal("0")  # 스냅샷 계산에서 margin 제외
        try:
            super()._check_daily_reset(now)
        finally:
            self.account.margin_used = mu

    # ── Account 업데이트 오버라이드 (cross margin) ─────────

    def _update_account(self, price: Decimal):
        """Cross margin: equity = balance + unrealized (margin 중복 제거)."""
        unrealized = Decimal("0")
        for pos in self.open_positions.values():
            if pos.avg_entry_price and pos.total_quantity > 0:
                unrealized += self._calc_pnl(pos.side, pos.avg_entry_price, price, pos.total_quantity, pos.leverage)
        self.account.unrealized_pnl = unrealized
        self.account.equity = self.account.balance + unrealized
        if self.account.equity > self.account.peak_equity:
            self.account.peak_equity = self.account.equity

    # ── Reset (DB 초기화 + 바이낸스 주문 전부 취소) ───────────

    def reset(self):
        """위험: 모든 데이터 초기화. 바이낸스 주문은 취소하지 않음."""
        logger.warning("[LIVE] Reset called — local state only")
        super().reset()

    # ── Admin: tick 버그로 취소된 entry tranche 재배치 ─────────

    async def replace_cancelled_entry_orders(self, pos_id: str) -> dict:
        """포지션의 CANCELLED entry tranche를 LIMIT 주문으로 다시 배치.
        tick size 버그(`Decimal("0.10")`) 수정 직후 한 번 회수용으로 사용."""
        async with self._lock:
            pos = self.open_positions.get(pos_id)
            if not pos:
                return {"error": "position not found", "pos_id": pos_id}

            binance_side = "BUY" if pos.side == PositionSide.LONG else "SELL"
            results: list[dict] = []

            for tranche in pos.entry_tranches:
                if tranche.status != OrderStatus.CANCELLED:
                    continue
                new_cid = f"{tranche.id}-r"
                try:
                    resp = await binance_client.place_order(
                        symbol="BTCUSDT",
                        side=binance_side,
                        order_type="LIMIT",
                        quantity=tranche.quantity,
                        price=tranche.target_price,
                        client_order_id=new_cid,
                    )
                    tranche.client_order_id = new_cid
                    tranche.binance_order_id = str(resp.get("orderId", ""))
                    tranche.status = OrderStatus.WAITING
                    results.append({
                        "tranche": tranche.id,
                        "status": "replaced",
                        "price": str(tranche.target_price),
                        "qty": str(tranche.quantity),
                        "binance_order_id": tranche.binance_order_id,
                    })
                    logger.info(f"[LIVE] Re-placed cancelled entry: {tranche.id} @ {tranche.target_price}")
                except Exception as e:
                    results.append({
                        "tranche": tranche.id,
                        "status": "failed",
                        "error": str(e),
                    })
                    logger.error(f"[LIVE] Replace cancelled entry failed: {tranche.id} — {e}")

            save_position(pos)
            return {"position_id": pos_id, "results": results}
