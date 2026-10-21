"""Read-only Telegram commands: mainnet-only start, allowed chat only, every command logged, replies built from memory
on the engine thread, network failures never raise / block."""
import json
import time
from decimal import Decimal

from live_v6 import tgcmd
from live_v6.notify import Notifier

from .test_faults import DOGE, opened, ready

OWNER = 7450291244


class FakeHttp:
    def __init__(self, updates=None, fail=None):
        self.updates, self.fail, self.sent, self.calls = list(updates or []), fail, [], []

    def post(self, url, data=None, timeout=None):
        assert url.startswith("https://api.telegram.org/bot")
        m = url.rsplit("/", 1)[1]
        self.calls.append(m)
        if self.fail:
            raise self.fail
        if m == "getUpdates":
            res, self.updates = self.updates, []
            return Resp({"ok": True, "result": res})
        if m == "sendMessage":
            self.sent.append(data)
            return Resp({"ok": True, "result": {}})


class Resp:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def upd(i, chat, text, user="ssh"):
    return {"update_id": i, "message": {"date": 1, "text": text, "chat": {"id": chat}, "from": {"id": chat, "username": user}}}


def test_only_owner_answered_and_everything_logged(offline, tmp_path):
    eng = ready(offline)
    opened(offline, eng)
    eng.marks[DOGE] = Decimal("0.151")
    http = FakeHttp([upd(1, OWNER, "/status"), upd(2, 999, "/status", "stranger"), upd(3, OWNER, "/today"),
                     upd(4, OWNER, "/more"), upd(5, OWNER, "hello")])
    bot = tgcmd.CommandBot("T", eng, log_path=str(tmp_path / "cmd.jsonl"), http=http)
    bot.poll_once()
    n_ex = len(offline.fx.calls)
    assert bot.offset == 6 and bot.inbox.qsize() == 3
    bot.poll()
    replies = [bot.outbox.get_nowait() for _ in range(3)]
    assert all(c == OWNER for c, _ in replies)
    st, today, more = (t for _, t in replies)
    j = eng.st["pos"][DOGE]
    assert "📟 상태" in st and f"{j['entry_px']}" in st and f"손절 {j['stop_px']}" in st and "오늘(KST) 실현" in st
    assert "잔고" in st and ("진입 가능" in st or "진입 보류" in st)
    assert today.startswith("📊 오늘 결산") and "보유:" in today
    assert "/status" in more and "/halt" not in more and "/resume" not in more
    log = [json.loads(x) for x in (tmp_path / "cmd.jsonl").read_text().splitlines()]
    assert [(r["chat_id"], r["text"], r["accepted"]) for r in log] == [
        (OWNER, "/status", True), (999, "/status", False), (OWNER, "/today", True), (OWNER, "/more", True)]
    assert log[1]["username"] == "stranger" and all(r["ts"] for r in log)
    assert len(offline.fx.calls) == n_ex                    # replies never touch the exchange


def test_no_trading_commands():
    assert set(tgcmd.COMMANDS) == {"/status", "/today", "/more"}
    src = open(tgcmd.__file__).read()
    assert "halt(" not in src and "resume(" not in src and ".close(" not in src and ".enter(" not in src


def test_reply_never_calls_the_exchange(offline):
    eng = ready(offline)
    n = len(offline.fx.calls)
    for c in ("/status", "/today", "/more", "/chart", "/x@bot"):
        assert tgcmd.reply_for(eng, c)
    assert len(offline.fx.calls) == n                       # in-memory only: no REST from the engine thread


def test_network_failure_never_raises_and_backs_off(offline):
    eng = ready(offline)
    http = FakeHttp(fail=ConnectionError("down"))
    bot = tgcmd.CommandBot("T", eng, http=http, poll_timeout=0)
    bot.start()
    time.sleep(0.3)
    bot.stop()
    assert bot.errors >= 1 and http.calls.count("getUpdates") <= 3     # backoff (5 s), no hot loop
    bot.poll()                                               # engine hook: nothing queued, no error


def test_mainnet_only(offline):
    eng = ready(offline)
    for net, mode, tok in (("testnet", "testnet", "t"), ("mainnet", "testnet", "t"), ("mainnet", "live", "")):
        eng.tg = Notifier(token=tok, chat_id="1" if tok else "", mode=mode)
        assert tgcmd.maybe_start(eng, net) is None


def test_reply_failure_isolated(offline):
    eng = ready(offline)
    bot = tgcmd.CommandBot("T", eng, http=FakeHttp())
    eng.daily_summary = lambda d: 1 / 0
    bot.inbox.put((OWNER, "/today"))
    bot.poll()
    assert bot.outbox.get_nowait()[1].startswith("⚠️ 명령 처리 실패")
