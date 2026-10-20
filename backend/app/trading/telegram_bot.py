"""텔레그램 봇 명령어 수신 모듈 (단순화, validation spec §13).

기본 명령:
  /status  — 3줄: 잔고·봇상태 / 포지션(진입·SL·TP) / 오늘 손익
  /halt    — 수동 매매 중단
  /resume  — 수동 중단 해제
  /more    — 그 외 명령 목록 (/today, /chart). /help 는 /more 별칭.
보조 (/more 아래):
  /today   — 오늘(KST) 일일 결산
  /chart   — 캔들 PNG 차트
"""

import asyncio
import logging

import httpx

from app.config import settings
from app.trading.tg_format import (
    MORE_TEXT, build_daily_summary, fmt_daily_block, fmt_status, incidents_on, kst_date,
)

logger = logging.getLogger(__name__)


class TelegramBot:
    """텔레그램 봇 명령어 수신 + 응답."""

    def __init__(self):
        self._token = settings.alert_telegram_bot_token
        self._chat_id = settings.alert_telegram_chat_id
        self._client: httpx.AsyncClient | None = None
        self._last_update_id = 0
        self._running = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def start(self):
        """Long polling으로 메시지 수신 시작."""
        if not self._token or not self._chat_id:
            logger.warning("[TG_BOT] Telegram not configured, bot disabled")
            return

        self._running = True
        logger.info("[TG_BOT] Telegram bot started (long polling)")

        while self._running:
            try:
                client = await self._get_client()
                resp = await client.get(
                    f"https://api.telegram.org/bot{self._token}/getUpdates",
                    params={"offset": self._last_update_id + 1, "timeout": 10},
                )
                if resp.status_code != 200:
                    await asyncio.sleep(5)
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    message = update.get("message", {})
                    text = message.get("text", "")
                    chat_id = str(message.get("chat", {}).get("id", ""))

                    if chat_id != self._chat_id:
                        continue

                    await self._dispatch(chat_id, text)

            except Exception as e:
                logger.error(f"[TG_BOT] Polling error: {e}")
                await asyncio.sleep(5)

    def stop(self):
        self._running = False

    async def _dispatch(self, chat_id: str, text: str):
        """명령 → 핸들러 라우팅."""
        text = text.strip()
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:]

        try:
            if cmd == "/status":
                await self._handle_status(chat_id)
            elif cmd == "/halt":
                await self._handle_halt(chat_id, " ".join(args) if args else "")
            elif cmd == "/resume":
                await self._handle_resume(chat_id)
            elif cmd in ("/more", "/help"):
                await self._send(chat_id, MORE_TEXT)
            elif cmd == "/today":
                await self._handle_today(chat_id)
            elif cmd == "/chart":
                tf = args[0] if args else "1h"
                await self._handle_chart(chat_id, tf)
        except Exception as e:
            logger.exception(f"[TG_BOT] handler error for {cmd}")
            await self._send(chat_id, f"⚠️ <b>{cmd}</b> 처리 중 오류: <code>{e}</code>")

    async def _send(self, chat_id: str, text: str):
        if len(text) > 4000:
            text = text[:3997] + "..."
        client = await self._get_client()
        await client.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )

    # ── 핸들러 ────────────────────────────────────────────────

    async def _handle_status(self, chat_id: str):
        from app.trading.engine import trading_engine

        status = trading_engine.get_status()
        pos = None
        for p in trading_engine.get_open_positions()[:1]:
            tp = next((o["price"] for o in p.get("exit_orders", [])
                       if o.get("status") in ("pending", "waiting")), None)
            pos = {"side": p["side"], "qty": p["quantity"], "entry": p["avg_entry_price"],
                   "sl": p["stop_loss_price"], "tp": tp}
        s = today_summary(trading_engine)
        await self._send(chat_id, fmt_status(
            balance=status["balance"], position=pos,
            today_pnl=s["net_pnl_usdt"], today_pct=s["net_pnl_pct"],
            today_trades=s["trades"], halted=bool(status["anomaly"]["is_halted"]),
        ))

    async def _handle_today(self, chat_id: str):
        from app.trading.engine import trading_engine

        await self._send(chat_id, fmt_daily_block(today_summary(trading_engine)))

    async def _handle_halt(self, chat_id: str, reason: str):
        from app.trading.engine import trading_engine

        ad = getattr(trading_engine, "anomaly_detector", None)
        if not ad:
            await self._send(chat_id, "⚠️ anomaly_detector 사용 불가")
            return
        info = ad.set_manual_halt(reason or "manual via telegram /halt")
        await self._send(chat_id, f"🛑 매매 중단 ({info.get('halt_reason', '')})\n재개: /resume")

    async def _handle_resume(self, chat_id: str):
        from app.trading.engine import trading_engine

        ad = getattr(trading_engine, "anomaly_detector", None)
        if not ad:
            await self._send(chat_id, "⚠️ anomaly_detector 사용 불가")
            return
        info = ad.release_manual_halt()
        still = info.get("is_halted")
        await self._send(chat_id, "✅ 수동 중단 해제" + (" · ⚠️ 자동중단 아직 유효" if still else " · 매매 재개"))

    async def _handle_chart(self, chat_id: str, tf: str):
        """S3 의 charting 모듈을 사용해 PNG 전송."""
        try:
            from app.trading.charting import render_chart
        except ImportError:
            await self._send(chat_id, "⚠️ charting 모듈 미설치 (matplotlib 필요)")
            return

        valid_tfs = {"5m", "15m", "30m", "1h", "4h", "1d"}
        if tf not in valid_tfs:
            await self._send(chat_id, f"⚠️ TF 잘못됨: {tf}. 사용: {', '.join(sorted(valid_tfs))}")
            return

        try:
            png_bytes, caption = await render_chart(tf)
        except Exception as e:
            logger.exception("[TG_BOT] chart render failed")
            await self._send(chat_id, f"⚠️ 차트 생성 실패: <code>{e}</code>")
            return

        from app.trading.engine import trading_engine
        if hasattr(trading_engine, "alert_sender"):
            await trading_engine.alert_sender.send_photo(png_bytes, caption=caption)
        else:
            await self._send(chat_id, "⚠️ alert_sender 사용 불가")


def today_summary(engine, date: str | None = None) -> dict:
    """엔진 거래기록으로 KST 일일 결산 dict (date 미지정 = 오늘)."""
    date = date or kst_date()
    trades = getattr(engine, "trade_history", None)
    if trades is None:
        from app.trading.persistence import load_trades
        trades = load_trades()
    acct = getattr(engine, "account", None)
    end_bal = getattr(acct, "balance", None) if acct is not None else None
    return build_daily_summary(
        trades, date, end_balance=end_bal, incidents=incidents_on(date),
        ledger_vs_exchange_balance_diff=getattr(engine, "ledger_vs_exchange_balance_diff", None),
        skipped=engine.skip_counts(date) if hasattr(engine, "skip_counts") else None,
    )


def _parse_int(s: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(s)
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return default


telegram_bot = TelegramBot()
