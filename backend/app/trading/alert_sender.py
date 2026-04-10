"""알림 전송 모듈 (Telegram + Webhook).

AnomalyDetector가 생성한 AnomalyAlert를 외부로 전송.

설정:
  환경변수 또는 .env:
    ALERT_TELEGRAM_BOT_TOKEN=<bot token>
    ALERT_TELEGRAM_CHAT_ID=<chat id>
    ALERT_WEBHOOK_URL=<optional webhook URL>

2026-04-06 설계.
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict

import httpx

from app.trading.anomaly_detector import AnomalyAlert, AnomalyAction

logger = logging.getLogger(__name__)


class AlertSender:
    """알림 전송기. Telegram + Webhook (선택)."""

    def __init__(
        self,
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        webhook_url: str = "",
    ):
        self._telegram_token = telegram_bot_token
        self._telegram_chat_id = telegram_chat_id
        self._webhook_url = webhook_url
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def send(self, alert: AnomalyAlert):
        """알림 전송. Telegram + Webhook 동시 시도."""
        tasks = []
        if self._telegram_token and self._telegram_chat_id:
            tasks.append(self._send_telegram(alert))
        if self._webhook_url:
            tasks.append(self._send_webhook(alert))

        if not tasks:
            logger.warning(
                "No alert channels configured. Set ALERT_TELEGRAM_BOT_TOKEN + "
                "ALERT_TELEGRAM_CHAT_ID or ALERT_WEBHOOK_URL in .env"
            )
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Alert send failed (channel {i}): {result}")

    async def _send_telegram(self, alert: AnomalyAlert):
        """텔레그램 메시지 전송."""
        emoji = {
            "WARNING": "\u26a0\ufe0f",
            "CRITICAL": "\U0001f6a8",
            "EMERGENCY": "\U0001f198",
        }.get(alert.severity, "\u2753")

        action_label = {
            AnomalyAction.ALERT: "Alert only (trading continues)",
            AnomalyAction.REDUCE: "Position size reduced to 50%",
            AnomalyAction.HALT_SHORT: "Trading HALTED (auto-resume)",
            AnomalyAction.HALT_LONG: "Trading HALTED (auto-resume, extended)",
            AnomalyAction.HALT_MANUAL: "Trading HALTED (MANUAL resume required)",
        }.get(alert.action_taken, str(alert.action_taken))

        resume_info = ""
        if alert.requires_manual_resume:
            resume_info = (
                "\n\n<b>To resume:</b> Set <code>anomaly_manual_resume=true</code> "
                "in config after investigation."
            )
        elif alert.halt_until > 0:
            remaining_sec = max(0, (alert.halt_until - alert.timestamp) // 1000)
            minutes = remaining_sec // 60
            resume_info = f"\n\n<b>Auto-resume in:</b> {minutes} minutes"

        text = (
            f"{emoji} <b>ANOMALY: {alert.rule_name.upper()}</b>\n"
            f"<b>Severity:</b> {alert.severity}\n\n"
            f"{alert.message}\n\n"
            f"<b>Action:</b> {action_label}"
            f"{resume_info}\n\n"
            f"<code>{json.dumps(alert.details, indent=2, default=str)}</code>"
        )

        # Telegram 4096자 제한
        if len(text) > 4000:
            text = text[:3997] + "..."

        url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
        client = await self._get_client()
        resp = await client.post(url, json={
            "chat_id": self._telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        if resp.status_code != 200:
            logger.error(f"Telegram API error: {resp.status_code} {resp.text}")
        else:
            logger.info(f"Telegram alert sent: [{alert.severity}] {alert.rule_name}")

    async def _send_webhook(self, alert: AnomalyAlert):
        """Webhook (JSON POST) 전송."""
        payload = {
            "rule_name": alert.rule_name,
            "severity": alert.severity,
            "action_taken": alert.action_taken.value,
            "message": alert.message,
            "details": alert.details,
            "halt_until": alert.halt_until,
            "requires_manual_resume": alert.requires_manual_resume,
            "timestamp": alert.timestamp,
        }
        client = await self._get_client()
        resp = await client.post(
            self._webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 201, 202, 204):
            logger.error(f"Webhook error: {resp.status_code} {resp.text}")
        else:
            logger.info(f"Webhook alert sent: [{alert.severity}] {alert.rule_name}")

    async def _send_telegram_text(self, text: str):
        """간단한 텍스트 메시지 직접 전송 (AnomalyAlert 없이)."""
        if not self._telegram_token or not self._telegram_chat_id:
            logger.warning("Telegram not configured, skipping message")
            return
        if len(text) > 4000:
            text = text[:3997] + "..."
        url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
        client = await self._get_client()
        resp = await client.post(url, json={
            "chat_id": self._telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        if resp.status_code != 200:
            logger.error(f"Telegram send error: {resp.status_code} {resp.text}")

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
