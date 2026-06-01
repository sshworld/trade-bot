"""텔레그램 봇 명령어 수신 모듈.

명령:
  /status   — 현재 상태 요약 (잔고, 포지션, 시그널)
  /position — /status alias
  /signal   — 8TF 시그널 스냅샷 (점수/패밀리/conf/reject)
  /detail   — 포지션 상세 (TP 도달, 트레일링, 보유 시간)
  /history  — 최근 거래 N건 (default 10)
  /equity   — 최근 30일 PnL 텍스트 그래프
  /halt     — 수동 매매 중단
  /resume   — 수동 중단 해제
  /chart    — 캔들 PNG 차트 (S3, charting 모듈 의존)
  /help     — 명령어 목록
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
            if cmd == "/status" or cmd == "/position":
                await self._handle_status(chat_id)
            elif cmd == "/signal":
                await self._handle_signal(chat_id)
            elif cmd == "/detail":
                await self._handle_detail(chat_id)
            elif cmd == "/history":
                limit = _parse_int(args[0] if args else "10", default=10, lo=1, hi=50)
                await self._handle_history(chat_id, limit)
            elif cmd == "/equity":
                await self._handle_equity(chat_id)
            elif cmd == "/halt":
                await self._handle_halt(chat_id, " ".join(args) if args else "")
            elif cmd == "/resume":
                await self._handle_resume(chat_id)
            elif cmd == "/chart":
                tf = args[0] if args else "1h"
                await self._handle_chart(chat_id, tf)
            elif cmd == "/help":
                await self._handle_help(chat_id)
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

    async def _handle_help(self, chat_id: str):
        await self._send(
            chat_id,
            "🤖 <b>Trade Bot Commands</b>\n\n"
            "📊 <b>상태</b>\n"
            "/status — 잔고/포지션/시그널 요약\n"
            "/signal — 8TF 시그널 스냅샷\n"
            "/detail — 포지션 상세 (TP/트레일링/보유시간)\n"
            "/history [N] — 최근 N건 거래 (default 10)\n"
            "/equity — 최근 PnL 그래프\n"
            "/chart [TF] — 캔들 차트 PNG (TF: 5m/15m/30m/1h/4h/1d)\n\n"
            "🛑 <b>운영</b>\n"
            "/halt [사유] — 수동 매매 중단\n"
            "/resume — 수동 중단 해제\n\n"
            "/help — 이 메시지",
        )

    async def _handle_status(self, chat_id: str):
        from app.trading.engine import trading_engine
        from app.tasks.scheduler import latest_results

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

        pos_summary = ""
        if positions_count > 0:
            for p in trading_engine.get_open_positions():
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
                for o in p.get("exit_orders", []):
                    s = "✅" if o["status"] == "filled" else "⏳" if o["status"] in ("pending", "waiting") else "❌"
                    tp_pct = ""
                    if p["avg_entry_price"] and float(p["avg_entry_price"]) > 0:
                        diff = abs(float(o["price"]) - float(p["avg_entry_price"])) / float(p["avg_entry_price"]) * 100
                        tp_pct = f" ({diff:.1f}%)"
                    pos_summary += f"\n  {s} TP ${o['price']}{tp_pct} × {o['qty']}"

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

    async def _handle_signal(self, chat_id: str):
        from app.tasks.scheduler import latest_results

        all_tfs = ["5m", "15m", "30m", "1h", "4h", "1d"]
        lines = [f"📡 <b>SIGNAL — 8TF Snapshot</b>", "━" * 28]

        for tf in all_tfs:
            r = latest_results.get(tf)
            if not r:
                lines.append(f"<b>{tf}</b>: 데이터 없음")
                continue
            bull = r.get("bull_score", 0)
            bear = r.get("bear_score", 0)
            bull_fam = r.get("bull_families", 0)
            bear_fam = r.get("bear_families", 0)
            conf_count = r.get("confluence_count", 0)
            dom = "🟢" if bull > bear else "🔴" if bear > bull else "⚪"
            lines.append(
                f"{dom} <b>{tf}</b>  B{bull:.1f}({bull_fam}f) / S{bear:.1f}({bear_fam}f) | conf={conf_count}"
            )
            for conf in r.get("confluence", [])[:3]:
                direction_icon = "🟢" if conf.get("direction") == "bullish" else "🔴"
                reject = conf.get("reject_reason", "")
                tag = f" ❌{reject}" if reject else " ✅"
                msg = conf.get("message", "")[:60]
                lines.append(f"  {direction_icon} {msg}{tag}")

        await self._send(chat_id, "\n".join(lines))

    async def _handle_detail(self, chat_id: str):
        from app.trading.engine import trading_engine

        positions = trading_engine.get_open_positions()
        if not positions:
            await self._send(chat_id, "📭 열린 포지션 없음")
            return

        now_ms = int(time.time() * 1000)
        lines = []
        for p in positions:
            side_icon = "🟢" if p["side"] == "long" else "🔴"
            entry = Decimal(p["avg_entry_price"]) if p["avg_entry_price"] else Decimal("0")
            sl = Decimal(p["stop_loss_price"]) if p["stop_loss_price"] else Decimal("0")
            mark = Decimal(p["mark_price"]) if p["mark_price"] else Decimal("0")
            held_ms = now_ms - p.get("opened_at", now_ms)
            held_h = held_ms / 3_600_000
            sig_msg = (p.get("signal_message") or "")[:80]

            lines.append(
                f"{side_icon} <b>{p['side'].upper()} {p.get('leverage', 5)}x</b>\n"
                f"  진입가  ${entry}\n"
                f"  현재가  ${mark}  ({p['pnl_percent']:+.2f}%)\n"
                f"  SL     ${sl}\n"
                f"  보유   {held_h:.1f}h"
            )

            tp_lines = []
            for i, o in enumerate(p.get("exit_orders", []), 1):
                s = "✅" if o["status"] == "filled" else "⏳" if o["status"] in ("pending", "waiting") else "❌"
                fp = o.get("filled_price") or "-"
                tp_lines.append(f"  TP{i} {s} ${o['price']} × {o['qty']} (fill ${fp})")
            if tp_lines:
                lines.append("\n".join(tp_lines))

            entry_lines = []
            for i, o in enumerate(p.get("entry_orders", []), 1):
                s = "✅" if o["status"] == "filled" else "⏳" if o["status"] in ("pending", "waiting") else "❌"
                fp = o.get("filled_price") or "-"
                entry_lines.append(f"  E{i} {s} ${o['price']} × {o['qty']} (fill ${fp})")
            if entry_lines:
                lines.append("\n".join(entry_lines))

            lines.append(f"  시그널: {sig_msg}")
            lines.append("━" * 28)

        await self._send(chat_id, "📌 <b>POSITION DETAIL</b>\n" + "━" * 28 + "\n" + "\n".join(lines))

    async def _handle_history(self, chat_id: str, limit: int):
        from app.trading.engine import trading_engine

        history = trading_engine.get_trade_history(limit=limit, offset=0)
        trades = history.get("trades", [])
        total = history.get("total", 0)
        if not trades:
            await self._send(chat_id, "📭 거래 기록 없음")
            return

        lines = [f"📜 <b>HISTORY</b> — 최근 {len(trades)}/{total}건", "━" * 28]
        for t in trades:
            side = t.get("side", "?").upper()
            side_icon = "🟢" if side == "LONG" else "🔴"
            pnl = Decimal(str(t.get("realized_pnl", "0")))
            pnl_icon = "📈" if pnl >= 0 else "📉"
            entry = t.get("avg_entry_price") or t.get("entry_price") or "-"
            exit_p = t.get("avg_exit_price") or t.get("exit_price") or "-"
            closed_ms = t.get("closed_at", 0)
            closed_str = time.strftime("%m-%d %H:%M", time.localtime(closed_ms / 1000)) if closed_ms else "-"
            reason = t.get("close_reason", "")[:20]
            lines.append(
                f"{side_icon} {closed_str} {side} ${entry}→${exit_p} {pnl_icon} ${pnl:+.2f} <i>{reason}</i>"
            )

        await self._send(chat_id, "\n".join(lines))

    async def _handle_equity(self, chat_id: str):
        from app.trading.persistence import load_daily_snapshots

        snaps = load_daily_snapshots()[:30]  # 최근 30일 (DESC)
        if not snaps:
            await self._send(chat_id, "📭 일일 스냅샷 없음")
            return

        snaps = list(reversed(snaps))  # 오래된 → 최근
        max_abs = max(abs(float(s["pnl"])) for s in snaps) or 1.0

        lines = [f"📈 <b>EQUITY</b> — 최근 {len(snaps)}일", "━" * 28]
        cum = 0.0
        for s in snaps:
            pnl = float(s["pnl"])
            cum += pnl
            bar_len = int(abs(pnl) / max_abs * 12)
            bar = ("█" * bar_len) if pnl >= 0 else ("█" * bar_len)
            color = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"<code>{s['date'][5:]}</code> {color}{bar:<12} <code>${pnl:+8.2f}</code> (Σ${cum:+.2f})"
            )

        await self._send(chat_id, "\n".join(lines))

    async def _handle_halt(self, chat_id: str, reason: str):
        from app.trading.engine import trading_engine

        ad = getattr(trading_engine, "anomaly_detector", None)
        if not ad:
            await self._send(chat_id, "⚠️ anomaly_detector 사용 불가")
            return
        info = ad.set_manual_halt(reason or "manual via telegram /halt")
        await self._send(
            chat_id,
            f"🛑 <b>HALT 활성화</b>\n"
            f"reason: <code>{info.get('halt_reason', '')}</code>\n"
            f"재개: /resume",
        )

    async def _handle_resume(self, chat_id: str):
        from app.trading.engine import trading_engine

        ad = getattr(trading_engine, "anomaly_detector", None)
        if not ad:
            await self._send(chat_id, "⚠️ anomaly_detector 사용 불가")
            return
        info = ad.release_manual_halt()
        await self._send(
            chat_id,
            f"✅ <b>RESUME</b>\n"
            f"manual_halt: <code>{info.get('manual_halt')}</code>\n"
            f"halted: <code>{info.get('is_halted')}</code>",
        )

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


def _parse_int(s: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(s)
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return default


telegram_bot = TelegramBot()
