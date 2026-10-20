"""LiveV1Engine — A-fixed Turtle (4h) with the outage-safety layer.

Invariants (spec v1 §8-10, v2 §8-9):
  * Exchange is authoritative. Balance/position/orders/fills/fees/funding are read from Binance;
    the local DB is a cache + journal. Local never overwrites the exchange.
  * Sizing uses a fresh exchange balance fetched right before each entry.
  * Every open position has a live closePosition STOP_MARKET on the exchange, or it is closed.
  * One position, no averaging: an entry is refused whenever the exchange shows any position.
  * Each order intent has a deterministic client id; unknown outcomes are resolved by querying
    that id. Entries are NEVER re-sent after an unknown outcome; reduce-only exits may be re-sent
    only after the id is confirmed absent (reduce-only cannot over-close or flip).
  * Any mismatch / API-error streak / stale feed blocks NEW entries (existing stops untouched).
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal

from pydantic import BaseModel

from app.trading.engine import PaperTradingEngine
from app.trading.persistence import delete_position, load_kv, save_account, save_kv, save_position, save_trade
from app.trading.schemas import OrderStatus, Position, PositionSide, TradeRecord, TrancheOrder
from app.trading.tg_format import fmt_entry, fmt_exit, kst_date, trade_net_pnl
from app.trading.live_v1 import safety as S
from app.trading.live_v1.exchange import (
    ExchangeError, ExchangeUnavailable, OrderRejected, SymbolRules, WouldTrigger, close_side,
)
from app.trading.live_v1.strategy import TurtleParams, allowed_side, compute_signals, replay

logger = logging.getLogger(__name__)

TAKER_FEE = Decimal("0.0005")


class LiveV1Settings(BaseModel):
    symbol: str = "BTCUSDT"              # configurable (team may switch to ETHUSDT)
    direction: str = "both"              # both | long_only  (spec v2 §8: both until v2 decides)
    risk_pct: float = 0.5                # % of fresh exchange wallet per trade
    max_risk_pct: float = 1.0            # skip if risk after rounding (+ round-trip taker fees) exceeds this
    rules_refresh_s: float = 86400.0     # exchangeInfo filters cache (refresh daily)
    max_leverage: int = 10               # TA review: cap 10x (liquidation guard below still applies)
    interval: str = "4h"
    kline_limit: int = 1000              # ATR warm-up ≫ 14 bars → converged to research values
    act_window_s: int = 900              # entries only within 15 min after bar close
    N: int = 55
    M: int = 20
    k: float = 2.0
    atr_n: int = 14
    api_error_n: int = 5
    api_error_window_s: float = 300.0
    query_retries: int = 3
    query_delay_s: float = 1.0
    stop_attempts: int = 3
    ledger_tol_pct: float = 0.5
    income_interval_s: float = 60.0      # ledger/income reconciliation cadence (spec v2 §9: 1 min)
    autohalt_dd_pct: float = 15.0
    autohalt_pf: float = 0.8             # review alert only (TA): never halts / blocks
    autohalt_pf_after: int = 30
    maint_margin_rate: float = 0.004     # fallback only; per-symbol MMR comes from /fapi/v1/leverageBracket
    breach_grace_s: float = 1.0          # after mark crosses the stop, give the exchange stop this long to fire
    liq_buffer_ratio: float = 0.7        # stop distance ≤ 0.7 × liquidation distance
    fallback_stop_pct: float = 3.0       # only if ATR is unavailable when adopting an unknown position

    @property
    def params(self) -> TurtleParams:
        return TurtleParams(self.N, self.M, self.k, self.atr_n)


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _now_ms() -> int:
    return int(time.time() * 1000)


class LiveV1Engine(PaperTradingEngine):
    def __init__(self, exchange, settings: LiveV1Settings | None = None):
        super().__init__()
        self.ex = exchange
        self.v1 = settings or LiveV1Settings()
        self.gate = S.EntryGate()
        self.gate.block(S.STARTUP, "startup")
        self.breaker = S.ApiErrorBreaker(self.v1.api_error_n, self.v1.api_error_window_s)
        self.hb = S.Heartbeat()
        self.meta: dict = load_kv("v1:meta") or {}
        self.pos: dict | None = load_kv("v1:pos")          # current position journal (cache)
        self.alerts: list[str] = []
        self.ledger_vs_exchange_balance_diff: float | None = None
        self._ledger_strikes = 0
        self._last_income_check = 0.0
        self._consistent_streak = 0
        self._initialized = False
        self._autohalted = False
        self.rules: SymbolRules | None = None
        self.brackets: list[dict] = []
        self.last_mark: Decimal | None = None
        self._breach_task: asyncio.Task | None = None
        self._rules_at = 0.0
        self.settings.max_leverage = self.v1.max_leverage

    # ── infra ──────────────────────────────────────────────
    async def _alert(self, title: str, detail: str = "", action: str = ""):
        self.alerts.append(title)
        logger.critical(f"[V1] 🚨 {title} | {detail} | {action}")
        try:
            await self.alert_sender.push_alert(title, detail, action)
        except Exception as e:
            logger.error(f"[V1] alert send failed: {e}")

    async def _call(self, coro):
        """Await an exchange call with API-error accounting (spec §10)."""
        try:
            r = await coro
        except WouldTrigger:
            raise
        except ExchangeError:
            if self.breaker.error():
                self.gate.block(S.API_ERRORS)
                await self._alert("API 오류 연속 — 신규 진입 중단",
                                  f"{self.breaker.n}회 연속 실패", "기존 손절 유지 · 복구 시 자동 재개")
            raise
        if self.breaker.success():
            await self._clear(S.API_ERRORS)
        return r

    def _save_meta(self):
        save_kv("v1:meta", self.meta)

    def _save_pos(self):
        save_kv("v1:pos", self.pos)

    def entries_allowed(self) -> bool:
        return self.gate.allowed() and not self.anomaly_detector.is_halted()

    async def _clear(self, reason: str, notify: bool = True) -> bool:
        """Clear a safety block; if entries are now allowed, push one line saying which block cleared."""
        if not self.gate.clear(reason):
            return False
        logger.warning(f"[V1] block cleared: {reason}")
        if notify and self.entries_allowed():
            try:
                await self.alert_sender.send_text(f"✅ 신규 진입 재개 — {S.BLOCK_LABELS.get(reason, reason)} 해제")
            except Exception as e:
                logger.error(f"[V1] resume notice failed: {e}")
        return True

    def _skip(self, reason: str, detail: str = ""):
        """Count a skipped entry signal per KST day and reason (→ daily summary / Notion)."""
        from app.trading.tg_format import kst_date
        day = kst_date()
        skips = self.meta.setdefault("skips", {})
        for d in sorted(d for d in skips if d < day)[:-7]:    # keep ~a week
            skips.pop(d, None)
        skips.setdefault(day, {})
        skips[day][reason] = skips[day].get(reason, 0) + 1
        self._save_meta()
        logger.warning(f"[V1] entry skipped ({reason}): {detail}")

    def skip_counts(self, date: str) -> dict:
        return dict((self.meta.get("skips") or {}).get(date, {}))

    # ── PaperTradingEngine hooks (legacy strategy C disabled) ──
    async def on_signal(self, signal: dict, current_price: Decimal):
        return None

    async def on_price_update(self, price: Decimal) -> list[dict]:
        """BTCUSDT aggTrade feed (chart/analysis). Not the v1 heartbeat — see on_mark_price."""
        return []

    async def on_mark_price(self, symbol: str, mark: Decimal):
        """Mark-price stream of the CONFIGURED symbol: heartbeat + immediate stop-breach guard."""
        if symbol.upper() != self.v1.symbol.upper():
            return
        self.last_mark = mark
        self._last_price = mark
        self.hb.price_tick()
        self.anomaly_detector.record_price_update(_now_ms())
        if self._crossed(mark) and (self._breach_task is None or self._breach_task.done()):
            self._breach_task = asyncio.create_task(self._breach_guard(mark, source="mark stream"))

    def _crossed(self, mark: Decimal | None) -> bool:
        if not self.pos or mark is None or not self.pos.get("stop_px"):
            return False
        stop = _d(self.pos["stop_px"])
        return mark <= stop if self.pos["side"] > 0 else mark >= stop

    async def _breach_guard(self, mark: Decimal, source: str, locked: bool = False):
        """Mark crossed the model stop. If the exchange STILL shows the position after a short grace
        (exchange stop missing / not fired), close it now with a reduce-only market order, halt, 🚨."""
        if self.v1.breach_grace_s > 0:
            await asyncio.sleep(self.v1.breach_grace_s)
        if locked:
            await self._breach_close(mark, source)
        else:
            async with self._lock:
                await self._breach_close(mark, source)

    async def _breach_close(self, mark: Decimal, source: str):
        if not self.pos:
            return
        try:
            p = await self._call(self.ex.position())
        except ExchangeError as e:
            logger.error(f"[V1] breach check: position read failed: {e}")
            return
        if p["amt"] == 0:
            await self._record_close("stop_loss")              # exchange stop fired normally
            return
        stop = self.pos["stop_px"]
        cid = f"{self.pos['cid']}b"                            # one breach close per position
        self.anomaly_detector.set_manual_halt("v1 stop breached, exchange stop did not fire")
        try:
            book = await self._call(self.ex.book())
            self.pos["exit_ref"] = str(book["bid"] if p["amt"] > 0 else book["ask"])
            o = await self._submit_market(close_side(p["amt"]), abs(p["amt"]), cid, reduce_only=True)
            self.pos["exit_order_id"] = (o or {}).get("id")
        except ExchangeError as e:
            logger.error(f"[V1] breach close order error: {e}")
        await self._alert("손절가 돌파 — 즉시 시장가 청산 + 매매 중단",
                          f"mark {mark} vs 손절 {stop} ({source}) · 거래소 손절 미작동",
                          "확인 후 /resume")
        try:
            p2 = await self._call(self.ex.position())
            if p2["amt"] == 0:
                for so in await self._call(self.ex.open_orders()):
                    if so["close_position"] or so["reduce_only"]:
                        await self._call(self.ex.cancel_stop(so))
                await self._record_close("stop_breach")
        except ExchangeError as e:
            logger.error(f"[V1] breach close verify failed (next reconcile retries): {e}")

    async def check_heartbeat(self):
        if not self.hb.price_ok():
            if self.gate.block(S.HEARTBEAT):
                await self._alert("하트비트 끊김 (가격 피드)", f"{self.hb.price_stale_s:.0f}초 이상 가격 없음",
                                  "신규 진입 중단 · 거래소 손절 유지")
        else:
            await self._clear(S.HEARTBEAT)

    # ── startup ────────────────────────────────────────────
    async def initialize(self):
        """Reconcile FIRST: every exchange position gets a live stop or is closed before anything else."""
        self.gate.block(S.STARTUP, "startup")
        try:
            async with self._lock:
                await self._ensure_rules()
                await self._reconcile()
                await self._ensure_isolated()
                if "live_start_wallet" not in self.meta:
                    acct = await self._call(self.ex.account())
                    self.meta.update(live_start_wallet=str(acct["wallet"]), live_start_ms=_now_ms(),
                                     ledger_balance=str(acct["wallet"]), income_cursor=_now_ms(),
                                     net_transfers="0")
                    self._save_meta()
                await self._clear(S.STARTUP, notify=False)
        except ExchangeError as e:
            logger.error(f"[V1] startup reconcile failed, entries stay blocked: {e}")
        self._initialized = True

    async def _ensure_isolated(self) -> bool:
        """ISOLATED margin for the symbol, verified by read-back. Failure → entries blocked + 🚨
        (retried by the 5s reconcile while flat)."""
        err = ""
        try:
            try:
                await self._call(self.ex.set_margin_type("ISOLATED"))
            except OrderRejected as e:                # e.g. -4048 open position / open orders
                err = str(e)
            mt = await self._call(self.ex.margin_type())
        except ExchangeError as e:
            mt, err = "?", str(e)
        if mt == "ISOLATED":
            if S.MARGIN in self.gate.reasons:
                await self._clear(S.MARGIN)
            return True
        if S.MARGIN not in self.gate.reasons:
            self.gate.block(S.MARGIN, f"margin {mt}")
            await self._alert("마진 모드 ISOLATED 설정 실패 — 신규 진입 중단",
                              f"{self.v1.symbol} 현재 {mt} {err[:80]}".strip(),
                              "포지션/주문 정리 후 자동 재시도")
        return False

    # ── sizing / helpers ───────────────────────────────────
    async def _ensure_rules(self) -> SymbolRules:
        """tick/step/minQty/minNotional from exchangeInfo; cached, refreshed daily."""
        if self.rules is None or time.time() - self._rules_at > self.v1.rules_refresh_s:
            try:
                self.rules = await self._call(self.ex.symbol_rules())
                self._rules_at = time.time()
                logger.info(f"[V1] symbol rules {self.rules}")
                try:
                    self.brackets = await self._call(self.ex.leverage_brackets()) or self.brackets
                except ExchangeError as e:
                    logger.warning(f"[V1] leverageBracket unavailable → MMR fallback "
                                   f"{self.v1.maint_margin_rate}: {e}")
            except ExchangeError:
                if self.rules is None:
                    raise
                logger.warning("[V1] exchangeInfo refresh failed; using cached rules")
        return self.rules

    def _stop_price(self, entry: Decimal, side: int, dist: Decimal) -> Decimal:
        """Stop rounded to tick TOWARD the entry (never wider than the model stop)."""
        raw = entry - side * dist
        return self.rules.price(raw, "up" if side > 0 else "down") if self.rules else raw

    async def _atr_stop_dist(self) -> Decimal | None:
        try:
            bars = await self._call(self.ex.klines(self.v1.interval, self.v1.kline_limit))
            sd = compute_signals([b for b in bars if b["close_time"] < _now_ms()], self.v1.params).stop_dist
            if sd and sd[-1] == sd[-1]:
                return _d(sd[-1])
        except Exception as e:
            logger.error(f"[V1] ATR fetch failed: {e}")
        return None

    async def _wait_order(self, cid: str) -> dict | None:
        """Resolve an unknown outcome by client id. Returns order, None (confirmed absent) or raises."""
        last_exc: Exception | None = None
        for _ in range(self.v1.query_retries):
            await asyncio.sleep(self.v1.query_delay_s)
            try:
                return await self._call(self.ex.get_order(cid))
            except ExchangeUnavailable as e:
                last_exc = e
        raise ExchangeUnavailable(f"order {cid} status unknown") from last_exc

    async def _submit_market(self, side: str, qty: Decimal, cid: str, reduce_only: bool) -> dict | None:
        """Idempotent market order. Never double-submits (see module docstring)."""
        existing = await self._call(self.ex.get_order(cid))      # replay after restart → reuse
        if existing is not None:
            return existing
        try:
            return await self._call(self.ex.market(side, qty, cid, reduce_only))
        except ExchangeUnavailable:
            logger.warning(f"[V1] order {cid} outcome unknown → query before any retry")
            try:
                found = await self._wait_order(cid)
            except ExchangeUnavailable:
                self.gate.block(S.UNKNOWN_ORDER, cid)
                await self._alert("주문 상태 확인 불가 — 신규 진입 중단", cid, "대조 루프가 거래소 기준으로 정리")
                raise
            if found is not None:
                return found
            if not reduce_only:
                logger.warning(f"[V1] entry {cid} confirmed absent → NOT re-sent (signal skipped)")
                return None
            return await self._call(self.ex.market(side, qty, cid + "r", reduce_only))

    def _position_side(self, amt: Decimal) -> int:
        return 1 if amt > 0 else -1 if amt < 0 else 0

    # ── stop protection ────────────────────────────────────
    async def _find_stop(self, amt: Decimal, orders: list[dict] | None = None) -> dict | None:
        orders = orders if orders is not None else await self._call(self.ex.open_orders())
        cs = close_side(amt)
        for o in orders:
            if o["side"] == cs and (o["type"] or "").startswith("STOP") and (o["close_position"] or o["reduce_only"]):
                return o
        return None

    async def _ensure_stop(self, amt: Decimal, stop_px: Decimal, cid_base: str) -> bool:
        """True iff a live reduce-only/closePosition stop for this position is CONFIRMED on the exchange."""
        try:
            if await self._find_stop(amt):
                return True
        except ExchangeError:
            pass
        cs = close_side(amt)
        for attempt in range(self.v1.stop_attempts):
            seq = int((self.pos or {}).get("stop_seq", 0))
            if self.pos is not None:
                self.pos["stop_seq"] = seq + 1
                self._save_pos()
            cid = f"{cid_base}s{seq}"                    # unique per placement attempt (audit trail)
            try:
                await self._call(self.ex.stop(cs, stop_px, cid))
            except WouldTrigger:
                logger.error(f"[V1] stop {stop_px} would trigger immediately → close")
                return False
            except OrderRejected as e:
                logger.error(f"[V1] stop rejected ({e}); attempt {attempt + 1}")
            except ExchangeUnavailable as e:
                logger.error(f"[V1] stop placement unknown ({e}); read-back")
            try:
                if await self._find_stop(amt):
                    return True
            except ExchangeError:
                continue
        return False

    async def _emergency_close(self, reason: str, halt: bool = True) -> None:
        """Reduce-only market close of whatever the exchange holds; halt + 🚨."""
        for attempt in range(3):
            try:
                p = await self._call(self.ex.position())
                if p["amt"] == 0:
                    break
                book = await self._call(self.ex.book())
                ref = book["bid"] if p["amt"] > 0 else book["ask"]
                o = await self._submit_market(close_side(p["amt"]), abs(p["amt"]),
                                              f"v1x{_now_ms()}", reduce_only=True)
                if self.pos:
                    self.pos["exit_ref"] = str(ref)
                    self.pos["exit_order_id"] = (o or {}).get("id")
            except ExchangeError as e:
                logger.error(f"[V1] emergency close attempt {attempt + 1} failed: {e}")
        if halt:
            self.anomaly_detector.set_manual_halt(f"v1 {reason}")
        await self._alert(f"비상청산 + 매매 중단 ({reason})", "손절을 거래소에 확인하지 못함",
                          "확인 후 /resume")
        try:
            p = await self._call(self.ex.position())
            if p["amt"] == 0 and self.pos:
                await self._record_close(reason)
        except ExchangeError:
            pass

    # ── reconciliation (exchange → local) ──────────────────
    async def reconcile_orders(self):
        """Scheduler hook (every few seconds)."""
        if not self._initialized:
            return
        async with self._lock:
            try:
                await self._ensure_rules()
                await self._reconcile()
                if S.STARTUP in self.gate.reasons:
                    await self._clear(S.STARTUP)
                await self._check_ledger()
            except ExchangeError as e:
                logger.error(f"[V1] reconcile failed: {e}")

    async def _reconcile(self):
        self.hb.loop_tick()
        acct = await self._call(self.ex.account())
        p = await self._call(self.ex.position())
        orders = await self._call(self.ex.open_orders())
        self.account.balance = acct["wallet"]                   # cache only
        self.account.equity = acct["wallet"]
        amt = p["amt"]
        mismatch: list[str] = []

        if amt != 0 and self.pos:
            try:
                mark = await self._call(self.ex.mark_price())
                self.last_mark = mark
            except ExchangeError:
                mark = None
            if self._crossed(mark):
                await self._breach_guard(mark, source="5s reconcile", locked=True)
                return

        if amt == 0 and S.MARGIN in self.gate.reasons:
            await self._ensure_isolated()                       # retry once flat

        if amt == 0 and self.pos:
            # position gone on the exchange → stop (or manual) fill
            await self._record_close("stop_loss" if self.pos.get("stop_px") else "exchange_close")
        elif amt != 0 and not self.pos:
            mismatch.append(f"기록 없는 포지션 {amt} {self.v1.symbol} @ {p['entry']}")
            await self._adopt(p)
        elif amt != 0 and self.pos and _d(self.pos["qty"]) * self.pos["side"] != amt:
            mismatch.append(f"수량 불일치 로컬 {self.pos['side'] * float(self.pos['qty']):+} / 거래소 {amt}")
            await self._adopt(p, keep_stop=True)

        if amt != 0:
            if not await self._find_stop(amt, orders):
                stop_px = _d(self.pos["stop_px"]) if self.pos and self.pos.get("stop_px") else None
                if stop_px is None:
                    sd = await self._atr_stop_dist() or p["entry"] * _d(self.v1.fallback_stop_pct) / 100
                    stop_px = self._stop_price(p["entry"], self._position_side(amt), sd)
                await self._alert("손절 주문 없음 — 재등록 시도", f"{amt} {self.v1.symbol} · 손절 {stop_px}")
                if not await self._ensure_stop(amt, stop_px, (self.pos or {}).get("cid", f"v1a{_now_ms()}")):
                    await self._emergency_close("sl_missing")
                    return
                orders = await self._call(self.ex.open_orders())

        # stray orders: anything that is not a protective stop of the current position
        prot = await self._find_stop(amt, orders) if amt != 0 else None
        for o in orders:
            if prot and o["id"] == prot["id"]:
                continue
            if amt == 0 and o["close_position"] and str(o["client_id"]).startswith("v1"):
                try:
                    await self._call(self.ex.cancel_stop(o))   # our own stale stop, position flat
                except ExchangeError:
                    pass
                continue
            mismatch.append(f"예상 밖 주문 {o['type']} {o['side']} ({o['client_id']})")

        if mismatch:
            self._consistent_streak = 0
            if self.gate.block(S.MISMATCH, "; ".join(mismatch)):
                await self._alert("대조 불일치 — 신규 진입 중단", mismatch[0][:120],
                                  "거래소 기준으로 덮어씀 · 일치 확인 후 자동 재개")
        else:
            self._consistent_streak += 1
            if self._consistent_streak >= 2:
                await self._clear(S.MISMATCH)
                await self._clear(S.UNKNOWN_ORDER)
        save_account(self.account)

    async def _adopt(self, p: dict, keep_stop: bool = False):
        """Overwrite the local journal with the exchange position."""
        side = self._position_side(p["amt"])
        old = self.pos or {}
        stop_px = old.get("stop_px") if keep_stop else None
        if stop_px is None:
            sd = await self._atr_stop_dist() or p["entry"] * _d(self.v1.fallback_stop_pct) / 100
            stop_px = str(self._stop_price(p["entry"], side, sd))
            risk = abs(p["entry"] - _d(stop_px)) * abs(p["amt"])
        else:
            risk = _d(old.get("risk_usdt", "0"))
        self.pos = {
            "cid": old.get("cid", f"v1a{_now_ms()}"), "side": side, "qty": str(abs(p["amt"])),
            "entry_px": str(p["entry"]), "stop_px": str(stop_px), "risk_usdt": str(risk),
            "opened_at": old.get("opened_at", _now_ms()), "entry_order_id": old.get("entry_order_id"),
            "entry_ref": old.get("entry_ref", str(p["entry"])), "adopted": True,
        }
        self._save_pos()
        self._sync_position_view()

    def _sync_position_view(self):
        """Mirror the journal into PaperTradingEngine.open_positions (for /status, API)."""
        for pid in list(self.open_positions):
            delete_position(pid)
        self.open_positions.clear()
        if not self.pos:
            return
        side = PositionSide.LONG if self.pos["side"] > 0 else PositionSide.SHORT
        qty = _d(self.pos["qty"]); entry = _d(self.pos["entry_px"])
        t = TrancheOrder(id=f"{self.pos['cid']}-e0", position_id=self.pos["cid"], side=side, is_entry=True,
                         target_price=entry, quantity=qty, filled_price=entry, status=OrderStatus.FILLED,
                         client_order_id=self.pos["cid"], created_at=self.pos["opened_at"])
        lev = int(self.pos.get("leverage") or self.v1.max_leverage)
        pos = Position(id=self.pos["cid"], symbol=self.v1.symbol, side=side, leverage=lev, signal_type="turtle_v1",
                       signal_strength=1.0, entry_tranches=[t], exit_tranches=[],
                       stop_loss_price=_d(self.pos["stop_px"]), avg_entry_price=entry, total_quantity=qty,
                       allocated_quantity=qty, allocated_margin=(entry * qty / lev),
                       timeframe=self.v1.interval, status="open", opened_at=self.pos["opened_at"],
                       signal_details={"tg_risk_usdt": self.pos.get("risk_usdt", "0")})
        self.open_positions[pos.id] = pos
        save_position(pos)

    # ── ledger vs exchange (income API) ────────────────────
    async def _check_ledger(self):
        if "live_start_wallet" not in self.meta:
            return
        if time.time() - self._last_income_check < self.v1.income_interval_s:
            return
        self._last_income_check = time.time()
        cursor = int(self.meta.get("income_cursor", _now_ms()))
        seen = set(self.meta.get("income_seen", []))          # tran ids already booked at `cursor` ms
        rows = await self._call(self.ex.income(None, cursor))  # inclusive; dedupe by tranId
        ledger = _d(self.meta["ledger_balance"]); transfers = _d(self.meta.get("net_transfers", "0"))
        for r in sorted(rows, key=lambda r: r["time"]):
            key = f"{r['type']}:{r['tran_id']}"
            if r["time"] < cursor or (r["time"] == cursor and key in seen):
                continue
            ledger += r["amount"]
            if r["type"] == "TRANSFER":
                transfers += r["amount"]
            if r["time"] > cursor:
                cursor, seen = r["time"], set()
            seen.add(key)
        self.meta.update(ledger_balance=str(ledger), net_transfers=str(transfers), income_cursor=cursor,
                         income_seen=sorted(seen))
        self._save_meta()
        wallet = self.account.balance
        diff = wallet - ledger
        self.ledger_vs_exchange_balance_diff = round(float(diff), 4)
        if wallet > 0 and abs(diff) / wallet * 100 >= _d(self.v1.ledger_tol_pct):
            self._ledger_strikes += 1
            if self._ledger_strikes >= 2 and self.gate.block(S.LEDGER, str(diff)):
                self.anomaly_detector.set_manual_halt("v1 ledger vs exchange diff")
                await self._alert("장부-거래소 잔고 차이 — 매매 중단",
                                  f"차이 {float(diff):+.2f} USDT ({float(abs(diff) / wallet * 100):.2f}%)",
                                  "확인 후 /resume")
        else:
            self._ledger_strikes = 0
            await self._clear(S.LEDGER)
        await self._check_autohalt()

    async def _check_autohalt(self):
        if "live_start_wallet" not in self.meta:
            return
        await self._check_pf_review()
        if self._autohalted:
            return
        reason = S.autohalt_reason(_d(self.meta["live_start_wallet"]), self.account.balance,
                                   _d(self.meta.get("net_transfers", "0")), self.v1.autohalt_dd_pct)
        if reason:
            self._autohalted = True
            self.anomaly_detector.set_manual_halt(f"v1 autohalt: {reason}")
            await self._alert("자동 중단 — 실거래 한도 도달", reason, "신규 진입 중단 · 보고 후 /resume")

    async def _check_pf_review(self):
        """PF < 0.8 after 30 trades → one ⚠️ review message (first trigger only) + daily memo note."""
        if self.meta.get("pf_review"):
            return
        start_ms = int(self.meta.get("live_start_ms", 0))
        nets = [trade_net_pnl(t) for t in self.trade_history
                if t.signal_type == "turtle_v1" and t.closed_at >= start_ms]
        text = S.pf_review_text(nets, self.v1.autohalt_pf, self.v1.autohalt_pf_after)
        if not text:
            return
        self.meta["pf_review"] = {"date": kst_date(), "text": text}
        self._save_meta()                                   # persisted → never re-sent after restart
        logger.warning(f"[V1] {text}")
        try:
            await self.alert_sender.send_text(text)
        except Exception as e:
            logger.error(f"[V1] review alert send failed: {e}")

    def review_notes(self, date: str) -> list[str]:
        r = self.meta.get("pf_review") or {}
        return [r["text"].removeprefix("⚠️ ")] if r.get("date") == date else []

    # ── strategy loop ──────────────────────────────────────
    async def on_bar_tick(self):
        """Scheduler hook (every ~20s): act once per newly closed bar."""
        if not self._initialized:
            return
        try:
            bars = await self._call(self.ex.klines(self.v1.interval, self.v1.kline_limit))
        except ExchangeError:
            return
        now = _now_ms()
        closed = [b for b in bars if b["close_time"] < now]
        if not closed or closed[-1]["close_time"] <= int(self.meta.get("last_bar_close", 0)):
            return
        async with self._lock:
            await self.on_bar_close(closed, now)

    async def on_bar_close(self, closed: list[dict], now: int | None = None):
        now = now or _now_ms()
        last = closed[-1]
        st = replay(closed, self.v1.params)
        self.meta["last_bar_close"] = last["close_time"]
        self._save_meta()
        late = now - last["close_time"] > self.v1.act_window_s * 1000
        cur = self.pos["side"] if self.pos else 0

        if cur != 0 and (st.pend_exit or st.pos != cur):
            # model exits on signal (or no longer holds this side, e.g. model stop hit first) → close
            await self._exit("signal_exit" if st.pend_exit else "model_sync")
        if st.pend_entry and allowed_side(st.pend_entry, self.v1.direction):
            if late:
                self._skip("late", f"bar closed {(now - last['close_time']) / 1000:.0f}s ago")
            else:
                await self._enter(st.pend_entry, _d(st.pend_stop_dist), last["close_time"])

    async def _enter(self, side: int, stop_dist: Decimal, bar_close_ms: int) -> bool:
        if not self.entries_allowed():
            self._skip("safety_block", str(self.gate.reasons or "halted"))
            return False
        try:
            p = await self._call(self.ex.position())
            if p["amt"] != 0 or self.pos:          # one position, never add (no averaging)
                logger.warning(f"[V1] entry refused: position exists ({p['amt']})")
                return False
            orders = await self._call(self.ex.open_orders())
            if any(not (o["close_position"] or o["reduce_only"]) for o in orders):
                self.gate.block(S.MISMATCH, "open entry order before entry")
                return False
            rules = await self._ensure_rules()
            acct = await self._call(self.ex.account())         # fresh exchange balance (§9)
            book = await self._call(self.ex.book())
        except ExchangeError as e:
            logger.error(f"[V1] entry pre-check failed: {e}")
            return False
        ref = book["ask"] if side > 0 else book["bid"]
        wallet = acct["wallet"]                                # qty is risk-sized only: never trimmed to margin
        stop_frac = float(stop_dist / ref)                    # stop_pct = |entry_ref − stop| / entry_ref
        risk_usdt = wallet * _d(self.v1.risk_pct) / 100
        qty = rules.floor_qty(risk_usdt / stop_dist)           # round DOWN to LOT_SIZE.stepSize
        notional = qty * ref
        if qty < rules.min_qty or notional < rules.min_notional:
            self._skip("min_notional", f"qty {qty} {self.v1.symbol} (notional {notional:.2f}) "
                                       f"< minQty {rules.min_qty} / minNotional {rules.min_notional}")
            return False
        br = S.bracket_for(self.brackets, notional)           # tier holding the ACTUAL order notional
        mmr = br["mmr"] if br else self.v1.maint_margin_rate
        lev = S.choose_leverage(stop_frac, self.v1.max_leverage, br["max_lev"] if br else None,
                                mmr, self.v1.liq_buffer_ratio)
        if lev is None:
            self._skip("leverage", f"stop {stop_frac:.2%} (MMR {mmr}): leverage rule < 1")
            return False
        if not S.liquidation_ok(stop_frac, lev, mmr, self.v1.liq_buffer_ratio):   # final check
            self._skip("leverage", f"stop {stop_frac:.2%} not inside {self.v1.liq_buffer_ratio}× "
                                   f"liquidation distance at {lev}x (MMR {mmr})")
            return False
        est_stop = self._stop_price(ref, side, stop_dist)
        risk_after = qty * abs(ref - est_stop) + notional * 2 * TAKER_FEE
        if risk_after > wallet * _d(self.v1.max_risk_pct) / 100:
            self._skip("risk_cap", f"risk after rounding {risk_after:.2f} USDT "
                                   f"> max {self.v1.max_risk_pct}% of {wallet:.2f}")
            return False
        try:
            avail = (await self._call(self.ex.account()))["available"]   # fresh, at this moment
        except ExchangeError as e:
            logger.error(f"[V1] entry skipped: balance re-check failed: {e}")
            return False
        need = notional / lev
        if need > avail:                                       # skip-only (TA): no quantity-trim path
            self._skip("margin", f"required margin {need:.2f} (= {notional:.2f}/{lev}x) "
                                 f"> available {avail:.2f} USDT")
            await self._alert(f"증거금 부족으로 진입 건너뜀 — 잔고/계산 점검 필요 "
                              f"(필요 {need:.2f}, 가용 {avail:.2f})")
            return False
        try:
            await self._call(self.ex.set_leverage(lev))
            got = await self._call(self.ex.leverage())
            err = "" if got == lev else f"read-back {got}x"
        except ExchangeError as e:
            err = str(e)[:80]
        if err:
            self._skip("leverage", f"set leverage {lev}x failed: {err}")
            await self._alert(f"레버리지 {lev}x 설정 실패 — 진입 건너뜀", f"{self.v1.symbol} {err}")
            return False
        cid = f"v1{bar_close_ms}{'L' if side > 0 else 'S'}"
        try:
            o = await self._submit_market("BUY" if side > 0 else "SELL", qty, cid, reduce_only=False)
        except ExchangeError as e:
            await self._alert("진입 주문 실패", f"{cid} {qty} {self.v1.symbol}", str(e)[:100])
            return False
        if o is None or o["executed_qty"] <= 0:
            return False
        fill = o["avg_price"] if o["avg_price"] > 0 else ref
        filled = o["executed_qty"]
        stop_px = self._stop_price(fill, side, stop_dist)
        slip_px = side * (fill - ref)
        self.pos = {
            "cid": cid, "side": side, "qty": str(filled), "entry_px": str(fill), "stop_px": str(stop_px),
            "stop_dist": str(stop_dist), "risk_usdt": str((abs(fill - stop_px) * filled).quantize(Decimal("0.01"))),
            "entry_ref": str(ref), "entry_slip_usdt": str(slip_px * filled),
            "entry_slip_pct": float(slip_px / ref * 100), "entry_order_id": o["id"], "opened_at": _now_ms(),
            "leverage": lev, "mmr": mmr,
        }
        self._save_pos()                                       # journal BEFORE the stop step
        if not await self._ensure_stop(filled * side, stop_px, cid):
            await self._emergency_close("sl_failed")
            return False
        self._sync_position_view()
        try:
            await self.alert_sender.send_text(fmt_entry(PositionSide.LONG if side > 0 else PositionSide.SHORT,
                                                        fill, stop_px, None, self.pos["risk_usdt"]))
        except Exception:
            pass
        return True

    async def _exit(self, reason: str) -> bool:
        try:
            p = await self._call(self.ex.position())
            if p["amt"] == 0:
                if self.pos:
                    await self._record_close("stop_loss")
                return True
            book = await self._call(self.ex.book())
            ref = book["bid"] if p["amt"] > 0 else book["ask"]
            cid = f"{(self.pos or {}).get('cid', 'v1')}x"
            o = await self._submit_market(close_side(p["amt"]), abs(p["amt"]), cid, reduce_only=True)
            if self.pos is not None:
                self.pos.update(exit_ref=str(ref), exit_order_id=(o or {}).get("id"))
            p2 = await self._call(self.ex.position())
            if p2["amt"] != 0:
                await self._alert("청산 미완료", f"잔여 {p2['amt']} {self.v1.symbol}", "손절 유지 · 다음 대조에서 재시도")
                return False
            for so in await self._call(self.ex.open_orders()):
                if so["close_position"] or so["reduce_only"]:
                    try:
                        await self._call(self.ex.cancel_stop(so))
                    except ExchangeError:
                        pass
            if self.pos:
                await self._record_close(reason)
            return True
        except ExchangeError as e:
            logger.error(f"[V1] exit failed (stop remains on exchange): {e}")
            return False

    # ── journal from exchange fills / income ───────────────
    async def _record_close(self, reason: str):
        pos = self.pos
        if not pos:
            return
        side = pos["side"]; opened = int(pos["opened_at"])
        qty = _d(pos["qty"]); entry = _d(pos["entry_px"])
        fills, funding_rows = [], []
        try:
            fills = await self._call(self.ex.user_trades(opened - 60_000))
            funding_rows = await self._call(self.ex.income("FUNDING_FEE", opened))
        except ExchangeError as e:
            logger.error(f"[V1] fills/income fetch failed, journaling with estimates: {e}")
        close_side_ = "SELL" if side > 0 else "BUY"
        entry_fills = [f for f in fills if f["order_id"] == str(pos.get("entry_order_id"))]
        exit_fills = [f for f in fills if f["side"] == close_side_ and f["time"] >= opened - 1000
                      and f["order_id"] != str(pos.get("entry_order_id"))]
        xq = sum((f["qty"] for f in exit_fills), Decimal("0"))
        exit_px = (sum((f["price"] * f["qty"] for f in exit_fills), Decimal("0")) / xq) if xq > 0 else \
            (_d(self._last_price) if self._last_price else entry)
        gross = sum((f["realized_pnl"] for f in exit_fills), Decimal("0")) if exit_fills else side * (exit_px - entry) * qty
        fees = sum((f["commission"] for f in entry_fills + exit_fills), Decimal("0"))
        funding_cost = -sum((r["amount"] for r in funding_rows), Decimal("0"))
        fee_est = (entry * qty + exit_px * qty) * TAKER_FEE
        exit_ref = _d(pos.get("exit_ref") or (pos["stop_px"] if reason == "stop_loss" else exit_px))
        exit_slip_px = side * (exit_ref - exit_px)
        slip_usdt = _d(pos.get("entry_slip_usdt", "0")) + exit_slip_px * qty
        now = _now_ms()
        details = {
            "slippage_usdt": str(slip_usdt), "entry_slip_pct": pos.get("entry_slip_pct", 0.0),
            "exit_slip_pct": float(exit_slip_px / exit_ref * 100) if exit_ref else 0.0,
            "entry_ref": pos.get("entry_ref"), "exit_ref": str(exit_ref), "stop_px": pos.get("stop_px"),
            "funding_usdt": str(funding_cost), "fee_ledger_est": str(fee_est),
            "fee_diff_usdt": str(fees - fee_est) if fills else "0", "tg_risk_usdt": pos.get("risk_usdt", "0"),
            "source": "exchange" if fills else "estimate",
        }
        bal_before = self.account.balance
        trade = TradeRecord(
            id=pos["cid"], symbol=self.v1.symbol, side=PositionSide.LONG if side > 0 else PositionSide.SHORT,
            leverage=int(pos.get("leverage") or self.v1.max_leverage), avg_entry_price=entry, avg_exit_price=exit_px.quantize(Decimal("0.01")),
            quantity=qty, realized_pnl=gross, pnl_percent=0.0, signal_type="turtle_v1",
            signal_details=details, close_reason=reason, total_fees=fees, opened_at=opened, closed_at=now,
            duration_seconds=int((now - opened) / 1000),
        )
        net = trade_net_pnl(trade)
        trade.pnl_percent = round(float(net / bal_before * 100), 3) if bal_before > 0 else 0.0
        self.trade_history.append(trade)
        save_trade(trade)
        self.account.total_trades += 1
        self.account.winning_trades += 1 if net > 0 else 0
        self.pos = None
        self._save_pos()
        self._sync_position_view()
        try:
            acct = await self._call(self.ex.account())
            self.account.balance = acct["wallet"]
        except ExchangeError:
            pass
        save_account(self.account)
        try:
            risk = _d(details["tg_risk_usdt"])
            await self.alert_sender.send_text(fmt_exit(trade.side, reason, net,
                                                       trade.pnl_percent, float(net / risk) if risk > 0 else None,
                                                       self.account.balance))
        except Exception:
            pass
        await self._check_autohalt()

    def get_status(self) -> dict:
        s = super().get_status()
        s["v1"] = {"direction": self.v1.direction, "entry_blocks": dict(self.gate.reasons),
                   "ledger_diff": self.ledger_vs_exchange_balance_diff}
        return s
