import asyncio

import pytest

from app.binance.ws_consumer import BinanceWSConsumer, OUTGOING_QUEUE_MAXSIZE


class StubManager:
    def __init__(self):
        self.broadcasted: list[dict] = []

    async def broadcast(self, message: dict):
        self.broadcasted.append(message)


def make_consumer():
    return BinanceWSConsumer(manager=StubManager())


async def test_enqueue_outgoing_when_queue_has_space():
    """큐에 공간 있을 때 메시지가 추가된다."""
    consumer = make_consumer()
    consumer._enqueue_outgoing({"type": "tick", "data": {"price": "1"}})
    assert consumer._outgoing_queue.qsize() == 1


async def test_enqueue_outgoing_drops_oldest_when_full():
    """큐 maxsize 도달 시 oldest drop 후 신규 push."""
    consumer = make_consumer()
    # 큐를 maxsize 까지 채움 (각 메시지 sequence 식별자 부여)
    for i in range(OUTGOING_QUEUE_MAXSIZE):
        consumer._enqueue_outgoing({"seq": i})
    assert consumer._outgoing_queue.qsize() == OUTGOING_QUEUE_MAXSIZE

    # 추가 1개 → 가장 오래된 메시지 (seq=0) 가 drop 되고 새 메시지 (seq=999) 들어감
    consumer._enqueue_outgoing({"seq": 999})
    assert consumer._outgoing_queue.qsize() == OUTGOING_QUEUE_MAXSIZE

    # 큐 비우면서 순서 확인 — seq=0 가 사라지고 seq=1..., seq=999 가 마지막
    drained: list[int] = []
    while not consumer._outgoing_queue.empty():
        drained.append(consumer._outgoing_queue.get_nowait()["seq"])
    assert 0 not in drained
    assert drained[-1] == 999
    assert drained[0] == 1


async def test_process_outgoing_drains_queue_via_broadcast():
    """worker 가 큐의 모든 메시지를 manager.broadcast 로 전달한다."""
    consumer = make_consumer()
    for i in range(5):
        consumer._enqueue_outgoing({"seq": i})

    consumer._running = True
    worker = asyncio.create_task(consumer._process_outgoing())
    # 큐가 비워질 때까지 짧게 대기
    for _ in range(20):
        if consumer._outgoing_queue.empty():
            break
        await asyncio.sleep(0.02)
    consumer._running = False
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass

    assert len(consumer.manager.broadcasted) == 5
    assert [m["seq"] for m in consumer.manager.broadcasted] == [0, 1, 2, 3, 4]
