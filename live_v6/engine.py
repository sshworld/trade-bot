"""V6Engine — live engine for the TA-approved v6 H7 row (spec v4 base + H7, 6-coin portfolio, live sizing §8a).

Invariants (ported from the verified live_v1 safety layer, spec v1 §8-10 / v2 §8-9 / TA rules 2026-10-20):
  * The exchange is authoritative for balance, positions, orders, fills, fees, funding. The journal is a cache;
    local never overwrites the exchange. Sizing uses a fresh exchange balance right before each entry.
  * Every open position has a live exchange-side STOP_MARKET (closePosition, MARK_PRICE) or it is closed.
    Protective stops and exits are never limit orders and are never "cancel and give up": exits are reduceOnly
    MARKET for the WHOLE remaining qty (one order, no dust) and are retried until the exchange shows flat (+ 🚨).
  * One position per symbol, never adding (no averaging). Every order intent has a deterministic client id;
    an unknown outcome is resolved by querying that id. Entries are never re-sent after an unknown outcome.
  * Stop rejected / stop missing and not re-armable / stop breach → flatten ALL positions + halt + 🚨.
  * Any reconcile mismatch, API-error burst, unknown order, ledger gap or margin-mode failure blocks NEW entries;
    existing stops are never touched by a block.
  * strategy equity ≤ halt_fraction (0.75) × start capital (transfers excluded) → flatten all + halt (§8e-2). PF < 0.8 after 30 trades = review alert only.
  * TA R4 (unknown positions): a position on the exchange that is NOT in the state file is never market-closed — not
    by the strategy (model_sync), not by a breach / stop-failure close, not by flatten-all. It is kept in
    st["unknown"]: 🚨 once (Telegram on mainnet only), new entries blocked for THAT coin, its risk counted in the
    portfolio risk, and if it has no exchange stop a closePosition MARK_PRICE stop is placed at the model's exit
    line (20-bar channel low for a long / high for a short; 1×ATR(14, 4h) from the mark if price is already beyond
    the line; 3 % from the mark if channel/ATR data is missing). Existing stops are never moved or cancelled.
    Resolution is manual (close by hand, or `python -m live_v6.tools.adopt_position`). Only exception (protection
    beats ownership): the exchange keeps REJECTING the stop and none is confirmed within 5 min of detection →
    reduceOnly MARKET close of that position + 🚨.
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from . import strategy as S
from .events import MARKET_EVENTS, AccountUpdate, Kline, Mark, OrderUpdate, StreamStatus, Trade
from .strategies.base import DataNotReady
from .exchange import ExchangeError, ExchangeUnavailable, OrderRejected, WouldTrigger, rules_from_info
from .notify import Notifier
from .rules import D, stop_price
from .sizing import SizingParams, size_entry

log = logging.getLogger("live_v6.engine")

SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
# FROZEN (TA review 57b0888 item 1): processing order of simultaneous bar-close entry signals. It is the order the
# research portfolio used at its first full 6-coin tie (2023-01-14 00:00 UTC); see README "Simultaneous-signal tie
# order" for why research itself has no fixed order. The only live setting — never change without a TA review.
ENTRY_ORDER = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "DOGEUSDT", "XRPUSDT", "SOLUSDT")
H4 = S.H4_MS
KST = timezone(timedelta(hours=9))

MODEL_EXITS = ("signal_exit", "model_sync")   # strategy-driven exits: the model is already flat
REASON_KO = {"stop_loss": "손절", "signal_exit": "M20 채널 청산", "model_sync": "모델 동기화 청산", "stop_breach": "손절 미작동 정리",
             "sl_failed": "손절 등록 실패 정리", "stop_lost_breach": "손절 주문 소실 후 손절가 돌파 정리", "emergency": "비상 전체 정리", "dust_entry": "소액 부분 체결 정리"}

# entry-blocking reasons (transient; cleared automatically when the condition clears)
UNKNOWN_POS = "unknown_position"                    # per-coin entry block (st["unknown"]), never a global block
STARTUP, MISMATCH, API_ERRORS, UNKNOWN_ORDER, LEDGER, MARGIN, WS_STALE, MARKET_STALE, BAR_STALE, RATE_LIMIT = (
    "startup", "reconcile_mismatch", "api_errors", "order_status_unknown", "ledger_vs_exchange", "margin_mode",
    "stream_stale", "market_data_stale", "bar_close_stale", "rate_limited")


@dataclass
class Settings:
    symbols: tuple = SIX
    entry_order: tuple = ENTRY_ORDER    # FROZEN tie order of simultaneous signals (README); live refuses anything else
    regime_symbol: str = "BTCUSDT"
    min_notional_floor: dict = field(default_factory=lambda: {"BTCUSDT": "100"})   # v6: BTC min order 100 (PM/TA)
    sizing: SizingParams = field(default_factory=SizingParams)
    params: S.Params = field(default_factory=S.Params)
    max_positions: int = 6              # v6 H7 has no extra cap (one per symbol); enforced at placement anyway
    cid_prefix: str = "v6"
    act_window_s: float = 900           # entries only within 15 min after the bar close
    bar_delay_s: float = 3              # wait this long after a bar close before acting
    kline_fetch: int = 100
    bootstrap_bars: int = 1500
    daily_fetch: int = 400
    funding_lookback_ms: int = 100 * S.DAY_MS
    funding_wait_s: float = 600         # max wait for the settlement stamp at T before skipping (`funding_data`)
    breach_grace_s: float = 2.0
    query_retries: int = 3
    query_delay_s: float = 1.0
    stop_attempts: int = 3              # §8c L1: re-place a missing/rejected stop up to 3× within 10 s
    stop_retry_delay_s: float = 3.0
    exit_attempts: int = 5
    exit_retry_delay_s: float = 1.0
    exit_alert_every: int = 12          # while an exit keeps failing: 🚨 every N reconcile retries (~1 min)
    api_recover_n: int = 3              # §8c L0: entries paused on any transient error until 3 calls succeed
    transient_alert_s: float = 60       # §8c L0: alert only when a transient fault lasts longer than this
    api_dead_s: float = 300             # §8c L3(c): API unresponsive this long + unprotected position → flatten all
    capital_fraction: float = 1.0       # §8e-2: trading capital C0 = capital_fraction × S0 (S0 = wallet at live start)
    halt_fraction: float = 0.75         # §8e-2 / §8c L3(a): flatten all + halt when strategy equity ≤ halt_fraction × C0
    pf_review: float = 0.8
    pf_review_after: int = 30
    ledger_tol_pct: float = 0.5
    income_interval_s: float = 60
    fallback_stop_pct: float = 3.0      # TA R4: unknown position, no channel/ATR data → stop this % from the mark
    unknown_stop_deadline_s: float = 300.0   # TA R4 last resort: stop REJECTED and none confirmed this long after
                                             # detection → reduceOnly MARKET close of that position + 🚨
    use_streams: bool = False           # runner sets True; then stale/down streams block entries
    pace_weight: int = 1000             # startup pacing: used weight ≥ this (≈42 % of 2400) → wait for the next minute
    bar_stale_s: float = 300.0          # TA: bar decision (meta.last_bar_close + every model's last_open) not advanced
                                        # within this long after a decision boundary → block entries + 🚨; ✅ on catch-up
    market_stale_s: float = 60.0        # TA: no mark / kline / aggTrade (per feed) for > 60 s → block entries + alert
    stream_stale_s: float = 15.0        # no market event for this long → entries blocked (markPrice@1s)
    reconcile_s: float = 5.0            # REST safety net cadence (always on)
    heartbeat_s: float = 4 * 3600       # 💓 Telegram heartbeat cadence
    slip_review_n: int = 30             # §8d entry-slippage review over the first N entries (alert only)
    slip_assumed_bp: float = 2.0        # model: entry = trigger (level + 1 tick) + 2 bp
    slip_alert_bp: float = 10.0
    trade_from_ms: int = 0              # replay harness: no orders before this bar close
    trade_until_ms: int = 1 << 62


class V6Engine:
    def __init__(self, ex, settings: Settings | None = None, store=None, notifier: Notifier | None = None,
                 clock=None, sleep=None, strategy=None):
        from .store import MemoryStore
        self.ex = ex
        self.cfg = settings or Settings()
        self.store = store or MemoryStore()
        self.tg = notifier or Notifier()
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        self.st = self.store.load() or {}
        for k in ("strategy", "pos", "intents", "meta", "unknown"):
            self.st.setdefault(k, {})
        if strategy is None:
            from .strategies.v6_h7 import V6H7
            c = self.cfg
            strategy = V6H7(params=c.params, kline_fetch=c.kline_fetch, bootstrap_bars=c.bootstrap_bars,
                            daily_fetch=c.daily_fetch, funding_lookback_ms=c.funding_lookback_ms)
        strategy.state = self.st["strategy"] or strategy.state
        self.strategy = strategy
        self.marks: dict = {}
        self._stream_up: dict = {}
        self._breach_seen: dict = {}
        self._last_ok_reconcile = -1e18
        self.deadman = None                                 # runner attaches deadman.DeadMan (HEARTBEAT_URL)
        self._last_market_ev = self.clock()
        self._feed_last: dict = {}                          # feed ("mark" / "kline" / "trade") → last event (clock s)
        self._dirty = False
        self._last_reconcile = 0.0
        self.blocks: dict[str, str] = {STARTUP: "startup"}
        self.rules: dict = {}
        self.brackets: dict = {}
        self.started = False
        self._fault_since: float | None = None   # first transient API error of the current streak
        self._block_since: dict = {}
        self._block_alerted: set = set()
        self._ok_streak = 0
        self._consistent = 0
        self._last_income = 0.0
        self._ledger_strikes = 0
        self._bar_first_try: dict[int, float] = {}
        self._cache: dict = {}
        self._own_cancels: dict[str, float] = {}           # client ids WE cancelled → not a "stop lost" event
        self._queued: dict[str, str] = {}                  # 418 ban: sym → "stop" | "close", sent the moment it ends
        inner = getattr(ex, "inner", ex)
        if hasattr(inner, "on_rate_limit"):
            inner.on_rate_limit = self._on_rate_limit

    # ───────────────────────── infra ─────────────────────────
    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    @property
    def meta(self) -> dict:
        return self.st["meta"]

    def save(self):
        self.store.save(self.st)

    def alert(self, title, detail="", event_ms=None):
        log.critical("🚨 %s | %s", title, detail)
        self.tg.alert(title, detail, event_ms=event_ms, decision_ms=self.now_ms())

    def notify(self, text, kind=None, event_ms=None):
        """Every Telegram message goes through here (event time vs decision time → alerts log, §TA timeliness)."""
        self.tg.send(text, kind=kind, event_ms=event_ms, decision_ms=self.now_ms())

    def x(self, name, *a, **kw):
        """Exchange call with §8c L0 accounting: a transient error (timeout / 5xx / 429 / 418 / network) pauses NEW
        entries only — never closes anything; 3 successful calls clear it; alert only if it lasts > 60 s."""
        if name == "cancel" and len(a) > 1 and isinstance(a[1], dict):
            now = self.clock()
            self._own_cancels[str(a[1].get("client_id"))] = now      # our cancel → its CANCELED event is expected
            for k in [k for k, t in self._own_cancels.items() if now - t > 3600]:
                self._own_cancels.pop(k, None)
        try:
            r = getattr(self.ex, name)(*a, **kw)
        except ExchangeUnavailable as e:
            self._ok_streak = 0
            if self._fault_since is None:
                self._fault_since = self.clock()
            self.block(API_ERRORS, f"{name}: {str(e)[:80]}")
            raise
        self._ok_streak += 1
        if self._ok_streak >= self.cfg.api_recover_n:
            self._fault_since = None
            if API_ERRORS in self.blocks:
                self.unblock(API_ERRORS)
        return r

    TRANSIENT = (API_ERRORS, WS_STALE, RATE_LIMIT)

    def block(self, reason, detail="", alert=None):
        """Pause NEW entries. Transient reasons (§8c L0) alert only once they last > transient_alert_s."""
        new = reason not in self.blocks
        self.blocks[reason] = detail
        if new:
            self._block_since[reason] = self.clock()
            if alert and reason not in self.TRANSIENT:
                self.alert(alert, detail)
                self._block_alerted.add(reason)
        return new

    def unblock(self, reason):
        if self.blocks.pop(reason, None) is not None:
            self._block_since.pop(reason, None)
            if reason in self._block_alerted and self.entries_allowed():
                self.notify(f"✅ 신규 진입 재개 — {reason} 해제")
            self._block_alerted.discard(reason)

    def check_transient(self):
        now = self.clock()
        for r in self.TRANSIENT:
            if r in self.blocks and r not in self._block_alerted and now - self._block_since.get(r, now) > self.cfg.transient_alert_s:
                self._block_alerted.add(r)
                self.alert(f"일시 장애 {self.cfg.transient_alert_s:.0f}초 넘게 지속 — 신규 진입 보류 (정리 안 함)",
                           f"{r}: {self.blocks[r]} · 거래소 손절 유지",
                           event_ms=int(self._block_since.get(r, now) * 1000))

    def entries_allowed(self) -> bool:
        return not self.blocks and not self.meta.get("halted")

    def halt(self, reason):
        if not self.meta.get("halted"):
            self.meta["halted"] = reason
            self.save()
            self.alert(f"매매 중단 (halt): {reason}", "신규 진입 중단 · 확인 후 `python -m live_v6 resume`")

    def resume(self):
        self.meta.pop("halted", None)
        self.save()

    def skip(self, sym, reason, detail=""):
        day = datetime.fromtimestamp(self.now_ms() / 1000, KST).strftime("%Y-%m-%d")
        sk = self.meta.setdefault("skips", {})
        for d in sorted(sk)[:-14]:
            sk.pop(d, None)
        sk.setdefault(day, {})
        sk[day][reason] = sk[day].get(reason, 0) + 1
        self.meta.setdefault("skip_log", []).append([self.now_ms(), sym, reason, detail[:160]])
        del self.meta["skip_log"][:-2000]
        self.save()
        log.warning("skip %s %s: %s", sym, reason, detail)

    def cid(self, sym, t_ms) -> str:
        return f"{self.cfg.cid_prefix}{sym.removesuffix('USDT')}{t_ms // 1000}"

    # ───────────────────────── startup ─────────────────────────
    def startup(self):
        self.blocks[STARTUP] = "startup"
        try:
            self.load_rules()
            self.resolve_intents()
            self.reconcile()
            for s in self.cfg.symbols:
                if s not in self.st["pos"] and s not in self.st["unknown"]:
                    self.pace()
                    self.ensure_isolated(s)
            if "start_wallet" not in self.meta:
                a = self.x("account")
                self.meta.update(start_wallet=str(a["wallet"]), capital0=str(D(a["wallet"]) * D(self.cfg.capital_fraction)),
                                 start_ms=self.now_ms(), ledger_balance=str(a["wallet"]),
                                 income_cursor=self.now_ms(), income_seen=[], net_transfers="0")
            self.strategy.on_start(self)
            self.st["strategy"] = self.strategy.state
            self.save()
            self.blocks.pop(STARTUP, None)
            self.started = True
            self.notify(f"▶️ live_v6 시작 · {self.ex!r} · 포지션 {len(self.st['pos'])}개"
                         + (f" · 기록 없는 포지션 {','.join(self.st['unknown'])}" if self.st["unknown"] else "") + " · "
                         f"{'중단 상태: ' + self.meta['halted'] if self.meta.get('halted') else '진입 가능' if self.entries_allowed() else '진입 차단: ' + ','.join(self.blocks)}")
        except ExchangeError as e:
            log.error("startup failed, entries stay blocked: %s", e)

    def load_rules(self):
        info = self.x("exchange_info")
        self.rules = rules_from_info(info, self.cfg.symbols, self.cfg.min_notional_floor)
        for s in self.cfg.symbols:
            try:
                self.brackets[s] = self.x("brackets", s)
            except ExchangeError as e:
                log.warning("leverageBracket %s unavailable → MMR fallback: %s", s, e)
                self.brackets.setdefault(s, [])

    def resolve_intents(self):
        """An entry intent survives a crash between 'order sent' and 'position journaled': resolve it by client id."""
        for cid, it in list(self.st["intents"].items()):
            try:
                o = self.x("get_order", it["sym"], cid)
            except ExchangeUnavailable:
                self.block(UNKNOWN_ORDER, cid, "주문 상태 확인 불가 — 신규 진입 중단")
                continue
            if o and o["executed_qty"] > 0 and it["sym"] not in self.st["pos"]:
                self._journal_entry(it["sym"], it, o)
            self.st["intents"].pop(cid, None)
            self.save()

    def ensure_isolated(self, sym) -> bool:
        err = ""
        try:
            try:
                self.x("set_margin_type", sym, "ISOLATED")
            except OrderRejected as e:
                err = str(e)
            mt = self.x("positions", self.cfg.symbols)[sym]["margin_type"]
        except ExchangeError as e:
            mt, err = "?", str(e)
        key = f"{MARGIN}:{sym}"
        if mt == "ISOLATED":
            if key in self.blocks:
                self.unblock(key)
            return True
        self.block(key, f"{sym} {mt} {err[:80]}", "마진 모드 ISOLATED 설정 실패 — 신규 진입 중단")
        return False

    def pace(self):
        """Startup / bootstrap pacing (TA rate-limit rule: stay < 50 % of 2400/min): if this minute's used weight
        is already ≥ pace_weight, sleep to the next minute boundary. No-op for clients without weight tracking."""
        ex = getattr(self.ex, "inner", self.ex)
        fn = getattr(ex, "weight_now", None)
        w = fn() if callable(fn) else 0
        if w >= self.cfg.pace_weight:
            wait = 61 - (time.time() % 60)
            log.warning("startup pacing: used weight %s ≥ %s → waiting %.0fs", w, self.cfg.pace_weight, wait)
            self.sleep(wait)

    # ───────────────────────── data for strategies (ctx) ─────────────────────────
    def live_positions(self) -> dict:
        return copy.deepcopy(self.st["pos"])

    def closed_bars(self, sym, interval, limit):
        now = self.now_ms()
        return [b for b in self.x("klines", sym, interval, limit) if b.get("close_time", b["open_time"] + H4 - 1) < now]

    def daily(self, limit):
        key = ("daily", self.now_ms() // 60_000)
        if key not in self._cache:
            now = self.now_ms()
            self._cache = {k: v for k, v in self._cache.items() if k[0] != "daily"}
            self._cache[key] = [(b["open_time"], b["close"]) for b in self.x("klines", self.cfg.regime_symbol, "1d", limit)
                                if b.get("close_time", b["open_time"] + S.DAY_MS - 1) < now]
        return self._cache[key]

    def funding(self, sym, start_ms):
        key = ("fund", sym, start_ms)
        c = self._cache.get(key)
        if c and len(c) >= 2 and c[-1][0] + (c[-1][0] - c[-2][0]) <= self.now_ms():
            del self._cache[key]                            # a newer settlement is due → refetch
        if key not in self._cache:
            self._cache = {k: v for k, v in self._cache.items() if not (k[0] == "fund" and k[1] == sym)}
            self._cache[key] = S.normalise_funding(self.x("funding", sym, start_ms))
        return self._cache[key]

    # ───────────────────────── bar close ─────────────────────────
    def due_bar(self) -> int | None:
        iv = self.strategy.decision_interval_ms
        if not iv:
            return None
        T = (self.now_ms() - int(self.cfg.bar_delay_s * 1000)) // iv * iv
        return T if T > int(self.meta.get("last_bar_close", 0)) else None

    def on_bar_close(self):
        """Scheduled decision of the strategy plug-in (REST-confirmed bars; also the fallback if a kline-close
        event was missed)."""
        T = self.due_bar()
        if T is None:
            return
        self._bar_first_try.setdefault(T, self.clock())
        force = self.clock() - self._bar_first_try[T] >= self.cfg.funding_wait_s
        try:
            self.reconcile()
            before = copy.deepcopy(self.strategy.state)
            try:
                intents = self.strategy.on_bar_close(T, self, force)
            except BaseException:
                self.strategy.state = before                # never half-commit a model step
                raise
        except DataNotReady as e:
            log.info("bar %s not ready: %s", T, e)
            return
        except ExchangeError as e:
            log.error("bar %s: data fetch failed (retry next tick): %s", T, e)
            return
        self.st["strategy"] = self.strategy.state
        self.meta["last_bar_close"] = T
        self._bar_first_try.pop(T, None)
        self.save()
        self.execute(intents, T)

    def execute(self, intents, T=None):
        """Run strategy intents. Exits always; entries only inside the act window and trading period."""
        for it in intents:
            sym = it["sym"]
            if it["type"] == "exit":
                j = self.st["pos"].get(sym)
                if j and not j.get("closing"):
                    self.close(sym, it["reason"])
            elif it["type"] == "skip":
                self.skip(sym, it["reason"], it.get("detail", ""))
                if it.get("alert"):
                    self.alert(f"{sym} 진입 건너뜀 ({it['reason']})", it.get("detail", ""))
            elif it["type"] == "enter":
                t = it["T"]
                if not (self.cfg.trade_from_ms <= t < self.cfg.trade_until_ms):
                    continue
                max_age = min(self.cfg.act_window_s, it.get("max_age_s", self.cfg.act_window_s))
                if self.now_ms() - t > max_age * 1000:
                    self.skip(sym, "late", f"signal {(self.now_ms() - t) / 1000:.1f}s old > {max_age}s")
                    continue
                self.enter(sym, it["stop_dist"], t, model_id=it.get("model_id"), signal_px=it.get("signal_px"))

    # ───────────────────────── stream events ─────────────────────────
    def on_event(self, ev):
        """Websocket event → fast safety reactions + strategy. REST stays the source of truth."""
        now = self.clock()
        if isinstance(ev, StreamStatus):
            self._stream_up[ev.name] = ev.up
            if not ev.up:
                self.block(WS_STALE, f"{ev.name} stream down: {ev.detail}", f"웹소켓 끊김 ({ev.name}) — 신규 진입 중단")
            else:
                self._last_market_ev = now if ev.name == "market" else self._last_market_ev
                self._dirty = True                          # resubscribed → immediate REST reconcile
            return
        if isinstance(ev, MARKET_EVENTS):
            self._last_market_ev = now
            self._feed_last[self._feed_of(ev)] = now
            if isinstance(ev, Mark):
                self.marks[ev.sym] = ev.price
                j = self.st["pos"].get(ev.sym)
                if j and j.get("stop_lost") and not j.get("closing") and ev.price <= D(j["stop_lost"]["px"]):
                    self.lost_stop_breach(ev.sym, ev.price)  # no exchange stop + price through it → reduceOnly close
                elif self.ban_left() > 0:
                    pass                                    # 418: no REST at all; the exchange stop protects
                elif (j and not j.get("closing") and ev.price <= D(j["stop_px"])
                        and now - self._breach_seen.get(ev.sym, -1e18) >= self.cfg.reconcile_s):
                    self._breach_seen[ev.sym] = now                 # at most one REST check per symbol per 5 s
                    self.breach_check(ev.sym, ev.price, "mark stream")
        elif isinstance(ev, (OrderUpdate, AccountUpdate)):
            self.stop_monitor(ev)                           # TA: stop CANCELED/EXPIRED → replace now (no REST read)
            self._dirty = True                              # fills / position change → reconcile from REST now
        if self.started:
            intents = self.strategy.on_event(ev, self)
            if intents:
                self.save()                                 # strategy flags (e.g. one entry per bar) before acting
                self.execute(intents)

    @staticmethod
    def _feed_of(ev):
        return "mark" if isinstance(ev, Mark) else "kline" if isinstance(ev, Kline) else "trade" if isinstance(ev, Trade) else "other"

    def expected_feeds(self) -> tuple:
        s = self.strategy
        return ("mark",) + (("kline",) if getattr(s, "stream_intervals", ()) else ()) + (("trade",) if getattr(s, "wants_trades", False) else ())

    def market_data_guard(self):
        """TA staleness guard: any expected market feed silent > market_stale_s → block NEW entries + 🚨 (positions and
        their exchange stops untouched, no closes — §8c L0); fresh data on every feed → unblock + recovery notice."""
        if not self.cfg.use_streams:
            return
        now = self.clock()
        for f in self.expected_feeds():
            self._feed_last.setdefault(f, now)              # grace from start
        stale = {f: now - t for f, t in self._feed_last.items() if f in self.expected_feeds() and now - t > self.cfg.market_stale_s}
        if stale:
            detail = ", ".join(f"{f} {age:.0f}s" for f, age in sorted(stale.items()))
            if MARKET_STALE not in self.blocks:
                self.block(MARKET_STALE, detail)
                self._block_alerted.add(MARKET_STALE)
                self._block_alerted.add(WS_STALE)           # one alert for the same outage
                since = min(self._feed_last[f] for f in stale)
                self.alert(f"시장 데이터 {self.cfg.market_stale_s:.0f}초 넘게 수신 없음 — 신규 진입 차단 (포지션·손절 유지, 정리 안 함)",
                           detail, event_ms=int(since * 1000))
            else:
                self.blocks[MARKET_STALE] = detail
        elif MARKET_STALE in self.blocks:
            self.blocks.pop(MARKET_STALE, None)
            self._block_since.pop(MARKET_STALE, None)
            self._block_alerted.discard(MARKET_STALE)
            self.notify(f"✅ 시장 데이터 수신 재개 — {'신규 진입 재개' if self.entries_allowed() else '다른 차단 사유 남음: ' + ','.join(self.blocks)}",
                        kind="recovery")

    def stream_health(self):
        """Entries are blocked while any stream is down or the market stream is silent; REST reconcile carries on."""
        stale = (self.clock() - self._last_market_ev > self.cfg.stream_stale_s) if self.cfg.use_streams else False
        down = [k for k, v in self._stream_up.items() if not v]
        if stale or down:
            self.block(WS_STALE, f"stale={stale} down={down}", "웹소켓 지연/끊김 — 신규 진입 중단 (REST 대조 유지)")
        elif WS_STALE in self.blocks:
            self.unblock(WS_STALE)

    # ───────────────────────── protection monitor (TA 2026-10-21) ─────────────────────────
    STOP_GONE = ("CANCELED", "EXPIRED", "REJECTED")

    def _on_rate_limit(self, status, retry_after):
        if status == 418:
            self.alert(f"IP 차단 (HTTP 418) — {retry_after:.0f}초 동안 REST 요청 전면 중단",
                       "신규 진입 중단 · 거래소 손절만 보호 · 손절 소실/돌파 시 조치는 차단 해제 즉시 실행 · 자동 정리 안 함")

    def ban_left(self) -> float:
        """Seconds left of a 418 IP ban (0 if none / fake exchange)."""
        ex = getattr(self.ex, "inner", self.ex)
        until = getattr(ex, "ban_until", 0) or 0
        clk = getattr(ex, "clock", None)
        left = until - (clk() if callable(clk) else time.time())
        return left if left > 0 else 0.0

    def stop_monitor(self, ev):
        """User data stream: the protective stop of an open position went CANCELED / EXPIRED (std ORDER_TRADE_UPDATE or
        ALGO_UPDATE — Binance conditional orders live in the algo service) and it was not our own cancel →
        🚨 + one replacement stop at once (critical call; during a 418 ban it is queued for the moment the ban ends)."""
        raw = ev.raw if isinstance(ev, OrderUpdate) else (ev.raw.get("o") if ev.raw.get("e") == "ALGO_UPDATE" else None)
        if not isinstance(raw, dict):
            return
        sym, status = raw.get("s"), str(raw.get("X") or "")
        cid = str(raw.get("caid") or raw.get("c") or "")
        j = self.st["pos"].get(sym)
        if status not in self.STOP_GONE or not j or j.get("closing") or not cid.startswith(j["cid"]):
            return
        if cid[len(j["cid"]):][:1] not in ("p", "s"):        # p = pre-arm, s<n> = protective stop; x<n> = exits
            return
        if self._own_cancels.pop(cid, None) is not None:
            return
        cp = raw.get("cp")
        j["stop_lost"] = {"cid": cid, "status": status, "t": self.now_ms(), "px": j["stop_px"],
                          "cp": cp is True or str(cp).lower() == "true"}
        self.save()
        self.alert(f"손절 주문 {status} 감지 — {sym} 즉시 재등록" + (" (IP 차단 중: 해제 즉시 전송)" if self.ban_left() else ""),
                   f"{cid} · 손절 {j['stop_px']} · 수량 {j['qty']}", event_ms=ev.t or None)
        self.replace_lost_stop(sym)

    def replace_lost_stop(self, sym) -> bool:
        j = self.st["pos"].get(sym)
        if not j or not j.get("stop_lost"):
            return True
        if self.ban_left() > 0:
            self._queued.setdefault(sym, "stop")
            return False
        lost = j["stop_lost"]
        seq = int(j.get("stop_seq", 0))
        j["stop_seq"] = seq + 1
        self.save()
        try:                                                # one closePosition per side → a lost qty stop is
            self.x("stop", sym, "SELL", D(lost["px"]), f"{j['cid']}s{seq}",       # replaced by a qty stop
                   **({} if lost.get("cp") else {"qty": D(j["qty"])}))
        except WouldTrigger:
            self.lost_stop_breach(sym, self.marks.get(sym))
            return False
        except ExchangeError as e:
            if self.ban_left() > 0:
                self._queued.setdefault(sym, "stop")
                return False
            lost["failed"] = str(e)[:120]
            self.save()
            self.alert(f"손절 재등록 실패 — {sym} 시장가가 원래 손절가 {lost['px']} 도달 시 즉시 시장가 정리",
                       f"{str(e)[:100]} · 대조 루프가 계속 재시도")
            return False
        j.pop("stop_lost", None)
        self.save()
        self.notify(f"✅ 손절 재등록 완료 — {sym} 손절 {lost['px']}", kind="recovery")
        return True

    def lost_stop_breach(self, sym, mark):
        """No exchange stop (lost, replacement failed / pending) and mark through the original stop → reduceOnly MARKET
        close of THIS position at once (no grace: there is no exchange stop to wait for). 418 → queued for unban."""
        j = self.st["pos"].get(sym)
        if not j or j.get("closing"):
            return
        self.alert("손절 주문 없음 + 손절가 돌파 — 이 포지션 시장가 정리" + (" (IP 차단 중: 해제 즉시 전송)" if self.ban_left() else ""),
                   f"{sym} mark {mark} vs 손절 {j['stop_lost']['px']} · 다른 포지션 유지")
        self.close(sym, "stop_lost_breach")

    def flush_queued(self):
        """First tick after a 418 ban: send the queued protective actions before anything else."""
        for sym, kind in list(self._queued.items()):
            self._queued.pop(sym, None)
            j = self.st["pos"].get(sym)
            if not j:
                continue
            if kind == "close" or j.get("closing"):
                self.close(sym, j.get("close_reason") or "stop_lost_breach")
            else:
                self.replace_lost_stop(sym)

    def breach_check(self, sym, mark, source):
        self.sleep(self.cfg.breach_grace_s)                 # give the exchange stop a moment to fire
        try:
            if self.x("positions", self.cfg.symbols)[sym]["amt"] == 0:
                self._dirty = True
                return
        except ExchangeError:
            return                                          # REST reconcile retries in ≤5 s
        self.alert("손절가 돌파인데 거래소 손절 미작동 — 이 포지션만 정리",
                   f"{sym} mark {mark} vs 손절 {self.st['pos'][sym]['stop_px']} ({source}) · 다른 포지션 유지")
        self.close(sym, "stop_breach")                      # §8c L1: only THAT position (reduceOnly MARKET)

    # ───────────────────────── entry ─────────────────────────
    def _open_book(self, positions) -> list[dict]:
        out = []
        for s, p in positions.items():
            if p["amt"] != 0:
                j = self.st["pos"].get(s) or self.st["unknown"].get(s) or {}   # TA R4: unknown positions count too
                out.append({"sym": s, "side": 1 if p["amt"] > 0 else -1,
                            "risk_frac": float(j.get("risk_frac", self.cfg.sizing.risk_pct / 100 * 2))})  # not yet seen → 1%
        return out

    def enter(self, sym, stop_dist: Decimal, T: int, model_id=None, signal_px=None) -> bool:
        if not self.entries_allowed():
            self.skip(sym, "safety_block", str(self.meta.get("halted") or self.blocks))
            return False
        if sym in self.st["unknown"]:                       # TA R4: entries blocked for THIS coin only
            self.skip(sym, UNKNOWN_POS, f"exchange position {self.st['unknown'][sym].get('amt')} not in the state file")
            return False
        if not (stop_dist > 0):
            self.skip(sym, "risk_cap", f"stop distance {stop_dist}")
            return False
        try:
            pos = self.x("positions", self.cfg.symbols)
            if pos[sym]["amt"] != 0 or sym in self.st["pos"]:
                log.warning("entry %s refused: position exists (no averaging)", sym)
                return False
            oo = self.x("open_orders", sym)
            if any(not (o["close_position"] or o["reduce_only"]) for o in oo):
                self.block(MISMATCH, f"{sym} open entry order before entry", "대조 불일치 — 신규 진입 중단")
                return False
            for o in oo:                                    # our own leftover stops must never touch a new position
                if str(o["client_id"]).startswith(self.cfg.cid_prefix):
                    self.x("cancel", sym, o)
            if pos[sym]["margin_type"] != "ISOLATED" and not self.ensure_isolated(sym):
                self.skip(sym, "margin_mode", "ISOLATED read-back failed")
                return False
            acct = self.x("account")
            ref = self.x("book", sym)["ask"]
        except ExchangeError as e:
            log.error("entry %s pre-check failed: %s", sym, e)
            return False
        book = self._open_book(pos)
        # §8e-2 capital: sizing on C0 + realised PnL since start (= the full wallet when capital_fraction = 1, transfers
        # excluded); margin guard: margin in use + new margin never exceeds strategy equity (incl. unrealised)
        cap = self.strategy_equity(acct["wallet"])
        room = self.strategy_equity(acct.get("equity", acct["wallet"])) - D(acct.get("margin_used", 0))
        sz = size_entry(self.rules[sym], self.brackets.get(sym, []), cap, min(D(acct["available"]), room), ref, stop_dist, 1,
                        book, self.cfg.sizing)
        if sz.skip:
            self.skip(sym, sz.skip, sz.detail)
            if sz.skip == "margin":
                self.alert("증거금 부족으로 진입 건너뜀 — 잔고/계산 점검 필요", f"{sym} {sz.detail}")
            return False
        # leverage set + read-back; the same fresh positions read is the FINAL gate right before the order:
        # no averaging, ISOLATED, max positions, total open risk ≤ 2.5% (TA: enforced at order placement)
        try:
            if pos[sym]["leverage"] != sz.lev:              # skip the call when already set (entry latency)
                self.x("set_leverage", sym, sz.lev)
            pos = self.x("positions", self.cfg.symbols)
            err = "" if pos[sym]["leverage"] == sz.lev else f"read-back {pos[sym]['leverage']}x"
        except ExchangeError as e:
            err, pos = str(e)[:80], None
        if err:
            self.skip(sym, "leverage", f"set {sz.lev}x failed: {err}")
            self.alert(f"레버리지 {sz.lev}x 설정 실패 — 진입 건너뜀", f"{sym} {err}")
            return False
        book = self._open_book(pos)
        if pos[sym]["amt"] != 0:
            log.warning("entry %s refused at placement: position appeared", sym)
            return False
        if pos[sym]["margin_type"] != "ISOLATED":
            self.skip(sym, "margin_mode", f"read-back {pos[sym]['margin_type']}")
            return False
        if len(book) >= self.cfg.max_positions:
            self.skip(sym, "max_positions", f"{len(book)} open")
            return False
        if sum(b["risk_frac"] for b in book) + sz.risk_frac > self.cfg.sizing.portfolio_risk_cap + 1e-12:
            self.skip(sym, "risk_cap_portfolio", f"open {sum(b['risk_frac'] for b in book):.4%} + {sz.risk_frac:.4%}")
            return False
        cid = self.cid(sym, T)
        intent = {"sym": sym, "cid": cid, "T": T, "model_id": model_id if model_id is not None else T,
                  "signal_px": str(signal_px) if signal_px is not None else None, "stop_dist": str(stop_dist), "ref": str(ref), "qty": str(sz.qty),
                  "lev": sz.lev, "mmr": sz.mmr, "risk_frac": sz.risk_frac, "risk_pct_used": sz.risk_pct_used,
                  "wallet": str(acct["wallet"])}
        # PRE-ARM: a reduceOnly STOP_MARKET for the planned qty is live on the exchange BEFORE the entry is sent, so
        # there is no instant between fill and stop without exchange-side protection (closePosition stops cannot be
        # placed without a position: -4509). Not confirmed → no entry.
        pre = self._prearm(sym, sz.stop_px, sz.qty, cid)
        if pre is None:
            self.skip(sym, "stop_prearm", f"protective stop {sz.stop_px} not confirmed → entry not sent")
            return False
        intent["prearm"] = pre["id"]
        self.st["intents"][cid] = intent
        self.save()                                         # journal the intent BEFORE sending
        try:
            o = self.submit_market(sym, "BUY", sz.qty, cid, reduce_only=False)
        except ExchangeError as e:
            self.alert("진입 주문 결과 불명", f"{cid} {sz.qty} {sym}: {str(e)[:100]} · 선행 손절 유지 · 대조 루프가 정리")
            return False
        if o is None or o["executed_qty"] <= 0:
            self.st["intents"].pop(cid, None)
            self.save()
            self._cancel_quiet(sym, pre)
            return False
        j = self._journal_entry(sym, intent, o)
        self.st["intents"].pop(cid, None)
        self.save()
        self._upgrade_stop(sym, j, pre)                     # closePosition at the fill-based stop, THEN cancel pre-arm
        try:                                                 # late fills after a partial: exchange qty is the truth
            amt = self.x("positions", self.cfg.symbols)[sym]["amt"]
            if amt != 0 and abs(amt) != D(j["qty"]):
                j["qty"] = str(abs(amt))
                self.save()
        except ExchangeError:
            pass
        # partial fill: the unfilled rest is NOT chased; a filled part below min notional is closed at once (no dust)
        if D(j["qty"]) * D(j["entry_px"]) < self.rules[sym].min_notional:
            self.notify(f"⚪ {sym} 부분 체결 {j['qty']} (최소 주문금액 미만) → 즉시 정리")
            self.close(sym, "dust_entry")
            return False
        part = f" (부분 체결 {o['executed_qty']}/{sz.qty}, 나머지 취소·추격 안 함)" if o["executed_qty"] < sz.qty else ""
        self.notify(f"🟢 진입 {sym} 롱 · 수량 {j['qty']} · 체결가 {j['entry_px']}{part}\n"
                     f"손절 {j['stop_px']} · {sz.lev}x · 위험 {D(j['risk_usdt']):.4f} USDT ({sz.risk_pct_used}%)",
                     kind="entry", event_ms=intent.get("model_id") or intent.get("T"))
        self._slippage_monitor(sym, j, intent)
        return True

    def _slippage_monitor(self, sym, j, intent):
        """§8d: mean entry slippage of the first 30 entries worse than the model assumption by > 10 bp → alert only."""
        sp = intent.get("signal_px")
        if not sp:
            return
        bp = float((D(j["entry_px"]) / D(sp) - 1) * 10000)
        j["slip_bp"] = round(bp, 2)
        sl = self.meta.setdefault("slip_bp", [])
        if len(sl) < self.cfg.slip_review_n:
            sl.append(bp)
            if len(sl) == self.cfg.slip_review_n:
                mean = sum(sl) / len(sl)
                if mean - self.cfg.slip_assumed_bp > self.cfg.slip_alert_bp:
                    self.alert("진입 슬리피지 가정보다 나쁨 (자동 정지 아님)",
                               f"첫 {len(sl)}건 평균 {mean:.1f}bp vs 가정 {self.cfg.slip_assumed_bp}bp (+{self.cfg.slip_alert_bp}bp 초과)")
                else:
                    self.notify(f"ℹ️ 첫 {len(sl)}건 진입 슬리피지 평균 {mean:.1f}bp (가정 {self.cfg.slip_assumed_bp}bp)")
        self.save()

    def _journal_entry(self, sym, intent, o) -> dict:
        sd = D(intent["stop_dist"])
        fill = o["avg_price"] if o["avg_price"] > 0 else D(intent["ref"])
        qty = o["executed_qty"]
        stp = stop_price(self.rules[sym], fill, 1, sd)       # re-placed from the FILL at the same distance (TA)
        j = {"cid": intent["cid"], "side": 1, "qty": str(qty), "entry_px": str(fill), "stop_px": str(stp),
             "stop_dist": str(sd), "risk_usdt": str((fill - stp) * qty), "risk_frac": intent["risk_frac"],
             "lev": intent["lev"], "mmr": intent["mmr"], "model_entry_open": intent.get("model_id", intent["T"]), "opened_ms": self.now_ms(),
             "entry_order_id": o["id"], "entry_ref": intent["ref"], "wallet_at_entry": intent["wallet"],
             "planned_qty": intent["qty"], "stop_seq": 0, "exit_seq": 0}
        self.st["pos"][sym] = j
        self.save()
        return j

    def _wait_order(self, sym, cid):
        last = None
        for _ in range(self.cfg.query_retries):
            self.sleep(self.cfg.query_delay_s)
            try:
                return self.x("get_order", sym, cid)
            except ExchangeUnavailable as e:
                last = e
        raise ExchangeUnavailable(f"order {cid} status unknown") from last

    def submit_market(self, sym, side, qty, cid, reduce_only) -> dict | None:
        """Idempotent market order: reuse an existing id (restart replay); unknown outcome → query, never double-send."""
        existing = self.x("get_order", sym, cid)
        if existing is not None:
            return existing
        try:
            return self.x("market", sym, side, qty, cid, reduce_only)
        except ExchangeUnavailable:
            log.warning("order %s outcome unknown → query before any retry", cid)
            try:
                found = self._wait_order(sym, cid)
            except ExchangeUnavailable:
                self.block(UNKNOWN_ORDER, cid, "주문 상태 확인 불가 — 신규 진입 중단")
                raise
            if found is None and not reduce_only:
                self.skip(sym, "order_absent", f"{cid} confirmed absent → NOT re-sent")
            return found

    # ───────────────────────── stops ─────────────────────────
    @staticmethod
    def find_stop(amt: Decimal, orders) -> dict | None:
        """Exchange stop that fully protects `amt`: STOP_MARKET closePosition, or reduceOnly with qty ≥ |amt|."""
        cs = "SELL" if amt > 0 else "BUY"
        ok = [o for o in orders if o["side"] == cs and (o["type"] or "").startswith("STOP")
              and (o["close_position"] or (o["reduce_only"] and D(o.get("qty") or 0) >= abs(amt)))]
        ok.sort(key=lambda o: not o["close_position"])       # closePosition preferred
        return ok[0] if ok else None

    def _cancel_quiet(self, sym, o):
        try:
            self.x("cancel", sym, o)
        except ExchangeError as e:
            log.error("%s cancel %s failed (reconcile retries): %s", sym, o.get("client_id"), e)

    def _prearm(self, sym, stop_px, qty, cid) -> dict | None:
        try:
            return self.x("stop", sym, "SELL", stop_px, f"{cid}p", qty=qty)
        except WouldTrigger:
            return None
        except ExchangeError as e:
            log.error("%s pre-arm stop failed: %s → read-back", sym, e)
        try:
            return next((o for o in self.x("open_orders", sym) if o["client_id"] == f"{cid}p"), None)
        except ExchangeError:
            return None                                     # unknown: no entry; reconcile cancels it when flat

    def _upgrade_stop(self, sym, j, pre):
        """After the fill: closePosition stop at the fill-based price; the pre-arm is cancelled only once the new stop
        is confirmed (new before old). If it cannot be placed the pre-arm (qty ≥ filled) stays as the stop."""
        amt = D(j["qty"])
        for attempt in range(self.cfg.stop_attempts):
            seq = int(j.get("stop_seq", 0))
            j["stop_seq"] = seq + 1
            self.save()
            try:
                self.x("stop", sym, "SELL", D(j["stop_px"]), f"{j['cid']}s{seq}")
            except WouldTrigger:
                break
            except ExchangeError as e:
                log.error("%s closePosition stop attempt %d: %s", sym, attempt + 1, e)
            try:
                oo = self.x("open_orders", sym)
                cp = next((o for o in oo if o["close_position"] and o["side"] == "SELL"), None)
                if cp:
                    j["stop_px"] = str(cp["stop_price"])
                    self._cancel_quiet(sym, pre)
                    self.save()
                    return
            except ExchangeError:
                pass
            if attempt + 1 < self.cfg.stop_attempts:
                self.sleep(self.cfg.stop_retry_delay_s)
        log.warning("%s keeps the pre-armed reduceOnly stop %s", sym, pre["stop_price"])
        j["stop_px"] = str(pre["stop_price"])
        self.save()
        self._dirty = True                                  # reconcile re-verifies (qty ≥ position) right away

    def ensure_stop(self, sym, amt: Decimal, stop_px: Decimal, cid_base: str) -> str:
        """§8c L1: make sure a protective stop is CONFIRMED on the exchange, re-placing up to stop_attempts times
        (within ~10 s). A replacement is placed BEFORE any old/insufficient stop of ours is cancelled.
        Returns 'ok' | 'rejected' | 'would_trigger' | 'unavailable'."""
        side = "SELL" if amt > 0 else "BUY"
        try:
            oo = self.x("open_orders", sym)
            if self.find_stop(amt, oo):
                return "ok"
        except ExchangeError:
            oo = None
        j = self.st["pos"].get(sym)
        status = "unavailable"
        for attempt in range(self.cfg.stop_attempts):
            seq = int((j or {}).get("stop_seq", 0))
            if j is not None:
                j["stop_seq"] = seq + 1
                self.save()
            has_cp = oo is None or any(o["close_position"] and o["side"] == side for o in oo)
            try:                                              # one closePosition per side → overlap with a qty stop
                self.x("stop", sym, side, stop_px, f"{cid_base}s{seq}", **({"qty": abs(amt)} if has_cp else {}))
            except WouldTrigger:
                log.error("%s stop %s would trigger immediately", sym, stop_px)
                return "would_trigger"
            except OrderRejected as e:
                status = "rejected"
                log.error("%s stop rejected (%s), attempt %d", sym, e, attempt + 1)
            except ExchangeUnavailable as e:
                log.error("%s stop placement unknown (%s) → read-back", sym, e)
            try:
                oo = self.x("open_orders", sym)
                prot = self.find_stop(amt, oo)
                if prot:
                    for o in oo:                              # now (and only now) drop our insufficient old stops
                        if (o["id"] != prot["id"] and str(o["client_id"]).startswith(self.cfg.cid_prefix)
                                and o["reduce_only"] and not o["close_position"]):
                            self._cancel_quiet(sym, o)
                    return "ok"
            except ExchangeError:
                oo = None
            if attempt + 1 < self.cfg.stop_attempts:
                self.sleep(self.cfg.stop_retry_delay_s)
        return status

    def protect(self, sym, amt, stop_px, cid_base) -> bool:
        """§8c L1 → L3(b). Stop re-placed (3 tries); rejected/would-trigger → close ONLY this position; if even that
        fails the position cannot be protected → flatten all + halt. Transient outage → keep retrying via reconcile
        (L3(c) after api_dead_s)."""
        j = self.st["pos"].get(sym)
        r = self.ensure_stop(sym, amt, stop_px, cid_base)
        if r == "ok":
            if j is not None and j.pop("unprotected", None):
                self.save()
            return True
        if j is not None:
            j["unprotected"] = j.get("unprotected") or self.clock()
            self.save()
        if r == "unavailable":
            log.error("%s stop not confirmed (exchange unavailable) — reconcile retries", sym)
            return False
        self.alert("손절 등록 실패 — 이 포지션만 정리", f"{sym} {amt} · 손절 {stop_px} · {r} · 다른 포지션 유지")
        if not self.close(sym, f"sl_failed ({r})"):
            self.emergency_flatten_all(f"unprotected {sym}")
        return False

    # ───────────────────────── exits ─────────────────────────
    def close(self, sym, reason) -> bool:
        """Close the WHOLE position with reduceOnly MARKET orders until the exchange shows flat. The protective stop stays
        until flat is confirmed. A remainder (partial fill) is always closed in ONE order (no dust chunks)."""
        j = self.st["pos"].get(sym)
        if j is None:                                       # TA R4: never market-close a position the state file
            log.critical("close(%s, %s) refused: not in the state file (unknown positions are never closed by the bot)",
                         sym, reason)                       # does not hold — whatever the caller
            return False
        if not j.get("closing"):
            j["closing"], j["close_reason"] = True, reason
            self.save()
        if self.ban_left() > 0:                             # 418: nothing can be sent → queued for the unban tick
            self._queued[sym] = "close"
            log.error("%s close (%s) queued: IP ban %.0fs left", sym, reason, self.ban_left())
            return False
        for attempt in range(self.cfg.exit_attempts):
            try:
                amt = self.x("positions", self.cfg.symbols)[sym]["amt"]
                if amt == 0:
                    self._after_flat(sym, j.get("close_reason", reason))
                    return True
                seq = int(j.get("exit_seq", 0))
                j["exit_seq"] = seq + 1
                if not j.get("exit_ref"):
                    try:
                        j["exit_ref"] = str(self.x("book", sym)["bid"])
                    except ExchangeError:
                        pass
                self.save()
                self.submit_market(sym, "SELL" if amt > 0 else "BUY", abs(amt), f"{j['cid']}x{seq}", reduce_only=True)
                amt2 = self.x("positions", self.cfg.symbols)[sym]["amt"]
                if amt2 == 0:
                    self._after_flat(sym, j.get("close_reason", reason))
                    return True
                log.warning("%s exit left %s → closing the remainder in one order", sym, amt2)
            except ExchangeError as e:
                log.error("%s exit attempt %d failed: %s", sym, attempt + 1, e)
            self.sleep(self.cfg.exit_retry_delay_s)
        n = j.get("exit_fail_n", 0) + 1
        j["exit_fail_n"] = n
        self.save()
        if n == 1 or n % self.cfg.exit_alert_every == 0:
            self.alert(f"청산 미완료 — 계속 재시도 ({sym})", f"사유 {reason} · 거래소 손절 유지 · {n}회째")
        return False

    def _after_flat(self, sym, reason):
        try:
            for o in self.x("open_orders", sym):
                if (o["close_position"] or o["reduce_only"]) and str(o["client_id"]).startswith(self.cfg.cid_prefix):
                    self.x("cancel", sym, o)
        except ExchangeError as e:
            log.error("%s stale stop cancel failed (reconcile retries): %s", sym, e)
        self.record_close(sym, reason)

    def emergency_flatten_all(self, reason):
        """§8c L3 only: equity ≤ halt_fraction × C0 (−25 %), a position that stays unprotected after L1, or API dead > 5 min with an
        unprotected position → close ALL positions (reduceOnly MARKET) + halt."""
        self.halt(f"emergency: {reason}")
        self.alert("비상청산 — 전 포지션 정리 + 매매 중단", reason)
        for s in list(self.st["pos"]):                   # TA R4: only positions in the state file; unknown ones keep
            self.close(s, f"emergency ({reason})")          # their exchange stop and stay for manual handling
        if self.st["unknown"]:
            self.alert("비상청산 대상 아님 — 기록 없는 포지션은 그대로 둠 (손절 유지, 수동 처리)",
                       ", ".join(f"{s} {u.get('amt')} 손절 {u.get('stop_px')}" for s, u in self.st["unknown"].items()))

    def record_close(self, sym, reason):
        j = self.st["pos"].pop(sym, None)
        self.save()
        if not j:
            return
        opened = int(j.get("opened_ms", self.now_ms()))
        fills, fund = [], []
        try:
            fills = self.x("user_trades", sym, opened - 60_000)
            fund = self.x("income", sym, "FUNDING_FEE", opened)
        except ExchangeError as e:
            log.error("%s fills fetch failed, journaling estimate: %s", sym, e)
        entry_fills = [f for f in fills if f["order_id"] == str(j.get("entry_order_id"))]
        exit_fills = [f for f in fills if f["side"] == "SELL" and f["time"] >= opened - 1000]
        gross = sum((f["realized_pnl"] for f in exit_fills), Decimal(0))
        fees = sum((f["commission"] for f in entry_fills + exit_fills), Decimal(0))
        funding = sum((r["amount"] for r in fund), Decimal(0))
        xq = sum((f["qty"] for f in exit_fills), Decimal(0))
        xpx = sum((f["price"] * f["qty"] for f in exit_fills), Decimal(0)) / xq if xq else Decimal(0)
        net = gross - fees + funding
        risk = D(j.get("risk_usdt", "0"))
        rec = {"sym": sym, "cid": j["cid"], "reason": reason, "qty": j["qty"], "entry_px": j["entry_px"], "exit_px": str(xpx),
               "stop_px": j["stop_px"], "opened_ms": opened, "model_entry_open": j.get("model_entry_open"),
               "lev": j.get("lev"), "wallet_at_entry": j.get("wallet_at_entry"), "risk_frac": j.get("risk_frac"), "closed_ms": self.now_ms(), "gross": str(gross), "fees": str(fees),
               "funding": str(funding), "net": str(net), "planned_R": "-1",
               "R": str((net / risk).quantize(Decimal("0.001"))) if risk > 0 else None,
               "source": "exchange" if exit_fills else "estimate"}
        t_x = max((f["time"] for f in exit_fills), default=self.now_ms())
        if reason.split(" ")[0] not in MODEL_EXITS:              # exchange stop / safety close, not a model exit
            if self.strategy.on_live_closed(sym, j.get("model_entry_open"), reason, t_x, self):
                rec["model_closed"] = "stop_out"
                self.st["strategy"] = self.strategy.state
        self.meta.setdefault("trades", []).append(rec)
        del self.meta["trades"][:-1000]
        self.save()
        self.notify(f"{'🔴' if net < 0 else '🔵'} 청산 {sym} 롱 · {REASON_KO.get(reason.split(' ')[0], reason)}\n"
                     f"수량 {j['qty']} · {j['entry_px']} → {xpx:.8g} · 손절 {j['stop_px']}\n"
                     f"순손익 {net:+.4f} USDT" + (f" · {rec['R']}R" if rec["R"] else "")
                     + f" (수수료 {fees:.4f} · 펀딩 {funding:+.4f})", kind="exit", event_ms=t_x)
        self.check_halts()

    # ───────────────────────── reconcile (exchange → local) ─────────────────────────
    def reconcile(self):
        if self.st["intents"]:
            self.resolve_intents()                              # unknown entry outcomes first (by client id)
        acct = self.x("account")
        pos = self.x("positions", self.cfg.symbols)
        try:
            marks = self.x("mark_prices")
        except ExchangeError:
            marks = {}
        self.meta["wallet"] = str(acct["wallet"])
        self.meta["equity"] = str(acct.get("equity", acct["wallet"]))
        mismatch = []
        for sym in self.cfg.symbols:
            amt = pos[sym]["amt"]
            j = self.st["pos"].get(sym)
            orders = self.x("open_orders", sym)
            if amt == 0:
                if j:
                    self.record_close(sym, j.get("close_reason") or "stop_loss")
                u = self.st["unknown"].pop(sym, None)
                if u is not None:                               # TA R4: resolved by hand (or its stop fired)
                    self.save()
                    self.notify(f"✅ 기록 없는 포지션 해소 — {sym} {u.get('amt')} 거래소에서 0 · 이 코인 신규 진입 재개", kind="recovery")
                pending = tuple(f"{c}p" for c in self.st["intents"])        # pre-arm of an unresolved entry stays
                for o in orders:
                    if (str(o["client_id"]).startswith(self.cfg.cid_prefix) and (o["close_position"] or o["reduce_only"])
                            and str(o["client_id"]) not in pending):
                        try:
                            self.x("cancel", sym, o)                 # our own stale stop, position flat
                        except ExchangeError:
                            pass
                    elif not (o["close_position"] or o["reduce_only"]) and str(o["client_id"]).startswith(self.cfg.cid_prefix):
                        mismatch.append(f"{sym} 예상 밖 진입 주문 {o['client_id']}")
                if f"{MARGIN}:{sym}" in self.blocks:
                    self.ensure_isolated(sym)
                continue
            if j is None:
                if any(it.get("sym") == sym for it in self.st["intents"].values()):
                    mismatch.append(f"{sym} 진입 결과 확인 중 {amt}")     # our own unresolved entry (pre-arm protects it)
                    continue
                self._unknown_position(sym, pos[sym], orders, marks.get(sym))   # TA R4: never closed
                continue
            if sym in self.st["unknown"]:                    # adopted into the state file by ops meanwhile
                self.st["unknown"].pop(sym, None)
                self.save()
            if amt < 0:
                mismatch.append(f"{sym} 숏 포지션 {amt} (롱 전용 전략)")
            if D(j["qty"]) != abs(amt):
                mismatch.append(f"{sym} 수량 불일치 로컬 {j['qty']} / 거래소 {amt}")
                j["qty"] = str(abs(amt))                       # exchange wins
                self.save()
            if j.get("closing"):
                self.close(sym, j.get("close_reason", "retry"))
                continue
            mk = marks.get(sym)
            stp = D(j["stop_px"])
            if mk is not None and ((amt > 0 and mk <= stp) or (amt < 0 and mk >= stp)):
                self.breach_check(sym, mk, "5s reconcile")
                if (self.meta.get("halted") or "").startswith("emergency"):
                    return
                continue
            if not self.find_stop(amt, orders):
                self.alert("손절 주문 없음 — 재등록 시도", f"{sym} {amt} · 손절 {stp}")
                if not self.protect(sym, amt, stp, j["cid"]):
                    if self.meta.get("halted", "") and str(self.meta["halted"]).startswith("emergency"):
                        return
                    continue
                orders = self.x("open_orders", sym)
            elif j.get("unprotected"):
                j.pop("unprotected", None)
                self.save()
            if j.get("stop_lost") and self.find_stop(amt, orders):
                j.pop("stop_lost", None)                    # REST confirms a protective stop again
                self.save()
            prot = self.find_stop(amt, orders)
            if prot and prot["stop_price"] > 0 and D(prot["stop_price"]) != stp:
                j["stop_px"] = str(prot["stop_price"])          # §8c L2: the live exchange stop is the truth
                self.save()
            for o in orders:
                if prot and o["id"] == prot["id"]:
                    continue
                if not (o["close_position"] or o["reduce_only"]):
                    mismatch.append(f"{sym} 예상 밖 주문 {o['type']} {o['client_id']}")
                elif (prot and prot["close_position"] and o["reduce_only"] and not o["close_position"]
                      and str(o["client_id"]).startswith(self.cfg.cid_prefix)):
                    self._cancel_quiet(sym, o)                   # leftover pre-arm, closePosition stop is live
        if mismatch:
            self._consistent = 0
            self.block(MISMATCH, "; ".join(mismatch), "대조 불일치 — 신규 진입 중단")
        else:
            self._consistent += 1
            if self._consistent >= 2:
                for r in (MISMATCH, UNKNOWN_ORDER):
                    if r in self.blocks:
                        self.unblock(r)
        self.save()
        self.check_ledger()
        self.check_halts()

    def _unknown_position(self, sym, p, orders, mark):
        """TA R4: exchange position that is NOT in the state file (opened by hand, or the state file was lost).
        Never market-closed by the bot. 🚨 once, entries blocked for this coin (st["unknown"]), risk counted in the
        portfolio risk; without an exchange stop → closePosition MARK_PRICE stop at the model's exit line (20-bar
        channel low / high), or 1×ATR(14, 4h) from the mark if price is already beyond it. An existing stop is never
        moved or cancelled. Resolution is manual (close by hand, or tools/adopt_position.py)."""
        amt = p["amt"]
        side = 1 if amt > 0 else -1
        u = self.st["unknown"].get(sym)
        first = u is None or int(u.get("side", 0)) != side
        if first:
            u = {"side": side, "detected_ms": self.now_ms(), "stop_seq": 0}
            self.st["unknown"][sym] = u
        u.update(amt=str(amt), qty=str(abs(amt)), entry_px=str(p["entry"]))
        if u.get("closing"):                                # last-resort close already decided → retry until flat
            self._unknown_last_resort(sym, u, amt)
            return
        if mark is None:
            try:
                mark = self.x("mark_prices").get(sym)
            except ExchangeError:
                mark = None
        prot = self.find_stop(amt, orders)
        if prot is not None:
            if u.get("stop_cid") != prot.get("client_id"):
                u["stop_src"] = "exchange (existing, untouched)"
            u.update(stop_px=str(prot["stop_price"]), stop_cid=prot.get("client_id"))
            u.pop("unprotected", None)
            u.pop("stop_rejects", None)
        elif not self._unknown_stop(sym, u, amt, mark):
            age = self.now_ms() - int(u["detected_ms"])
            if int(u.get("stop_rejects", 0)) > 0 and age >= self.cfg.unknown_stop_deadline_s * 1000:
                u["closing"] = True                         # TA R4 last resort: protection beats ownership
                self.save()
                self.alert(f"기록 없는 포지션 손절이 {self.cfg.unknown_stop_deadline_s / 60:.0f}분 넘게 거부됨 — 최후 수단으로 {sym} 시장가 정리",
                           f"{sym} {amt} · 발견 {age / 1000:.0f}초 전 · 손절 거부 {u.get('stop_rejects')}회 · "
                           f"마지막 사유 {u.get('last_reject', '-')} · reduceOnly MARKET")
                self._unknown_last_resort(sym, u, amt)
                return
        self._unknown_risk(u, mark if mark is not None else p["entry"])
        self.save()
        if first:
            self.alert(f"기록 없는 포지션 발견 — {sym} 자동 청산 안 함 · 이 코인 신규 진입 차단 · 수동 처리 필요",
                       f"{sym} {'롱' if side > 0 else '숏'} {abs(amt)} @ {p['entry']} · "
                       f"손절 {u.get('stop_px') or '없음 (등록 재시도 중)'} ({u.get('stop_src', '-')}) · "
                       f"포트폴리오 위험에 포함 {u.get('risk_frac', 0):.2%} · 해결: 직접 청산 또는 ops가 adopt_position 으로 등록")

    def _unknown_stop(self, sym, u, amt, mark) -> bool:
        """Place the protective stop for an unknown position. True = placed (exchange accepted it). Rejections
        (OrderRejected / WouldTrigger) are counted for the 5-min last resort; transient errors are not."""
        side = 1 if amt > 0 else -1
        if mark is None:
            self._unknown_unprotected(sym, u, "mark 가격 없음 — 손절 계산 불가, 재시도")
            return False
        r = self.rules[sym]
        rnd = "down" if side > 0 else "up"                  # away from the price
        ref = self.strategy.exit_line(sym, side)            # (20-bar channel line, ATR14 4h) or None
        line = atr = None
        if ref is None:                                     # TA R4: no channel / ATR data yet → 3 % from the mark
            px, src = mark * (1 - side * D(self.cfg.fallback_stop_pct) / 100), f"fallback {self.cfg.fallback_stop_pct:g}% from mark (no channel/ATR data)"
        else:
            line, atr = D(ref[0]), D(ref[1])
            beyond = (mark <= line) if side > 0 else (mark >= line)
            px, src = (mark - side * atr, "1×ATR14 from mark (price beyond the 20-bar line)") if beyond else (line, "20-bar channel exit line")
        px = r.price(px, rnd)
        seq = int(u.get("stop_seq", 0))
        u["stop_seq"] = seq + 1
        self.save()
        cs = "SELL" if side > 0 else "BUY"
        cid = f"{self.cfg.cid_prefix}{sym.removesuffix('USDT')}u{int(u['detected_ms']) // 1000}s{seq}"
        try:
            try:
                o = self.x("stop", sym, cs, px, cid)          # closePosition=true, MARK_PRICE (reduce-only by nature)
            except WouldTrigger:
                if atr is None or src.startswith("1×ATR"):
                    raise
                px = r.price(mark - side * atr, rnd)
                src = "1×ATR14 from mark (line would trigger)"
                o = self.x("stop", sym, cs, px, f"{cid}b")
        except (OrderRejected, WouldTrigger) as e:
            u["stop_rejects"] = int(u.get("stop_rejects", 0)) + 1
            u["last_reject"] = str(e)[:80]
            self._unknown_unprotected(sym, u, f"손절 거부 {px}: {str(e)[:80]}")
            return False
        except ExchangeError as e:
            self._unknown_unprotected(sym, u, f"손절 등록 결과 불명 {px}: {str(e)[:80]} (재조회 후 재시도)")
            return False
        u.update(stop_px=str(o.get("stop_price") or px), stop_cid=o.get("client_id", cid), stop_src=src)
        if line is not None:
            u.update(stop_line=str(line), stop_atr=str(atr))
        u.pop("unprotected", None)
        u.pop("stop_rejects", None)
        log.warning("%s unknown position %s: stop %s placed (%s)", sym, amt, u["stop_px"], src)
        return True

    def _unknown_last_resort(self, sym, u, amt):
        """TA R4 last resort (only after 5 min of REJECTED stops): reduceOnly MARKET for the whole position, retried
        every reconcile until the exchange shows flat; then the unknown entry is cleared (reconcile flat branch)."""
        seq = int(u.get("exit_seq", 0))
        u["exit_seq"] = seq + 1
        self.save()
        cid = f"{self.cfg.cid_prefix}{sym.removesuffix('USDT')}u{int(u['detected_ms']) // 1000}x{seq}"
        try:
            self.submit_market(sym, "SELL" if amt > 0 else "BUY", abs(amt), cid, reduce_only=True)
            left = self.x("positions", self.cfg.symbols)[sym]["amt"]
        except ExchangeError as e:
            log.error("%s unknown position last-resort close failed (retry next reconcile): %s", sym, e)
            return
        if left == 0:
            self.st["unknown"].pop(sym, None)
            self.save()
            self.alert(f"기록 없는 포지션 최후 수단 정리 완료 — {sym}", f"{amt} → 0 · 손절이 계속 거부되어 시장가로 정리함")
        else:
            log.warning("%s unknown position last-resort close left %s → retry next reconcile", sym, left)

    def _unknown_unprotected(self, sym, u, why):
        n = int(u.get("unprot_n", 0)) + 1
        u["unprot_n"] = n
        u["unprotected"] = u.get("unprotected") or self.clock()
        self.save()
        if n > 1 and n % self.cfg.exit_alert_every == 0:
            self.alert(f"기록 없는 포지션 손절 미확인 — {sym} 정리 안 함, 계속 재시도", why)
        log.error("%s unknown position without a confirmed stop: %s", sym, why)

    def _unknown_risk(self, u, ref_px):
        """Risk of the unknown position in the portfolio-risk sum: |ref − stop| × qty / capital (no stop → 10 % of
        notional as a placeholder), never below the old 'unknown → 2 × risk_pct' floor."""
        qty, ref = D(u["qty"]), D(ref_px)
        stp = D(u["stop_px"]) if u.get("stop_px") else None
        risk = abs(ref - stp) * qty if stp is not None else ref * qty / 10
        try:
            cap = self.strategy_equity() if "start_wallet" in self.meta else D(self.meta.get("wallet") or 0)
        except Exception:  # noqa: BLE001
            cap = D(self.meta.get("wallet") or 0)
        frac = float(risk / cap) if cap > 0 else 1.0
        u.update(risk_usdt=str(risk), risk_frac=max(frac, self.cfg.sizing.risk_pct / 100 * 2))

    # ───────────────────────── ledger / halts ─────────────────────────
    def check_ledger(self):
        if "start_wallet" not in self.meta or self.clock() - self._last_income < self.cfg.income_interval_s:
            return
        self._last_income = self.clock()
        cursor = int(self.meta.get("income_cursor", self.now_ms()))
        seen = set(self.meta.get("income_seen", []))
        try:
            rows = self.x("income", None, None, cursor)
        except ExchangeError:
            return
        ledger, tr = D(self.meta["ledger_balance"]), D(self.meta.get("net_transfers", "0"))
        for r in sorted(rows, key=lambda r: r["time"]):
            k = f"{r['type']}:{r['tran_id']}"
            if r["time"] < cursor or (r["time"] == cursor and k in seen):
                continue
            ledger += r["amount"]
            if r["type"] == "TRANSFER":
                tr += r["amount"]
            if r["time"] > cursor:
                cursor, seen = r["time"], set()
            seen.add(k)
        self.meta.update(ledger_balance=str(ledger), net_transfers=str(tr), income_cursor=cursor, income_seen=sorted(seen))
        wallet = D(self.meta.get("wallet", "0"))
        diff = wallet - ledger
        if wallet > 0 and abs(diff) / wallet * 100 >= D(self.cfg.ledger_tol_pct):
            self._ledger_strikes += 1
            if self._ledger_strikes >= 2:
                self.block(LEDGER, str(diff), f"장부-거래소 잔고 차이 {diff:+.4f} USDT — 신규 진입 중단")
        else:
            self._ledger_strikes = 0
            if LEDGER in self.blocks:
                self.unblock(LEDGER)
        self.save()

    # ───────────────────────── capital (§8e-2) ─────────────────────────
    def capital0(self) -> Decimal:
        return D(self.meta.get("capital0") or D(self.meta["start_wallet"]) * D(self.cfg.capital_fraction))

    def strategy_equity(self, value=None) -> Decimal:
        """C0 + PnL since start (transfers excluded). `value` = exchange wallet (realised) or equity (incl. unrealised)."""
        v = D(value if value is not None else (self.meta.get("equity") or self.meta.get("wallet") or self.meta["start_wallet"]))
        return self.capital0() + (v - D(self.meta["start_wallet"]) - D(self.meta.get("net_transfers", "0")))

    def drawdown_breached(self) -> tuple[bool, Decimal, Decimal]:
        """S0 = wallet at live start (persisted). Breached when strategy equity (incl. unrealised, deposits/withdrawals
        from income TRANSFER rows excluded) ≤ halt_fraction × C0. Single source of truth: Settings.halt_fraction."""
        c0 = self.capital0()
        eq = self.strategy_equity()
        thr = c0 * D(self.cfg.halt_fraction)
        return c0 > 0 and eq <= thr, eq, thr

    def check_halts(self):
        if "start_wallet" not in self.meta:
            return
        hit, adj, thr = self.drawdown_breached()
        if hit and not self.meta.get("halted"):
            self._last_income = -1e18                       # a fresh transfer sync first: a withdrawal not yet
            self.check_ledger()                             # booked must not look like a loss
            hit, adj, thr = self.drawdown_breached()
        if hit and not self.meta.get("halted"):
            self.emergency_flatten_all(f"자산 {adj:.2f} ≤ {thr:.2f} (시작 자본 {self.capital0():.2f} × "
                                       f"{self.cfg.halt_fraction}, 입출금 제외)")   # §8c L3(a) / §8e-2
        nets = [D(t["net"]) for t in self.meta.get("trades", []) if int(t["closed_ms"]) >= int(self.meta.get("start_ms", 0))]
        if len(nets) >= self.cfg.pf_review_after and not self.meta.get("pf_review"):
            g, l_ = sum(x for x in nets if x > 0), -sum(x for x in nets if x < 0)
            pf = float(g / l_) if l_ > 0 else float("inf")
            if pf < self.cfg.pf_review:
                self.meta["pf_review"] = f"{len(nets)}건 PF {pf:.2f}"
                self.save()
                self.notify(f"⚠️ 점검 필요: {len(nets)}건 PF {pf:.2f} < {self.cfg.pf_review} (자동 정지 아님)")

    # ───────────────────────── Telegram reports ─────────────────────────
    def reports(self):
        now = self.now_ms()
        day = datetime.fromtimestamp(now / 1000, KST).strftime("%Y-%m-%d")
        last = self.meta.get("settled_day")
        if last is None:
            self.meta["settled_day"] = day
            self.meta["day_start_wallet"] = self.meta.get("wallet")
        elif last != day:
            self.notify(self.daily_summary(last))
            self.meta.update(settled_day=day, day_start_wallet=self.meta.get("wallet"))
            self.save()
        if self.clock() - self.meta.get("heartbeat_at", 0) >= self.cfg.heartbeat_s:
            self.meta["heartbeat_at"] = self.clock()
            self.notify(f"💓 작동 중 · 잔고 {D(self.meta.get('wallet', '0')):.2f} USDT · 포지션 {len(self.st['pos'])}개"
                         + (f" · 기록 없는 포지션 {','.join(self.st['unknown'])}" if self.st["unknown"] else "")
                         + (f" · 진입 보류: {','.join(self.blocks)}" if self.blocks else "")
                         + (f" · 중단: {self.meta['halted']}" if self.meta.get("halted") else ""))
            self.save()

    def daily_summary(self, day: str) -> str:
        """일일 결산 (KST day): 잔고·손익·거래·skip 사유·보유 포지션·정지 상태."""
        trades = [t for t in self.meta.get("trades", [])
                  if datetime.fromtimestamp(int(t["closed_ms"]) / 1000, KST).strftime("%Y-%m-%d") == day]
        net = sum((D(t["net"]) for t in trades), Decimal(0))
        w, w0, sw = (D(self.meta.get(k) or self.meta.get("wallet") or "0") for k in ("wallet", "day_start_wallet", "start_wallet"))
        cum = (w - sw - D(self.meta.get("net_transfers", "0"))) / sw * 100 if sw > 0 else Decimal(0)
        wins = sum(1 for t in trades if D(t["net"]) > 0)
        sk = self.meta.get("skips", {}).get(day, {})
        lines = [f"📊 일일 결산 {day} (KST)",
                 f"잔고 {w:.2f} USDT (전일 대비 {w - w0:+.2f}) · 시작 대비 {cum:+.1f}%",
                 f"청산 {len(trades)}건 (이익 {wins} / 손실 {len(trades) - wins}) · 실현 순손익 {net:+.4f} USDT"]
        lines += [f"  {t['sym']} {REASON_KO.get(str(t['reason']).split(' ')[0], t['reason'])} {D(t['net']):+.4f}"
                  + (f" ({t['R']}R)" if t.get("R") else "") for t in trades]
        lines.append("보유: " + (", ".join(f"{s} {j['qty']} @ {j['entry_px']} 손절 {j['stop_px']}" for s, j in self.st["pos"].items())
                                 or "없음"))
        if self.st["unknown"]:
            lines.append("⚠️ 기록 없는 포지션 (자동 청산 안 함): " + ", ".join(
                f"{s} {u.get('amt')} @ {u.get('entry_px')} 손절 {u.get('stop_px') or '없음'}" for s, u in self.st["unknown"].items()))
        if sk:
            lines.append("진입 건너뜀: " + ", ".join(f"{k} {v}" for k, v in sorted(sk.items())))
        if self.meta.get("halted"):
            lines.append(f"⛔ 매매 중단 상태: {self.meta['halted']}")
        return "\n".join(lines)

    def check_api_dead(self):
        """§8c L3(c): exchange unresponsive > api_dead_s AND a position without a confirmed stop → flatten all."""
        if self._fault_since is None or self.clock() - self._fault_since <= self.cfg.api_dead_s:
            return
        if self.ban_left() > 0:                             # 418: nothing can be sent; queued actions run at unban
            return
        bad = [s for s, j in self.st["pos"].items() if j.get("unprotected")]   # unknown positions never trigger a flatten
        if bad and not str(self.meta.get("halted") or "").startswith("emergency"):
            self.emergency_flatten_all(f"API 무응답 {self.clock() - self._fault_since:.0f}s + 손절 미확인 {bad}")

    # ───────────────────────── loop ─────────────────────────
    def tick(self, force_reconcile=True):
        """Main-loop step: REST reconcile (safety net, every `reconcile_s`, or at once after a user-stream event),
        stream health, scheduled strategy decision."""
        if not self.started:
            self.startup()
            if not self.started:
                return
        backoff = self.rate_backoff()
        if self._queued and not self.ban_left():
            self.flush_queued()                             # 418 over → queued stop / close go out first
        if backoff:                                         # 429/418: honour Retry-After — no polling (it extends a
            self.block(RATE_LIMIT, f"Retry-After {backoff:.0f}s")   # ban); exchange stops stay; protective calls
            self.check_api_dead()                           # (stop / cancel / close) still go out when triggered
        elif RATE_LIMIT in self.blocks:
            self.unblock(RATE_LIMIT)
            self._dirty = True
        if not backoff and (force_reconcile or self._dirty or self.clock() - self._last_reconcile >= self.cfg.reconcile_s):
            self._dirty = False
            self._last_reconcile = self.clock()
            try:
                self.reconcile()
                self._last_ok_reconcile = self.clock()
            except ExchangeError as e:
                log.error("reconcile failed: %s", e)
                self.check_api_dead()
        self.stream_health()
        self.market_data_guard()
        self.check_transient()
        self.reports()
        try:
            if not backoff:
                self.on_bar_close()                         # scheduled strategy decision (4h close → models step)
        except Exception:  # noqa: BLE001  never skip the guards / dead-man below; bar_guard alerts if it persists
            log.exception("bar decision failed (retry next tick)")
        self.bar_guard()
        ok = self.healthy()
        self.meta["health"] = {"t": self.now_ms(), "ok": ok, "blocks": sorted(self.blocks)}   # read by the external
        if self.deadman is not None:                                                     # pinger (heartbeat_ping.sh)
            self.deadman.maybe_ping(ok)

    def rate_backoff(self) -> float:
        """Seconds left of the REST client's 429/418 backoff (0 if none / fake exchange)."""
        ex = getattr(self.ex, "inner", self.ex)
        until = getattr(ex, "backoff_until", 0) or 0
        clk = getattr(ex, "clock", None)
        left = until - (clk() if callable(clk) else time.time())
        return left if left > 0 else 0.0

    def bar_lag(self) -> tuple[int | None, list]:
        """Latest decision boundary T and what has NOT been committed for it yet: [] when meta.last_bar_close ≥ T and
        every model stepped the bar that closed at T (last_open ≥ T − interval)."""
        iv = self.strategy.decision_interval_ms
        if not iv:
            return None, []
        T = self.now_ms() // iv * iv
        behind = []
        if int(self.meta.get("last_bar_close") or 0) < T:
            behind.append(f"last_bar_close {self.meta.get('last_bar_close')}")
        for s, m in (self.strategy.state.get("models") or {}).items():
            if int(m.get("last_open", -1)) < T - iv:
                behind.append(f"{s} last_open {m.get('last_open')}")
        return T, behind

    def bar_guard(self):
        """TA stale-bar guard: the bar decision for the latest boundary is not committed within bar_stale_s after it →
        block NEW entries + 🚨 (positions / exchange stops untouched); caught up → unblock + ✅."""
        T, behind = self.bar_lag()
        if T is None:
            return
        if behind and self.now_ms() - T > self.cfg.bar_stale_s * 1000:
            detail = f"봉 {datetime.fromtimestamp(T / 1000, KST):%m-%d %H:%M} KST 마감 미반영 · " + ", ".join(behind)[:300]
            if BAR_STALE not in self.blocks:
                self.block(BAR_STALE, detail)
                self._block_alerted.add(BAR_STALE)
                self.alert(f"4시간 봉 마감 {self.cfg.bar_stale_s:.0f}초 넘게 미반영 — 신규 진입 차단 (포지션·손절 유지, 정리 안 함)",
                           detail, event_ms=T)
            else:
                self.blocks[BAR_STALE] = detail
        elif not behind and BAR_STALE in self.blocks:
            self.blocks.pop(BAR_STALE, None)
            self._block_since.pop(BAR_STALE, None)
            self._block_alerted.discard(BAR_STALE)
            self.notify(f"✅ 4시간 봉 마감 반영 완료 — {'신규 진입 재개' if self.entries_allowed() else '다른 차단 사유 남음: ' + ','.join(self.blocks)}",
                        kind="recovery")

    def healthy(self) -> bool:
        """Dead-man ping only while: started, not halted, last REST reconcile succeeded within 3× reconcile_s, no
        position flagged unprotected, bar decisions current (no stale-bar block)."""
        return (self.started and not self.meta.get("halted") and self.clock() - self._last_ok_reconcile <= 3 * self.cfg.reconcile_s
                and BAR_STALE not in self.blocks
                and not any(j.get("unprotected") for j in self.st["pos"].values())
                and not any(u.get("unprotected") for u in self.st["unknown"].values()))
