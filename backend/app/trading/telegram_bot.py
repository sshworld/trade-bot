"""텔레그램 봇 명령어 수신 모듈.

/status — 현재 상태 요약 (잔고, 포지션, 시그널)
/position — 열린 포지션 상세
"""

import asyncio
import logging
import time
from decimal import Decimal

import httpx

from app.config import settings

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

                    # 본인 chat_id만 응답
                    if chat_id != self._chat_id:
                        continue

                    if text.startswith("/status"):
                        await self._handle_status(chat_id)
                    elif text.startswith("/position"):
                        await self._handle_position(chat_id)
                    elif text.startswith("/help"):
                        await self._handle_help(chat_id)

            except Exception as e:
                logger.error(f"[TG_BOT] Polling error: {e}")
                await asyncio.sleep(5)

    def stop(self):
        self._running = False

    async def _send(self, chat_id: str, text: str):
        if len(text) > 4000:
            text = text[:3997] + "..."
        client = await self._get_client()
        await client.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )

    async def _handle_help(self, chat_id: str):
        await self._send(chat_id,
            "🤖 <b>Trade Bot Commands</b>\n\n"
            "/status — 현재 상태 요약\n"
            "/position — 열린 포지션 상세\n"
            "/help — 명령어 목록"
        )

    async def _handle_status(self, chat_id: str):
        from app.trading.engine import trading_engine
        from app.tasks.scheduler import latest_results, ENTRY_TIMEFRAMES

        status = trading_engine.get_status()
        balance = Decimal(status["balance"])
        equity = Decimal(status["equity"])
        margin_used = Decimal(status["margin_used"])
        unrealized = Decimal(status["unrealized_pnl"])
        daily_pnl = Decimal(status["daily_pnl"])
        total_fees = Decimal(status["total_fees"])
        trades = status["daily_trades"]
        total_trades = status["total_trades"]
        positions_count = status["open_positions_count"]
        win_rate = status["win_rate"]
        halted = status["anomaly"]["is_halted"]
        available = balance - margin_used

        # 포지션 상세 (현재가, TP, SL 포함)
        pos_summary = ""
        if positions_count > 0:
            pos_list = trading_engine.get_open_positions()
            for p in pos_list:
                side_icon = "🟢" if p["side"] == "long" else "🔴"
                pnl_icon = "📈" if float(p["unrealized_pnl"]) >= 0 else "📉"
                pos_summary += (
                    f"\n{side_icon} <b>{p['side'].upper()} {p.get('leverage', 5)}x</b>"
                    f" | {p['quantity']} BTC @ ${p['avg_entry_price']}"
                    f"\n💲 <b>현재:</b> ${p['mark_price']}"
                    f"\n{pnl_icon} <b>PnL:</b> ${p['unrealized_pnl']} ({p['pnl_percent']:+.2f}%)"
                    f"\n🛑 <b>SL:</b> ${p['stop_loss_price']}"
                    f"\n🎯 <b>진입:</b> {p['filled_entries']}/{p['total_entries']}"
                    f" | <b>익절:</b> {p['filled_exits']}/{p['total_exits']}"
                )
                # TP 목록
                for o in p.get("exit_orders", []):
                    s = "✅" if o["status"] == "filled" else "⏳" if o["status"] in ("pending", "waiting") else "❌"
                    tp_pct = ""
                    if p["avg_entry_price"] and float(p["avg_entry_price"]) > 0:
                        diff = abs(float(o["price"]) - float(p["avg_entry_price"])) / float(p["avg_entry_price"]) * 100
                        tp_pct = f" ({diff:.1f}%)"
                    pos_summary += f"\n  {s} TP ${o['price']}{tp_pct} × {o['qty']}"

        # 시그널 상황
        signal_lines = []
        for tf in ["30m", "1h", "4h"]:
            r = latest_results.get(tf)
            if not r:
                continue
            bull = r.get("bull_score", 0)
            bear = r.get("bear_score", 0)
            conf = r.get("confluence_count", 0)
            bull_fam = r.get("bull_families", 0)
            bear_fam = r.get("bear_families", 0)
            dom = "🟢" if bull > bear else "🔴" if bear > bull else "⚪"
            conf_mark = " ✅" if conf > 0 else ""
            signal_lines.append(
                f"  {dom} <b>{tf}</b>: B{bull:.1f}({bull_fam}f) / S{bear:.1f}({bear_fam}f){conf_mark}"
            )
        signals_text = "\n".join(signal_lines) if signal_lines else "  데이터 없음"

        filter_state = status.get("filter_state", "normal")
        filter_icons = {
            "boost": "🚀 BOOST", "normal": "✅ NORMAL",
            "caution": "⚠️ CAUTION", "critical": "🔶 CRITICAL", "stop": "🔴 STOP",
        }
        filter_label = filter_icons.get(filter_state, filter_state)
        state = "🔴 HALTED" if halted else ("📈 포지션 보유" if positions_count > 0 else "⏳ 대기 중")
        daily_icon = "📈" if daily_pnl >= 0 else "📉"
        unreal_icon = "💚" if unrealized >= 0 else "💔"

        msg = (
            f"📊 <b>STATUS</b> — {state}\n"
            f"🎚 <b>필터:</b> {filter_label}\n"
            f"{'━' * 28}\n\n"
            f"💰 <b>잔고:</b> <code>${balance:,.2f}</code>\n"
            f"💎 <b>평가:</b> <code>${equity:,.2f}</code>\n"
            f"🏦 <b>가용:</b> <code>${available:,.2f}</code>\n"
            f"🔒 <b>마진:</b> <code>${margin_used:,.2f}</code>\n"
            f"{unreal_icon} <b>미실현:</b> <code>${unrealized:,.2f}</code>\n\n"
            f"{daily_icon} <b>금일 PnL:</b> <code>${daily_pnl:,.2f}</code>"
            f" | 거래 {trades}건\n"
            f"📊 <b>누적:</b> 총 {total_trades}건"
            f" | 승률 {win_rate}%"
            f" | 수수료 ${total_fees:,.2f}\n"
        )

        if pos_summary:
            msg += f"\n{'━' * 28}\n<b>📌 포지션</b>{pos_summary}\n"

        msg += f"\n{'━' * 28}\n<b>📡 시그널</b>\n{signals_text}"

        await self._send(chat_id, msg)

    async def _handle_position(self, chat_id: str):
        """포지션 상세 → /status로 통합."""
        await self._handle_status(chat_id)


telegram_bot = TelegramBot()
