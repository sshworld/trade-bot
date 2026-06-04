"""S2 — 고아 주문 제거 테스트.

_nuke_all_binance_orders read-back 검증/재시도, clean book 진입 검증.
네트워크 호출 없음 (binance_client monkeypatch).
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

import app.trading.engine  # noqa: F401  — 순환 import 회피
from app.trading import live_engine as le_mod
from app.trading.live_engine import LiveTradingEngine


@pytest.fixture
def eng(monkeypatch):
    e = LiveTradingEngine()
    e.open_positions.clear()
    e.trade_history.clear()
    monkeypatch.setattr(le_mod.asyncio, "sleep", AsyncMock())
    return e


@pytest.mark.asyncio
async def test_nuke_readback_clears_first_try(eng, monkeypatch):
    monkeypatch.setattr(le_mod.binance_client, "get_open_algo_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(le_mod.binance_client, "get_open_orders", AsyncMock(return_value=[]))
    cancel_all = AsyncMock(return_value={})
    monkeypatch.setattr(le_mod.binance_client, "cancel_all_open_orders", cancel_all)
    monkeypatch.setattr(le_mod.binance_client, "cancel_algo_order", AsyncMock(return_value={}))

    await eng._nuke_all_binance_orders()
    assert eng.anomaly_detector._manual_halt is False  # clean → halt 없음


@pytest.mark.asyncio
async def test_nuke_retries_then_clean(eng, monkeypatch):
    # 첫 조회는 dirty(algo 1개), 이후 clean
    algo_seq = [[{"algoId": "A1"}], [{"algoId": "A1"}], [], []]
    calls = {"n": 0}
    async def get_algos(symbol="BTCUSDT"):
        i = min(calls["n"], len(algo_seq) - 1)
        calls["n"] += 1
        return algo_seq[i]
    monkeypatch.setattr(le_mod.binance_client, "get_open_algo_orders", get_algos)
    monkeypatch.setattr(le_mod.binance_client, "get_open_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(le_mod.binance_client, "cancel_all_open_orders", AsyncMock(return_value={}))
    cancel_algo = AsyncMock(return_value={})
    monkeypatch.setattr(le_mod.binance_client, "cancel_algo_order", cancel_algo)

    await eng._nuke_all_binance_orders()
    assert cancel_algo.await_count >= 1
    assert eng.anomaly_detector._manual_halt is False  # 결국 clean


@pytest.mark.asyncio
async def test_nuke_persistent_dirty_halts(eng, monkeypatch):
    # 항상 dirty → 3회 후 HALT
    monkeypatch.setattr(le_mod.binance_client, "get_open_algo_orders",
                        AsyncMock(return_value=[{"algoId": "A1"}]))
    monkeypatch.setattr(le_mod.binance_client, "get_open_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(le_mod.binance_client, "cancel_all_open_orders", AsyncMock(return_value={}))
    monkeypatch.setattr(le_mod.binance_client, "cancel_algo_order", AsyncMock(return_value={}))

    await eng._nuke_all_binance_orders()
    assert eng.anomaly_detector._manual_halt is True   # 잔존 → HALT


@pytest.mark.asyncio
async def test_ensure_clean_book_dirty_then_nuke(eng, monkeypatch):
    # 첫 조회 dirty → nuke 호출 후 clean
    seq_algo = [[{"algoId": "A1"}], [], [], []]
    seq_ord = [[], [], [], []]
    ia = {"n": 0}; io = {"n": 0}
    async def ga(symbol="BTCUSDT"):
        i = min(ia["n"], len(seq_algo) - 1); ia["n"] += 1; return seq_algo[i]
    async def go(symbol="BTCUSDT"):
        i = min(io["n"], len(seq_ord) - 1); io["n"] += 1; return seq_ord[i]
    monkeypatch.setattr(le_mod.binance_client, "get_open_algo_orders", ga)
    monkeypatch.setattr(le_mod.binance_client, "get_open_orders", go)
    monkeypatch.setattr(le_mod.binance_client, "cancel_all_open_orders", AsyncMock(return_value={}))
    monkeypatch.setattr(le_mod.binance_client, "cancel_algo_order", AsyncMock(return_value={}))
    nuke = AsyncMock()
    monkeypatch.setattr(eng, "_nuke_all_binance_orders", nuke)

    ok = await eng._ensure_clean_book()
    assert nuke.await_count == 1    # dirty → nuke 선행
    assert ok is True               # nuke 후 clean


@pytest.mark.asyncio
async def test_ensure_clean_book_already_clean(eng, monkeypatch):
    monkeypatch.setattr(le_mod.binance_client, "get_open_algo_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(le_mod.binance_client, "get_open_orders", AsyncMock(return_value=[]))
    nuke = AsyncMock()
    monkeypatch.setattr(eng, "_nuke_all_binance_orders", nuke)

    ok = await eng._ensure_clean_book()
    assert nuke.await_count == 0    # 이미 clean → nuke 안 함
    assert ok is True
