"""Read-only Telegram commands for the live (mainnet) bot: /status, /today, /more (alias /help). No trading commands
(user: /halt and /resume not needed). /chart is not offered (needs matplotlib + extra REST klines on the VPS).

  * mainnet only: runner starts it only when the notifier is live AND configured; never in testnet / tests / replay.
  * only chat id ALLOWED_CHAT (성헌) is answered; every command (any chat) is logged: who / when / what / accepted.
  * long-poll getUpdates (timeout 50 s) on a daemon thread; replies go out on a second daemon thread. The engine
    thread only builds the reply text from in-memory state (no REST, no blocking) via `poll()` (runner loop hook).
  * any failure (network, 409 conflict, bad JSON) is logged by type only (the token is in the URL) with backoff;
    nothing here can raise into, block or crash the engine."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

log = logging.getLogger("live_v6.tgcmd")
ALLOWED_CHAT = 7450291244
KST = timezone(timedelta(hours=9))
COMMANDS = {"/status": "잔고·봇 상태·포지션(진입가/손절)·오늘 손익·돌파까지 거리", "/today": "오늘(KST) 결산", "/more": "명령 목록"}


def _kst(ms) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, KST).strftime("%m-%d %H:%M") if ms else "-"


def _d(x, default="0") -> Decimal:
    try:
        return Decimal(str(x if x not in (None, "") else default))
    except Exception:  # noqa: BLE001
        return Decimal(default)


def today_pnl(eng) -> tuple[Decimal, int, Decimal]:
    day = datetime.fromtimestamp(eng.now_ms() / 1000, KST).strftime("%Y-%m-%d")
    trades = [t for t in eng.meta.get("trades", [])
              if datetime.fromtimestamp(int(t["closed_ms"]) / 1000, KST).strftime("%Y-%m-%d") == day]
    realised = sum((_d(t["net"]) for t in trades), Decimal(0))
    w, w0 = _d(eng.meta.get("wallet")), _d(eng.meta.get("day_start_wallet") or eng.meta.get("wallet"))
    return realised, len(trades), w - w0


def status_text(eng) -> str:
    m = eng.meta
    state = (f"⛔ 중단: {m['halted']}" if m.get("halted") else "✅ 진입 가능" if eng.entries_allowed()
             else "⏸ 진입 보류: " + ", ".join(eng.blocks))
    lines = [f"📟 상태 {_kst(eng.now_ms())} KST",
             f"잔고 {_d(m.get('wallet')):.2f} USDT · 평가 {_d(m.get('equity') or m.get('wallet')):.2f} USDT",
             state,
             f"4h 마감 반영: {_kst(m.get('last_bar_close'))} KST"]
    pos = eng.st.get("pos", {})
    if pos:
        lines.append(f"포지션 {len(pos)}개")
        for s, j in pos.items():
            mk = eng.marks.get(s)
            up = f" · 현재 {mk} (미실현 {(_d(mk) - _d(j['entry_px'])) * _d(j['qty']):+.4f})" if mk is not None else ""
            lines.append(f"  {s} {j['qty']} @ {j['entry_px']} · 손절 {j['stop_px']}{up}")
    else:
        lines.append("포지션 없음")
    r, n, dw = today_pnl(eng)
    lines.append(f"오늘(KST) 실현 {r:+.4f} USDT ({n}건) · 잔고 변화 {dw:+.4f}")
    dist = []
    trig = getattr(eng.strategy, "trigger", None)
    for s in eng.cfg.symbols:
        mk = eng.marks.get(s)
        if trig is None or mk is None or s in pos:
            continue
        try:
            t = trig(s, eng)
        except Exception:  # noqa: BLE001
            t = None
        if t:
            dist.append((float(t) / float(mk) - 1, s, t))
    if dist:
        lines.append("돌파까지: " + " · ".join(f"{s.removesuffix('USDT')} {d * 100:+.2f}%" for d, s, _ in sorted(dist)))
    return "\n".join(lines)


def today_text(eng) -> str:
    day = datetime.fromtimestamp(eng.now_ms() / 1000, KST).strftime("%Y-%m-%d")
    return eng.daily_summary(day).replace("📊 일일 결산", "📊 오늘 결산 (진행 중)", 1)


def more_text() -> str:
    return "명령 목록 (조회 전용)\n" + "\n".join(f"{c} — {d}" for c, d in COMMANDS.items()) + "\n(차트 명령은 지원하지 않아요)"


def reply_for(eng, text: str) -> str:
    cmd = (text or "").strip().split()[0].split("@")[0].lower() if (text or "").strip() else ""
    if cmd == "/status":
        return status_text(eng)
    if cmd == "/today":
        return today_text(eng)
    return more_text()                                   # /more, /help, /start, anything else


class CommandBot:
    def __init__(self, token: str, eng, allowed_chat: int = ALLOWED_CHAT, log_path: str | None = None,
                 http=None, poll_timeout: int = 50, clock=time.time):
        self.token, self.eng, self.allowed = token, eng, int(allowed_chat)
        self.log_path, self.poll_timeout, self.clock = log_path, poll_timeout, clock
        self.http = http or httpx.Client(timeout=poll_timeout + 15)
        self.inbox: queue.Queue = queue.Queue()
        self.outbox: queue.Queue = queue.Queue()
        self.offset = None
        self.stop_flag = threading.Event()
        self.errors = 0
        self.records: list[dict] = []

    # ── network threads ──
    def _api(self, method, **params):
        r = self.http.post(f"https://api.telegram.org/bot{self.token}/{method}", data=params,
                           timeout=self.poll_timeout + 15 if method == "getUpdates" else 10)
        if r.status_code == 409:
            raise RuntimeError("409 conflict (another getUpdates poller or a webhook)")
        r.raise_for_status()
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"telegram ok=false {body.get('error_code')}")
        return body.get("result")

    def _skip_backlog(self):
        res = self._api("getUpdates", offset=-1, timeout=0) or []
        self.offset = (res[-1]["update_id"] + 1) if res else None

    def poll_once(self):
        params = {"timeout": self.poll_timeout, "allowed_updates": json.dumps(["message"])}
        if self.offset is not None:
            params["offset"] = self.offset
        for u in self._api("getUpdates", **params) or []:
            self.offset = u["update_id"] + 1
            self.handle_update(u)

    def handle_update(self, u):
        msg = u.get("message") or {}
        text = str(msg.get("text") or "")
        if not text.startswith("/"):
            return
        chat = (msg.get("chat") or {}).get("id")
        frm = msg.get("from") or {}
        ok = chat == self.allowed
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "msg_ts": msg.get("date"),
               "chat_id": chat, "from_id": frm.get("id"), "username": frm.get("username"), "text": text[:100], "accepted": ok}
        self._log(rec)
        if ok:
            self.inbox.put((chat, text))

    def _log(self, rec):
        self.records.append(rec)
        del self.records[:-200]
        log.warning("tg command %s from chat %s (%s) %s", rec["text"], rec["chat_id"], rec.get("username"),
                    "accepted" if rec["accepted"] else "IGNORED (not allowed)")
        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError as e:
                log.error("command log write failed: %s", e)

    def _poll_loop(self):
        backoff = 5.0
        try:
            self._skip_backlog()                          # commands sent while the bot was down are not replayed
        except Exception as e:  # noqa: BLE001
            log.error("telegram commands: backlog skip failed: %s", type(e).__name__)
        while not self.stop_flag.is_set():
            try:
                self.poll_once()
                backoff = 5.0
            except Exception as e:  # noqa: BLE001  (never the exception text: the token is in the URL)
                self.errors += 1
                log.error("telegram commands: getUpdates failed (%s) → retry in %.0fs", str(e)[:60] if isinstance(e, RuntimeError) else type(e).__name__, backoff)
                self.stop_flag.wait(backoff)
                backoff = min(backoff * 2, 120.0)

    def _send_loop(self):
        while not self.stop_flag.is_set():
            try:
                chat, text = self.outbox.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._api("sendMessage", chat_id=chat, text=text[:4000])
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                log.error("telegram commands: reply failed: %s", type(e).__name__)

    def start(self):
        for fn in (self._poll_loop, self._send_loop):
            threading.Thread(target=fn, daemon=True, name=f"tgcmd-{fn.__name__}").start()
        return self

    def stop(self):
        self.stop_flag.set()

    # ── engine thread (runner loop hook): cheap, in-memory only ──
    def poll(self, max_n: int = 5):
        for _ in range(max_n):
            try:
                chat, text = self.inbox.get_nowait()
            except queue.Empty:
                return
            try:
                out = reply_for(self.eng, text)
            except Exception as e:  # noqa: BLE001
                log.exception("telegram command %s failed", text[:20])
                out = f"⚠️ 명령 처리 실패 ({type(e).__name__})"
            self.outbox.put((chat, out))


def maybe_start(eng, network: str, log_path: str | None = None):
    """Mainnet + live notifier + token only; otherwise None (no thread, no request)."""
    n = eng.tg
    if network != "mainnet" or not getattr(n, "live", False) or not getattr(n, "configured", False):
        return None
    return CommandBot(n.token, eng, log_path=log_path).start()
