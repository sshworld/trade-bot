import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

SEND_TIMEOUT_SEC = 2.0


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """모든 연결된 클라이언트에 메시지 브로드캐스트.

        slow client 1명이 전체 broadcast 를 지연시키지 않도록 병렬 send +
        per-client timeout 적용. timeout 또는 예외 발생 클라이언트는 자동 disconnect.
        """
        if not self.active_connections:
            return
        data = json.dumps(message, default=str)
        connections = list(self.active_connections)
        results = await asyncio.gather(
            *(asyncio.wait_for(c.send_text(data), timeout=SEND_TIMEOUT_SEC) for c in connections),
            return_exceptions=True,
        )
        for conn, result in zip(connections, results):
            if isinstance(result, BaseException):
                try:
                    self.active_connections.remove(conn)
                except ValueError:
                    continue
                logger.info(
                    f"Client disconnected ({type(result).__name__}). "
                    f"Total: {len(self.active_connections)}"
                )

    @property
    def client_count(self) -> int:
        return len(self.active_connections)


manager = ConnectionManager()
