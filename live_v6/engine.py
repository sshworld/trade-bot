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
  * qrmtf (user 2026-10-30): that −25 % total halt is OFF (halt_fraction None); instead daily_loss_halt 0.10 → equity (wallet + uPnL,
    transfers excluded) ≤ 0.90 × equity at 00:00 UTC (09:00 KST) → close all bot positions, 0 bot orders, no new entries for 24 h, auto-resume.
  * TA R4 (unknown positions): a position on the exchange that is NOT in the state file is never market-closed — not
    by the strategy (model_sync), not by a breach / stop-failure close, not by flatten-all. It is kept in
    st["unknown"]: 🚨 once (Telegram on mainnet only), new entries blocked for THAT coin, its risk counted in the
    portfolio risk, and if it has no exchange stop a closePosition MARK_PRICE stop is placed at the model's exit
    line (20-bar channel low for a long / high for a short; 1×ATR(14, 4h) from the mark if price is already beyond
    the line; 3 % from the mark if channel/ATR data is missing). Existing stops are never moved or cancelled.
    Resolution is manual (close by hand, or `python -m live_v6.tools.adopt_position`). Only exception (protection
    beats ownership): the exchange keeps REJECTING the stop and none is confirmed within 5 min of detection →
    reduceOnly MARKET close of that position + 🚨.
  * TA protection policy v1 (2026-11-09): scheme E, which had no TP on the remainder, rests a
    reduceOnly TAKE_PROFIT_MARKET at entry ± 3R (MARK_PRICE) after TP1, beside the chandelier stop.
    A scheme-E qty that cannot be split gets that +3R TP and the SL on the full size. Legacy keeps
    its +2R TP2. A failed SL/TP placement, including the entry-time stop, is retried at 1s, 3s, 10s
    (alert each time) and then reduceOnly-market closed. Once a minute, and again after a restart,
    a missing SL or TP is restored the same way. A symbol missing from the positions response is
    unknown: that read never cancels SL/TP and never market-closes.
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

# Current journal: every open position has a proved entry_qty, and fills live only in tp_ledger.
# Older files have no schema key. They are not migrated.
STATE_SCHEMA = 2
SCHEMA_HALT = "구 상태 파일 — 익절 없이 손절만 유지"
from .notify import Notifier
from .rules import D, SymbolRules, stop_price
from .sizing import TAKER_FEE, SizingParams, size_entry
from .tradelog import kst

log = logging.getLogger("live_v6.engine")

SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
# FROZEN (TA review 57b0888 item 1): processing order of simultaneous bar-close entry signals. It is the order the
# research portfolio used at its first full 6-coin tie (2023-01-14 00:00 UTC); see README "Simultaneous-signal tie
# order" for why research itself has no fixed order. The only live setting — never change without a TA review.
ENTRY_ORDER = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "DOGEUSDT", "XRPUSDT", "SOLUSDT")
H4 = S.H4_MS
KST = timezone(timedelta(hours=9))

QUIET_SKIPS = ("max_positions", "dir_cap", "risk_cap_portfolio", "total_risk_cap", "peak_dd")   # full book: log only, never an alert
MODEL_EXITS = ("signal_exit", "model_sync", "time_exit")   # strategy-driven exits: the model is already flat
REASON_KO = {"stop_loss": "손절", "signal_exit": "M20 채널 청산", "model_sync": "모델 동기화 청산", "stop_breach": "손절 미작동 정리",
             "sl_failed": "손절 등록 실패 정리", "stop_lost_breach": "손절 주문 소실 후 손절가 돌파 정리", "emergency": "비상 전체 정리", "dust_entry": "소액 부분 체결 정리",
             "time_exit": "24시간 보유 청산", "take_profit": "익절", "be_stop": "1차 익절 후 본절", "be_stop_breach": "본절 손절가 돌파 정리",
             "trail_stop": "추적 손절", "trail_stop_breach": "추적 손절가 돌파 정리",
             "daily_loss_halt": "일일 손실 한도 전체 정리"}

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
    sizing: SizingParams = field(default_factory=SizingParams)
    params: S.Params = field(default_factory=S.Params)
    max_positions: int = 6              # v6 H7 has no extra cap (one per symbol); enforced at placement anyway
    max_same_side: int | None = None    # TA PASS 2026-11-03: at most N open positions on one side (live 2); None/0 = off.
                                        # Counted from the fresh exchange positions read (restart-safe); quiet skip dir_cap
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
    halt_fraction: float | None = 0.75  # §8e-2 / §8c L3(a): flatten all + halt when strategy equity ≤ halt_fraction × C0 (None = off)
    daily_loss_halt: float | None = None  # qrmtf (user 2026-10-30): equity (incl. unrealised, transfers excluded) ≤ (1 − x) ×
                                          # equity at 00:00 UTC → flatten all + cancel orders + no new entries for daily_halt_s
    daily_halt_s: float = 24 * 3600.0     # daily-loss halt length from the trigger time, then auto-resume (persisted)
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
    residual_alert_n: int = 3           # TA R3: flat coin, bot-order cancel failed this many reconciles in a row → one 🚨
    heartbeat_s: float = 4 * 3600       # 💓 Telegram heartbeat cadence
    slip_review_n: int = 30             # §8d entry-slippage review over the first N entries (alert only)
    slip_assumed_bp: float = 2.0        # model: entry = trigger (level + 1 tick) + 2 bp
    slip_alert_bp: float = 10.0
    trade_from_ms: int = 0              # replay harness: no orders before this bar close
    trade_until_ms: int = 1 << 62
    # qrmtf (PM 2026-10-30): exchange-side TP1/TP2 + breakeven after TP1 + time exit. Off by default (legacy H7-T tests);
    # runner.live_settings() turns them on for the live strategy.
    enable_short: bool = False
    take_profit: bool = False           # TP1 = +tp1_r·R for tp1_frac of the qty, TP2 = +tp2_r·R for the rest (reduceOnly)
    tp1_r: float = 1.0
    tp1_frac: float = 0.5
    tp2_r: float | None = 2.0           # None/0 → no TP2 order (E chandelier, TA 2026-11-04): the trailing SL exits the rest
    be_offset: float = 0.001            # after TP1: SL → be ± be_offset (live 0.15 %, TA 2026-11-03), safe-side tick
    be_fee: float | None = None         # None: be = entry; f: be = fee-inclusive breakeven entry·(1±f)/(1∓f) (E: f = 0.0005)
    # E chandelier (TA 2026-11-04, replay variant E): from entry, SL = tighter(SL, best ∓ trail_atr_k·ATR14) where ATR14 =
    # Wilder ATR of the last CLOSED 1h bar and best = the 1m high (long) / low (short) extreme since entry, evaluated once
    # per closed minute (effective from the next candle); never looser. Replace = new reduceOnly STOP first, read back,
    # then the old stop cancelled. 0 = off.
    trail_atr_k: float = 0.0
    # peak-drawdown entry guard (TA 2026-11-03/04): equity (wallet + uPnL) < peak × peak_dd_guard → NEW entries blocked;
    # the peak (meta.peak_equity, name kept for state compatibility) ratchets on the WALLET only — uPnL never raises it;
    # one 🚨, open positions / SL / TP untouched; peak + halt persisted; cleared only by the team with
    # live_v6/tools/clear_peak_halt.py (service stopped; audit-logged; optional peak reset to the current wallet)
    peak_dd_guard: float | None = None
    peak_dd_init: float = 0.0           # peak floor at first run (live: real max seen, 132.88 USDT wallet 11/02)
    max_hold_s: float = 0               # > 0: reduceOnly market close after this long (24 h live)
    # live 2026-10-30 15:07 KST SOLUSDT: set 10x echoed, symbolConfig still 20x right after → entry skipped; re-read
    # symbolConfig up to lev_confirm_reads times (lev_confirm_wait_s apart) while it shows the wrong value
    lev_confirm_reads: int = 5
    lev_confirm_wait_s: float = 1.0
    startup_leverage: int | None = None  # set this leverage at startup on every flat coin (qrmtf live: 10)


