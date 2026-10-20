"""TelegramBot 명령 dispatch + 핸들러 메시지 포맷 검증.

network 호출 없음 (httpx 차단), 메시지 페이로드만 확인.
"""

from decimal import Decimal

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
async def test_more_and_help(bot: _FakeBot):
    await bot._dispatch(CHAT, "/more")
    await bot._dispatch(CHAT, "/help")
    assert len(bot.sent) == 2 and bot.sent[0] == bot.sent[1]
    msg = bot.sent[0]
    for c in ("/status", "/halt", "/resume", "/today", "/chart"):
        assert c in msg
    assert len(msg.splitlines()) <= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", ["/signal", "/detail", "/history 5", "/equity", "/position"])
async def test_removed_commands_silent(bot: _FakeBot, cmd):
    await bot._dispatch(CHAT, cmd)
    assert bot.sent == []


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
    assert any("매매 중단" in m for m in bot.sent)

    await bot._dispatch(CHAT, "/resume")
    assert ad.is_halted() is False
    assert any("해제" in m for m in bot.sent)


class _StatusEngine:
    def __init__(self, positions, trades=(), halted=False):
        from app.trading.schemas import AccountState
        self._positions = positions
        self.trade_history = list(trades)
        self.account = AccountState(balance=Decimal("1010"))
        self._halted = halted

    def get_status(self):
        return {"balance": "1010", "anomaly": {"is_halted": self._halted}}

    def get_open_positions(self):
        return self._positions


@pytest.mark.asyncio
async def test_status_three_lines_with_position(monkeypatch, bot: _FakeBot):
    from app.trading import engine as engine_mod

    pos = {"side": "long", "quantity": "0.010", "avg_entry_price": "67000",
           "stop_loss_price": "66500",
           "exit_orders": [{"price": "68000", "status": "pending", "qty": "0.01"}]}
    monkeypatch.setattr(engine_mod, "trading_engine", _StatusEngine([pos]))
    await bot._dispatch(CHAT, "/status")
    lines = bot.sent[0].splitlines()
    assert len(lines) == 3
    assert "$1,010.00" in lines[0] and "가동" in lines[0]
    assert "롱" in lines[1] and "66,500.0" in lines[1] and "68,000.0" in lines[1]
    assert "오늘" in lines[2]


@pytest.mark.asyncio
async def test_status_no_position_halted(monkeypatch, bot: _FakeBot):
    from app.trading import engine as engine_mod

    monkeypatch.setattr(engine_mod, "trading_engine", _StatusEngine([], halted=True))
    await bot._dispatch(CHAT, "/status")
    lines = bot.sent[0].splitlines()
    assert len(lines) == 3 and "중단" in lines[0] and "포지션 없음" in lines[1]


@pytest.mark.asyncio
async def test_today(monkeypatch, bot: _FakeBot):
    from app.trading import engine as engine_mod

    monkeypatch.setattr(engine_mod, "trading_engine", _StatusEngine([]))
    await bot._dispatch(CHAT, "/today")
    assert len(bot.sent[0].splitlines()) == 3
    assert "0건" in bot.sent[0]


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
