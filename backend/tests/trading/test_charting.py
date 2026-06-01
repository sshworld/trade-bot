"""charting.render_chart PNG 출력 검증.

네트워크 없이 mock kline_store 만으로 PNG 생성됨을 확인.
"""

import pandas as pd
import pytest

from app.trading import charting


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _fake_df(n=80, start_price=80_000.0):
    rows = []
    p = start_price
    t = 1_700_000_000_000
    for i in range(n):
        o = p
        c = p + (1 if i % 2 else -1) * 5
        h = max(o, c) + 3
        l = min(o, c) - 3
        rows.append({"open_time": t + i * 3_600_000, "open": o, "high": h, "low": l, "close": c, "volume": 100.0})
        p = c
    return pd.DataFrame(rows)


@pytest.mark.asyncio
async def test_render_chart_basic(monkeypatch):
    from app.binance import kline_store as ks_mod
    from app.trading import engine as engine_mod

    class _StubKS:
        def get_dataframe(self, symbol, interval):
            return _fake_df()

    class _StubEngine:
        def get_open_positions(self):
            return []

    monkeypatch.setattr(ks_mod, "kline_store", _StubKS())
    monkeypatch.setattr(engine_mod, "trading_engine", _StubEngine())

    png, caption = await charting.render_chart("1h")
    assert png.startswith(PNG_MAGIC)
    assert len(png) > 1000  # 실제 그림이 그려졌는지
    assert "BTCUSDT" in caption
    assert "1h" in caption


@pytest.mark.asyncio
async def test_render_chart_with_position(monkeypatch):
    from app.binance import kline_store as ks_mod
    from app.trading import engine as engine_mod

    class _StubKS:
        def get_dataframe(self, symbol, interval):
            return _fake_df()

    class _StubEngine:
        def get_open_positions(self):
            return [
                {
                    "side": "long",
                    "quantity": "0.001",
                    "avg_entry_price": "80050",
                    "mark_price": "80100",
                    "stop_loss_price": "79500",
                    "pnl_percent": 1.23,
                    "exit_orders": [
                        {"price": "80500", "qty": "0.0005", "status": "pending"},
                        {"price": "81000", "qty": "0.0005", "status": "pending"},
                    ],
                }
            ]

    monkeypatch.setattr(ks_mod, "kline_store", _StubKS())
    monkeypatch.setattr(engine_mod, "trading_engine", _StubEngine())

    png, caption = await charting.render_chart("4h")
    assert png.startswith(PNG_MAGIC)
    assert "LONG" in caption.upper()


@pytest.mark.asyncio
async def test_invalid_tf():
    with pytest.raises(ValueError):
        await charting.render_chart("invalid_tf")


@pytest.mark.asyncio
async def test_empty_klines(monkeypatch):
    from app.binance import kline_store as ks_mod

    class _StubKS:
        def get_dataframe(self, symbol, interval):
            return None

    monkeypatch.setattr(ks_mod, "kline_store", _StubKS())
    with pytest.raises(RuntimeError):
        await charting.render_chart("1h")