LOG_INTENT_KEYS = ("signal_px", "path", "risk_pct_used", "order_ms", "prearm_ms", "open_risk_after", "same_side_open")
EARLYCUT_MS = 4 * 3600_000                                  # record-only early-cut flag window (TA 2026-11-02)
EXIT_KIND = {"stop_loss": "exchange_close", "be_stop": "exchange_close", "trail_stop": "exchange_close", "take_profit": "exchange_close", "signal_exit": "exit_rule", "model_sync": "exit_rule", "daily_loss_halt": "halt"}   # live log exit_reason
# Flat journal whose own exit fills are still short of the opened qty: re-read on later reconciles (one poll
# each after the first, no query_retries sleep). Every CLOSE_HOLD_MAX short reads (12 × the 5s REST reconcile
# ≈ 1 minute) the "still unconfirmed" alert fires again. The journal stays open and the symbol stays blocked.
# A close is never committed on this timer.
CLOSE_HOLD_MAX = 12
# TA protection policy v1: three retries, then reduceOnly market close. Book audit once a minute.
PROTECT_RETRY_S = (1.0, 3.0, 10.0)
PROTECT_AUDIT_S = 60.0
# A conditional order is gone only when the exchange says so. Anything else can still fill.
_TP_GONE = frozenset({"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"})
_TP_DONE = frozenset({"FILLED", "FINISHED"})
_TP_RESTING = frozenset({"NEW", "WORKING", ""})


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
        self.events = None                                  # runner attaches tradelog.EventLog (live log v1); None = off
        self._sig_side = 1
        self._sig = None                                    # live log: (sym, signal_px, signal_ms) of the entry in progress
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
        self._trail_try: dict = {}           # sym → last closed 1m bar tried (E trailing: one try per minute)
        self._own_cancels: dict[str, float] = {}           # client ids WE cancelled → not a "stop lost" event
        self._queued: dict[str, str] = {}                  # 418 ban: sym → "stop" | "close", sent the moment it ends
        self._r3_fail: dict[str, int] = {}                 # TA R3: flat coin → reconciles in a row with a failed bot cancel
        self._r3_alerted: set = set()                      # flat coins whose residual 🚨 is out (cleared by one ✅)
        self._foreign_seen: set = set()                    # (sym, order id) of non-bot orders on a flat coin already 🚨'd
        self._flat_confirmed: set = set()                  # symbols whose position read in THIS process returned 0.
                                                           # empty after a restart until reconcile confirms again
        self._protect_audit_at = self.clock()              # protection audit is due PROTECT_AUDIT_S after this
        self._audit_unknown: set = set()                    # coins whose audit confirm is unread; alert once until known
        self._cp_hold: set = set()                          # -4130 hold already alerted; cleared when a read shows the stop
        self._cp_retry_at: dict = {}                        # sym → earliest clock() for another empty-book re-arm
        self._cp_book_sig: dict = {}                        # last book we already re-armed against during the hold
        self._tp_unknown: set = set()                       # book unreadable: TP not placed, alerted once until known
        self._book_down_since: dict = {}                    # sym → first unreadable open-order read (60s before the alert)
        self._tp_fail_alerted: set = set()                  # (symbol, tranche) already told that this order failed
        self._dup_unknown: set = set()                      # (sym, what) already alerted for an unreadable -4116
        self._dup_retry_at: dict = {}                       # (sym, what) → earliest clock() to look at that -4116 again
        self._tp_retry_at: dict = {}                        # (sym, what) → earliest clock() for another rejected-TP cycle
        self._tp_cooled: set = set()                        # rejected TPs whose next try is a single POST, not 1s+3s+10s
        self._armed_now: set = set()                        # symbols already stop-armed in this reconcile
        self._cap_retry_at: dict = {}                       # sym → earliest clock() to retry a rejected BE cap close
        self._cap_alerted: set = set()                      # symbols already told that a cap close was held
        self._schema_lock = False                          # old state: SL only, no take-profit and no entries
        self._lock_hold_alerted: set = set()               # (symbol, incident) already told under the schema lock
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
        self._day_count("incidents")

    def _lock_hold_alert(self, sym, incident: str, detail: str = ""):
        """One truthful notice per incident while the schema lock refuses a market close."""
        key = (str(sym), incident)
        if key in self._lock_hold_alerted:
            return
        self._lock_hold_alerted.add(key)
        self.alert(f"구 상태 잠금 — {sym} 손절만 유지 · 시장가 안 냄",
                   incident + (f" · {detail}" if detail else ""))

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
        fresh = getattr(self, "_fresh_blocks", None)
        if fresh is not None:
            fresh.add(reason)
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
        return not self.blocks and not self.meta.get("halted") and not self.meta.get("peak_dd")

    def halt(self, reason):
        if not self.meta.get("halted"):
            self.meta["halted"] = reason
            self.save()
            self.alert(f"매매 중단 (halt): {reason}", "신규 진입 중단 · 확인 후 `python -m live_v6 resume`")

    def resume(self):
        self.meta.pop("halted", None)
        self.meta.pop("daily_halt", None)       # peak_dd is NOT cleared here: team-only, live_v6/tools/clear_peak_halt.py
        self.save()

    def _peak_guard(self):
        g = self.cfg.peak_dd_guard
        if not g or self.meta.get("equity") is None:
            return
        eq = D(self.meta["equity"])                  # trigger: equity (wallet + uPnL) < peak × guard
        w = D(self.meta.get("wallet") or self.meta["equity"])
        pk = max(D(self.meta.get("peak_equity") or str(self.cfg.peak_dd_init)), w)   # TA 2026-11-04: peak = WALLET only
        if self.meta.get("peak_equity") is None or pk != D(self.meta["peak_equity"]):
            self.meta["peak_equity"] = str(pk)
            self.save()
        line = pk * D(str(g))
        if eq < line and not self.meta.get("peak_dd"):
            self.meta["peak_dd"] = {"t_ms": self.now_ms(), "equity": str(eq), "peak": str(pk), "line": str(line)}
            self.save()
            self.alert(f"고점 대비 -{(1 - D(str(g))) * 100:.0f}% 도달: 자산 {eq:.2f} < {line:.2f} (고점 {pk:.2f} × {g})",
                       "신규 진입 중단 · 보유 포지션 손절/익절 유지 · 해제는 팀(TA 판단 후 Developer): live_v6/tools/clear_peak_halt.py")

    def skip(self, sym, reason, detail="", signal_px=None, signal_ms=None):
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
        self._log_skip(sym, reason, detail, signal_px, signal_ms, t=self.meta["skip_log"][-1][0])
        if reason in QUIET_SKIPS and hasattr(self.strategy, "on_entry_skip"):   # no alert: scores to the signal log
            try:
                self.strategy.on_entry_skip(sym, self._sig_side, reason, detail, self.meta["skip_log"][-1][0])
            except Exception as e:  # noqa: BLE001  a log write never blocks trading
                log.error("entry skip log failed: %r", e)

    def cid(self, sym, t_ms) -> str:
        return f"{self.cfg.cid_prefix}{sym.removesuffix('USDT')}{t_ms // 1000}"

    # ───────────────────────── startup ─────────────────────────
    def startup(self):
        self.blocks[STARTUP] = "startup"
        try:
            self.load_rules()
            self._gate_state()
            if not self._schema_lock:
                self.resolve_intents()
            self.reconcile()
            for s in self.cfg.symbols:
                if s not in self.st["pos"] and s not in self.st["unknown"]:
                    self.pace()
                    self.ensure_isolated(s)
            self.startup_leverage()
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
            self.notify(f"▶️ live_v6 시작 · {self.ex!r} · 포지션 {self._open_position_count()}개"
                         + (f" · 기록 없는 포지션 {','.join(self.st['unknown'])}" if self.st["unknown"] else "") + " · "
                         f"{'중단 상태: ' + self.meta['halted'] if self.meta.get('halted') else '진입 가능' if self.entries_allowed() else '진입 차단: ' + ','.join(self.blocks)}")
        except ExchangeError as e:
            log.error("startup failed, entries stay blocked: %s", e)

    def startup_leverage(self):
        """Idempotent config write: every coin without a position gets cfg.startup_leverage (so the first entry does not
        depend on an immediate read-back of a fresh change). Logged per coin; failures only logged (the entry path
        still sets + confirms leverage itself)."""
        lev = self.cfg.startup_leverage
        if not lev:
            return
        try:
            pos = self.x("positions", self.cfg.symbols)
        except ExchangeError as e:
            log.warning("startup leverage: positions read failed: %s", e)
            return
        for s in self.cfg.symbols:
            row = pos.get(s)
            if row is None or self._row_amt(pos, s) != 0 or s in self.st["pos"] or s in self.st["unknown"]:
                log.info("startup leverage %s: position open or unknown, left at %sx", s, None if row is None else row.get("leverage"))
                continue
            was = pos.get(s, {}).get("leverage")
            try:
                if was == lev:
                    log.info("startup leverage %s: already %sx", s, lev)
                    continue
                echoed = self.x("set_leverage", s, lev)
                cfg_lev = self.x("leverage", s)
                log.info("startup leverage %s: %sx -> set response %sx, symbolConfig %sx", s, was, echoed, cfg_lev)
            except ExchangeError as e:
                log.warning("startup leverage %s: %sx -> set %sx failed: %s", s, was, lev, str(e)[:80])

    def load_rules(self):
        info = self.x("exchange_info")
        self.rules = rules_from_info(info, self.cfg.symbols)
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
            row = self.x("positions", self.cfg.symbols).get(sym) or {}
            mt = row.get("margin_type")
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
        self._log_bar_close(T, before, intents)
        self.execute(intents, T)

    def _log_bar_close(self, T, before, intents):
        """One INFO line per completed 4h bar per model: bar open (KST), then symbol=decision (no keys / account data)."""
        if not callable(getattr(self.strategy, "bar_decisions", None)):
            return
        try:
            dec = self.strategy.bar_decisions(T, self, before, intents)
            t_open = datetime.fromtimestamp((T - (self.strategy.decision_interval_ms or H4)) / 1000, KST).strftime("%Y-%m-%d %H:%M")
            log.info("bar_close model=%s bar_open=%s KST %s", self.strategy.name, t_open,
                     " ".join(f"{s}={dec.get(s, 'no_signal')}" for s in self.cfg.symbols))
        except Exception:  # noqa: BLE001  logging must never break the trading loop
            log.exception("bar_close log failed")

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
                    self.skip(sym, "late", f"signal {(self.now_ms() - t) / 1000:.1f}s old > {max_age}s",
                              signal_px=it.get("signal_px"), signal_ms=it.get("model_id") or t)
                    continue
                self.enter(sym, it["stop_dist"], t, model_id=it.get("model_id"), signal_px=it.get("signal_px"),
                           side=int(it.get("side", 1)))

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
                self._track_mark(ev)
                j = self.st["pos"].get(ev.sym)
                sd_ = int(j.get("side", 1)) if j else 1
                thru = (lambda px: ev.price <= px) if sd_ > 0 else (lambda px: ev.price >= px)
                if j and j.get("stop_lost") and not j.get("closing") and thru(D(j["stop_lost"]["px"])):
                    self.lost_stop_breach(ev.sym, ev.price)  # no exchange stop + price through it → reduceOnly close
                elif self.ban_left() > 0:
                    pass                                    # 418: no REST at all; the exchange stop protects
                elif (j and not j.get("closing") and thru(D(j["stop_px"]))
                        and now - self._breach_seen.get(ev.sym, -1e18) >= self.cfg.reconcile_s):
                    self._breach_seen[ev.sym] = now                 # at most one REST check per symbol per 5 s
                    self.breach_check(ev.sym, ev.price, "mark stream")
        elif isinstance(ev, (OrderUpdate, AccountUpdate)):
            self.stop_monitor(ev)                           # TA: stop CANCELED/EXPIRED → replace now (no REST read)
            self._note_exit_order(ev)
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
            self.x("stop", sym, self._cs(j), D(lost["px"]), f"{j['cid']}s{seq}",       # replaced by a qty stop
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
        if self._schema_lock:
            self._lock_hold_alert(sym, "lost_stop_breach", f"mark {mark}")
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
            amt_now = self._row_amt(self.x("positions", self.cfg.symbols), sym)
            if amt_now is None:
                return                                      # missing row is not a confirmed flat
            if amt_now == 0:
                self._dirty = True
                return
        except ExchangeError:
            return                                          # REST reconcile retries in ≤5 s
        if self._schema_lock:
            self._lock_hold_alert(sym, "stop_breach", f"mark {mark} vs {self.st['pos'][sym]['stop_px']} ({source})")
            return
        self.alert("손절가 돌파인데 거래소 손절 미작동 — 이 포지션만 정리",
                   f"{sym} mark {mark} vs 손절 {self.st['pos'][sym]['stop_px']} ({source}) · 다른 포지션 유지")
        self.close(sym, "stop_breach")                      # §8c L1: only THAT position (reduceOnly MARKET)

    # ───────────────────────── entry ─────────────────────────
    def _snapshot_missing(self, pos) -> list[str]:
        """Requested symbols with no row. An incomplete book is not a book the entry limits can trust."""
        if not isinstance(pos, dict):
            return list(self.cfg.symbols)
        return [s for s in self.cfg.symbols if self._row_amt(pos, s) is None]

    def _entry_reread(self, sym, pos, lev, echoed, *, after_set: bool):
        """'' when this re-read is a complete book and leverage checks out. A missing row is a skip reason, not a KeyError.
        `after_set` is the path that just called set_leverage: a missing echo is not a confirmed change."""
        missing = self._snapshot_missing(pos)
        if missing:
            return "snapshot missing " + ",".join(missing)
        row = pos.get(sym) if isinstance(pos, dict) else None
        if not isinstance(row, dict):
            return f"{sym} missing from positions"
        got = row.get("leverage")
        if after_set:
            return self._confirm_leverage(sym, lev, echoed, got)
        return "" if got == lev else f"read-back {got}x"

    def _open_book(self, positions) -> list[dict]:
        out = []
        for s, p in positions.items():
            if isinstance(p, dict) and p.get("amt") not in (None, 0):
                j = self.st["pos"].get(s) or self.st["unknown"].get(s) or {}   # TA R4: unknown positions count too
                out.append({"sym": s, "side": 1 if p["amt"] > 0 else -1,
                            "risk_frac": float(j.get("risk_frac", self.cfg.sizing.risk_pct / 100 * 2))})  # not yet seen → 1%
        return out

    def _dir_capped(self, sym, book, side) -> bool:
        cap = self.cfg.max_same_side
        n = sum(1 for b in book if b["side"] == side)
        if cap and n >= cap:
            self.skip(sym, "dir_cap", f"{n} {'long' if side > 0 else 'short'} open (cap {cap})")
            return True
        return False

    def _confirm_leverage(self, sym, lev: int, echoed, pr_lev) -> str:
        """After POST /fapi/v1/leverage: the new leverage counts only when the set response AND GET /fapi/v1/symbolConfig
        both equal the requested value (positionRisk can lag a successful change: live 2026-10-22 01:39 KST BNBUSDT,
        set 10x OK, positionRisk 20x, symbolConfig 10x). '' = confirmed, else the skip reason. Fail-safe: a failed
        symbolConfig read (timeout / 5xx / 429 / 418 / backoff / rejected / malformed body) = NOT confirmed — this
        method never raises, so the entry flow (and the other coins of the same bar) is not interrupted."""
        cfg_lev, cfg_err = None, ""
        reads = 0
        while echoed == lev and reads < max(1, self.cfg.lev_confirm_reads):
            if reads:
                self.sleep(self.cfg.lev_confirm_wait_s)
            reads += 1
            try:                                        # a FAILED read is not retried (no hammering on 429/418)
                cfg_lev = self.x("leverage", sym)
            except ExchangeError as e:
                cfg_err = f"symbolConfig failed: {str(e)[:70]}"
                break
            except Exception as e:  # noqa: BLE001  malformed response must not escape into execute()
                log.exception("%s symbolConfig read failed", sym)
                cfg_err = f"symbolConfig failed: {type(e).__name__}"
                break
            if cfg_lev == lev:
                break
        cfg_txt = cfg_err or (f"symbolConfig {cfg_lev}x" if cfg_lev is not None else "symbolConfig not read")
        log.warning("%s leverage %sx: set response %sx, positionRisk %sx, %s (reads %d)", sym, lev, echoed, pr_lev, cfg_txt,
                    reads)
        if echoed == lev and cfg_lev == lev:
            return ""
        return f"read-back {pr_lev}x, {cfg_txt} (set response {echoed}x)"

    @staticmethod
    def _cs(j) -> str:
        """Closing side of a journaled position."""
        return "SELL" if int(j.get("side", 1)) > 0 else "BUY"

    def _size_fresh(self, sym, stop_dist: Decimal, book: list, fixed_lev: int | None = None, side: int = 1):
        """Read EVERYTHING the order depends on right now (exchangeInfo filters, leverage bracket, book, mark price,
        wallet/available) and size from it. Nothing is taken from the startup cache or an earlier pass. Any failed
        read → skip `filter_read_failed`, no order. Returns (Sized, account, ref) or None (skip already recorded)."""
        try:
            rules = SymbolRules.from_exchange_info(self.x("exchange_info"), sym)
            brk = self.x("brackets", sym)
            bk = self.x("book", sym)
            ref, bid = (D(bk["ask"]), D(bk["bid"])) if side > 0 else (D(bk["bid"]), D(bk["ask"]))   # short: sells at the bid
            mark = D(self.x("mark_price", sym)) if rules.pct_up is not None else None
            acct = self.x("account")
        except (ExchangeError, KeyError, ArithmeticError, TypeError, ValueError, AttributeError) as e:
            self.skip(sym, "filter_read_failed", f"{type(e).__name__}: {str(e)[:100]}")
            return None
        self.rules[sym], self.brackets[sym] = rules, brk
        # §8e-2 capital: sizing on C0 + realised PnL since start (= the full wallet when capital_fraction = 1, transfers
        # excluded); margin guard: margin in use + new margin never exceeds strategy equity (incl. unrealised)
        cap = self.strategy_equity(acct["wallet"])
        room = self.strategy_equity(acct.get("equity", acct["wallet"])) - D(acct.get("margin_used", 0))
        sz = size_entry(rules, brk, cap, min(D(acct["available"]), room), ref, stop_dist, side, book, self.cfg.sizing,
                        bid=bid, mark=mark, fixed_lev=fixed_lev)
        if sz.skip:
            self.skip(sym, sz.skip, sz.detail)
            if sz.skip == "margin":
                self.alert("증거금 부족으로 진입 건너뜀 — 잔고/계산 점검 필요", f"{sym} {sz.detail}")
            return None
        return sz, acct, ref

    def enter(self, sym, stop_dist: Decimal, T: int, model_id=None, signal_px=None, side: int = 1) -> bool:
        """Entry flow (`_enter`); remembers the signal so a skip on the way is logged with its signal price."""
        self._sig = (sym, signal_px, model_id or T)
        self._sig_side = side
        try:
            return self._enter(sym, stop_dist, T, model_id=model_id, signal_px=signal_px, side=side)
        finally:
            self._sig, self._sig_side = None, 1

    def _enter(self, sym, stop_dist: Decimal, T: int, model_id=None, signal_px=None, side: int = 1) -> bool:
        if side < 0 and not self.cfg.enable_short:
            self.skip(sym, "short_disabled", "short entries are off (enable_short=False)")
            return False
        if not self.entries_allowed():
            if self.meta.get("peak_dd") and not self.meta.get("halted") and not self.blocks:
                self.skip(sym, "peak_dd", str(self.meta["peak_dd"]))
            else:
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
            missing = self._snapshot_missing(pos)
            if missing:                                     # any hole: refuse every new entry this tick
                self.skip(sym, "positions_incomplete", f"snapshot missing {','.join(missing)}")
                return False
            amt0 = self._row_amt(pos, sym)
            if amt0 is None or amt0 != 0 or sym in self.st["pos"]:
                log.warning("entry %s refused: position %s (no averaging)", sym, "unknown" if amt0 is None else amt0)
                return False
            oo = self.x("open_orders", sym)
            if any(not (o["close_position"] or o["reduce_only"]) for o in oo):
                self.block(MISMATCH, f"{sym} open entry order before entry", "대조 불일치 — 신규 진입 중단")
                return False
            for o in oo:                                    # our own leftover stops must never touch a new position
                if str(o["client_id"]).startswith(self.cfg.cid_prefix):
                    self.x("cancel", sym, o)
            row0 = pos.get(sym) or {}
            if row0.get("margin_type") != "ISOLATED" and not self.ensure_isolated(sym):
                self.skip(sym, "margin_mode", "ISOLATED read-back failed")
                return False
        except ExchangeError as e:
            log.error("entry %s pre-check failed: %s", sym, e)
            return False
        book = self._open_book(pos)
        if len(book) >= self.cfg.max_positions:             # ptp-short: gate order max_positions -> dir_cap -> risk caps -> margin
            self.skip(sym, "max_positions", f"{len(book)} open")
            return False
        if self._dir_capped(sym, book, side):
            return False
        got = self._size_fresh(sym, stop_dist, book, side=side)
        if got is None:
            return False
        sz, acct, ref = got
        # leverage set + read-back; the same fresh positions read is the FINAL gate right before the order:
        # no averaging, ISOLATED, max positions, total open risk ≤ 2.5% (TA: enforced at order placement)
        try:
            row = pos.get(sym) if isinstance(pos, dict) else None
            lev_now = row.get("leverage") if isinstance(row, dict) else None
            if lev_now is None:
                err, pos = f"{sym} missing from positions", None
            elif lev_now != sz.lev:                         # skip the call when already set (entry latency)
                echoed = self.x("set_leverage", sym, sz.lev)
                pos = self.x("positions", self.cfg.symbols)
                err = self._entry_reread(sym, pos, sz.lev, echoed, after_set=True)
            else:
                pos = self.x("positions", self.cfg.symbols)
                err = self._entry_reread(sym, pos, sz.lev, None, after_set=False)
        except ExchangeError as e:
            err, pos = str(e)[:80], None
        if err:
            reason = "positions_incomplete" if str(err).startswith("snapshot missing") else "leverage"
            self.skip(sym, reason, f"set {sz.lev}x failed: {err}" if reason == "leverage" else err)
            if reason == "leverage":
                self.alert(f"레버리지 {sz.lev}x 설정 실패 — 진입 건너뜀", f"{sym} {err}")
            return False
        book = self._open_book(pos) if pos else []
        placed = self._row_amt(pos, sym) if pos else None
        row = pos.get(sym) if isinstance(pos, dict) else None
        if pos is None or placed is None or placed != 0 or not isinstance(row, dict):
            log.warning("entry %s refused at placement: position %s", sym, "unknown" if placed is None else placed)
            return False
        if row.get("margin_type") != "ISOLATED":
            self.skip(sym, "margin_mode", f"read-back {row.get('margin_type')}")
            return False
        if len(book) >= self.cfg.max_positions:
            self.skip(sym, "max_positions", f"{len(book)} open")
            return False
        if self._dir_capped(sym, book, side):
            return False
        # SECOND PASS right before the order: price, ATR-based stop distance (as passed in), wallet, available balance,
        # exchangeInfo and brackets are read again and qty / minNotional / margin / bracket are recomputed with the
        # CONFIRMED leverage; nothing computed before the leverage call is reused.
        got = self._size_fresh(sym, stop_dist, book, fixed_lev=sz.lev, side=side)
        if got is None:
            return False
        sz, acct, ref = got
        if sum(b["risk_frac"] for b in book) + sz.risk_frac > sz.cap_frac + 1e-12:
            self.skip(sym, sz.cap_label, f"open {sum(b['risk_frac'] for b in book):.4%} + {sz.risk_frac:.4%}")
            return False
        cid = self.cid(sym, T)
        intent = {"sym": sym, "cid": cid, "T": T, "side": side, "model_id": model_id if model_id is not None else T,
                  "signal_px": str(signal_px) if signal_px is not None else None, "stop_dist": str(stop_dist), "ref": str(ref), "qty": str(sz.qty),
                  "lev": sz.lev, "mmr": sz.mmr, "risk_frac": sz.risk_frac, "risk_pct_used": sz.risk_pct_used,
                  "wallet": str(acct["wallet"]), "path": sz.path, "q0": str(sz.q0), "loss_frac": sz.loss_frac}
        # PRE-ARM: a reduceOnly STOP_MARKET for the planned qty is live on the exchange BEFORE the entry is sent, so
        # there is no instant between fill and stop without exchange-side protection (closePosition stops cannot be
        # placed without a position: -4509). Not confirmed → no entry.
        pre = self._prearm(sym, sz.stop_px, sz.qty, cid, side)
        if pre is None:
            self.skip(sym, "stop_prearm", f"protective stop {sz.stop_px} not confirmed → entry not sent")
            return False
        intent["prearm"] = pre["id"]
        intent.update(prearm_ms=self.now_ms(), order_ms=self.now_ms(),       # live log only (sent right after the save)
                      open_risk_after=sum(b["risk_frac"] for b in book) + sz.risk_frac,
                      same_side_open=sum(1 for b in book if b["side"] == side))
        self.st["intents"][cid] = intent
        self.save()                                         # journal the intent BEFORE sending
        try:
            o = self.submit_market(sym, "BUY" if side > 0 else "SELL", sz.qty, cid, reduce_only=False)
        except OrderRejected as e:                          # DEFINITIVE rejection: nothing was opened → undo everything
            self.st["intents"].pop(cid, None)
            self.save()
            self._cancel_quiet(sym, pre)                    # pre-armed stop must not outlive the rejected entry
            self.skip(sym, "entry_rejected", f"{sz.qty} @ {ref}: {str(e)[:120]}")
            self.alert("진입 주문 거절 — 선행 손절 취소, 포지션·기록 없음", f"{sym} {sz.qty}: {str(e)[:100]}")
            return False
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
        up = self._upgrade_stop(sym, j, pre)                # closePosition at the fill-based stop, THEN cancel pre-arm
        try:                                                 # late fills after a partial: exchange qty is the truth
            pos = self.x("positions", self.cfg.symbols)
            amt = self._row_amt(pos, sym)
            if amt not in (None, 0) and abs(amt) != D(j["qty"]):
                j["qty"] = j["entry_qty"] = str(abs(amt))
                self.save()
        except ExchangeError:
            pass
        if up == "rejected":                                # would-trigger: a stop there cannot rest → flatten now
            self.alert("진입 체결 후 손절 거절 — 전량 청산", f"{sym} {j['qty']} · 손절 {j['stop_px']} 거절/즉시발동 → reduceOnly 전량 청산")
            if not self.close(sym, "stop_rejected_after_fill"):
                log.error("%s flatten after rejected stop not complete — close() keeps retrying via reconcile", sym)
            return False
        if up == "failed":                                  # item 2 budget spent and no live stop (pre-arm included)
            self._give_up_protection(sym, j, "진입 손절", "재시도 한도 초과")
            return False
        # partial fill: the unfilled rest is NOT chased; a filled part below min notional is closed at once (no dust)
        if D(j["qty"]) * D(j["entry_px"]) < self.rules[sym].min_notional:
            self.notify(f"⚪ {sym} 부분 체결 {j['qty']} (최소 주문금액 미만) → 즉시 정리")
            self.close(sym, "dust_entry")
            return False
        part = f" (부분 체결 {o['executed_qty']}/{sz.qty}, 나머지 취소·추격 안 함)" if o["executed_qty"] < sz.qty else ""
        if sz.path == "qty_floor":
            fl = (f"qty_floor {sym}: q0 {sz.q0} < 거래소 최소 → 최소수량 {sz.qty} · 손절+수수료+슬리피지 위험 "
                  f"{sz.loss_frac:.2%} (지갑 대비, 한도 {self.cfg.sizing.min_order_loss_cap:.0%})")
            log.info(fl)
            part += f"\n⚠️ {fl}"
            fm = self.meta.setdefault("floor_log", [])
            fm.append([self.now_ms(), sym])
            del fm[:-200]
            self.save()
        # display only: ACTUAL risk = loss to the stop incl. fees/slippage (sizing.py loss model) ÷ wallet at entry.
        # Any failure → the configured label + one warning; the display never stops or delays the trade flow.
        try:
            qf, pf, wf = D(j["qty"]), D(j["entry_px"]), D(j["wallet_at_entry"])
            if not wf > 0:
                raise ValueError(f"wallet_at_entry {wf}")
            loss = side * (pf - D(j["stop_px"])) * qf + qf * pf * (2 * TAKER_FEE + D(self.cfg.sizing.entry_slippage)
                                                             + D(self.cfg.sizing.stop_slippage))
            act = f"{loss / wf * 100:.2f}"
        except Exception as e:  # noqa: BLE001  display only: must never stop or delay the entry
            act = f"{sz.risk_pct_used}"
            log.warning("entry alert %s: actual risk display failed (%r) → configured %s%%", sym, e, act)
        if self.cfg.take_profit:
            self._place_tps(sym, j)
        if not self._position_open(sym):
            return False
        tp = j.get("tp") or {}
        if tp.get("tp1"):
            part += (f"\n익절 TP1 {tp['tp1']} ({tp['q1']})"
                     + (f" · TP2 {tp['tp2']} ({tp['q2']})" if tp.get("tp2") else " · 이후 추적 손절"))
        elif tp.get("full") and tp.get("tp3"):
            part += f"\n익절 +3R {tp['tp3']} (전량 {tp['q3']})"
        self.notify(f"🟢 진입 {sym} {'롱' if side > 0 else '숏'} · 수량 {j['qty']} · 체결가 {j['entry_px']}{part}\n"
                     f"손절 {j['stop_px']} · {sz.lev}x · 위험 {D(j['risk_usdt']):.4f} USDT ({act}%)",
                     kind="entry", event_ms=intent.get("model_id") or intent.get("T"))
        log.info("entered %s " + ("long" if side > 0 else "short") + " qty %s fill %s stop %s lev %sx risk %s USDT (%s%%)", sym, j["qty"], j["entry_px"], j["stop_px"],
                 sz.lev, f"{D(j['risk_usdt']):.4f}", sz.risk_pct_used)
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
        side = int(intent.get("side", 1))
        stp = stop_price(self.rules[sym], fill, side, sd)    # re-placed from the FILL at the same distance (TA)
        j = {"cid": intent["cid"], "side": side, "qty": str(qty), "entry_qty": str(qty), "entry_px": str(fill),
             "stop_px": str(stp), "stop_px_entry": str(stp),
             "stop_dist": str(sd), "risk_usdt": str(abs(fill - stp) * qty), "risk_frac": intent["risk_frac"],
             "lev": intent["lev"], "mmr": intent["mmr"], "model_entry_open": intent.get("model_id", intent["T"]), "opened_ms": self.now_ms(),
             "entry_order_id": o["id"], "entry_ref": intent["ref"], "wallet_at_entry": intent["wallet"],
             "planned_qty": intent["qty"], "stop_seq": 0, "exit_seq": 0}
        j.update({k: intent.get(k) for k in LOG_INTENT_KEYS},                 # live log only: copied at entry
                 signal_ms=intent.get("model_id", intent["T"]), entry_fill_ms=o.get("update_time") or None)
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
        if reduce_only and self._schema_lock:
            log.warning("%s reduceOnly market %s not sent: schema lock", sym, cid)
            return None
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

    def _close_position_stop(self, j, orders):
        """A closePosition STOP on the exit side. A closePosition take-profit is not a stop."""
        cs = self._cs(j)
        return next((o for o in orders if o.get("close_position") and (o.get("type") or "").startswith("STOP")
                     and o.get("side") == cs), None)

    def _tp_fail_once(self, sym, what, err):
        """One alert per order. An earlier tranche must not hide a later one. Never a market close."""
        key = (sym, str(what))
        if key in self._tp_fail_alerted:
            return
        self._tp_fail_alerted.add(key)
        self.alert(f"보호 점검 보류 — {sym}", f"{what} · 익절 거절 · 손절 유지 · {err}")

    def _is_orphan_prearm(self, o) -> bool:
        """Bot pre-arm reduceOnly stop (`<cid>p`) whose entry intent no longer exists (rejected / resolved) and that is not a journaled position's stop."""
        cid = str(o.get("client_id") or "")
        return (cid.startswith(self.cfg.cid_prefix) and cid.endswith("p") and bool(o.get("reduce_only"))
                and not o.get("close_position") and cid[:-1] not in self.st["intents"])

    def _cancel_quiet(self, sym, o):
        try:
            self.x("cancel", sym, o)
        except ExchangeError as e:
            log.error("%s cancel %s failed (reconcile retries): %s", sym, o.get("client_id"), e)

    def _prearm(self, sym, stop_px, qty, cid, side: int = 1) -> dict | None:
        try:
            return self.x("stop", sym, "SELL" if side > 0 else "BUY", stop_px, f"{cid}p", qty=qty)
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
        is confirmed (new before old). Failures retry at 1s, 3s, 10s with an alert each time. If that budget ends
        and the pre-arm still protects the qty, it stays. Otherwise the caller market-closes. WouldTrigger (the
        price is already through the stop) returns 'rejected' so the caller closes at once.
        Returns 'ok' | 'kept' | 'rejected' | 'failed'."""
        amt = self._signed_qty(j)
        last = "closePosition stop not confirmed"
        rejected = False
        saw_4130 = False
        for i, delay in enumerate((*PROTECT_RETRY_S, None)):
            seq = int(j.get("stop_seq", 0))
            j["stop_seq"] = seq + 1
            self.save()
            cid_s = f"{j['cid']}s{seq}"
            try:
                self.x("stop", sym, self._cs(j), D(j["stop_px"]), cid_s)
                j["stop_cid"] = cid_s                       # accepted: later fills can find this id after seq grows
                self.save()
            except WouldTrigger:
                return "rejected"
            except OrderRejected as e:
                if getattr(e, "code", None) == -4130:
                    saw_4130 = True
                    last = str(e)
                    log.error("%s closePosition stop attempt %d already present (-4130)", sym, i + 1)
                    self._stop_covers(sym, j)                # confirm before any alert
                    try:
                        oo = self.x("open_orders", sym)
                    except ExchangeError as ex:
                        last = str(ex)
                        oo = None
                    cp = self._close_position_stop(j, oo) if oo is not None else None
                    if cp:
                        self._release_cp_hold(sym)
                        j["stop_px"] = str(cp["stop_price"])
                        j["stop_cid"] = cp.get("client_id")
                        j.update(stop_confirmed_ms=self.now_ms(), stop_px_entry=j.get("stop_px_entry") or j["stop_px"])
                        self._cancel_quiet(sym, pre)
                        self.save()
                        return "ok"
                    if sym not in self._cp_hold:
                        self.alert(f"보호 점검 보류 — {sym}", "진입 손절 · -4130 손절 존재 · 조회와 불일치 · 유지")
                    self._note_cp_hold(sym)                 # same hold as a missing-stop -4130: stop POSTing
                    break                                   # one -4130 is enough; do not POST s{n} again
                else:
                    rejected = True
                    last = str(e)
                    log.error("%s closePosition stop attempt %d rejected: %s", sym, i + 1, e)
            except ExchangeError as e:
                last = str(e)
                log.error("%s closePosition stop attempt %d: %s", sym, i + 1, e)
            try:
                oo = self.x("open_orders", sym)
                cp = self._close_position_stop(j, oo)
                if cp:
                    j["stop_px"] = str(cp["stop_price"])
                    j["stop_cid"] = cp.get("client_id")
                    j.update(stop_confirmed_ms=self.now_ms(), stop_px_entry=j["stop_px"])   # live log only
                    self._cancel_quiet(sym, pre)
                    self.save()
                    return "ok"
            except ExchangeError as e:
                last = str(e)
            if delay is not None:
                self.alert("보호 주문 실패 — 재시도",
                           f"{sym} 손절 · {i + 1}회 실패 · {delay:g}초 후 재시도 · {last}")
                self.sleep(delay)
        try:
            oo = self.x("open_orders", sym)
        except ExchangeError:
            if not j.get("stop_px_entry"):
                j["stop_px_entry"] = str(j["stop_px"])      # R is the initial stop, even if this book stayed unread
                self.save()
            return "kept"                                  # unknown book: do not flatten a confirmed pre-arm or a landed -4130
        if self.find_stop(amt, oo) or saw_4130:
            if self.find_stop(amt, oo):
                self._release_cp_hold(sym)                  # a covering stop is visible: the hold may alert again
            log.warning("%s keeps the protective stop %s", sym, pre["stop_price"])
            j["stop_px"] = str(pre["stop_price"])
            j.update(stop_confirmed_ms=j.get("prearm_ms"), stop_px_entry=j["stop_px"])  # live log only
            self.save()
            self._dirty = True                              # reconcile re-verifies (qty ≥ position) right away
            return "kept"                                   # pre-arm or -4130 covers the qty; a bare reject does not flatten it
        if rejected:
            return "failed"                                 # book was read and nothing covers the filled qty
        return "failed"

    # ───────────────────────── take profit / breakeven (qrmtf) ─────────────────────────
    def _tp_levels(self, sym, j):
        s, rules = int(j.get("side", 1)), self.rules[sym]
        e = D(j["entry_px"])
        r = abs(e - D(j.get("stop_px_entry") or j["stop_px"]))
        rnd = "up" if s > 0 else "down"                           # TP never closer than k·R
        qty = D(j["qty"])
        q1 = rules.floor_qty(qty * D(str(self.cfg.tp1_frac)))
        if q1 < rules.order_min_qty or q1 >= qty or (qty - q1) < rules.order_min_qty:
            q1 = Decimal(0)                                        # cannot split → legacy TP2 on the full qty; E uses +3R
        return (rules.price(e + s * r * D(str(self.cfg.tp1_r)), rnd), q1,
                rules.price(e + s * r * D(str(self.cfg.tp2_r)), rnd) if self.cfg.tp2_r else None, qty - q1)

    def _position_open(self, sym) -> bool:
        j = self.st["pos"].get(sym)
        return isinstance(j, dict) and not j.get("closing")

    def _runner_due(self, j) -> bool:
        """Scheme E only (no tp2_r). Legacy keeps its +2R TP2 and never gets this runner."""
        if self.cfg.tp2_r:
            return False
        tp = j.get("tp") or {}
        return bool(tp.get("full") or (j.get("tp1_done") and tp.get("tp1")))

    def _runner_px(self, sym, j) -> Decimal:
        """entry ± 3R. R is the same initial distance TP1 used (stop_px_entry), not the trailed stop."""
        s = int(j.get("side", 1))
        e = D(j["entry_px"])
        r = abs(e - D(j.get("stop_px_entry") or j["stop_px"]))
        return self.rules[sym].price(e + s * r * D(3), "up" if s > 0 else "down")

    def _bind_runner(self, sym, j, amt):
        if not self._runner_due(j):
            return
        tp = j.setdefault("tp", {})
        if not tp.get("tp3"):
            tp["tp3"] = str(self._runner_px(sym, j))
            tp["q3"] = str(abs(amt))
            self.save()

    def _signed_qty(self, j) -> Decimal:
        q = D(j.get("qty") or 0)
        return q if int(j.get("side", 1)) > 0 else -q

    def _qty_vs(self, sym, baseline: Decimal) -> str:
        """'same' | 'shrunk' | 'unknown'. A missing row or a failed read is unknown, never flat."""
        try:
            pos = self.x("positions", self.cfg.symbols)
        except ExchangeError:
            return "unknown"
        amt = self._row_amt(pos, sym)
        if amt is None:
            return "unknown"
        if amt == 0 or (baseline > 0 and abs(amt) < baseline):
            return "shrunk"
        return "same"

    def _cid_state(self, sym, cid) -> str:
        """'yes' the id is on the open book. 'filled' or 'terminal' (cancelled / expired)
        from the algo status. 'unknown' when that read fails or the book is the empty
        hold snapshot. 'no' only when a successful read shows neither a live nor a finished order."""
        try:
            oo = self.x("open_orders", sym)
        except ExchangeError:
            return "unknown"
        if any(o.get("client_id") == cid for o in oo):
            return "yes"
        empty_hold = not oo and sym in self._cp_hold
        try:
            st = self.x("algo_order", sym, cid)
        except ExchangeError:
            return "unknown"
        if not isinstance(st, dict):
            return "no"                                 # this id was never placed, even if the hold book is empty
        status = str(st.get("status") or "").upper()
        executed = D(st.get("executed_qty") or 0)
        if status in {"FILLED", "FINISHED"}:
            return "filled" if executed > 0 else "terminal"
        if status in {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}:
            return "terminal"
        if empty_hold:
            return "unknown"                            # a record exists; the empty snapshot can hide it
        return "no"                                     # NEW but not on a real book: the working order is gone

    def _tp_cid(self, j, which) -> str:
        """Client id of the take-profit we currently mean. A replaced id wins over the original."""
        stored = (j.get("tp_cids") or {}).get(which)
        return str(stored or f"{j['cid']}{which}")

    def _tp_fill_cids(self, j, which) -> list:
        base = f"{j['cid']}{which}"
        live = self._tp_cid(j, which)
        return [live] if live == base else [live, base]

    def _dup_paused(self, sym, what) -> bool:
        return self.clock() < self._dup_retry_at.get((sym, str(what)), 0)

    def _note_dup_unknown(self, sym, what):
        """-4116 but the book cannot say whether that id is still live. One alert, no close,
        and the next look is the 1-minute reconcile, not the next 5s tick."""
        key = (sym, str(what))
        self._dup_retry_at[key] = self.clock() + PROTECT_AUDIT_S
        if key in self._dup_unknown:
            return
        self._dup_unknown.add(key)
        self.alert(f"보호 점검 보류 — {sym}", f"{what} · -4116 주문 상태 불명 · 유지")

    def _clear_dup_unknown(self, sym, what):
        key = (sym, str(what))
        self._dup_unknown.discard(key)
        self._dup_retry_at.pop(key, None)

    def _note_filled_tp(self, sym, j, what):
        """The take-profit client id already filled. Book it; do not send another."""
        which = str(what).split()[-1]
        target = self._stage_qty(sym, j, which, 0)
        if target > 0 and self._got(j, which) < target:
            return
        if which == "t1" and not j.get("tp1_done"):
            try:
                amt = self._row_amt(self.x("positions", self.cfg.symbols), sym)
            except ExchangeError:
                amt = None
            if amt not in (None, 0):
                j.update(tp1_done=True, qty=str(abs(amt)))
            else:
                j["tp1_done"] = True
            self.save()
            return
        if which == "t2" and not j.get("tp2_done"):
            j["tp2_done"] = True
            self.save()
            return
        if which == "t3" and not j.get("tp3_done"):
            j["tp3_done"] = True
            if not j.get("exit_fill"):
                j["exit_fill"] = "take_profit"
            self.save()

    def _spent_is_unbooked_fill(self, sym, j, which) -> bool:
        """True only when this stage's ledger already holds its target. Position size is not a fill."""
        for cid in self._tp_fill_cids(j, which):
            self._record_stage_order(sym, j, which, cid)
        target = self._stage_qty(sym, j, which, 0)
        return target > 0 and self._got(j, which) >= target

    def _bump_tp_cid(self, j, which) -> str:
        """Next take-profit client id. The spent `{cid}t1` / `t2` / `t3` is not sent again."""
        n = int((j.get("tp_try") or {}).get(which, 0)) + 1
        j.setdefault("tp_try", {})[which] = n
        new = f"{j['cid']}{which}x{n}"
        j.setdefault("tp_cids", {})[which] = new
        self.save()
        return new

    def _mint_stop(self, sym, j):
        """Next stop client id, the same bump every other re-place uses."""
        seq = int(j.get("stop_seq", 0))
        j["stop_seq"] = seq + 1
        cid = f"{j['cid']}s{seq}"
        self.save()

        def place(cid=cid):
            self.x("stop", sym, self._cs(j), D(j["stop_px"]), cid)
            j["stop_cid"] = cid                         # only a stop the exchange accepted
            self.save()

        return cid, place

    def _stop_covers(self, sym, j) -> str:
        """'yes' | 'no' | 'unknown' from a fresh per-symbol open-order read."""
        try:
            oo = self.x("open_orders", sym)
        except ExchangeError:
            return "unknown"
        return "yes" if self.find_stop(self._signed_qty(j), oo) else "no"

    def _give_up_protection(self, sym, j, what, err) -> bool:
        """Retries exhausted. Market-close only a known nonzero row that has not shrunk.
        A missing row, a failed read, a flat row, or a partial fill is not a flatten."""
        self._protect_close_failed = False
        try:
            pos = self.x("positions", self.cfg.symbols)
        except ExchangeError as e:
            self.alert(f"보호 주문 실패 — {sym} 청산 보류", f"{what} · 포지션 조회 실패 · 손절·익절 유지 · {e}")
            return False
        amt = self._row_amt(pos, sym)
        if amt is None:
            self.alert(f"보호 주문 실패 — {sym} 청산 보류", f"{what} · 포지션 응답에 없음 · 손절·익절 유지 · {err}")
            return False
        baseline = abs(D(j.get("qty") or 0))
        if amt == 0 or (baseline > 0 and abs(amt) < baseline):
            return False                                    # flat or partial fill: next reconcile books it
        if self._schema_lock:
            self._lock_hold_alert(sym, "protection_failed", f"{what} · {err}")
            return False
        self.alert(f"보호 주문 실패 — {sym} 시장가 청산", f"{what} · reduceOnly MARKET · {err}")
        self._protect_close_failed = not bool(self.close(sym, "protection_failed"))
        return False

    def _on_4130(self, sym, j, what) -> bool:
        """A closePosition stop already exists. A visible one is success.
        Otherwise hold and do not market-close."""
        cover = self._stop_covers(sym, j)
        if cover == "yes":
            self._release_cp_hold(sym)
            return True
        if sym not in self._cp_hold:
            self.alert(f"보호 점검 보류 — {sym}", f"{what} · -4130 손절 존재 · 조회와 불일치 · 유지")
        self._note_cp_hold(sym)
        return False

    def _arm_protection(self, sym, j, what, cid, place, renew=None, once=False) -> bool:
        """Place `place()`. On failure alert and retry at 1s, 3s, 10s. Still failing → reduceOnly market close + 🚨.
        WouldTrigger propagates so the caller can close just the qty that is already through. -4116 is success only
        when that client id is still on the open book. A cancelled or expired id is not placed: `renew` mints the
        next id and the remaining attempts send it. A filled take-profit is booked, not sent again. An unreadable
        book keeps the position and is re-checked on the next 1-minute pass. -4130 means a closePosition stop is
        already there. A position that shrinks or disappears between tries is left for the next reconcile.
        An unreadable position is unknown: stop, and do not flatten. A take-profit is never a reason to close."""
        if self._dup_paused(sym, what):
            return False
        cur_cid, cur_place = cid, place
        self._protect_close_failed = False
        baseline = abs(D(j.get("qty") or 0))
        last = None
        steps = (None,) if once else (*PROTECT_RETRY_S, None)
        for i, delay in enumerate(steps):
            seen = self._qty_vs(sym, baseline) if baseline > 0 else "same"
            if seen == "unknown":
                self.alert(f"보호 주문 실패 — {sym} 청산 보류", f"{what} · 포지션 조회 불가 · 손절·익절 유지")
                return False
            if seen == "shrunk":
                if delay is not None:
                    self.sleep(delay)                       # finish the scheduled gaps; do not send another order
                    continue
                return False
            try:
                cur_place()
                self._clear_dup_unknown(sym, what)
                return True
            except WouldTrigger:
                raise
            except OrderRejected as e:
                code = getattr(e, "code", None)
                if code == -4116:
                    state = self._cid_state(sym, cur_cid)
                    which = str(what).split()[-1] if str(what).startswith("익절") else ""
                    if state == "yes":
                        self._clear_dup_unknown(sym, what)
                        return True                     # this id is on the book: do not send it again
                    if state == "unknown":
                        self._note_dup_unknown(sym, what)   # unreadable: not placed, no close, one alert
                        return False
                    if which and self._spent_is_unbooked_fill(sym, j, which):
                        self._note_filled_tp(sym, j, what)
                        self._clear_dup_unknown(sym, what)
                        return True                     # fill already in the position: do not send it again
                    if renew is not None and state in {"terminal", "filled", "no"}:
                        cur_cid, cur_place = renew()    # spent id: next client id, same attempt budget
                        last = e
                        if delay is None:               # the only step was this renew: send the new id now
                            try:
                                cur_place()
                                self._clear_dup_unknown(sym, what)
                                return True
                            except WouldTrigger:
                                raise
                            except OrderRejected as e2:
                                if getattr(e2, "code", None) == -4130:
                                    return self._on_4130(sym, j, what)
                                last = e2
                            except ExchangeError as e2:
                                last = e2
                                if not str(what).startswith("익절"):
                                    self.alert(f"보호 주문 실패 — {sym} 청산 보류",
                                               f"{what} · 주문 조회 불가 · 유지 · {e2}")
                                    return False
                            if str(what).startswith("익절"):
                                self._tp_fail_once(sym, what, last)
                                return False
                            return self._give_up_protection(sym, j, what, last)
                    else:
                        self._note_dup_unknown(sym, what)
                        return False
                elif code == -4130:
                    return self._on_4130(sym, j, what)
                else:
                    last = e
                    state = self._cid_state(sym, cur_cid)
                    if state == "yes":
                        return True
                    if state == "unknown":
                        if str(what).startswith("익절"):
                            self._tp_fail_once(sym, what, e)
                        else:
                            self.alert(f"보호 주문 실패 — {sym} 청산 보류", f"{what} · 주문 조회 불가 · 유지 · {e}")
                        return False
            except ExchangeError as e:
                last = e
                state = self._cid_state(sym, cur_cid)
                if state == "yes":
                    return True
                if state == "unknown":
                    if str(what).startswith("익절"):
                        self._tp_fail_once(sym, what, e)
                    else:
                        self.alert(f"보호 주문 실패 — {sym} 청산 보류", f"{what} · 주문 조회 불가 · 유지 · {e}")
                    return False
            if delay is not None:
                if not str(what).startswith("익절"):
                    self.alert("보호 주문 실패 — 재시도",
                               f"{sym} {what} · {i + 1}회 실패 · {delay:g}초 후 재시도 · {last}")
                self.sleep(delay)
        if str(what).startswith("익절"):
            self._tp_fail_once(sym, what, last)            # a rejected take-profit never market-closes
            return False
        return self._give_up_protection(sym, j, what, last)

    def _arm_stop(self, sym, j, amt) -> bool:
        """One closePosition STOP at the journal stop. False → the position was closed or the read stayed unknown."""
        self._armed_now.add(sym)
        if self._dup_paused(sym, "손절"):
            return False
        cid, place = self._mint_stop(sym, j)
        try:
            return self._arm_protection(sym, j, "손절", cid, place, renew=lambda: self._mint_stop(sym, j))
        except WouldTrigger:
            log.error("%s stop %s would trigger — market close", sym, D(j["stop_px"]))
            self._give_up_protection(sym, j, f"손절 {j['stop_px']} 즉시 발동", "would trigger")
            return False

    def _place_tp(self, sym, j, which, px, qty, working_type="CONTRACT_PRICE") -> bool:
        if self._schema_lock:
            return False
        """reduceOnly TAKE_PROFIT_MARKET. Price already beyond it → one alert, no market close. TP1 and TP2 stay
        on CONTRACT_PRICE (TA 2026-11-02). The +3R runner (which='t3') is MARK_PRICE. A failed placement is retried
        (policy v1). A live order with this client id is left as-is. A cancelled id is sent again under the next id."""
        what = f"익절 {which}"
        key = (sym, what)
        if self._dup_paused(sym, what) or self.clock() < self._tp_retry_at.get(key, 0):
            return False
        if (which == "t1" and j.get("tp1_done")) or (which == "t2" and j.get("tp2_done")) \
                or (which == "t3" and j.get("tp3_done")):
            return True
        rules = self.rules[sym]
        s = int(j.get("side", 1))
        px = rules.price(D(px), "up" if s > 0 else "down")
        qty = rules.floor_qty(D(qty))
        if qty <= 0:
            self._tp_fail_once(sym, what, "수량 0")
            return False
        pending = self._settle_pending_market(sym, j, which, qty)
        if pending == "done":
            return True
        if pending == "wait":
            return False
        cid = self._tp_cid(j, which)
        state = self._cid_state(sym, cid)
        if state == "yes":
            self._clear_dup_unknown(sym, what)
            return True                                 # already working: the tick does not POST
        if state == "unknown":
            try:                                        # a failed read alerts once; a hidden hold order does not
                self.x("open_orders", sym)
                self.x("algo_order", sym, cid)
            except ExchangeError:
                self._note_dup_unknown(sym, what)       # not placed, no close
            return False
        if state in {"terminal", "filled"}:
            for cid_i in self._tp_fill_cids(j, which):
                self._record_stage_order(sym, j, which, cid_i)
        try:
            fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            fresh = None
        sell = self._slice_sell(sym, j, which, fresh)
        if state in {"terminal", "filled"} and self._spent_is_unbooked_fill(sym, j, which):
            self._note_filled_tp(sym, j, what)
            self._clear_dup_unknown(sym, what)
            return True                                 # booked fill: no second order of this tranche
        if sell is None:
            self._tp_fail_once(sym, what, "포지션 조회 실패 · 기존 손절 유지")
            return False
        if sell <= 0:
            self._tp_fail_once(sym, what, "남은 수량 최소 미달")
            return False
        if fresh not in (None, 0) and abs(fresh) < abs(D(j.get("qty") or 0)):
            j["qty"] = str(abs(fresh))                   # a smaller read is the position; a larger one can be stale
            self.save()
        qty = sell
        if state in {"terminal", "filled"}:
            cid = self._bump_tp_cid(j, which)           # cancelled / expired: one POST under a new id

        def place(cid=cid):
            self.x("take_profit", sym, self._cs(j), px, cid, qty, working_type=working_type)

        def renew():
            new = self._bump_tp_cid(j, which)

            def place_new(cid=new):
                self.x("take_profit", sym, self._cs(j), px, cid, qty, working_type=working_type)

            return new, place_new

        try:
            ok = self._arm_protection(sym, j, what, cid, place, renew=renew, once=key in self._tp_cooled)
        except WouldTrigger:
            ok = self._on_tp_would_trigger(sym, j, which, px, qty, working_type)
        if ok:
            self._tp_cooled.discard(key)
            self._tp_retry_at.pop(key, None)
            rearm = j.get("tp_rearm")
            if isinstance(rearm, dict) and rearm.pop(which, None) is not None:
                self.save()
        else:
            self._tp_cooled.add(key)
            self._tp_retry_at[key] = self.clock() + PROTECT_AUDIT_S
        return ok

    def _decision_px(self, sym, working_type) -> Decimal:
        """CONTRACT_PRICE uses the last trade. A MARK_PRICE runner uses the mark.
        Neither decision uses the book bid."""
        if working_type == "MARK_PRICE":
            return D(self.x("mark_price", sym))
        return D(self.x("last_price", sym))

    @staticmethod
    def _executed_qty(order) -> Decimal:
        if not isinstance(order, dict):
            return Decimal(0)
        return D(order.get("executed_qty") or 0)

    def _book_realized_tp(self, j, which, left: Decimal):
        """Book a slice whose position re-read is already smaller. `left` is that re-read."""
        if which == "t1":
            j["tp1_done"] = True
            if left > 0:
                j["qty"] = str(left)
        elif which == "t2" and not j.get("tp2_done"):
            j["tp2_done"] = True
        elif which == "t3" and not j.get("tp3_done"):
            j["tp3_done"] = True
        if which == "t3" or left <= 0:
            if not j.get("exit_fill"):
                j["exit_fill"] = "take_profit"
        self.save()

    def _shrink_booked(self, sym, j, which, before) -> str:  # noqa: ARG002
        """'filled' only from the stage ledger. A position shrink is not a fill."""
        what = f"익절 {which}"
        try:
            fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            fresh = None
        if fresh is None:
            self._tp_fail_once(sym, what, "포지션 조회 실패 · 추가 주문 없음")
            return "unknown"
        target = self._stage_qty(sym, j, which, 0)
        if target > 0 and self._got(j, which) >= target:
            self._book_realized_tp(j, which, abs(fresh))
            return "filled"
        return "same"

    def _book_fill(self, sym, j, which, before, executed) -> bool:
        """A FILLED realization. Use the position re-read when it already shows the
        reduction; a lagging full snapshot does not replace the filled quantity."""
        try:
            fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            fresh = None
        stage = self._got(j, which)
        target = self._stage_qty(sym, j, which, 0)
        if fresh is not None and abs(fresh) < before:
            left = abs(fresh)
        elif executed > 0:
            left = max(before - D(executed), Decimal(0))
        else:
            return False
        if target > 0 and stage >= target:
            self._book_realized_tp(j, which, left)
            return True
        if executed > 0:
            self._note_partial(j, which, stage, left if left > 0 else None)
        return False

    def _slice_target(self, sym, qty) -> Decimal:
        return self.rules[sym].floor_qty(D(qty))

    def _state_current(self) -> bool:
        """True only for this schema, with a proved opened size on every open journal."""
        if self.st.get("schema") != STATE_SCHEMA:
            return False
        for j in (self.st.get("pos") or {}).values():
            if not isinstance(j, dict) or j.get("entry_qty") in (None, ""):
                return False
        return True

    def _book_is_clear(self) -> bool:
        """Flat means position 0 and no open order, regular or algo, on every symbol.
        A missing position row or a failed read is not flat."""
        try:
            pos = self.x("positions", self.cfg.symbols)
        except ExchangeError:
            return False
        for sym in self.cfg.symbols:
            amt = self._row_amt(pos, sym)
            if amt is None or amt != 0:
                return False
            try:
                orders = self.x("open_orders", sym)
            except ExchangeError:
                return False
            if orders:
                return False
        return True

    def _gate_state(self) -> None:
        """Old files are not migrated. A clear book may start an empty current ledger.
        Anything on the exchange, or a journal with no proved opened size, halts."""
        self._schema_lock = False
        if self._state_current():
            return
        if self._book_is_clear():
            self.st["schema"] = STATE_SCHEMA
            self.st["pos"] = {}
            self.st["intents"] = {}
            self.st["unknown"] = {}
            self.save()
            return
        self._schema_lock = True
        if not self.meta.get("halted"):
            self.halt(SCHEMA_HALT)

    def _ledger(self, j, which) -> dict:
        """One persisted record per stage: the client ids and the sum of their executedQty."""
        book = j.setdefault("tp_ledger", {}).setdefault(which, {"cids": [], "sum": "0"})
        book.setdefault("cids", [])
        return book

    def _ledger_add(self, j, which, cid, executed) -> Decimal:
        """Store this cid's executed qty. A later read never lowers what that cid already filled."""
        book = j.setdefault("tp_ledger", {}).setdefault(which, {"cids": [], "sum": "0"})
        book.setdefault("cids", [])
        cid = str(cid)
        executed = D(executed)
        row = next((r for r in book["cids"] if r.get("cid") == cid), None)
        if row is None:
            book["cids"].append({"cid": cid, "executed": str(executed)})
        else:
            executed = max(D(row.get("executed") or 0), executed)
            row["executed"] = str(executed)
        total = sum((D(r.get("executed") or 0) for r in book["cids"]), Decimal(0))
        book["sum"] = str(total)
        j.setdefault("tp_got", {})[which] = book["sum"]          # cache derived from the ledger
        self.save()
        return total

    def _record_stage_order(self, sym, j, which, cid) -> Decimal:
        """Copy one order's executedQty into the ledger. A failed read leaves the ledger as it was."""
        try:
            st = self.x("algo_order", sym, cid)
        except ExchangeError:
            return self._got(j, which)
        if not isinstance(st, dict):
            return self._got(j, which)
        return self._ledger_add(j, which, st.get("client_id") or cid, st.get("executed_qty") or 0)

    def _got(self, j, which) -> Decimal:
        return D(self._ledger(j, which).get("sum") or 0)

    def _opened_size(self, j):
        """Opened size stored on the journal. The current position is not a substitute:
        after a fill it is the remainder, and using it makes the runner reserve zero."""
        raw = j.get("entry_qty")
        if raw in (None, ""):
            return None
        return abs(D(raw))

    def _slice_sell(self, sym, j, which, fresh, last=None):
        """min(target − ledger, room above the reserved remainder, position).
        None when the position read is missing. 0 when nothing may be sold,
        including when the opened size was never stored (leave it to the stop)."""
        if fresh is None:
            return None
        rules = self.rules[sym]
        target = self._stage_qty(sym, j, which, 0)
        got = self._got(j, which)
        if fresh == 0 or (target > 0 and got >= target):
            return Decimal(0)
        entry = self._opened_size(j)
        if entry is None:
            return Decimal(0)
        prior = D((j.get("tp") or {}).get("q1") or 0) if which == "t2" and j.get("tp1_done") else Decimal(0)
        expect = Decimal(0) if which == "t3" else max(entry - prior - target, Decimal(0))
        room = abs(fresh) - expect
        if room <= 0:
            return Decimal(0)
        sell = rules.floor_qty(min(max(target - got, Decimal(0)), room, abs(fresh)))
        if sell < rules.order_min_qty:
            return Decimal(0)
        if last is not None and sell * D(last) < rules.min_notional:
            return Decimal(0)
        return sell

    def _note_partial(self, j, which, got: Decimal, left, release=False):
        """Mirror the ledger into tp_got. Drop a realization cid only once that order is terminal."""
        book = (j.get("tp_ledger") or {}).get(which)
        if isinstance(book, dict) and book.get("cids"):
            j.setdefault("tp_got", {})[which] = str(book.get("sum") or got)
        else:
            j.setdefault("tp_got", {})[which] = str(got)
        once = j.get("tp_market_once")
        if release and isinstance(once, dict):
            once.pop(which, None)
        if left is not None and left > 0:
            j["qty"] = str(left)
        self.save()

    def _apply_exec(self, j, which, order_exec, left, release, cid="") -> Decimal:
        """Record this realization cid in the ledger. The same cid is not added twice."""
        got = self._ledger_add(j, which, cid or f"{j.get('cid', '')}{which}:market", order_exec)
        self._note_partial(j, which, got, left, release=release)
        return got

    def _stage_qty(self, sym, j, which, fallback) -> Decimal:
        key = {"t1": "q1", "t2": "q2", "t3": "q3"}.get(which, "q1")
        return self._slice_target(sym, (j.get("tp") or {}).get(key) or fallback)

    def _book_exchange_fill(self, sym, j, which, st) -> str:
        """Book this stage from the order's executed qty. 'live' can still fill. 'gone' is terminal."""
        if not isinstance(st, dict):
            return "gone"
        status = str(st.get("status") or "").upper()
        executed = D(st.get("executed_qty") or 0)
        self._ledger_add(j, which, st.get("client_id") or self._tp_cid(j, which), executed)
        got = self._got(j, which)
        target = self._stage_qty(sym, j, which, 0)
        terminal = status in _TP_GONE or status in _TP_DONE
        if target > 0 and got >= target and terminal:
            try:
                fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
            except ExchangeError:
                fresh = None
            self._book_realized_tp(j, which, abs(fresh) if fresh is not None else Decimal(0))
            return "done"
        if not terminal:
            return "live"
        return "gone"

    def _quote_market(self, sym, j, which, qty, last):
        """min(remaining slice, position read in this call). The next call is the market send.
        Returns (sell, signed_position, why) with why in ok, live, done, dust, flat."""
        try:
            st = self.x("algo_order", sym, self._tp_cid(j, which))
        except ExchangeError:
            return None, None, "live"
        if self._book_exchange_fill(sym, j, which, st) == "live":
            return None, None, "live"
        if self._got(j, which) >= self._stage_qty(sym, j, which, qty) > 0 and (
                not isinstance(st, dict) or str(st.get("status") or "").upper() in _TP_GONE | _TP_DONE):
            try:
                fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
            except ExchangeError:
                fresh = None
            if fresh is not None and not (
                    (which == "t1" and j.get("tp1_done")) or (which == "t2" and j.get("tp2_done"))
                    or (which == "t3" and j.get("tp3_done"))):
                self._book_realized_tp(j, which, abs(fresh))
            return Decimal(0), fresh, "done"
        try:
            fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            return None, None, "live"
        if fresh is None:
            return None, None, "live"
        if fresh == 0:
            return Decimal(0), fresh, "flat"
        target = self._stage_qty(sym, j, which, qty)
        got = self._got(j, which)
        if target > 0 and got >= target:
            self._book_realized_tp(j, which, abs(fresh))
            return Decimal(0), fresh, "done"
        sell = self._slice_sell(sym, j, which, fresh, last)
        if not sell:
            if target > 0 and got >= target:
                self._book_realized_tp(j, which, abs(fresh))
                return Decimal(0), fresh, "done"
            entry = self._opened_size(j)
            if entry is None:
                return Decimal(0), fresh, "dust"          # opened size unknown: do not sell the remainder
            prior = D((j.get("tp") or {}).get("q1") or 0) if which == "t2" and j.get("tp1_done") else Decimal(0)
            expect = Decimal(0) if which == "t3" else max(entry - prior - target, Decimal(0))
            if abs(fresh) - expect <= 0:
                return Decimal(0), fresh, "flat"
            return Decimal(0), fresh, "dust"
        return sell, fresh, "ok"

    def _settle_pending_market(self, sym, j, which, qty) -> str:
        """Look up a realization cid before any new take-profit POST.
        'done' is booked, 'wait' sends nothing, 'go' may place."""
        pending = (j.get("tp_market_once") or {}).get(which)
        if not isinstance(pending, dict):
            return "go"
        what = f"익절 {which}"
        target = self._slice_target(sym, qty)
        try:
            order = self.x("get_order", sym, str(pending.get("cid") or ""))
        except ExchangeError:
            self._tp_fail_once(sym, what, "체결 조회 실패 · 추가 주문 없음")
            self.block(UNKNOWN_ORDER, str(pending.get("cid") or ""), "주문 상태 확인 불가 — 신규 진입 중단")
            return "wait"
        if not isinstance(order, dict):
            (j.get("tp_market_once") or {}).pop(which, None)    # confirmed absent: the permit was not spent
            j.setdefault("tp_rearm", {})[which] = True
            self.save()
            return "rearm"
        order_exec = self._executed_qty(order)
        status = str(order.get("status") or "").upper()
        terminal = status in _TP_GONE or status in _TP_DONE
        try:
            fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            fresh = None
        left = abs(fresh) if fresh not in (None, 0) else None
        got = self._apply_exec(j, which, order_exec, left, release=False, cid=str(pending.get("cid") or ""))
        if got >= target > 0 and terminal:
            self._book_fill(sym, j, which, D(pending.get("before") or 0), order_exec)
            return "done"
        if not terminal:
            if order_exec > 0:
                self._tp_fail_once(sym, what, f"부분 체결 {got} · 남은 수량 다음 확인")
            return "wait"                                      # still live, including PARTIALLY_FILLED
        (j.get("tp_market_once") or {}).pop(which, None)        # FILLED / CANCELED / EXPIRED: the row is done
        self.save()
        if order_exec > 0 and got < target:
            self._tp_fail_once(sym, what, f"부분 체결 {got} · 남은 수량 다음 확인")
        return "go"

    def _release_working_tp(self, sym, j, which) -> str:
        """Before a realization market: a still-working conditional order is cancelled
        and confirmed gone. 'blocked' means send nothing. 'clear' means it cannot fill later."""
        what = f"익절 {which}"
        try:
            st = self.x("algo_order", sym, self._tp_cid(j, which))
        except ExchangeError:
            self._tp_fail_once(sym, what, "주문 조회 실패 · 추가 주문 없음")
            return "blocked"
        if not isinstance(st, dict):
            return "clear"
        status = str(st.get("status") or "").upper()
        executed = D(st.get("executed_qty") or 0)
        self._ledger_add(j, which, st.get("client_id") or self._tp_cid(j, which), executed)
        if status in {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}:
            return "clear"
        if status in {"FILLED", "FINISHED"}:
            return "clear"                                 # terminal: it will not fire again
        if status in _TP_RESTING:
            return "new"                                   # NEW or WORKING: cancel only immediately before the market
        self._tp_fail_once(sym, what, f"익절 주문 살아 있음 · {status or 'UNKNOWN'} · 시장가 없음")
        return "live"

    def _cancel_working_tp(self, sym, j, which) -> bool:
        """Cancel a NEW conditional order and confirm it is CANCELED. False: still live, send nothing."""
        what = f"익절 {which}"
        try:
            st = self.x("algo_order", sym, self._tp_cid(j, which))
        except ExchangeError:
            self._tp_fail_once(sym, what, "익절 취소 미확인 · 시장가 없음")
            return False
        if not isinstance(st, dict):
            return True
        status = str(st.get("status") or "").upper()
        if status in _TP_GONE:
            return True
        if status not in _TP_RESTING:                       # TRIGGERING / FILLED / unknown: not a confirmed cancel
            return False
        oid = st.get("id")
        if not oid:
            self._tp_fail_once(sym, what, "익절 취소 미확인 · 시장가 없음")
            return False
        try:
            self.x("cancel", sym, {"kind": "algo", "id": oid, "client_id": self._tp_cid(j, which), "symbol": sym})
        except ExchangeError:
            self._tp_fail_once(sym, what, "익절 취소 미확인 · 시장가 없음")
            return False
        try:
            again = self.x("algo_order", sym, self._tp_cid(j, which))
        except ExchangeError:
            self._tp_fail_once(sym, what, "익절 취소 미확인 · 시장가 없음")
            return False
        if isinstance(again, dict) and str(again.get("status") or "").upper() not in _TP_GONE:
            self._tp_fail_once(sym, what, "익절 취소 미확인 · 시장가 없음")
            return False
        return True

    def _post_rest(self, sym, j, which, px, qty, working_type, what) -> bool:
        if self._schema_lock:
            return False
        """Rest min(target − ledger, room, position). Unknown id: not a success, no POST."""
        cid = self._tp_cid(j, which)
        state = self._cid_state(sym, cid)
        if state == "unknown":
            self._tp_fail_once(sym, what, "주문 조회 실패 · 추가 주문 없음")
            return False
        if state == "yes":
            return True                                 # confirmed on the book already
        if state in {"terminal", "filled"}:
            for cid_i in self._tp_fill_cids(j, which):
                self._record_stage_order(sym, j, which, cid_i)
            cid = self._bump_tp_cid(j, which)
        try:
            fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            fresh = None
        if self._got(j, which) >= self._stage_qty(sym, j, which, qty) > 0:
            self._note_filled_tp(sym, j, what)
            return True
        sell = self._slice_sell(sym, j, which, fresh)
        if sell is None:
            self._tp_fail_once(sym, what, "포지션 조회 실패 · 기존 손절 유지")
            return False
        if sell <= 0:
            self._tp_fail_once(sym, what, "남은 수량 최소 미달")
            return False
        try:
            self.x("take_profit", sym, self._cs(j), px, cid, sell, working_type=working_type)
        except OrderRejected as e:
            self._tp_fail_once(sym, what, f"시장가 청산 거절 · {e}")
            return False
        except ExchangeError as e:
            self._tp_fail_once(sym, what, f"주문 조회 실패 · {e}")
            return False
        return True

    def _on_tp_would_trigger(self, sym, j, which, px, qty, working_type, place_tp=True) -> bool:
        if self._schema_lock:
            return False
        """Price was through this take-profit. Re-read the last trade. Still through →
        one reduceOnly market for this slice, ever. Its qty is min(the remaining slice,
        the position read immediately before the send). Book tp1_done, the breakeven
        stop and the runner only after that fill. Back inside → rest the rounded order
        once. A slice under min notional is not sold: it stays with the stop or the
        next stage. The stop is not replaced."""
        what = f"익절 {which}"
        s = int(j.get("side", 1))
        try:
            last = self._decision_px(sym, working_type)
        except ExchangeError:
            self._tp_fail_once(sym, what, "가격 조회 실패 · 기존 손절 유지")
            return False
        try:
            amt = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            amt = None
        if amt is None:
            self._tp_fail_once(sym, what, "포지션 조회 실패 · 기존 손절 유지")
            return False
        try:
            self.x("open_orders", sym)
        except ExchangeError:
            self._tp_fail_once(sym, what, "주문 조회 실패 · 기존 손절 유지")
            return False
        through = (s > 0 and last >= D(px)) or (s < 0 and last <= D(px))
        sent = (j.get("tp_market_once") or {}).get(which)
        if isinstance(sent, dict):
            before_sent = D(sent.get("before") or 0)
            try:
                order = self.x("get_order", sym, str(sent.get("cid") or ""))
            except ExchangeError:
                self._tp_fail_once(sym, what, "체결 조회 실패 · 추가 주문 없음")
                self.block(UNKNOWN_ORDER, str(sent.get("cid") or ""), "주문 상태 확인 불가 — 신규 진입 중단")
                return False                            # unreadable: keep the cid, send nothing
            if not isinstance(order, dict):
                (j.get("tp_market_once") or {}).pop(which, None)
                j.setdefault("tp_rearm", {})[which] = True
                self.save()
            else:
                order_exec = self._executed_qty(order)
                target = self._stage_qty(sym, j, which, qty)
                status = str(order.get("status") or "").upper()
                terminal = status in _TP_GONE or status in _TP_DONE
                got = self._apply_exec(j, which, order_exec, None, release=False, cid=str(sent.get("cid") or ""))
                if got >= target > 0 and terminal:
                    return self._book_fill(sym, j, which, before_sent, order_exec)
                if not terminal:
                    if order_exec > 0:
                        self._tp_fail_once(sym, what, f"부분 체결 {got} · 남은 수량 다음 확인")
                    return False                        # still live, including PARTIALLY_FILLED
                (j.get("tp_market_once") or {}).pop(which, None)
                self.save()
                if order_exec > 0 and got < target:
                    self._tp_fail_once(sym, what, f"부분 체결 {got} · 남은 수량 다음 확인")
                if through or not place_tp:
                    return False
                return self._post_rest(sym, j, which, px, qty, working_type, what)
        if (j.get("tp_rearm") or {}).get(which):
            if through:
                return False                            # unsent order: do not sell the slice again while through
            ok = self._post_rest(sym, j, which, px, qty, working_type, what)
            if ok:
                j.get("tp_rearm", {}).pop(which, None)
                self.save()
            return ok
        if not through:
            if not place_tp:
                return False
            return self._post_rest(sym, j, which, px, qty, working_type, what)
        gate = self._release_working_tp(sym, j, which)
        if gate in {"blocked", "live"}:
            return False
        try:                                                # a failed read cancels nothing
            amt = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            amt = None
        if amt is None:
            self._tp_fail_once(sym, what, "포지션 조회 실패 · 기존 손절 유지")
            return False
        cancelled_now = False
        if gate == "new":
            if not self._cancel_working_tp(sym, j, which):
                try:
                    st = self.x("algo_order", sym, self._tp_cid(j, which))
                except ExchangeError:
                    self._tp_fail_once(sym, what, "주문 조회 실패 · 추가 주문 없음")
                    return False
                if self._book_exchange_fill(sym, j, which, st) == "done":
                    return True
                self._tp_fail_once(sym, what, "익절 주문 살아 있음 · 시장가 없음")
                return False
            cancelled_now = True
        seq = int(j.get("exit_seq", 0))
        j["exit_seq"] = seq + 1
        cid_x = f"{j['cid']}x{seq}"
        try:
            existing = self.x("get_order", sym, cid_x)
        except ExchangeError as e:
            j["exit_seq"] = seq
            if cancelled_now:                               # the TP is gone and the market was not sent
                j.setdefault("tp_rearm", {})[which] = True
            self.save()
            self._tp_fail_once(sym, what, f"주문 조회 실패 · {e}")
            return False
        if self._executed_qty(existing) > 0:
            return self._book_fill(sym, j, which, abs(amt), self._executed_qty(existing))
        sell, fresh, why = self._quote_market(sym, j, which, qty, last)
        if why == "done":
            return True
        if why == "dust":
            self._tp_fail_once(sym, what, "남은 수량 최소 미달")
            return False
        if why != "ok" or fresh in (None, 0) or sell is None or sell <= 0:
            if why == "live":
                self._tp_fail_once(sym, what, "익절 주문 살아 있음 · 시장가 없음")
            return False
        side = "SELL" if fresh > 0 else "BUY"
        target = self._stage_qty(sym, j, which, qty)
        got = self._got(j, which)
        try:
            result = self.x("market", sym, side, sell, cid_x, True)
        except OrderRejected as e:
            self._tp_fail_once(sym, what, f"시장가 청산 거절 · {e}")
            return False                                # explicit reject: permit not spent, retry after the cooldown
        except ExchangeError:
            try:
                result = self.x("get_order", sym, cid_x)
            except ExchangeError as e2:
                j.setdefault("tp_market_once", {})[which] = {
                    "cid": cid_x, "before": str(abs(fresh)), "accepted": False}
                self.save()
                self.block(UNKNOWN_ORDER, cid_x, "주문 상태 확인 불가 — 신규 진입 중단")
                self._tp_fail_once(sym, what, f"시장가 청산 결과 불명 · {e2}")
                return False
            if not isinstance(result, dict):
                j.setdefault("tp_rearm", {})[which] = True   # never accepted: permit not spent
                self.save()
                self._tp_fail_once(sym, what, "시장가 청산 미확인 · 기존 손절 유지")
                return False
        if not isinstance(result, dict) or not (result.get("id") or result.get("status")):
            self._tp_fail_once(sym, what, "시장가 청산 미확인 · 기존 손절 유지")
            return False
        j.setdefault("tp_market_once", {})[which] = {
            "cid": cid_x, "before": str(abs(fresh)), "accepted": True}
        self.save()
        executed = self._executed_qty(result)
        status = str(result.get("status") or "").upper()
        try:
            left_amt = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            left_amt = None
        left = abs(left_amt) if left_amt is not None else max(abs(fresh) - executed, Decimal(0))
        booked = self._apply_exec(j, which, executed, left if left > 0 else None, release=False, cid=cid_x)
        if booked >= target > 0 and (status in _TP_DONE or status in _TP_GONE
                                      or executed >= max(target - got, Decimal(0)) > 0):
            if which == "t3" and not j.get("exit_fill"):
                j["exit_fill"] = "take_profit"
            self._book_realized_tp(j, which, left)
            return True
        if executed > 0 and booked < target and (status in _TP_DONE or status in _TP_GONE):
            (j.get("tp_market_once") or {}).pop(which, None)
            self.save()
        if executed > 0:
            self._tp_fail_once(sym, what, f"부분 체결 {booked} · 남은 수량 다음 확인")
            return False
        self._tp_fail_once(sym, what, "시장가 청산 미확인 · 기존 손절 유지")
        return False

    def _arm_unsplittable(self, sym, j):
        """Cannot split off TP1: +3R reduceOnly TP and the SL, both on the full qty. No TP is not allowed."""
        s = int(j.get("side", 1))
        qty = D(j["qty"])
        px = self._runner_px(sym, j)
        j["tp"] = {"tp1": None, "q1": "0", "tp2": None, "q2": str(qty),
                   "tp3": str(px), "q3": str(qty), "full": True}
        j["tp1_done"] = False
        self.save()
        amt = qty if s > 0 else -qty
        try:
            oo = self.x("open_orders", sym)
        except ExchangeError:
            oo = None                                          # unknown book: do not stack a second stop
        if oo is not None and sym not in self._cp_hold and not self.find_stop(amt, oo):
            if not self._arm_stop(sym, j, amt) or not self._position_open(sym):
                return
        self._place_tp(sym, j, "t3", px, qty, working_type="MARK_PRICE")

    def _place_tps(self, sym, j):
        if self._schema_lock:
            return
        try:
            tp1, q1, tp2, q2 = self._tp_levels(sym, j)
        except Exception as e:  # noqa: BLE001  cannot price a TP → keep the stop, never flatten
            log.error("%s TP levels failed: %r", sym, e)
            self._tp_fail_once(sym, "익절 가격", e)
            return
        if q1 <= 0:
            qty = D(j["qty"])
            if tp2:                                            # legacy: +2R on the whole qty, as before
                j["tp"] = {"tp1": None, "q1": "0", "tp2": str(tp2), "q2": str(qty)}
                j["tp1_done"] = True
                self.save()
                self._place_tp(sym, j, "t2", tp2, qty)
                return
            self._arm_unsplittable(sym, j)                     # scheme E: +3R and the SL on the full qty
            return
        j["tp"] = {"tp1": str(tp1), "q1": str(q1), "tp2": str(tp2) if tp2 else None, "q2": str(q2)}
        j["tp1_done"] = False
        self.save()
        self._place_tp(sym, j, "t1", tp1, q1)
        if tp2 and self._position_open(sym):
            self._place_tp(sym, j, "t2", tp2, q2)

    def _manage_tps(self, sym, j, amt, orders, mk, hold=False):
        """Every reconcile: missing TP orders re-placed; after TP1 the +3R runner is armed and the stop moves to breakeven.
        During a -4130 hold the book is not proof those orders are gone, so only the breakeven move runs."""
        self._bind_runner(sym, j, amt)
        tp, cids = j["tp"], {o["client_id"] for o in orders}
        for w, k in (("t1", "tp1"), ("t2", "tp2"), ("t3", "tp3")):  # a TP missing from open orders most likely just fired:
            if (tp.get(k) and self._tp_cid(j, w) not in cids      # `amt` / `mk` may predate it -> fresh position read
                    and not (w == "t1" and j.get("tp1_done"))):     # first (testnet LINK + PEPE 2026-10-30: re-place ->
                try:                                                 # -2021 -> a 2nd market TP1 closed the remainder)
                    fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
                except ExchangeError:
                    return
                if fresh is None:
                    return                                  # missing row: do not guess a fill from amount 0
                if abs(fresh) < abs(amt):
                    self._dirty = True                            # filled: next reconcile books it (tp1_done / flat)
                    return
        if hold:
            key = (sym, "익절 t1")
            if (not j.get("tp1_done") and tp.get("tp1") and self._position_open(sym)
                    and self.clock() >= self._tp_retry_at.get(key, 0)):
                try:
                    fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
                except ExchangeError:
                    fresh = None
                if fresh not in (None, 0):
                    ok = self._on_tp_would_trigger(
                        sym, j, "t1", D(tp["tp1"]), D(tp["q1"]), "CONTRACT_PRICE", place_tp=False)
                    if not ok and not j.get("tp1_done"):
                        self._tp_cooled.add(key)
                        self._tp_retry_at[key] = self.clock() + PROTECT_AUDIT_S
                    if j.get("tp1_done"):
                        booked = abs(D(j.get("qty") or 0))
                        if booked > 0:
                            amt = booked if int(j.get("side", 1)) > 0 else -booked
            if j.get("tp1_done") and tp.get("tp1") and not j.get("be_done") and self._position_open(sym):
                try:
                    now_amt = self._row_amt(self.x("positions", self.cfg.symbols), sym)
                except ExchangeError:
                    now_amt = None
                if now_amt not in (None, 0):
                    self._move_stop_be(sym, j, amt, orders, mk)
            return
        if not j.get("tp1_done") and self._tp_cid(j, "t1") not in cids and tp.get("tp1"):
            self._place_tp(sym, j, "t1", D(tp["tp1"]), D(tp["q1"]))
            if not self._position_open(sym):
                return
            if j.get("tp1_done"):
                try:
                    fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
                except ExchangeError:
                    fresh = None
                if fresh == 0:
                    return
                booked = abs(D(j.get("qty") or 0))
                if fresh is not None and (booked <= 0 or abs(fresh) <= booked):
                    amt = fresh
                    j["qty"] = str(abs(fresh))
                    self.save()
                elif booked > 0:
                    amt = booked if int(j.get("side", 1)) > 0 else -booked
        if tp.get("tp2") and not self.cfg.tp2_r:                   # adopted pre-E position: TP2 cancelled (E has none)
            o2 = next((o for o in orders if o["client_id"] == self._tp_cid(j, "t2")), None)
            try:
                if o2 is not None:
                    self.x("cancel", sym, o2)
                tp["tp2"] = None
                self.save()
                log.info("%s TP2 %s (E: no TP2, trailing SL)", sym, "cancelled" if o2 else "dropped (not open)")
            except ExchangeError as e:
                log.error("%s TP2 cancel failed (retried next reconcile): %s", sym, e)
        elif tp.get("tp2") and not j.get("tp2_done") and self._tp_cid(j, "t2") not in cids and self._position_open(sym):
            self._place_tp(sym, j, "t2", D(tp["tp2"]), D(tp.get("q2") or abs(amt)))
            if not self._position_open(sym):
                return
        self._bind_runner(sym, j, amt)                      # TP1 may have been booked earlier in this pass
        if self._runner_due(j) and not j.get("tp3_done") and tp.get("tp3") and self._tp_cid(j, "t3") not in cids \
                and self._position_open(sym):
            self._place_tp(sym, j, "t3", D(tp["tp3"]), D(tp.get("q3") or abs(amt)), working_type="MARK_PRICE")
            if not self._position_open(sym):
                return
        if j.get("tp1_done") and tp.get("tp1") and not j.get("be_done") and self._position_open(sym):
            self._move_stop_be(sym, j, amt, orders, mk)

    def _exit_fills(self, sym, j, amt, orders):
        """Fill detection from the exchange order status, not from position-qty diffs (TA 2026-10-30): our SL / BE stop /
        TP1 / TP2 missing from `orders` is looked up (algo status → resulting order executedQty). `amt` / `orders` may
        predate a fire (testnet: it fires between the position read and the open-orders read), so after a fill both
        are read again. Returns (amt, orders, filled kinds) | None (nothing missing, or status unreadable → legacy
        path) | False (a closing fill is not reflected in the position yet → skip this symbol, nothing re-placed)."""
        cid, open_ = j["cid"], {o["client_id"] for o in orders}
        cand = {}
        if not self.find_stop(amt, orders):
            seq = int(j.get("stop_seq", 0))
            cids = [f"{cid}p"]
            live = str(j.get("stop_cid") or "")
            if live:
                cids.append(live)
            if seq > 0 and f"{cid}s{seq - 1}" not in cids:
                cids.append(f"{cid}s{seq - 1}")
            cand.update({c: "stop" for c in cids})
        if j.get("tp"):
            if j["tp"].get("tp1") and not j.get("tp1_done"):
                cand.update({c: "tp1" for c in self._tp_fill_cids(j, "t1")})
            if j["tp"].get("tp2"):
                cand.update({c: "tp2" for c in self._tp_fill_cids(j, "t2")})
            if j["tp"].get("tp3") and self._runner_due(j):
                cand.update({c: "tp3" for c in self._tp_fill_cids(j, "t3")})
        cand = {c: k for c, k in cand.items() if c not in open_}
        if not cand:
            return None
        filled = {}
        rows = []
        for c, k in cand.items():
            try:
                st = self.x("algo_order", sym, c)
            except ExchangeError as e:
                log.error("%s order status %s unreadable (%s) → position-based fallback", sym, c, e)
                return None
            executed = D(st.get("executed_qty") or 0) if isinstance(st, dict) else Decimal(0)
            if executed > 0:
                filled[k] = filled.get(k, Decimal(0)) + executed
                rows.append((c, k, executed))
        if not filled:
            return None
        try:
            amt = self._row_amt(self.x("positions", self.cfg.symbols), sym)
            orders = self.x("open_orders", sym)
        except ExchangeError:
            return False
        if amt is None:
            return False                                    # missing row is not a confirmed flat fill
        stage_of = {"tp1": "t1", "tp2": "t2", "tp3": "t3"}
        for c, k, executed in rows:
            which = stage_of.get(k)
            if which:
                self._ledger_add(j, which, c, executed)
        log.info("%s exit fill from order status: %s → position %s", sym, filled, amt)
        if "stop" in filled:
            j["exit_fill"] = "trail_stop" if j.get("trailed") else "be_stop" if j.get("be_done") else "stop_loss"
            self.save()
            if amt != 0 and "tp1" not in filled:
                sig = f"{amt}|" + ",".join(f"{k}:{v}" for k, v in sorted(filled.items()))
                if j.get("_partial_exit") != sig:
                    j["_partial_exit"] = sig               # one pass may still be the fill landing
                    self._dirty = True
                    self.save()
                    return False
                j["qty"] = str(abs(amt))                   # same residual again: the exit is done
                j.pop("_partial_exit", None)
                self.save()
                return amt, orders, filled
        if "tp1" in filled and not j.get("tp1_done") and amt != 0 and self._got(j, "t1") >= self._stage_qty(sym, j, "t1", 0) > 0:
            j.update(tp1_done=True, qty=str(abs(amt)))
            self.save()
            self.notify(f"🔵 {sym} TP1 체결 {filled['tp1']} → 남은 수량 {abs(amt)} · 손절을 본절로 이동", kind="exit")
        if "tp2" in filled and self._got(j, "t2") >= self._stage_qty(sym, j, "t2", 0) > 0:
            j["tp2_done"] = True
            j["exit_fill"] = "take_profit"
            self.save()
        if "tp3" in filled and self._got(j, "t3") >= self._stage_qty(sym, j, "t3", 0) > 0:
            j["tp3_done"] = True
            j["exit_fill"] = "take_profit"
            self.save()
        return amt, orders, filled

    def _be_target(self, sym, j) -> Decimal:
        """After TP1: be ± be_offset (safe-side tick); be = entry, or with be_fee the fee-inclusive breakeven."""
        s, e = int(j.get("side", 1)), D(j["entry_px"])
        if self.cfg.be_fee is not None:
            f = D(str(self.cfg.be_fee))
            e = e * (1 + f) / (1 - f) if s > 0 else e * (1 - f) / (1 + f)
        return self.rules[sym].price(e * (1 + s * D(str(self.cfg.be_offset))), "up" if s > 0 else "down")

    def _move_stop_be(self, sym, j, amt, orders, mk=None):  # noqa: ARG002  (orders: kept for callers; read-back used)
        tgt = self._be_target(sym, j)
        if int(j.get("side", 1)) * (tgt - D(j["stop_px"])) <= 0:
            j["be_done"] = True                                   # stop already at/above breakeven
            self.save()
            return
        if self._replace_stop(sym, j, amt, tgt, mk, "be") == "ok":
            j["be_done"] = True
            self.save()
            self.notify(f"🛡️ {sym} 손절 본절 이동 {tgt} (진입 {j['entry_px']})", kind="exit")

    def _replace_stop(self, sym, j, amt, tgt, mk, why) -> str:
        """Move our stop to `tgt`: NEW reduceOnly STOP (qty = position) first, read back, THEN every other STOP of ours
        cancelled — never a moment without a stop; at most a short overlap of two (both reduceOnly, only one can fill
        the position). Mark already at/through tgt → reduceOnly market close. Returns 'ok' | 'closed' | 'pending'
        (not confirmed: the old stop stays, one 🚨, retried by reconcile)."""
        if self.clock() < self._cap_retry_at.get(sym, 0):
            return "pending"                                 # the close already failed: do not POST another stop
        s, breach = int(j.get("side", 1)), ("be_stop_breach" if why == "be" else "trail_stop_breach")
        if mk is not None and s * (D(mk) - tgt) <= 0:             # SL must not sit past breakeven after TP1
            log.warning("%s mark %s already beyond %s stop %s → close remainder", sym, mk, why, tgt)
            return self._cap_close(sym, j, breach)
        seq = int(j.get("stop_seq", 0))
        j["stop_seq"] = seq + 1
        self.save()
        cid = f"{j['cid']}s{seq}"
        sent = False
        try:                                                      # NEW stop first (qty: one closePosition per side)
            self.x("stop", sym, self._cs(j), tgt, cid, qty=abs(amt))
            sent = True
        except WouldTrigger:                                      # price already back through the level → close now
            return self._cap_close(sym, j, breach)
        except ExchangeError as e:
            log.error("%s %s stop placement: %s → read-back", sym, why, e)
        try:
            oo = self.x("open_orders", sym)
            new = next((o for o in oo if o["client_id"] == cid), None)
        except ExchangeError:
            oo, new = [], None
        if new is None and sent and sym in self._cp_hold:
            j.update(stop_px=str(tgt), stop_cid=cid)       # hold book is not proof the accepted stop is missing
            j.pop(f"{why}_alerted", None)
            if why == "trail":
                j["trailed"] = True
            self.save()
            return "ok"
        if new is None:
            try:                                                  # accepted but fired at once (instant fire)?
                flat = self._row_amt(self.x("positions", self.cfg.symbols), sym) == 0
            except ExchangeError:
                flat = False
            if flat:                                              # remainder already gone → cancel old stop + TPs, record
                self.close(sym, breach)
                return "closed"
            if not j.get(f"{why}_alerted"):                       # not confirmed → old stop stays, 🚨, retried
                j[f"{why}_alerted"] = True
                self.alert(f"{'본절' if why == 'be' else '추적'} 손절 이동 미확인 — 기존 손절 유지 ({sym})",
                           f"목표 {tgt} · 기존 {j['stop_px']} · 대조 루프가 재시도")
            self.save()
            return "pending"
        j.update(stop_px=str(tgt), stop_cid=cid)
        j.pop(f"{why}_alerted", None)
        if why == "trail":
            j["trailed"] = True
        self.save()
        for o in oo:                                              # THEN cancel the old stop(s) of ours (fresh read-back)
            if (o["client_id"] != cid and (o["type"] or "").startswith("STOP")
                    and str(o["client_id"]).startswith(self.cfg.cid_prefix)):
                self._cancel_quiet(sym, o)
        return "ok"

    def _trail_atr(self, sym, j) -> Decimal | None:
        """ATR14 (Wilder) of the last CLOSED 1h bar, cached in the journal per hour (one 150-bar read per hour)."""
        h_last = self.now_ms() // 3_600_000 * 3_600_000 - 3_600_000
        if j.get("atr") and int(j.get("atr_h") or 0) >= h_last:
            return D(j["atr"])
        try:
            bars = self.closed_bars(sym, "1h", 150)
        except ExchangeError as e:
            log.error("%s 1h klines for ATR: %s (previous ATR kept)", sym, e)
            bars = []
        if len(bars) >= 15:
            from .strategies.qrmtf import atr14
            j.update(atr=str(D(str(atr14([{k: float(b[k]) for k in ("high", "low", "close")} for b in bars])))),
                     atr_h=int(bars[-1]["open_time"]))
            self.save()
        return D(j["atr"]) if j.get("atr") else None

    def _trail(self, sym, j, amt, mk):
        """E chandelier, once per closed 1m bar: best ← extreme of the closed 1m bars since entry (catch-up after a
        restart / adoption from j['trail_t']); SL → tighter(SL, best ∓ k·ATR14, after TP1 also the fee-BE floor)."""
        k = self.cfg.trail_atr_k
        if not k:
            return
        last = self.now_ms() // 60_000 * 60_000 - 60_000         # newest closed 1m bar
        if self._trail_try.get(sym) == last:                      # query-light: one try per symbol per minute
            return
        self._trail_try[sym] = last
        s = int(j.get("side", 1))
        o0 = int(j.get("opened_ms") or self.now_ms()) // 60_000 * 60_000
        done = int(j.get("trail_t") or (o0 - 60_000))
        best = D(j.get("best") or j["entry_px"])
        if done < last:
            try:
                bars = [b for b in self.closed_bars(sym, "1m", min(1500, (last - done) // 60_000 + 2))
                        if done < int(b["open_time"]) <= last and int(b["open_time"]) >= o0]
            except ExchangeError as e:
                log.error("%s 1m klines for trailing: %s (retried next minute)", sym, e)
                bars = []
            for b in bars:
                best = max(best, D(str(b["high"]))) if s > 0 else min(best, D(str(b["low"])))
            if bars:
                j.update(best=str(best), trail_t=int(bars[-1]["open_time"]))
                self.save()
        if j.get("best") is None:                                  # first try before any 1m bar since entry closed:
            j.update(best=str(best), trail_t=done)                # persist the seed so a restart restores the same best
            self.save()
        stop = D(j["stop_px"])
        cands = []
        atr = self._trail_atr(sym, j)
        if atr:
            cands.append(self.rules[sym].price(best - s * D(str(k)) * atr, "down" if s > 0 else "up"))
        if self.cfg.be_fee is not None and j.get("tp1_done") and (j.get("tp") or {}).get("tp1"):
            cands.append(self._be_target(sym, j))                 # adopted pre-E BE stop → tightened to the fee-BE floor
        tgt = stop
        for c in cands:
            tgt = max(tgt, c) if s > 0 else min(tgt, c)
        if s * (tgt - stop) > 0:
            r = self._replace_stop(sym, j, amt, tgt, mk, "trail")
            log.info("%s trail stop %s → %s (best %s, ATR %s): %s", sym, stop, tgt, best, atr, r)

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
        if self._schema_lock:
            self._lock_hold_alert(sym, "sl_failed", f"{stop_px} · {r}")
            return False
        self.alert("손절 등록 실패 — 이 포지션만 정리", f"{sym} {amt} · 손절 {stop_px} · {r} · 다른 포지션 유지")
        if not self.close(sym, f"sl_failed ({r})"):
            self.emergency_flatten_all(f"unprotected {sym}")
        return False

    # ───────────────────────── exits ─────────────────────────
    def close(self, sym, reason) -> bool:
        """Close the WHOLE position with reduceOnly MARKET orders until the exchange shows flat. The protective stop stays
        until flat is confirmed. A remainder (partial fill) is always closed in ONE order (no dust chunks)."""
        if self._schema_lock:
            log.warning("%s close (%s) refused: schema lock — exchange stop stays, no market", sym, reason)
            return False
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
                amt = self._row_amt(self.x("positions", self.cfg.symbols), sym)
                if amt is None:
                    raise ExchangeError(f"{sym} missing from positions")
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
                amt2 = self._row_amt(self.x("positions", self.cfg.symbols), sym)
                if amt2 is None:
                    raise ExchangeError(f"{sym} missing from positions")
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

    def _note_cp_hold(self, sym):
        """Remember a -4130 hold. The next empty-book retry waits a minute so a live
        closePosition is not re-POSTed every reconcile."""
        self._cp_hold.add(sym)
        self._cp_retry_at[sym] = self.clock() + PROTECT_AUDIT_S

    def _release_cp_hold(self, sym):
        self._cp_hold.discard(sym)
        self._cp_retry_at.pop(sym, None)
        self._cp_book_sig.pop(sym, None)

    def _clear_symbol_holds(self, sym):
        self._release_cp_hold(sym)
        self._audit_unknown.discard(sym)
        self._tp_unknown.discard(sym)
        self._book_down_since.pop(sym, None)
        self._tp_fail_alerted = {k for k in self._tp_fail_alerted
                                 if (k[0] if isinstance(k, tuple) else k) != sym}
        self._dup_unknown = {k for k in self._dup_unknown if k[0] != sym}
        self._dup_retry_at = {k: v for k, v in self._dup_retry_at.items() if k[0] != sym}
        self._tp_cooled = {k for k in self._tp_cooled if k[0] != sym}
        self._tp_retry_at = {k: v for k, v in self._tp_retry_at.items() if k[0] != sym}
        self._cap_retry_at.pop(sym, None)
        self._cap_alerted.discard(sym)

    @staticmethod
    def _book_sig(orders):
        return tuple(sorted(str(o.get("client_id") or o.get("id") or "") for o in orders))

    def _cap_alert_once(self, sym, detail):
        if sym in self._cap_alerted:
            return
        self._cap_alerted.add(sym)
        self.alert(f"보호 점검 보류 — {sym}", detail)

    def _cap_close(self, sym, j, reason) -> str:
        """One reduceOnly MARKET for the qty just read. A failed read sends nothing.
        A rejected close keeps the old stop and is reconsidered in a minute.
        Returns 'closed' | 'pending'."""
        if self._schema_lock:
            return "pending"
        if self.clock() < self._cap_retry_at.get(sym, 0):
            return "pending"
        try:
            amt = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            amt = None
        if amt is None:
            self._cap_alert_once(sym, "본절 이탈 · 포지션 조회 실패 · 기존 손절 유지")
            self._cap_retry_at[sym] = self.clock() + PROTECT_AUDIT_S
            return "pending"
        if amt == 0:
            j["closing"], j["close_reason"] = True, reason
            self.save()
            self._after_flat(sym, reason)
            return "closed"
        try:
            self.x("open_orders", sym)
        except ExchangeError:
            self._cap_alert_once(sym, "본절 이탈 · 주문 조회 실패 · 기존 손절 유지")
            self._cap_retry_at[sym] = self.clock() + PROTECT_AUDIT_S
            return "pending"
        seq = int(j.get("exit_seq", 0))
        j["exit_seq"] = seq + 1
        self.save()
        side = "SELL" if amt > 0 else "BUY"                # opposite the position: reduceOnly cannot flip it
        try:
            self.submit_market(sym, side, abs(amt), f"{j['cid']}x{seq}", reduce_only=True)
        except OrderRejected as e:
            self._cap_alert_once(sym, f"본절 이탈 · 시장가 청산 거절 · 기존 손절 유지 · {e}")
            self._cap_retry_at[sym] = self.clock() + PROTECT_AUDIT_S
            return "pending"
        except ExchangeError as e:
            self._cap_alert_once(sym, f"본절 이탈 · 시장가 청산 결과 불명 · 기존 손절 유지 · {e}")
            self._cap_retry_at[sym] = self.clock() + PROTECT_AUDIT_S
            return "pending"
        try:
            left = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError:
            left = None
        if left == 0:
            j["closing"], j["close_reason"] = True, reason
            self.save()
            self._after_flat(sym, reason)
            return "closed"
        return "pending"

    def _hold_should_rearm(self, sym, orders) -> bool:
        """A failed read never reaches here. A book whose order set changed (a TP
        appeared, or the empty book gained orders) re-arms now. An unchanged book,
        empty or not, retries once per 60s."""
        if sym not in self._cp_hold:
            return False
        sig = self._book_sig(orders)
        due = self.clock() >= self._cp_retry_at.get(sym, 0)
        changed = bool(orders) and sig != self._cp_book_sig.get(sym)
        if not (changed or due):
            return False
        self._cp_book_sig[sym] = sig
        self._cp_retry_at[sym] = self.clock() + PROTECT_AUDIT_S
        return True

    def _after_flat(self, sym, reason):
        """Cancel protective orders only after the freshest position read is still 0."""
        j = self.st["pos"].get(sym)
        if j is not None:
            verdict, _fresh = self.record_close(sym, reason)
            if verdict != "flat":
                return
        self._clear_symbol_holds(sym)                       # a later position on this coin must alert again
        try:
            for o in self.x("open_orders", sym):
                if (o["close_position"] or o["reduce_only"]) and str(o["client_id"]).startswith(self.cfg.cid_prefix):
                    self.x("cancel", sym, o)
        except ExchangeError as e:
            log.error("%s stale stop cancel failed (reconcile retries): %s", sym, e)

    def _residual_watch(self, sym, failed, foreign):
        """TA R3 alert (2026-10-29), flat coin only, alerts only: which orders get cancelled is unchanged. Counters live
        in memory (a restart starts a fresh count; at most one repeat per restart)."""
        if failed:
            n = self._r3_fail[sym] = self._r3_fail.get(sym, 0) + 1
            if n >= self.cfg.residual_alert_n and sym not in self._r3_alerted:
                self._r3_alerted.add(sym)
                self.alert(f"남은 주문 취소 실패 — {sym} 포지션 0 · 계속 재시도",
                           f"봇 주문 {', '.join(c for c, _ in failed)} · {n}회 연속 실패: {str(failed[0][1])[:80]}")
        else:
            self._r3_fail.pop(sym, None)
            if sym in self._r3_alerted:
                self._r3_alerted.discard(sym)
                self.notify(f"✅ 남은 주문 정리 완료 — {sym} 포지션 0 · 봇 주문 0", kind="recovery")
        live = {(sym, str(o["id"])) for o in foreign}
        self._foreign_seen = {k for k in self._foreign_seen if k[0] != sym or k in live}
        for o in foreign:
            if (sym, str(o["id"])) not in self._foreign_seen:
                self._foreign_seen.add((sym, str(o["id"])))
                self.alert(f"봇이 걸지 않은 주문 있음 — {sym} 포지션 0 · 자동 취소 안 함",
                           f"{o.get('type')} {o.get('side')} {o['client_id']} · 확인 후 직접 정리")

    def emergency_flatten_all(self, reason):
        """§8c L3 only: equity ≤ halt_fraction × C0 (−25 %), a position that stays unprotected after L1, or API dead > 5 min with an
        unprotected position → close ALL positions (reduceOnly MARKET) + halt."""
        if self._schema_lock:
            self._lock_hold_alert("*", "emergency_flatten", reason)
            return
        self.halt(f"emergency: {reason}")
        self.alert("비상청산 — 전 포지션 정리 + 매매 중단", reason)
        for s in list(self.st["pos"]):                   # TA R4: only positions in the state file; unknown ones keep
            self.close(s, f"emergency ({reason})")          # their exchange stop and stay for manual handling
        if self.st["unknown"]:
            self.alert("비상청산 대상 아님 — 기록 없는 포지션은 그대로 둠 (손절 유지, 수동 처리)",
                       ", ".join(f"{s} {u.get('amt')} 손절 {u.get('stop_px')}" for s, u in self.st["unknown"].items()))

    # ───────────────────────── live log v1 (recording only; never raises, never sleeps, no REST) ─────────────────────────
    def _emit(self, kind, build):
        """Build and append one log line. Any failure (unwritable path, disk full, writer bug, bad field) is caught here:
        journald error + daily `log_write_fail` count — trading code never sees it."""
        if self.events is None:
            return
        try:
            self.events.write(kind, build())
        except Exception as e:  # noqa: BLE001  a log write must never block or delay trading
            log.error("%s log write failed (trading unaffected): %r", kind, e)
            self._day_count("log_write_fail")

    def _day_count(self, key):
        """Per-UTC-day counters for the daily line (meta.log_day, last 3 days); persisted by the next state save."""
        if self.events is None:
            return
        try:
            day = datetime.fromtimestamp(self.now_ms() / 1000, timezone.utc).strftime("%Y-%m-%d")
            ld = self.meta.setdefault("log_day", {})
            for d in sorted(ld)[:-3]:
                ld.pop(d, None)
            c = ld.setdefault(day, {})
            c[key] = c.get(key, 0) + 1
        except Exception as e:  # noqa: BLE001
            log.error("log day count failed: %r", e)

    def _closed_flat_confirmed(self, sym, j) -> bool:
        """Drop a held journal from open risk only when this process has read the exchange position as 0.
        Nonzero, a failed read, or a restart (nothing confirmed yet) still counts. The row stays in st['pos'],
        so a new entry on that symbol is still refused."""
        return bool(isinstance(j, dict) and j.get("close_held") and sym in self._flat_confirmed)

    def _open_journals(self) -> list:
        return [j for sym, j in self.st["pos"].items()
                if isinstance(j, dict) and not self._closed_flat_confirmed(sym, j)]

    def _open_position_count(self) -> int:
        return len(self._open_journals()) + sum(1 for j in self.st["unknown"].values() if isinstance(j, dict))

    def _open_risk_pct(self) -> float:
        dflt = self.cfg.sizing.risk_pct / 100 * 2                    # same default as _open_book for unseen positions
        js = self._open_journals() + [j for j in self.st["unknown"].values() if isinstance(j, dict)]
        return sum(float(j.get("risk_frac", dflt)) for j in js) * 100

    def _log_skip(self, sym, reason, detail, signal_px=None, signal_ms=None, t=None):
        if self.events is None:
            return
        self._day_count("skips")
        sig = self._sig
        if signal_px is None and sig and sig[0] == sym:
            signal_px, signal_ms = sig[1], sig[2]

        def build():
            now = self.now_ms() if t is None else t
            return {"time": now, "time_kst": kst(now), "coin": sym, "side": "short" if self._sig_side < 0 else "long",
                    "signal_price": None if signal_px is None else str(signal_px), "signal_time": signal_ms,
                    "reason": reason, "detail": str(detail)[:500],
                    "open_positions": self._open_position_count(), "open_risk_sum": round(self._open_risk_pct(), 6),
                    "code_commit": self.events.commit}
        self._emit("skips", build)

    def skip_note(self, sym, reason, detail="", signal_px=None):
        """Log-only skip (strategy-side reasons such as h7t `missed` / `bar_not_in_model`): skips file + daily count only —
        no skip_log, no KST skip counts, no alert, no state change."""
        log.info("log-only skip %s %s: %s", sym, reason, detail)
        self._log_skip(sym, reason, detail, signal_px)

    def _track_mark(self, ev):
        """MAE/MFE from the mark stream the bot already receives (in memory in the position journal; the regular state
        save persists it, so a restart resumes). A silence > stream_stale_s (incl. downtime) is recorded as a gap."""
        if self.events is None:
            return
        try:
            j = self.st["pos"].get(ev.sym)
            if not j:
                return
            t, last = int(ev.t), j.get("mk_last")
            if last is not None and t - int(last) > self.cfg.stream_stale_s * 1000:
                g = j.setdefault("mark_gaps", [])
                g.append([int(last), t])
                del g[:-50]
            if j.get("mk_lo") is None or ev.price < D(j["mk_lo"]):
                j["mk_lo"] = str(ev.price)
            if j.get("mk_hi") is None or ev.price > D(j["mk_hi"]):
                j["mk_hi"] = str(ev.price)
            j["mk_last"] = max(t, int(last or 0))
            self._track_earlycut(j, t, ev.price)
        except Exception as e:  # noqa: BLE001
            log.error("mark tracking failed: %r", e)

    def _track_earlycut(self, j, t, px):
        """Record-only 4 h early-cut flag (TA 2026-11-02; no trading effect, never touches orders): favourable mark extreme
        in the first 4 h after the entry fill, the first mark at/after the 4 h mark and whether TP1 had filled by then."""
        t_in = int(j.get("entry_fill_ms") or j.get("opened_ms") or 0)
        if not t_in or "earlycut_px_at_4h" in j:
            return
        if t - t_in < EARLYCUT_MS:
            f = j.get("earlycut_fav")
            if f is None or (px > D(f) if int(j.get("side", 1)) > 0 else px < D(f)):
                j["earlycut_fav"] = str(px)
        else:
            j.update(earlycut_px_at_4h=str(px), earlycut_t_4h=t,
                     earlycut_tp1_at_4h=bool(j.get("tp1_done") and (j.get("tp") or {}).get("tp1")))

    def _note_exit_order(self, ev):
        """Exit order type + raw order id from ORDER_TRADE_UPDATE fills the stream already delivers; the fill itself is
        kept too (record_close falls back to it when userTrades lags the close, live SOL 2026-11-02/03)."""
        if not isinstance(ev, OrderUpdate):
            return
        try:
            r, j = ev.raw, self.st["pos"].get(ev.sym)
            if j and r.get("x") == "TRADE" and r.get("S") == ("SELL" if int(j.get("side", 1)) > 0 else "BUY"):
                xs = j.setdefault("exit_orders", [])
                xs.append({"id": str(r.get("i")), "client_id": r.get("c"), "type": r.get("o"), "orig_type": r.get("ot"),
                           "status": r.get("X"), "time": r.get("T")})
                del xs[:-20]
                if D(r.get("l") or 0) > 0:
                    fs = j.setdefault("stream_fills", [])
                    fs.append({"order_id": str(r.get("i")), "trade_id": str(r.get("t")), "client_id": r.get("c"),
                               "side": r.get("S"), "price": str(r.get("L")), "qty": str(r.get("l")),
                               "commission": str(r.get("n") or 0), "realized_pnl": str(r.get("rp") or 0),
                               "time": int(r.get("T") or 0)})
                    del fs[:-40]
                # durable before the next reconcile: a restart must still see fills the stream already delivered
                self.save()
        except Exception as e:  # noqa: BLE001
            log.error("exit order note failed: %r", e)

    def _loss_to_stop(self, qty, fill, stop, side: int = 1):
        """Same loss model as sizing.py / the entry alert: stop distance + round-trip taker fees + both slippages."""
        sz = self.cfg.sizing
        return qty * side * (fill - stop) + qty * fill * (2 * TAKER_FEE + D(sz.entry_slippage) + D(sz.stop_slippage))

    def _trade_line(self, j, rec, entry_fills, exit_fills, t_x) -> dict:
        q = lambda x, e: None if x is None else str(x.quantize(Decimal(e)))   # noqa: E731
        s = int(j.get("side", 1))
        qty, fill = D(rec["entry_qty"]), D(j["entry_px"])        # ptp-short: the ENTRY qty, not the remainder
        stop0 = D(rec["init_stop_px"])
        sig = D(j["signal_px"]) if j.get("signal_px") is not None else None
        raw = rec["reason"].split(" ")[0]
        kind = EXIT_KIND.get(raw, "halt" if raw.startswith("emergency") else "other")
        # slippage of the LAST exit leg vs the trigger of the order that filled it: TP1/TP2 price for a TP, the stop
        # price live at the close (the BE stop after the move) for the stop, the book ref for our market exits.
        # Not the qty-weighted average of all legs vs the stop (that mixed the TP1 leg in).
        legs, tp = rec.get("exit_legs") or [], j.get("tp") or {}
        last = max(legs, key=lambda g: g["time"] or 0) if legs else None
        xpx = D(last["price"]) if last else D(rec["exit_px"])
        lcid = {str(x["id"]): str(x.get("client_id") or "") for x in j.get("exit_orders") or []}.get(
            str(last["order_id"]) if last else "", "")
        suf = lcid[len(j["cid"]):] if lcid.startswith(j["cid"]) else ""
        if suf in ("t1", "t2") and tp.get("tp" + suf[1]):
            ref = D(tp["tp" + suf[1]])
        elif suf == "p" or (suf[:1] == "s" and suf[1:].isdigit()) or (not suf and kind == "exchange_close"):
            ref = D(j["stop_px"])
        else:
            ref = D(j["exit_ref"]) if j.get("exit_ref") else None
        t_in = max((f["time"] for f in entry_fills), default=None) or j.get("entry_fill_ms")
        t_out = t_x if exit_fills else None
        xs = j.get("exit_orders") or []
        lo, hi = j.get("mk_lo"), j.get("mk_hi")
        adv, fav = (lo, hi) if s > 0 else (hi, lo)
        mae = s * (fill - D(adv)) / fill if adv is not None else None
        mfe = s * (D(fav) - fill) / fill if fav is not None else None
        per_r = abs(fill - stop0) / fill if stop0 != fill else None    # 1 R (= the record R unit) as a fraction of entry
        net = D(rec["net"])
        ef, e4 = j.get("earlycut_fav"), j.get("earlycut_px_at_4h")
        mfe4 = max(Decimal(0), s * (D(ef) - fill) / fill / per_r) if ef is not None and per_r else (Decimal(0) if per_r else None)
        fire = None if e4 is None or mfe4 is None else bool(
            not j.get("earlycut_tp1_at_4h") and mfe4 < Decimal("0.5") and s * (D(e4) - fill) < 0)
        return {
            "trade_id": j["cid"], "coin": rec["sym"], "side": "long" if s > 0 else "short",
            "path": {"q0": "normal"}.get(j.get("path"), j.get("path")),
            "signal_time": j.get("signal_ms"), "signal_time_kst": kst(j.get("signal_ms")),
            "signal_price": None if sig is None else str(sig),
            "entry_order_time": j.get("order_ms"), "entry_fill_time": t_in, "entry_fill_time_kst": kst(t_in),
            "entry_fill_price": str(fill), "entry_slip_bp": q(s * (fill - sig) / sig * 10000, "0.01") if sig else None,
            "qty": str(qty), "notional": str(qty * fill), "leverage": j.get("lev"), "wallet_at_entry": j.get("wallet_at_entry"),
            "stop_price": str(stop0), "stop_dist_frac": q(s * (fill - stop0) / fill, "0.000001"),
            "stop_confirmed_time": j.get("stop_confirmed_ms"), "stop_confirmed_time_kst": kst(j.get("stop_confirmed_ms")),
            "planned_risk_pct": j.get("risk_pct_used"),
            "actual_risk_pct": rec["actual_risk_pct"],                 # incl. round-trip fees + slippage model
            "price_risk_pct": q(qty * abs(fill - stop0) / D(j["wallet_at_entry"]) * 100, "0.0001")
            if j.get("wallet_at_entry") and D(j["wallet_at_entry"]) > 0 else None,   # qty x |entry - initial stop| only
            "open_risk_sum_after_entry": None if j.get("open_risk_after") is None else round(float(j["open_risk_after"]) * 100, 6),
            "same_side_open_count": j.get("same_side_open"),
            "exit_time": t_out, "exit_time_kst": kst(t_out), "exit_price": str(xpx),
            "exit_reason": kind, "exit_reason_raw": rec["reason"],
            "exit_order_type": (xs[-1].get("orig_type") or xs[-1].get("type")) if xs else None,
            "exit_order_ids": [x["id"] for x in xs],
            "exit_slip_bp": q(s * (ref - xpx) / ref * 10000, "0.01") if ref and xpx > 0 else None,
            "exit_slip_ref": None if ref is None else str(ref),
            "fee_entry": str(sum((f["commission"] for f in entry_fills), Decimal(0))),
            "fee_exit": str(sum((f["commission"] for f in exit_fills), Decimal(0))),
            "funding_sum": rec["funding"], "pnl_gross": rec["gross"], "pnl_net": rec["net"],
            "R_net": q(net / (qty * abs(fill - stop0)), "0.0001") if stop0 != fill and qty > 0 else None,   # = record R
            "entry_qty": rec["entry_qty"], "remaining_qty": rec["remaining_qty"], "tp1_qty": rec["tp1_qty"],
            "tp1_frac_actual": rec["tp1_frac_actual"], "exit_legs": rec["exit_legs"], "exit_price_avg": rec["exit_px_avg"],
            "hold_minutes": round(((t_out or rec["closed_ms"]) - (t_in or rec["opened_ms"])) / 60000, 2),
            "MFE_frac": q(mfe, "0.000001") if mfe is not None else None,
            "MAE_frac": q(mae, "0.000001") if mae is not None else None,
            "MFE_R": q(mfe / per_r, "0.0001") if mfe is not None and per_r else None,
            "MAE_R": q(mae / per_r, "0.0001") if mae is not None and per_r else None,
            "mae_mfe_source": "mark", "mark_gaps": j.get("mark_gaps", []),
            "earlycut_would_fire": fire, "earlycut_px_at_4h": e4, "earlycut_t_4h": j.get("earlycut_t_4h"),   # record-only
            "earlycut_tp1_at_4h": j.get("earlycut_tp1_at_4h"), "mfe_R_4h": q(mfe4, "0.0001") if mfe4 is not None else None,
            "fills_source": rec["source"], "code_commit": self.events.commit}

    def _daily_line(self):
        """One line per UTC day, written on the first tick after 00:00 UTC for the day that just ended (the 📊 summary
        stays on KST). Peak wallet is sampled from the reconciled wallet."""
        if self.events is None:
            return
        try:
            now = self.now_ms()
            day = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d")
            w = self.meta.get("wallet")
            if w is not None and (self.meta.get("peak_wallet") is None or D(w) > D(self.meta["peak_wallet"])):
                self.meta["peak_wallet"] = str(w)
            last = self.meta.get("log_daily_utc")
            self.meta["log_daily_utc"] = day
            if last is None or last == day:
                return
        except Exception as e:  # noqa: BLE001
            log.error("daily log failed: %r", e)
            return
        self._emit("daily", lambda: self._daily_rec(last, now))

    def _daily_rec(self, day, now) -> dict:
        c = self.meta.get("log_day", {}).get(day, {})
        w, pk = self.meta.get("wallet"), self.meta.get("peak_wallet")
        try:
            if self.cfg.daily_loss_halt:                 # distance to the current day −10 % line (00:00 UTC baseline)
                eq, thr = self._daily_equity()
            else:
                _, eq, thr = self.drawdown_breached()
            dist = str(((eq - thr) / eq * 100).quantize(Decimal("0.01"))) if eq and thr is not None else None
        except Exception:  # noqa: BLE001
            eq, dist = self.meta.get("equity"), None
        ops = []
        for sym, j in list(self.st["pos"].items()) + list(self.st["unknown"].items()):
            if sym in self.st["pos"] and self._closed_flat_confirmed(sym, j):
                continue                                    # flat, waiting on fills: not an open position
            m, e, n = self.marks.get(sym), j.get("entry_px"), j.get("qty") or j.get("amt")
            u = (D(m) - D(e)) * D(n) * int(j.get("side", 1)) if m is not None and e and n else None
            ops.append({"coin": sym, "side": "long" if int(j.get("side", 1)) > 0 else "short", "qty": n,
                        "uPnL": None if u is None else str(u), "known": sym in self.st["pos"]})
        trades = sum(1 for r in self.meta.get("trades", [])
                     if datetime.fromtimestamp(int(r.get("closed_ms", 0)) / 1000, timezone.utc).strftime("%Y-%m-%d") == day)
        return {"date": day, "time": now, "time_kst": kst(now), "wallet": w, "equity": self.meta.get("equity"),
                "open_positions": ops, "open_risk_sum": round(self._open_risk_pct(), 6),
                "drawdown_from_peak": str(((D(pk) - D(w)) / D(pk) * 100).quantize(Decimal("0.01"))) if w and pk and D(pk) > 0 else None,
                "distance_to_halt": dist, "trades_today": trades, "skips_today": c.get("skips", 0),
                "incidents": c.get("incidents", 0), "log_write_fail": c.get("log_write_fail", 0),
                "code_commit": self.events.commit}

    @staticmethod
    def _opened_qty(j, entry_fills) -> Decimal:
        """Opened size the close must cover.

        ``entry_qty`` when the journal has it. Otherwise the opening-side fills: legacy rows from before that field
        keep only the post-TP1 remainder in ``j['qty']``, and using that remainder makes a complete close look
        over-filled. The journal qty is the last resort, when those entry fills are not in the read.
        """
        if j.get("entry_qty") not in (None, ""):
            return D(j["entry_qty"])
        got = sum((D(f["qty"]) for f in entry_fills), Decimal(0))
        return got if got else D(j["qty"])

    @staticmethod
    def _entry_fills(j, fills, opened) -> list:  # noqa: ARG004  opened kept so callers stay stable
        """Entry fills are the entry order's rows only. A time window would pull in a neighbor's trade."""
        eid = j.get("entry_order_id")
        if not eid:
            return []
        return [f for f in fills if str(f.get("order_id")) == str(eid)]

    def _own_exit_order_ids(self, sym, j) -> set[str]:
        """Exchange order ids of THIS trade's SL / TP / close orders. Not a time window."""
        ids = set()
        base = str(j.get("cid") or "")

        def _keep(oid, client) -> bool:
            if oid in (None, "", "None"):
                return False
            c = str(client or "")
            return (not c) or (bool(base) and c.startswith(base))

        for o in (j.get("exit_orders") or []) + (j.get("own_orders") or []):
            if _keep(o.get("id"), o.get("client_id")):
                ids.add(str(o["id"]))
        for f in j.get("stream_fills") or []:
            if _keep(f.get("order_id"), f.get("client_id")):
                ids.add(str(f["order_id"]))
        cid = str(j.get("cid") or "")
        if not cid:
            return ids
        tp = j.get("tp") or {}
        cids = [f"{cid}p"]
        if tp.get("tp1"):
            cids.append(f"{cid}t1")
        if tp.get("tp2"):
            cids.append(f"{cid}t2")
        if tp.get("tp3"):
            cids.append(f"{cid}t3")
        for extra in (j.get("tp_cids") or {}).values():
            if extra and str(extra) not in cids:
                cids.append(str(extra))
        cids += [f"{cid}s{i}" for i in range(int(j.get("stop_seq") or 0))]
        cids += [f"{cid}x{i}" for i in range(int(j.get("exit_seq") or 0))]
        for c in cids:
            try:
                st = self.x("algo_order", sym, c)
            except ExchangeError:
                st = None
            if isinstance(st, dict) and st.get("order_id") not in (None, "", "None"):
                ids.add(str(st["order_id"]))
            try:
                od = self.x("get_order", sym, c)
            except ExchangeError:
                od = None
            if isinstance(od, dict) and od.get("id") not in (None, "", "None"):
                ids.add(str(od["id"]))
        return ids

    @staticmethod
    def _row_amt(pos, sym):
        """Explicit amount from a positions snapshot, or None when `sym` is absent. Absence is unknown, not flat."""
        row = pos.get(sym) if isinstance(pos, dict) else None
        if not isinstance(row, dict) or row.get("amt") is None:
            return None
        return row["amt"]

    def _position_amt(self, sym):
        """(amount, ok). A failed read, or a symbol missing from the response, clears the flat confirmation so the
        journal counts in risk again. Only an explicit amount of 0 is flat."""
        try:
            syms = tuple(dict.fromkeys((*self.cfg.symbols, sym)))
            pos = self.x("positions", syms)
        except ExchangeError:
            self._flat_confirmed.discard(sym)
            return None, False
        amt = self._row_amt(pos, sym)
        if amt is None:
            self._flat_confirmed.discard(sym)
            return None, False
        if amt == 0:
            self._flat_confirmed.add(sym)
        else:
            self._flat_confirmed.discard(sym)
        return amt, True

    def _mark_pending(self, sym, j, reason, why):
        """Fills are not safe to book (missing trade id, or this trade's own orders over-filled). Stay open."""
        j["close_held"] = True
        j["reconcile_pending"] = True
        j.setdefault("close_reason", reason)
        n = int(j.get("pending_n") or 0) + 1
        j["pending_n"] = n
        log.error("%s close reconcile pending: %s", sym, why)
        if n == 1 or n % CLOSE_HOLD_MAX == 0:
            self.alert(f"청산 대조 보류 — {sym}", f"{why} · {n}회 대조")
        self.save()

    @classmethod
    def _dedupe_trade_ids(cls, fills) -> list:
        """One REST row per trade id. A duplicated id would be counted as extra quantity."""
        seen = set()
        out = []
        for f in fills:
            tid = cls._fill_id(f)
            if tid:
                if tid in seen:
                    continue
                seen.add(tid)
            out.append(f)
        return out

    @staticmethod
    def _fill_id(f) -> str:
        tid = str(f.get("trade_id") or "")
        return "" if tid in ("", "None", "0") else tid

    @classmethod
    def _as_fill(cls, f) -> dict:
        return {"order_id": str(f["order_id"]), "trade_id": cls._fill_id(f), "side": f.get("side"),
                "price": D(f["price"]), "qty": D(f["qty"]), "commission": D(f.get("commission") or 0),
                "realized_pnl": D(f.get("realized_pnl") or 0), "time": int(f.get("time") or 0),
                "client_id": f.get("client_id")}

    @classmethod
    def _merge_exit_fills(cls, rest, stream) -> list:
        """Union userTrades with user-stream fills by trade id.

        A remainder often fills as several partials of one order (SOL 2026-11-02, order 254785178715, four trade ids).
        Dropping every stream fill whose order id is already in userTrades throws away the slices REST has not indexed
        yet. Trade ids make the union exact. Rows with no trade id keep the older rule: use the stream's fills for
        that order only when they cover strictly more quantity (a partial REST slice, the stream saw the whole order).
        """
        rest_f = [cls._as_fill(f) for f in rest]
        seen, stream_f = set(), []
        for f in stream or []:
            g = cls._as_fill(f)
            if g["trade_id"]:
                if g["trade_id"] in seen:
                    continue
                seen.add(g["trade_id"])
            stream_f.append(g)
        rest_ids = {f["trade_id"] for f in rest_f if f["trade_id"]}
        rest_by, stream_by = {}, {}
        for f in rest_f:
            rest_by.setdefault(f["order_id"], []).append(f)
        for f in stream_f:
            stream_by.setdefault(f["order_id"], []).append(f)
        out = list(rest_f)
        for oid, sfs in stream_by.items():
            rfs = rest_by.get(oid)
            if not rfs:
                out.extend(sfs)
                continue
            if any(f["trade_id"] for f in rfs):
                out.extend(f for f in sfs if f["trade_id"] and f["trade_id"] not in rest_ids)
                continue
            if sum((f["qty"] for f in sfs), Decimal(0)) > sum((f["qty"] for f in rfs), Decimal(0)):
                out = [f for f in out if f["order_id"] != oid]
                out.extend(sfs)
        return out

    def _hold_close(self, sym, j, opened_qty, closed_qty, reason, *, fetch_failed=False):
        """Leave the position journal open and warn once. The next reconcile reads again.

        An under-qty hold counts toward CLOSE_HOLD_MAX. A failed userTrades or income read does not: that gap must
        not commit on a timer with entry fees or funding missing.
        """
        j["close_held"] = True
        j.setdefault("close_reason", reason)                 # halt / signal / time_exit survive the next reconcile
        if fetch_failed:
            log.error("%s close record held: fill read failed (exit %s, opened %s)", sym, closed_qty, opened_qty)
        else:
            n = int(j.get("close_hold_n") or 0) + 1
            j["close_hold_n"] = n
            log.error("%s close record held: exit qty %s != opened qty %s", sym, closed_qty, opened_qty)
            if n == 1 or n % CLOSE_HOLD_MAX == 0:
                self.alert(f"청산 기록 보류 — {sym} 체결 수량 미확정",
                           f"열린 {opened_qty.normalize():f} · 청산 체결 {closed_qty.normalize():f}"
                           f" · 종료로 기록하지 않음 · {n}회 대조")
        if fetch_failed and not j.get("close_incomplete_alerted"):
            j["close_incomplete_alerted"] = True
            self.alert(f"청산 기록 보류 — {sym} 체결 조회 실패",
                       f"열린 {opened_qty.normalize():f} · 청산 체결 {closed_qty.normalize():f}"
                       f" · 종료로 기록하지 않음 · 다음 대조에서 다시 조회")
        self.save()

    def record_close(self, sym, reason):
        """Book the close, or leave the journal open.

        Returns ``("flat", 0)`` only when the freshest position read is 0 (the caller may cancel protective
        orders), ``("open", amt)`` when that read is nonzero, or ``("unknown", None)`` when it failed. A later
        nonzero or a failed read is not a flat confirmation, and it must not be followed by a cancel.
        """
        j = self.st["pos"].get(sym)
        if not j:
            return "flat", Decimal(0)
        opened = int(j.get("opened_ms", self.now_ms()))
        amt, ok = self._position_amt(sym)
        if not ok:
            return "unknown", None
        if amt != 0:
            return "open", amt
        fund, entry_fills, raw_exit = [], [], []
        own = self._own_exit_order_ids(sym, j)
        stream = [f for f in (j.get("stream_fills") or []) if str(f.get("order_id")) in own]
        # the closing fill can lag userTrades (live SOL 2026-11-01). The first attempt re-reads query_retries times;
        # once the journal is already held, one poll per reconcile so other symbols are not stalled on the sleeps.
        retries = 1 if j.get("close_held") else self.cfg.query_retries
        try:
            for i in range(retries):
                if i:
                    self.sleep(self.cfg.query_delay_s)
                raw_rows = self.x("user_trades", sym, opened - 60_000)
                # Before dedupe or the REST/stream merge: an own-order row with no trade id is not bookable,
                # even when another row of that same order already has an id (the merge would drop the id-less one).
                raw_own = [f for f in raw_rows if str(f.get("order_id")) in own]
                if any(not self._fill_id(f) for f in raw_own) or any(not self._fill_id(f) for f in stream):
                    self._mark_pending(sym, j, reason, "체결 id 없는 청산 체결 · 손익 기록 안 함")
                    return "flat", Decimal(0)
                fills = self._dedupe_trade_ids(raw_rows)
                entry_fills = self._entry_fills(j, fills, opened)
                raw_exit = [f for f in fills if str(f.get("order_id")) in own]
                want = self._opened_qty(j, entry_fills)
                got = self._merge_exit_fills(raw_exit, stream)
                if got and not any(not self._fill_id(f) for f in got) and sum((f["qty"] for f in got), Decimal(0)) == want:
                    break
            fund = self.x("income", sym, "FUNDING_FEE", opened)
        except ExchangeError as e:
            log.error("%s fills fetch failed, close record held: %s", sym, e)
            want = self._opened_qty(j, entry_fills)
            closed = sum((f["qty"] for f in self._merge_exit_fills(raw_exit, stream)), Decimal(0))
            self._hold_close(sym, j, want, closed, reason, fetch_failed=True)
            return "flat", Decimal(0)                         # the position read was 0; the fill read is what failed
        want = self._opened_qty(j, entry_fills)
        exit_fills = self._merge_exit_fills(raw_exit, stream)
        if any(not self._fill_id(f) for f in exit_fills):
            self._mark_pending(sym, j, reason, "체결 id 없는 청산 체결 · 손익 기록 안 함")
            return "flat", Decimal(0)
        closed_qty = sum((f["qty"] for f in exit_fills), Decimal(0))
        if closed_qty > want:
            self._mark_pending(sym, j, reason,
                               f"이 거래 주문 체결 {closed_qty.normalize():f} > 열린 {want.normalize():f} · 손익 기록 안 함")
            return "flat", Decimal(0)
        if closed_qty < want:
            self._hold_close(sym, j, want, closed_qty, reason)   # stays open; the bound only re-alerts
            return "flat", Decimal(0)
        self.st["pos"].pop(sym, None)
        gross = sum((f["realized_pnl"] for f in exit_fills), Decimal(0))
        fees = sum((f["commission"] for f in entry_fills + exit_fills), Decimal(0))
        funding = sum((r["amount"] for r in fund), Decimal(0))
        xq = sum((f["qty"] for f in exit_fills), Decimal(0))
        xpx = sum((f["price"] * f["qty"] for f in exit_fills), Decimal(0)) / xq if xq else Decimal(0)
        net = gross - fees + funding
        # ptp-short: 1R = ENTRY qty x |entry - INITIAL stop| (TP1 shrinks j["qty"]; the BE move changes j["stop_px"]);
        # journals from before this change have no entry_qty -> the entry order fills, then the journal qty
        eq = want                                              # opened size (legacy: opening fills, not the post-TP1 remainder)
        e0, stop0 = D(j["entry_px"]), D(j.get("stop_px_entry") or j["stop_px"])
        risk = eq * abs(e0 - stop0)
        w0 = D(j.get("wallet_at_entry") or "0")
        tp1q = D(j["tp"]["q1"]) if j.get("tp1_done") and j.get("tp") else Decimal(0)
        legs = {}
        for f in exit_fills:                                     # one leg per exit order (TP1 / TP2 / stop / close)
            g = legs.setdefault(str(f["order_id"]), [Decimal(0), Decimal(0), f["time"]])
            g[0] += f["qty"]
            g[1] += f["price"] * f["qty"]
            g[2] = max(g[2], f["time"])
        nz = lambda x: f"{x.normalize():f}"                    # noqa: E731
        exit_legs = [{"order_id": k, "price": nz(g[1] / g[0]), "qty": nz(g[0]), "time": g[2]} for k, g in legs.items() if g[0]]
        # which exit order filled each leg (stream exit_orders / stream fills); a flat-at-reconcile close has no
        # close_reason / exit_fill and used to default to "stop_loss" even when TP2 or the BE stop closed it
        cids = {str(o.get("id")): o.get("client_id") or "" for o in (j.get("exit_orders") or []) + [
            {"id": f["order_id"], "client_id": f.get("client_id")} for f in j.get("stream_fills") or []]}
        suf = lambda k: cids.get(k, "")[len(j["cid"]):] if cids.get(k, "").startswith(j["cid"]) else ""   # noqa: E731
        # a held default of stop_loss must still be reclassified from the last leg; a real stored reason must not
        if (exit_legs and reason == "stop_loss" and not j.get("exit_fill")
                and j.get("close_reason") in (None, "", "stop_loss")):
            last_suf = suf(max(exit_legs, key=lambda g: g["time"] or 0)["order_id"])
            if last_suf.startswith("t"):
                reason = "take_profit"
            elif j.get("trailed") and (last_suf.startswith("s") or not last_suf):
                reason = "trail_stop"       # after a trailing move the only stop left is the trailed stop
            elif j.get("be_done") and (last_suf.startswith("s") or not last_suf):
                reason = "be_stop"          # after the BE move the only stop left is the BE stop (no stream: algo fill cid unknown)
        rec = {"sym": sym, "cid": j["cid"], "reason": reason, "qty": str(eq), "entry_px": j["entry_px"], "exit_px": str(xpx),
               "stop_px": j["stop_px"], "opened_ms": opened, "model_entry_open": j.get("model_entry_open"),
               "lev": j.get("lev"), "wallet_at_entry": j.get("wallet_at_entry"), "risk_frac": j.get("risk_frac"), "closed_ms": self.now_ms(), "gross": str(gross), "fees": str(fees),
               "funding": str(funding), "net": str(net), "planned_R": "-1",
               "R": str((net / risk).quantize(Decimal("0.001"))) if risk > 0 else None,
               "source": "exchange" if exit_fills else "estimate",
               # qty = entry_qty (the traded size); remaining_qty = journal qty at the close (after TP1)
               "entry_qty": str(eq), "remaining_qty": j["qty"], "tp1_qty": str(tp1q),
               "tp1_frac_actual": str((tp1q / eq).quantize(Decimal("0.0001"))) if eq > 0 else None,
               "init_stop_px": str(stop0), "risk_usdt_1R": str(risk),
               "actual_risk_pct": str((self._loss_to_stop(eq, e0, stop0, int(j.get("side", 1))) / w0 * 100)
                                      .quantize(Decimal("0.0001"))) if w0 > 0 else None,
               "exit_legs": exit_legs, "exit_px_avg": str(xpx)}       # exit_px = exit_px_avg (qty-weighted, kept for old readers)
        rec["outcome"] = REASON_KO.get(reason.split(" ")[0], reason)   # TA: TP1 then the BE stop = "1차 익절 후 본절"
        t_x = max((f["time"] for f in exit_fills), default=self.now_ms())
        if reason.split(" ")[0] not in MODEL_EXITS:              # exchange stop / safety close, not a model exit
            if self.strategy.on_live_closed(sym, j.get("model_entry_open"), reason, t_x, self):
                rec["model_closed"] = "stop_out"
                self.st["strategy"] = self.strategy.state
        self.meta.setdefault("trades", []).append(rec)
        del self.meta["trades"][:-1000]
        self.save()
        lab = {"t1": "TP1", "t2": "TP2", "t3": "+3R", "p": "손절"}
        leg_lines = []
        for x in sorted(exit_legs, key=lambda g: g["time"] or 0):
            k = x["order_id"]
            sx = suf(k)
            name = lab.get(sx) or ("추적손절" if sx.startswith("s") and j.get("trailed") else "본절" if sx.startswith("s") and j.get("be_done") else "손절" if sx.startswith("s") else "청산")
            fx = [f for f in exit_fills if str(f["order_id"]) == k]
            leg_lines.append(f"• {name} {x['qty']}@{x['price']} 손익 {sum((f['realized_pnl'] for f in fx), Decimal(0)):+.4f}"
                             f" · 수수료 {sum((f['commission'] for f in fx), Decimal(0)):.4f}")
        efee = sum((f["commission"] for f in entry_fills), Decimal(0))
        self.notify(f"{'🔴' if net < 0 else '🔵'} 청산 {sym} {'롱' if int(j.get('side', 1)) > 0 else '숏'} · {REASON_KO.get(reason.split(' ')[0], reason)}\n"
                     f"전체 순손익 {net:+.4f} USDT" + (f" · {rec['R']}R" if rec["R"] else "")
                     + f" (수수료 {fees:.4f} · 펀딩 {funding:+.4f})\n"
                     f"수량 {eq} · {j['entry_px']} → {'평균 ' if len(exit_legs) > 1 else ''}{xpx:.8g}"
                     + (" (" + " / ".join(f"{x['qty']}@{x['price']}" for x in exit_legs) + ")" if len(exit_legs) > 1 else "")
                     + f" · 손절 {j['stop_px']}\n"
                     + "\n".join(leg_lines + [f"• 진입 수수료 {efee:.4f}"]), kind="exit", event_ms=t_x)
        self._emit("trades", lambda: dict(self._trade_line(j, rec, entry_fills, exit_fills, t_x), outcome=rec["outcome"]))
        self.check_halts(daily=False)   # daily-loss check runs at the end of reconcile
        return "flat", Decimal(0)

    def _realization_unreadable(self) -> bool:
        """True while a realization cid still cannot be queried. That is not a reason to drop UNKNOWN_ORDER."""
        for sym, j in (self.st.get("pos") or {}).items():
            if not isinstance(j, dict):
                continue
            for row in (j.get("tp_market_once") or {}).values():
                if not isinstance(row, dict) or not row.get("cid"):
                    continue
                try:
                    self.x("get_order", sym, str(row["cid"]))
                except ExchangeError:
                    return True
        return False

    # ───────────────────────── reconcile (exchange → local) ─────────────────────────
    def reconcile(self):
        self._gate_state()
        self._fresh_blocks = set()
        self._armed_now = set()
        self._in_reconcile = True
        if self.st["intents"] and not self._schema_lock:
            self.resolve_intents()                              # unknown entry outcomes first (by client id)
        acct = self.x("account")
        try:
            pos = self.x("positions", self.cfg.symbols)
        except ExchangeError:
            self._flat_confirmed.clear()                    # unknown size: keep every journal in the risk sum
            raise
        # Apply the whole snapshot before any per-symbol read. A later symbol must not keep a stale flat
        # flag when an earlier symbol's open_orders (or any other follow-up) raises. A symbol with no row
        # is unknown: drop any stale flat confirmation. Only an explicit amount of 0 is flat.
        for sym in self.cfg.symbols:
            amt0 = self._row_amt(pos, sym)
            if amt0 == 0:
                self._flat_confirmed.add(sym)
            else:
                self._flat_confirmed.discard(sym)
        try:
            marks = self.x("mark_prices")
        except ExchangeError:
            marks = {}
        self.meta["wallet"] = str(acct["wallet"])
        self.meta["equity"] = str(acct.get("equity", acct["wallet"]))
        mismatch = []
        book_unread = False
        for sym in self.cfg.symbols:
            amt = self._row_amt(pos, sym)
            if amt is None:
                book_unread = True                       # a missing row is not a clean pass
                continue                                 # unknown: keep the journal in risk, do not cancel SL/TP
            j = self.st["pos"].get(sym)
            try:
                orders = self.x("open_orders", sym)
            except ExchangeError as e:
                # Unreadable book: do not place a TP and do not flatten. An open position still
                # fails the pass so a later symbol is not reconciled on a half-read.
                if j and amt not in (None, 0) and not j.get("closing"):
                    since = self._book_down_since.get(sym)
                    now = self.clock()
                    if since is None:
                        self._book_down_since[sym] = now
                    elif now - since >= self.cfg.transient_alert_s and sym not in self._tp_unknown:
                        self._tp_unknown.add(sym)
                        self.alert(f"보호 점검 보류 — {sym}", f"주문 상태 불명 · 익절 주문 안 냄 · {e}")
                    raise
                book_unread = True                      # flat or no journal: do not treat the pass as consistent
                continue
            self._tp_unknown.discard(sym)
            self._book_down_since.pop(sym, None)
            filled = None
            if j and amt != 0 and not self._schema_lock:       # exit order missing → its exchange status decides
                r = self._exit_fills(sym, j, amt, orders)
                if r is False:
                    continue                                    # closing fill still being applied → next reconcile
                if r is not None:
                    amt, orders, filled = r
                    try:                                        # the mark predates the fill too → re-read
                        marks[sym] = self.x("mark_prices")[sym]
                    except (ExchangeError, KeyError):
                        marks.pop(sym, None)
            if amt == 0 and j:
                # record_close re-reads. A newer nonzero, or a failed read, replaces this snapshot: do not cancel.
                verdict, fresh = self.record_close(sym, j.get("close_reason") or j.get("exit_fill") or "stop_loss")
                if verdict == "flat":
                    self._clear_symbol_holds(sym)           # exchange flat does not go through _after_flat
                elif verdict == "open":
                    amt = fresh
                else:
                    side = 1 if int(j.get("side", 1)) > 0 else -1
                    amt = D(j.get("qty") or 0) * side or Decimal(side)
            if amt == 0:
                u = self.st["unknown"].pop(sym, None)
                if u is not None:                               # TA R4: resolved by hand (or its stop fired)
                    self.save()
                    self.notify(f"✅ 기록 없는 포지션 해소 — {sym} {u.get('amt')} 거래소에서 0 · 이 코인 신규 진입 재개", kind="recovery")
                pending = tuple(f"{c}p" for c in self.st["intents"])        # pre-arm of an unresolved entry stays
                failed, foreign = [], []
                for o in orders:
                    if (str(o["client_id"]).startswith(self.cfg.cid_prefix) and (o["close_position"] or o["reduce_only"])
                            and str(o["client_id"]) not in pending):
                        try:
                            self.x("cancel", sym, o)                 # our own stale stop, position flat
                        except ExchangeError as e:
                            failed.append((str(o["client_id"]), e))  # retried next reconcile; R3 alert below
                    elif not (o["close_position"] or o["reduce_only"]) and str(o["client_id"]).startswith(self.cfg.cid_prefix):
                        mismatch.append(f"{sym} 예상 밖 진입 주문 {o['client_id']}")
                    elif not str(o["client_id"]).startswith(self.cfg.cid_prefix) and (o["close_position"] or o["reduce_only"]):
                        foreign.append(o)                            # TA R3/R4: alert only for reducing (SL/TP) orders; never cancelled
                self._residual_watch(sym, failed, foreign)
                if f"{MARGIN}:{sym}" in self.blocks:
                    self.ensure_isolated(sym)
                continue
            if j is None:
                if any(it.get("sym") == sym for it in self.st["intents"].values()):
                    mismatch.append(f"{sym} 진입 결과 확인 중 {amt}")     # our own unresolved entry (pre-arm protects it)
                    continue
                # TA condition 1 (2026-10-26): an orphan pre-arm (entry definitively rejected, its cancel failed, no intent) is the BOT's own
                # order protecting nothing. It must never count as protection of a position the bot does not own, and it is cancelled
                # right away (after _unknown_position, whether or not that position has a stop): left alive it could close the user's
                # position at the bot's price (R4: the bot never closes a position it did not open). The unprotected alert is separate.
                orphans = [o for o in orders if self._is_orphan_prearm(o)]
                self._unknown_position(sym, pos[sym], [o for o in orders if o not in orphans], marks.get(sym))   # TA R4: never closed
                for o in orphans:
                    self._cancel_quiet(sym, o)
                continue
            if sym in self.st["unknown"]:                    # adopted into the state file by ops meanwhile
                self.st["unknown"].pop(sym, None)
                self.save()
            if (amt > 0) != (int(j.get("side", 1)) > 0):
                mismatch.append(f"{sym} 방향 불일치 로컬 {j.get('side', 1)} / 거래소 {amt}")
            if D(j["qty"]) != abs(amt):
                mismatch.append(f"{sym} 수량 불일치 로컬 {j['qty']} / 거래소 {amt}")
                j["qty"] = str(abs(amt))                       # exchange wins
                self.save()
            if not self._schema_lock and j.get("closing"):
                self.close(sym, j.get("close_reason", "retry"))
                continue
            if (not self._schema_lock and self.cfg.max_hold_s and not j.get("closing")
                    and self.now_ms() - int(j.get("opened_ms", self.now_ms())) >= self.cfg.max_hold_s * 1000):
                self.close(sym, "time_exit")                    # 24 h time exit (reduceOnly market)
                continue
            mk = marks.get(sym)
            stp = D(j["stop_px"])
            if mk is not None and ((amt > 0 and mk <= stp) or (amt < 0 and mk >= stp)):
                self.breach_check(sym, mk, "5s reconcile")
                if (self.meta.get("halted") or "").startswith("emergency"):
                    self._in_reconcile = False
                    return
                continue
            if not self.find_stop(amt, orders):
                rearm = sym not in self._cp_hold or self._hold_should_rearm(sym, orders)
                if not rearm:
                    pass                                    # hold stands: empty book is not retried every 5s
                else:
                    if sym not in self._cp_hold:
                        self.alert("손절 주문 없음 — 재등록 시도", f"{sym} {amt} · 손절 {stp}")
                    if not self._arm_stop(sym, j, amt):
                        if sym not in self._cp_hold:
                            left = self.st["pos"].get(sym)
                            held = isinstance(left, dict) and (left.get("close_held") or left.get("reconcile_pending"))
                            if left is not None and not held and getattr(self, "_protect_close_failed", False):
                                try:
                                    fresh = self._row_amt(self.x("positions", self.cfg.symbols), sym)
                                except ExchangeError:
                                    fresh = None
                                if fresh not in (None, 0):
                                    self.emergency_flatten_all(f"unprotected {sym}")
                            if self.meta.get("halted", "") and str(self.meta["halted"]).startswith("emergency"):
                                self._in_reconcile = False
                                return
                            continue
                    else:
                        try:
                            orders = self.x("open_orders", sym)
                        except ExchangeError:
                            continue
                if sym in self._cp_hold and sym not in self._cp_book_sig:
                    self._cp_book_sig[sym] = self._book_sig(orders)
            else:
                self._release_cp_hold(sym)                  # covering stop is visible again
            if self.find_stop(amt, orders) and j.get("unprotected"):
                j.pop("unprotected", None)
                self.save()
            if j.get("stop_lost") and self.find_stop(amt, orders):
                j.pop("stop_lost", None)                    # REST confirms a protective stop again
                self.save()
            prot = self.find_stop(amt, orders)
            mine = next((o for o in orders if j.get("stop_cid") and o["client_id"] == j["stop_cid"]), None)
            if mine and self.find_stop(amt, [mine]):
                prot = mine                                     # the moved (BE) stop is the bot's stop, not an old one
            if prot and prot["stop_price"] > 0 and D(prot["stop_price"]) != stp:
                j["stop_px"] = str(prot["stop_price"])          # §8c L2: the live exchange stop is the truth
                self.save()
            for o in orders:
                if prot and o["id"] == prot["id"]:
                    continue
                if not (o["close_position"] or o["reduce_only"]):
                    mismatch.append(f"{sym} 예상 밖 주문 {o['type']} {o['client_id']}")
                elif (prot and (prot["close_position"] or prot is mine) and o["reduce_only"] and (o["type"] or "").startswith("STOP")
                      and (not o["close_position"] or prot is mine) and str(o["client_id"]).startswith(self.cfg.cid_prefix)):
                    self._cancel_quiet(sym, o)                   # leftover pre-arm / old stop, the bot's stop is live
            if not j.get("closing") and sym in self.st["pos"] and not self._schema_lock:
                if not j.get("tp"):
                    if self.cfg.take_profit:
                        self._place_tps(sym, j)             # missing TP state is attached even during a hold
                        if not self._position_open(sym):
                            continue
                elif prot:
                    self._manage_tps(sym, j, amt, orders, mk)
                elif sym in self._cp_hold:
                    self._manage_tps(sym, j, amt, orders, mk, hold=True)
            if (prot and self.cfg.trail_atr_k and not self._schema_lock
                    and sym in self.st["pos"] and not self.st["pos"][sym].get("closing")):
                self._trail(sym, self.st["pos"][sym], amt, mk)
        if mismatch:
            self._consistent = 0
            self.block(MISMATCH, "; ".join(mismatch), "대조 불일치 — 신규 진입 중단")
        elif book_unread:
            pass                                            # unread only blocks a clean pass from advancing or clearing
        else:
            self._consistent += 1
            if self._consistent >= 2:
                for r in (MISMATCH, UNKNOWN_ORDER):
                    if r in self.blocks and r not in self._fresh_blocks:
                        if r == UNKNOWN_ORDER and self._realization_unreadable():
                            continue                    # a failed query is not a successful one
                        self.unblock(r)
        self.save()
        self._audit_protection_if_due()
        self._in_reconcile = False
        self._armed_now = set()
        self.check_ledger()
        self.check_halts()

    def _audit_protection_if_due(self):
        if self.clock() - self._protect_audit_at < PROTECT_AUDIT_S:
            return
        self._protect_audit_at = self.clock()
        self.audit_protection()

    def _read_open_orders_all(self):
        """One open-order read for every symbol when the adapter can do it. Otherwise one read per symbol."""
        if callable(getattr(self.ex, "open_orders_all", None)):
            return self.x("open_orders_all")
        rows = []
        for sym in self.cfg.symbols:
            rows.extend(self.x("open_orders", sym))
        return rows

    def audit_protection(self):
        """Once a minute: each known nonzero position has its SL and its stage TP. Missing → retry, then market
        close. A symbol absent from the positions response is unknown: this pass does not cancel or close it."""
        if not getattr(self, "_in_reconcile", False):
            self._armed_now = set()                 # a direct audit is not the reconcile that just armed
        if not self.st.get("pos"):
            return
        try:
            pos = self.x("positions", self.cfg.symbols)
        except ExchangeError as e:
            log.error("protection audit positions: %s", e)
            return
        need = []
        for sym, j in self.st["pos"].items():
            if not isinstance(j, dict) or j.get("closing"):
                continue
            amt = self._row_amt(pos, sym)
            if amt is None or amt == 0:
                continue                                   # unknown or flat: never cancel from this pass
            need.append((sym, j, amt))
        if not need:
            return
        try:
            orders = self._read_open_orders_all()
        except ExchangeError as e:
            log.error("protection audit orders: %s", e)
            return
        for sym, j, amt in need:
            if sym not in self.st["pos"]:
                continue
            self._audit_symbol(sym, self.st["pos"][sym], amt, [o for o in orders if o.get("symbol") == sym])

    def _audit_symbol(self, sym, j, amt, orders):
        if not self._position_open(sym):
            return
        self._bind_runner(sym, j, amt)
        if not self.find_stop(amt, orders) or self._tp_repairs(j, amt, orders):
            try:                                            # bundled book can be empty or partial: confirm this symbol
                orders = self.x("open_orders", sym)
            except ExchangeError as e:
                log.error("%s audit order read unknown — SL/TP left untouched", sym)
                since = self._book_down_since.get(sym)
                now = self.clock()
                if since is None:
                    self._book_down_since[sym] = now        # same 60s rule as a reconcile read failure
                elif now - since >= self.cfg.transient_alert_s and sym not in self._audit_unknown:
                    self._audit_unknown.add(sym)
                    self.alert(f"보호 점검 보류 — {sym}", f"주문 조회 불가 · 손절·익절 유지 · {e}")
                return
        self._audit_unknown.discard(sym)
        self._book_down_since.pop(sym, None)            # a successful confirm ends the outage window
        seen = self.find_stop(amt, orders)
        already = sym in self._armed_now
        if seen:
            self._release_cp_hold(sym)                      # covering stop is visible: the -4130 hold may alert again
        elif not already and sym in self._cp_hold and self._hold_should_rearm(sym, orders):
            if not self._arm_stop(sym, j, amt) or not self._position_open(sym):
                if not self._position_open(sym) or sym not in self._cp_hold:
                    return
        elif not already and sym not in self._cp_hold:
            if not self._arm_stop(sym, j, amt) or not self._position_open(sym):
                if not self._position_open(sym) or sym not in self._cp_hold:
                    return
        if not self._position_open(sym):
            return
        if not j.get("tp"):
            if self.cfg.take_profit:
                self._place_tps(sym, j)                     # no tp state yet: initialize and place
            return
        if sym in self._cp_hold and not self.find_stop(amt, orders):
            return                                          # contradictory book: do not re-place from it
        for which, px, qty, wt in self._tp_repairs(j, amt, orders):
            self._place_tp(sym, j, which, px, qty, working_type=wt)
            if not self._position_open(sym):
                return

    def _tp_repairs(self, j, amt, orders):
        """Missing take-profits the audit must put back. Legacy restores t2 (+2R). Scheme E restores the +3R runner."""
        tp = j.get("tp") or {}
        have = {o.get("client_id") for o in orders}
        out = []
        if tp.get("tp1") and not j.get("tp1_done") and self._tp_cid(j, "t1") not in have:
            out.append(("t1", D(tp["tp1"]), D(tp["q1"]), "CONTRACT_PRICE"))
        if tp.get("tp2") and not j.get("tp2_done") and self.cfg.tp2_r and self._tp_cid(j, "t2") not in have:
            out.append(("t2", D(tp["tp2"]), D(tp.get("q2") or abs(amt)), "CONTRACT_PRICE"))
        if self._runner_due(j) and not j.get("tp3_done") and tp.get("tp3") and self._tp_cid(j, "t3") not in have:
            out.append(("t3", D(tp["tp3"]), D(tp.get("q3") or abs(amt)), "MARK_PRICE"))
        return out

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
            if self._schema_lock:
                u.pop("closing", None)                      # keep placing a stop; the market stays gated
            else:
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
                if self._schema_lock:
                    self._lock_hold_alert(sym, "unknown_stop_rejected",
                                          f"거부 {u.get('stop_rejects')}회 · 손절 재시도 · 시장가 안 냄")
                else:
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
        if self._schema_lock:
            log.warning("%s unknown last-resort close refused: schema lock", sym)
            return
        seq = int(u.get("exit_seq", 0))
        u["exit_seq"] = seq + 1
        self.save()
        cid = f"{self.cfg.cid_prefix}{sym.removesuffix('USDT')}u{int(u['detected_ms']) // 1000}x{seq}"
        try:
            self.submit_market(sym, "SELL" if amt > 0 else "BUY", abs(amt), cid, reduce_only=True)
            left = self._row_amt(self.x("positions", self.cfg.symbols), sym)
        except ExchangeError as e:
            log.error("%s unknown position last-resort close failed (retry next reconcile): %s", sym, e)
            return
        if left is None:
            return                                          # missing row is not a confirmed flat
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
        if self.cfg.halt_fraction is None:               # qrmtf: replaced by the daily-loss halt
            return False, eq, None
        thr = c0 * D(self.cfg.halt_fraction)
        return c0 > 0 and eq <= thr, eq, thr

    # ── daily-loss halt (qrmtf, user 2026-10-30) ──
    def _daily_equity(self):
        # (equity incl. unrealised − transfers booked since the day baseline, the day line) or (None, None)
        b = self.meta.get("dl_base")
        if not b or self.meta.get("equity") is None:
            return None, None
        adj = D(self.meta["equity"]) - (D(self.meta.get("net_transfers", "0")) - D(self.meta.get("dl_tr", "0")))
        return adj, D(b) * (1 - D(str(self.cfg.daily_loss_halt)))

    def check_daily_halt(self):
        # daily-loss halt (user 2026-10-30): equity ≤ (1 − daily_loss_halt) × equity at 00:00 UTC → close all, 24 h no entries
        if not self.cfg.daily_loss_halt or self.meta.get("equity") is None:
            return
        now = self.now_ms()
        dh = self.meta.get("daily_halt")
        if dh and now >= int(dh["until_ms"]):            # 24 h after the trigger → auto-resume (survives restarts)
            self.meta.pop("daily_halt")
            if str(self.meta.get("halted") or "").startswith("daily_loss"):
                self.meta.pop("halted")
            self.save()
            self.notify(f"✅ 일일 손실 중단 해제 — 24시간 경과 · 신규 진입 재개 (중단 시각 {kst(int(dh['trigger_ms']))})",
                        kind="resume")
        day = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d")
        if self.meta.get("dl_day") != day:               # 00:00 UTC (09:00 KST): new baseline = equity now
            base = D(self.meta["equity"])
            if self.meta.get("dl_day") is None:          # first start mid-day: back out today's realised income (one
                try:                                     # income read; uPnL of positions open at 00:00 is not known)
                    d0 = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
                    base -= sum((r["amount"] for r in self.x("income", None, None, d0) if r["type"] != "TRANSFER"), D(0))
                except ExchangeError as e:
                    log.warning("daily halt: income read failed, baseline = equity now: %s", e)
            self.meta.update(dl_day=day, dl_base=str(base), dl_tr=self.meta.get("net_transfers", "0"))
            self.save()
            return
        if self.meta.get("halted") or self.meta.get("daily_halt"):
            # A schema halt already occupies `halted`. This −10% flatten is unchanged and
            # sends only after the operator clears that lock. It is not removed.
            return
        adj, line = self._daily_equity()
        if adj is None or adj > line:
            return
        if "start_wallet" in self.meta:                  # fresh transfer sync: a withdrawal must not look like a loss
            self._last_income = -1e18
            self.check_ledger()
            adj, line = self._daily_equity()
            if adj > line:
                return
        self._daily_halt_trigger(now, adj, line)

    def _daily_halt_trigger(self, now, adj, line):
        base, pct = D(self.meta["dl_base"]), int(round(self.cfg.daily_loss_halt * 100))
        until = now + int(self.cfg.daily_halt_s * 1000)
        reason = f"daily_loss: 자산 {adj:.2f} ≤ {line:.2f} (00:00 UTC {base:.2f} −{pct}%)"
        upnl, marks = {}, dict(self.marks)
        if self.st["pos"] and not marks:
            try:
                marks = self.x("mark_prices")
            except ExchangeError:
                pass
        for sym, j in self.st["pos"].items():
            m, e = marks.get(sym), j.get("entry_px")
            if m is not None and e:
                upnl[sym] = (D(m) - D(e)) * D(j["qty"]) * int(j.get("side", 1))
        self.meta["halted"] = reason
        self.meta["daily_halt"] = {"trigger_ms": now, "until_ms": until, "day_start_equity": str(base),
                                   "equity_at_trigger": str(adj), "line": str(line)}
        self.save()
        self._emit("daily", lambda: {"event": "halt", "halt_reason": "daily_loss", "detail": reason, "trigger_time": now,
                                     "trigger_time_kst": kst(now), "resume_time_kst": kst(until), "day_start_equity": str(base),
                                     "equity_at_trigger": str(adj), "line": str(line),
                                     "positions": sorted(self.st["pos"]), "code_commit": self.events.commit})
        for sym in list(self.st["pos"]):                 # state-file positions only (TA R4: unknown ones keep their stop)
            self.close(sym, "daily_loss_halt")           # reduceOnly MARKET; _after_flat cancels the bot orders → 0 residual
        self.alert(f"일일 손실 −{pct}% — 전 포지션 청산 · 24시간 신규 진입 중단",
                   f"자산 {adj:.2f} ≤ {line:.2f} (오늘 시작 {base:.2f}) · 재개 {kst(until)}\n" + self._daily_halt_lines(now, upnl))

    def _daily_halt_lines(self, now, upnl) -> str:
        # one line per trade of the UTC day (incl. the ones just closed) + per position still open: coin, side, PnL, entry scores
        d0 = now // 86_400_000 * 86_400_000
        fn = getattr(self.strategy, "entry_scores", None)
        def tside(t):    # trade recs carry no side (fixed schema): gross = side × (exit − entry) × qty
            mv = D(t["exit_px"]) - D(t["entry_px"])
            return 1 if mv == 0 or (D(t["gross"]) >= 0) == (mv > 0) else -1

        rows = [(t["sym"], tside(t), f"실현 {D(t['net']):+.2f}", int(t.get("opened_ms") or 0))
                for t in self.meta.get("trades", []) if int(t.get("closed_ms") or 0) >= d0]
        rows += [(s, int(j.get("side", 1)), f"미실현 {upnl[s]:+.2f}" if s in upnl else "미실현 ?", int(j.get("opened_ms") or 0))
                 for s, j in self.st["pos"].items()]
        out = []
        for sym, side, pnl, opened in rows[-12:]:
            sc = fn(sym, opened) if fn else None
            out.append(f"• {sym.removesuffix('USDT')} {'롱' if side > 0 else '숏'} {pnl}" + (f" · {sc}" if sc else ""))
        return "\n".join(out) or "오늘 거래 없음"

    def check_halts(self, daily=True):
        self._peak_guard()
        if daily:                                        # not from record_close: a close inside the reconcile loop must not
            self.check_daily_halt()                      # flatten other coins mid-loop (stale snapshot → false unknown)
        if "start_wallet" not in self.meta:
            return
        hit, adj, thr = self.drawdown_breached()
        if hit and not self.meta.get("halted"):
            self._last_income = -1e18                       # a fresh transfer sync first: a withdrawal not yet
            self.check_ledger()                             # booked must not look like a loss
            hit, adj, thr = self.drawdown_breached()
        if hit and not self.meta.get("halted"):
            # Same deferral as the daily −10% rule: a schema lock already halted the bot,
            # so this drawdown flatten does not send. The call itself stays.
            if self._schema_lock:
                log.warning("drawdown flatten deferred: schema lock — exchange stops stay")
            else:
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
        self._daily_line()
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
            held = [s for s, jj in self.st["pos"].items()
                    if isinstance(jj, dict) and (jj.get("close_held") or jj.get("reconcile_pending"))]
            self.notify(f"💓 작동 중 · 잔고 {D(self.meta.get('wallet', '0')):.2f} USDT · 포지션 {self._open_position_count()}개"
                         + (f" · 기록 없는 포지션 {','.join(self.st['unknown'])}" if self.st["unknown"] else "")
                         + (f" · 청산 미확정 {','.join(sorted(held))}" if held else "")
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
        lines.append("보유: " + (", ".join(f"{s} {j['qty']} @ {j['entry_px']} 손절 {j['stop_px']}"
                                           for s, j in self.st["pos"].items() if not self._closed_flat_confirmed(s, j))
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
        mins = self.strategy.decision_interval_ms // 60000
        tf = f"{mins // 60}시간" if mins >= 60 and mins % 60 == 0 else f"{mins}분"   # 4h → 4시간, qrmtf 1m → 1분
        lbc = int(self.meta.get("last_bar_close") or 0)
        due = min(T, lbc + self.strategy.decision_interval_ms) if lbc else T   # oldest uncommitted boundary (1m: T moves every minute)
        if behind and self.now_ms() - due > self.cfg.bar_stale_s * 1000:
            detail = f"봉 {datetime.fromtimestamp(T / 1000, KST):%m-%d %H:%M} KST 마감 미반영 · " + ", ".join(behind)[:300]
            if BAR_STALE not in self.blocks:
                self.block(BAR_STALE, detail)
                self._block_alerted.add(BAR_STALE)
                self.alert(f"{tf} 봉 마감 {self.cfg.bar_stale_s:.0f}초 넘게 미반영 — 신규 진입 차단 (포지션·손절 유지, 정리 안 함)",
                           detail, event_ms=due)
            else:
                self.blocks[BAR_STALE] = detail
        elif not behind and BAR_STALE in self.blocks:
            self.blocks.pop(BAR_STALE, None)
            self._block_since.pop(BAR_STALE, None)
            self._block_alerted.discard(BAR_STALE)
            self.notify(f"✅ {tf} 봉 마감 반영 완료 — {'신규 진입 재개' if self.entries_allowed() else '다른 차단 사유 남음: ' + ','.join(self.blocks)}",
                        kind="recovery")

    def healthy(self) -> bool:
        """Dead-man ping only while: started, not halted, last REST reconcile succeeded within 3× reconcile_s, no
        position flagged unprotected, bar decisions current (no stale-bar block)."""
        return (self.started and not self.meta.get("halted") and self.clock() - self._last_ok_reconcile <= 3 * self.cfg.reconcile_s
                and BAR_STALE not in self.blocks
                and not any(j.get("unprotected") for j in self.st["pos"].values())
                and not any(u.get("unprotected") for u in self.st["unknown"].values()))
