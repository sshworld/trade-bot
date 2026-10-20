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
from app.trading.tg_format import anomaly_push_text, fmt_alert, record_incident

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
        """텔레그램 전송. 경미한 경고는 로그만 (tg_format.anomaly_push_text 정책)."""
        text = anomaly_push_text(alert)
        if text is None:
            logger.info(
                f"[TG] push suppressed (log only): [{alert.severity}] {alert.rule_name} — {alert.message} "
                f"details={json.dumps(alert.details, default=str)}"
            )
            return
        record_incident(alert.timestamp or None)

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

    # public alias — bot 명령 핸들러 / 신규 호출 지점에서 사용
    async def send_text(self, text: str):
        await self._send_telegram_text(text)

    async def push_alert(self, title: str, detail: str = "", action: str = ""):
        """장애/안전 이벤트 즉시 푸시 (🚨, 최대 3줄) + 일일 incidents 집계."""
        record_incident()
        logger.warning(f"[TG] safety alert: {title} | {detail} | {action}")
        await self._send_telegram_text(fmt_alert(title, detail, action))

    async def send_photo(self, image_bytes: bytes, caption: str = ""):
        """PNG/JPG 이미지 전송. /chart 명령 등에서 사용."""
        if not self._telegram_token or not self._telegram_chat_id:
            logger.warning("Telegram not configured, skipping photo")
            return
        if len(caption) > 1000:
            caption = caption[:997] + "..."
        url = f"https://api.telegram.org/bot{self._telegram_token}/sendPhoto"
        client = await self._get_client()
        files = {"photo": ("chart.png", image_bytes, "image/png")}
        data = {
            "chat_id": self._telegram_chat_id,
            "caption": caption,
            "parse_mode": "HTML",
        }
        resp = await client.post(url, data=data, files=files)
        if resp.status_code != 200:
            logger.error(f"Telegram sendPhoto error: {resp.status_code} {resp.text}")

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
