"""Telegram message set (Korean): 🚨 incidents, entry/exit (symbol, side, qty, price, stop, R, PnL), daily settlement,
heartbeat. Mock sender — no network; the real sender is used once TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are set."""
import logging
import time
from decimal import Decimal

from live_v6.engine import Settings, V6Engine
from live_v6.notify import ENV_CHAT, ENV_TOKEN, Notifier
from live_v6.store import MemoryStore

from .fakes import FakeExchange

DOGE = "DOGEUSDT"


class MockPost:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, url, data, timeout):
        if self.fail:
            raise ConnectionError(f"boom {url}")
        self.calls.append((url, data))


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def eng_with(post, clock=None):
    tg = Notifier("123:TESTTOKEN", "42", post=post)
    eng = V6Engine(FakeExchange(), Settings(symbols=(DOGE, "SOLUSDT"), entry_order=(DOGE, "SOLUSDT"), cid_prefix="v6n",
                                            query_delay_s=0, exit_retry_delay_s=0, breach_grace_s=0, income_interval_s=0,
                                            bootstrap_bars=60),
                   store=MemoryStore(), notifier=tg, clock=clock, sleep=lambda s: None)
    eng.on_bar_close = lambda *a, **k: None
    eng.startup()
    return eng, tg


def test_env_names_and_unconfigured_is_silent(monkeypatch):
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    monkeypatch.delenv(ENV_CHAT, raising=False)
    post = MockPost()
    n = Notifier(post=post)
    assert not n.configured and n.missing_env() == ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    assert n.send("x") is False and not post.calls and n.sent == ["x"]


def test_send_uses_bot_api_and_never_raises_or_logs_token(caplog):
    post = MockPost()
    n = Notifier("123:SECRET", "42", post=post)
    assert n.alert("제목", "내용")
    url, data = post.calls[0]
    assert url == "https://api.telegram.org/bot123:SECRET/sendMessage" and data == {"chat_id": "42", "text": "🚨 제목\n내용"}
    bad = Notifier("123:SECRET", "42", post=MockPost(fail=True))
    with caplog.at_level(logging.DEBUG):
        assert bad.send("x") is False
    assert bad.failed == 1 and "SECRET" not in caplog.text


def test_entry_and_exit_messages():
    post = MockPost()
    eng, tg = eng_with(post)
    assert eng.enter(DOGE, Decimal("0.0045"), int(time.time()) * 1000)
    j = eng.st["pos"][DOGE]
    ent = next(m for m in tg.sent if m.startswith("🟢"))
    for part in ("진입 DOGEUSDT 롱", f"수량 {j['qty']}", f"체결가 {j['entry_px']}", f"손절 {j['stop_px']}", "위험"):
        assert part in ent, (part, ent)
    eng.ex.set_price(DOGE, "0.16")
    assert eng.close(DOGE, "signal_exit")
    ex = next(m for m in tg.sent if m.startswith("🔵") or m.startswith("🔴"))
    for part in ("청산 DOGEUSDT 롱", "M20 채널 청산", f"수량 {j['qty']}", f"{j['entry_px']} → 0.16", f"손절 {j['stop_px']}",
                 "순손익 +", "R", "수수료"):
        assert part in ex, (part, ex)
    assert any(d["text"] == ex for _, d in post.calls)          # really handed to the sender


def test_incident_alert_format():
    post = MockPost()
    eng, tg = eng_with(post)
    eng.alert("손절 등록 실패 — 이 포지션만 정리", "DOGEUSDT 1000")
    assert post.calls[-1][1]["text"] == "🚨 손절 등록 실패 — 이 포지션만 정리\nDOGEUSDT 1000"


def test_daily_settlement_and_heartbeat():
    from datetime import datetime, timedelta, timezone
    kst = timezone(timedelta(hours=9))
    t0 = time.time()                   # fake exchange stamps fills with the wall clock
    today = datetime.fromtimestamp(t0, kst)
    midnight = datetime(today.year, today.month, today.day, tzinfo=kst) + timedelta(days=1)
    clk = Clock(t0)
    post = MockPost()
    eng, tg = eng_with(post, clk)
    eng.tick()
    assert any(m.startswith("💓 작동 중") for m in tg.sent)
    assert eng.enter(DOGE, Decimal("0.0045"), int(clk.t) * 1000)
    eng.ex.set_price(DOGE, "0.14")
    eng.close(DOGE, "signal_exit")
    eng.skip("SOLUSDT", "min_notional", "test")
    n_hb = sum(m.startswith("💓") for m in tg.sent)
    clk.t = midnight.timestamp() + 60  # 00:01 KST next day → settlement of today
    eng.tick()
    s = next(m for m in tg.sent if m.startswith("📊"))
    assert f"일일 결산 {today:%Y-%m-%d} (KST)" in s and "청산 1건" in s and "실현 순손익 -" in s
    assert "DOGEUSDT M20 채널 청산" in s and "min_notional 1" in s and "보유: 없음" in s
    eng.tick()
    assert sum(m.startswith("📊") for m in tg.sent) == 1     # once per day
    n_hb = sum(m.startswith("💓") for m in tg.sent)
    clk.t += eng.cfg.heartbeat_s / 2
    eng.tick()
    assert sum(m.startswith("💓") for m in tg.sent) == n_hb  # not before heartbeat_s
    clk.t += eng.cfg.heartbeat_s / 2
    eng.tick()
    assert sum(m.startswith("💓") for m in tg.sent) == n_hb + 1
