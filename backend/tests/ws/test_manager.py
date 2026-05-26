import asyncio
import time

import pytest

from app.ws.manager import ConnectionManager


class FakeWebSocket:
    def __init__(self, delay: float = 0.0, raise_exc: Exception | None = None):
        self.delay = delay
        self.raise_exc = raise_exc
        self.sent: list[str] = []
        self.send_done_at: float | None = None

    async def accept(self):
        return None

    async def send_text(self, data: str):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_exc:
            raise self.raise_exc
        self.sent.append(data)
        self.send_done_at = time.perf_counter()


async def test_broadcast_parallel_dispatches_concurrently():
    """slow client 1명이 1.5초 sleep 해도 빠른 client 는 즉시 받아야 한다."""
    mgr = ConnectionManager()
    slow = FakeWebSocket(delay=1.5)
    fast = FakeWebSocket()
    await mgr.connect(slow)
    await mgr.connect(fast)

    start = time.perf_counter()
    await mgr.broadcast({"type": "tick", "data": {"price": "1"}})
    fast_done_at = fast.send_done_at

    assert fast_done_at is not None, "fast client should have received"
    assert fast_done_at - start < 0.5, (
        f"fast client received at {fast_done_at - start:.3f}s (>= 0.5s — serial)"
    )


async def test_broadcast_disconnects_slow_client_on_timeout():
    """send timeout 초과 client 는 broadcast 후 active_connections 에서 제거된다."""
    mgr = ConnectionManager()
    timeout_client = FakeWebSocket(delay=3.0)  # 2s timeout 초과
    healthy = FakeWebSocket()
    await mgr.connect(timeout_client)
    await mgr.connect(healthy)

    await mgr.broadcast({"type": "tick", "data": {"price": "1"}})

    assert timeout_client not in mgr.active_connections
    assert healthy in mgr.active_connections
    assert len(healthy.sent) == 1


async def test_broadcast_failing_client_does_not_block_others():
    """send 시 raise 하는 client 가 있어도 다른 client 는 정상 수신."""
    mgr = ConnectionManager()
    boom = FakeWebSocket(raise_exc=RuntimeError("boom"))
    healthy = FakeWebSocket()
    await mgr.connect(boom)
    await mgr.connect(healthy)

    await mgr.broadcast({"type": "tick", "data": {"price": "1"}})

    assert boom not in mgr.active_connections
    assert healthy in mgr.active_connections
    assert len(healthy.sent) == 1
