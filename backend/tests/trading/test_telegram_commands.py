"""TelegramBot 명령 dispatch + 핸들러 메시지 포맷 검증.

network 호출 없음 (httpx 차단), 메시지 페이로드만 확인.
"""

import pytest

from app.trading.anomaly_detector import AnomalyDetector
from app.trading.schemas import TradingSettings
from app.trading.telegram_bot import TelegramBot, _parse_int


CHAT = "test-chat"


class _FakeBot(TelegramBot):
    """텔레그램 API 호출을 차단하고 send 결과만 캡처."""

    def __init__(self):
        super().__init__()
        self._token = "FAKE"
        self._chat_id = CHAT
        self.sent: list[str] = []

    async def _send(self, chat_id: str, text: str):
        self.sent.append(text)


@pytest.fixture
def bot():
    return _FakeBot()


@pytest.mark.asyncio
async def test_parse_int():
    assert _parse_int("10", default=5, lo=1, hi=50) == 10
    assert _parse_int("abc", default=5, lo=1, hi=50) == 5
    assert _parse_int("100", default=5, lo=1, hi=50) == 50  # 상한
    assert _parse_int("0", default=5, lo=1, hi=50) == 1  # 하한


@pytest.mark.asyncio
async def test_help(bot: _FakeBot):
    await bot._dispatch(CHAT, "/help")
    assert len(bot.sent) == 1
    msg = bot.sent[0]
    assert "/status" in msg
    assert "/signal" in msg
    assert "/detail" in msg
    assert "/history" in msg
    assert "/equity" in msg
    assert "/halt" in msg
    assert "/resume" in msg
    assert "/chart" in msg


@pytest.mark.asyncio
async def test_unknown_command_silent(bot: _FakeBot):
    await bot._dispatch(CHAT, "/notacommand")
    assert bot.sent == []


@pytest.mark.asyncio
async def test_halt_then_resume(monkeypatch, bot: _FakeBot):
    from app.trading import telegram_bot as tb_mod
    from app.trading import engine as engine_mod

    ad = AnomalyDetector(TradingSettings())

    class _StubEngine:
        anomaly_detector = ad

    monkeypatch.setattr(engine_mod, "trading_engine", _StubEngine())

    await bot._dispatch(CHAT, "/halt blame buffett")
    assert ad.is_halted() is True
    assert any("HALT" in m for m in bot.sent)

    await bot._dispatch(CHAT, "/resume")
    assert ad.is_halted() is False
    assert any("RESUME" in m for m in bot.sent)


@pytest.mark.asyncio
async def test_history_empty(monkeypatch, bot: _FakeBot):
    from app.trading import engine as engine_mod

    class _StubEngine:
        def get_trade_history(self, limit, offset):
            return {"trades": [], "total": 0}

    monkeypatch.setattr(engine_mod, "trading_engine", _StubEngine())

    await bot._dispatch(CHAT, "/history 5")
    assert any("거래 기록 없음" in m for m in bot.sent)


@pytest.mark.asyncio
async def test_signal_no_data(monkeypatch, bot: _FakeBot):
    from app.tasks import scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "latest_results", {}, raising=False)
    await bot._dispatch(CHAT, "/signal")
    assert len(bot.sent) == 1
    # 모든 TF "데이터 없음" 라인 포함
    assert "데이터 없음" in bot.sent[0]


@pytest.mark.asyncio
async def test_detail_no_position(monkeypatch, bot: _FakeBot):
    from app.trading import engine as engine_mod

    class _StubEngine:
        def get_open_positions(self):
            return []

    monkeypatch.setattr(engine_mod, "trading_engine", _StubEngine())
    await bot._dispatch(CHAT, "/detail")
    assert any("열린 포지션 없음" in m for m in bot.sent)


@pytest.mark.asyncio
async def test_chart_missing_module(monkeypatch, bot: _FakeBot):
    """charting 모듈 없으면(S3 미적용 상태) 우아하게 안내."""
    import sys
    sys.modules.pop("app.trading.charting", None)
    monkeypatch.setitem(sys.modules, "app.trading.charting", None)
    # import 가 None 으로 평가되도록 ModuleType 가 아니라 ImportError 유발
    # 위 setitem 로 import 시 sys.modules["app.trading.charting"] = None →
    # Python 은 None 이면 ImportError 발생
    await bot._dispatch(CHAT, "/chart 1h")
    assert any("matplotlib" in m or "charting" in m for m in bot.sent)
