"""TA review 950438b (recommended): the Telegram bot token never appears in logs. The token is part of every Bot API
URL, and httpx puts the URL into exception messages (HTTPStatusError, ConnectError …) and into its own INFO
"HTTP Request:" lines. Drive the notifier and the command bot through REAL httpx clients (MockTransport) that fail in
every way, with all live_v6 loggers at DEBUG and httpx/httpcore at WARNING exactly as runner.run() sets them."""
import inspect
import logging
import threading
import time

import httpx
import pytest

from live_v6 import runner, tgcmd
from live_v6.notify import Notifier

TOKEN = "123456789:AAFakeDummyTokenForLogRedactionTest_xyz"


def _mode(kind):
    def handler(request: httpx.Request):
        assert TOKEN in str(request.url)                       # the token really is in the URL we must not log
        if kind == "connect":
            raise httpx.ConnectError(f"connection refused for {request.url}", request=request)
        if kind == "timeout":
            raise httpx.ReadTimeout(f"timed out {request.url}", request=request)
        if kind == "409":
            return httpx.Response(409, json={"ok": False, "error_code": 409})
        if kind == "okfalse":
            return httpx.Response(200, json={"ok": False, "error_code": 401, "description": f"bad {request.url}"})
        return httpx.Response(int(kind), json={"ok": False})
    return handler


KINDS = ("connect", "timeout", "401", "500", "409", "okfalse")


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG)
    lv = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    for n in lv:                                               # as runner.run()
        logging.getLogger(n).setLevel(logging.WARNING)
    yield caplog
    for n, v in lv.items():
        logging.getLogger(n).setLevel(v)


def _assert_clean(caplog, min_records=1):
    assert len(caplog.records) >= min_records
    text = caplog.text + "".join(str(r.args) + str(r.exc_info) + str(r.exc_text) for r in caplog.records)
    assert TOKEN not in text and TOKEN.split(":")[1] not in text


def test_runner_quiets_httpx_request_lines():
    assert "setup_logging()" in inspect.getsource(runner.run)
    src = inspect.getsource(runner.setup_logging)
    assert "httpx" in runner.NOISY_LOGGERS and "httpcore" in runner.NOISY_LOGGERS and "setLevel(logging.WARNING)" in src


@pytest.mark.parametrize("kind", KINDS)
def test_notifier_failure_never_logs_token(logs, kind):
    client = httpx.Client(transport=httpx.MockTransport(_mode(kind)))

    def post(url, data, timeout):
        r = client.post(url, data=data, timeout=timeout)
        r.raise_for_status()
        if not r.json().get("ok"):
            raise RuntimeError(f"telegram ok=false {url}")         # worst case: an exception that embeds the URL
        return r
    n = Notifier(token=TOKEN, chat_id="1", mode="live", post=post)
    assert n.send("🚨 test alert") is False and n.failed == 1
    _assert_clean(logs, 2)


@pytest.mark.parametrize("kind", KINDS)
def test_command_bot_failure_never_logs_token(logs, kind):
    bot = tgcmd.CommandBot(TOKEN, eng=None, http=httpx.Client(transport=httpx.MockTransport(_mode(kind))), poll_timeout=0)
    bot.outbox.put((1, "reply"))
    threads = [threading.Thread(target=f, daemon=True) for f in (bot._poll_loop, bot._send_loop)]
    for t in threads:
        t.start()
    deadline = time.time() + 5
    while bot.errors < 2 and time.time() < deadline:          # one getUpdates failure + one reply failure
        time.sleep(0.01)
    bot.stop()
    for t in threads:
        t.join(3)
    assert bot.errors >= 2
    _assert_clean(logs, 3)


def test_httpx_info_would_leak_so_the_guard_matters(caplog):
    """Sanity: without runner.run()'s WARNING level httpx's INFO line contains the token — the check above is real."""
    caplog.set_level(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))).post(
        f"https://api.telegram.org/bot{TOKEN}/getMe")
    assert TOKEN in caplog.text
