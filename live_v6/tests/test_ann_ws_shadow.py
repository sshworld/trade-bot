"""Announcement WebSocket shadow logger: signing, push parsing, keepalive, reconnect, safety — offline (no network)."""
from __future__ import annotations

import ast
import hashlib
import hmac
import json
import os
import pathlib
import threading
from urllib.parse import parse_qsl, urlsplit

import pytest

from live_v6.tools import ann_ws_shadow as S

DOC_PUSH = json.dumps({
    "type": "DATA", "topic": "com_announcement_en",
    "data": json.dumps({"catalogId": 161, "catalogName": "Delisting", "publishDate": 1753257631403,
                        "title": "Binance Will Delist AAA, BBB on 2025-07-25", "body": "This is...",
                        "disclaimer": "Trade on-the-go..."})})


# ───────────────────────── signing ─────────────────────────

def test_signed_url_signs_the_query_in_doc_order():
    url = S.signed_url("sekret", now_ms=1700000000000, rnd="abc123")
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "wss://api.binance.com/sapi/wss"
    assert [k for k, _ in parse_qsl(parts.query)] == ["random", "topic", "recvWindow", "timestamp", "signature"]
    signed = "random=abc123&topic=com_announcement_en&recvWindow=30000&timestamp=1700000000000"
    assert parts.query == signed + "&signature=" + hmac.new(b"sekret", signed.encode(), hashlib.sha256).hexdigest()
    assert "sekret" not in url                                   # the secret itself never goes on the wire


def test_signed_url_alphabetical_fallback_signs_the_sorted_query():
    url = S.signed_url("sekret", now_ms=1700000000000, rnd="abc123", order="alpha")
    signed = "random=abc123&recvWindow=30000&timestamp=1700000000000&topic=com_announcement_en"
    assert urlsplit(url).query == signed + "&signature=" + hmac.new(b"sekret", signed.encode(),
                                                                     hashlib.sha256).hexdigest()


def test_scrub_removes_the_signed_query_from_error_text():
    url = S.signed_url("sekret", now_ms=1, rnd="r")
    sig = dict(parse_qsl(urlsplit(url).query))["signature"]
    out = S.scrub(f"InvalidURI('{url}') while connecting to {url}")
    assert sig not in out and "signature" not in out and "timestamp" not in out
    assert "wss://api.binance.com/sapi/wss" in out


# ───────────────────────── push parsing ─────────────────────────

def test_parse_push_reports_raw_and_corrected_lag():
    rec = S.parse_push(DOC_PUSH, recv_ms=1753257633903.0, offset_ms=40.0, offset_age_s=12.0)
    assert rec["k"] == "ann" and rec["catalogId"] == 161 and rec["catalogName"] == "Delisting"
    assert rec["publish_ms"] == 1753257631403
    assert rec["lag_raw_ms"] == pytest.approx(2500.0)            # on our clock
    assert rec["lag_ms"] == pytest.approx(2540.0)                # + 40 ms clock offset to the exchange
    assert rec["offset_age_s"] == 12.0 and rec["title"].startswith("Binance Will Delist")
    assert rec["body_len"] == len("This is...") and "body" in rec["keys"]


def test_parse_push_without_a_valid_offset_keeps_the_raw_lag_only():
    rec = S.parse_push(DOC_PUSH, recv_ms=1753257633903.0, offset_ms=None)
    assert rec["lag_raw_ms"] == pytest.approx(2500.0) and rec["lag_ms"] is None and rec["offset_ms"] is None


@pytest.mark.parametrize("raw", [
    json.dumps({"type": "COMMAND", "data": "SUCCESS", "subType": "SUBSCRIBE", "code": "00000000"}),
    "not json", json.dumps({"type": "DATA", "data": "{broken"}), json.dumps([1, 2]), b"\x00\x01"])
def test_parse_push_ignores_non_announcements(raw):
    assert S.parse_push(raw, 1.0, 0.0) is None


def test_parse_push_without_publish_date_keeps_the_row():
    raw = json.dumps({"type": "DATA", "topic": "t", "data": json.dumps({"title": "x", "publishDate": True})})
    rec = S.parse_push(raw, 5.0, 0.0)
    assert rec["lag_ms"] is None and rec["lag_raw_ms"] is None and rec["title"] == "x"


# ───────────────────────── stream loop (fake socket, fake clock) ─────────────────────────

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeWS:
    def __init__(self, script, clock, pongs=True):
        self.script, self.clock, self.pongs, self.pings = list(script), clock, pongs, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ping(self, data=None):
        self.pings.append((self.clock.now, data))
        ev = threading.Event()
        if self.pongs:
            ev.set()
        return ev

    def recv(self, timeout=None):
        self.clock.now += timeout                                # every receive attempt costs the full timeout
        if not self.script:
            raise TimeoutError
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _shadow(tmp_path, script=(), clock=None, pongs=True):
    clock = clock or Clock()
    seen = {"urls": []}

    def connect(url, **kw):
        seen["urls"].append(url)
        seen["kw"] = kw
        seen["ws"] = FakeWS(script, clock, pongs)
        return seen["ws"]

    sh = S.Shadow("KEY", "SECRET", str(tmp_path / "out.jsonl"), connect=connect,
                  http_get=lambda u: {"serverTime": 0}, clock=clock, mono=clock)
    return sh, seen, clock


def _drain(sh):
    rows = []
    while not sh.q.empty():
        rows.append(sh.q.get_nowait())
    return rows


def test_run_once_logs_pushes_pings_empty_every_30s_and_sends_the_key_only_as_header(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RECONNECT_S", 95.0)                  # leave after ~95 s of fake time
    sh, seen, _ = _shadow(tmp_path, [TimeoutError(), DOC_PUSH, "weird frame"])
    sh.run_once()
    assert seen["kw"]["additional_headers"] == {"X-MBX-APIKEY": "KEY"} and seen["kw"]["ping_interval"] is None
    assert "KEY" not in seen["urls"][0] and "SECRET" not in seen["urls"][0]
    ping_times = [t for t, _ in seen["ws"].pings]
    assert all(d == b"" for _, d in seen["ws"].pings)            # doc: empty payload
    assert len(ping_times) == 3 and all(29.0 <= b - a <= 31.0 for a, b in zip(ping_times, ping_times[1:]))
    rows = _drain(sh)
    assert [r["k"] for r in rows] == ["conn", "ann", "other", "conn"]
    assert rows[1]["lag_ms"] is None                             # no clock offset measured yet → raw lag only
    assert rows[-1]["event"] == "planned_reconnect" and rows[-1]["pushes"] == 1 and rows[-1]["other"] == 1


def test_missing_pong_ends_the_connection_instead_of_silently_skipping_pings(tmp_path):
    sh, seen, _ = _shadow(tmp_path, [], pongs=False)
    with pytest.raises(ConnectionError, match="no pong"):
        sh.run_once()
    assert len(seen["ws"].pings) == 1                            # the second ping is never sent on a dead link


def test_unknown_frames_are_capped_per_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RECONNECT_S", 60.0)
    monkeypatch.setattr(S, "MAX_OTHER_PER_CONN", 3)
    sh, _, _ = _shadow(tmp_path, ["junk"] * 10)
    sh.run_once()
    rows = _drain(sh)
    assert sum(r["k"] == "other" for r in rows) == 3 and rows[-1]["other"] == 10


def _run_with_waits(sh, n):
    waits = []
    sh.clock_loop = lambda: None
    sh.writer_loop = lambda: None

    def wait(s):
        waits.append(s)
        if len(waits) >= n:
            sh.stop.set()
        return sh.stop.is_set()

    sh.stop.wait = wait
    sh.run()
    return waits


def test_run_reconnects_with_capped_backoff_and_never_spins(tmp_path):
    sh, _, _ = _shadow(tmp_path)

    def boom(url, **k):
        raise OSError(f"refused {url}")

    sh._connect = boom
    waits = _run_with_waits(sh, 8)
    assert waits == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0]
    rows = _drain(sh)
    errs = [r for r in rows if r.get("event") == "error"]
    assert len(errs) == 8 and all("signature" not in r["detail"] for r in errs)   # the signed URL is scrubbed
    assert rows[-1]["event"] == "stopped"


def test_rejected_handshake_alternates_the_signing_order_and_backs_off_for_minutes(tmp_path):
    sh, seen, _ = _shadow(tmp_path)

    class Resp:
        status_code = 401

    class InvalidStatus(Exception):
        response = Resp()

    orders = []

    def reject(url, **k):
        orders.append([k for k, _ in parse_qsl(urlsplit(url).query)][1])     # 2nd param tells the order
        raise InvalidStatus()

    sh._connect = reject
    waits = _run_with_waits(sh, 5)
    assert orders[:4] == ["topic", "recvWindow", "topic", "recvWindow"]   # url order ↔ alphabetical, alternating
    assert waits == [5.0, 600.0, 1200.0, 2400.0, 3600.0]         # never hammers a server that says no
    rows = [r for r in _drain(sh) if r.get("event") == "rejected"]
    assert rows[0]["status"] == 401 and rows[0]["order"] == "url" and rows[1]["order"] == "alpha"


# ───────────────────────── clock offset ─────────────────────────

def test_measure_clock_uses_the_request_midpoint(tmp_path):
    sh, _, clock = _shadow(tmp_path)

    def http_get(url):
        assert url == S.TIME_URL
        clock.now += 0.2                                         # 200 ms round trip
        return {"serverTime": (1000.1 * 1000) + 55}              # server is 55 ms ahead of our midpoint

    sh._http_get = http_get
    sh.measure_clock()
    assert sh.offset_ms == pytest.approx(55.0)
    row = _drain(sh)[-1]
    assert row["k"] == "clock" and row["rtt_ms"] == pytest.approx(200.0)
    assert sh._offset()[0] == pytest.approx(55.0)


def test_slow_time_request_is_not_used_and_an_old_offset_expires(tmp_path):
    sh, _, clock = _shadow(tmp_path)

    def slow(url):
        clock.now += 3.0
        return {"serverTime": 0}

    sh._http_get = slow
    sh.measure_clock()
    assert sh.offset_ms is None and _drain(sh)[-1]["skipped"] == "slow"
    sh.offset_ms, sh.offset_at = 12.0, clock.now
    clock.now += S.CLOCK_MAX_AGE_S + 1
    off, age = sh._offset()
    assert off is None and age > S.CLOCK_MAX_AGE_S               # lag_ms goes null instead of using a stale offset


# ───────────────────────── file output ─────────────────────────

def test_append_refuses_a_symlink_and_rotates_at_the_size_cap(tmp_path, monkeypatch):
    sh, _, _ = _shadow(tmp_path)
    victim = tmp_path / "mainnet.json"
    victim.write_text("{}")
    os.symlink(victim, sh.out_path)
    with pytest.raises(OSError):
        sh._append("x\n")
    assert victim.read_text() == "{}"                            # the bot's state file is untouched
    os.unlink(sh.out_path)
    monkeypatch.setattr(S, "MAX_FILE_BYTES", 10)
    sh._append("0123456789ABCDEF\n")
    sh._append("second\n")
    assert pathlib.Path(sh.out_path).read_text() == "second\n"
    assert pathlib.Path(sh.out_path + ".1").read_text() == "0123456789ABCDEF\n"
    assert oct(os.stat(sh.out_path).st_mode & 0o777) == "0o600"


def test_writer_survives_a_write_failure(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    calls = []

    def bad(line):
        calls.append(line)
        raise OSError("disk full")

    sh._append = bad
    sh.stop.wait = lambda s: sh.stop.set()                        # first failure: stop instead of sleeping 30 s
    sh.write(dict(k="x"))
    sh.writer_loop()                                             # must return, not raise
    assert len(calls) == 1


# ───────────────────────── safety of the tool itself ─────────────────────────

def test_redirects_are_never_followed():
    import websockets.sync.client as wsc
    assert S._connect_no_redirect() is wsc.connect and wsc.MAX_REDIRECTS == 1


def test_module_is_read_only_no_trading_imports():
    """The logger must stay passive: stdlib + websockets/httpx only, nothing from the bot's exchange / engine code."""
    src = pathlib.Path(S.__file__).read_text()
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports (would pull bot modules)"
            mods.add((node.module or "").split(".")[0])
    assert mods <= {"__future__", "argparse", "hashlib", "hmac", "json", "logging", "os", "queue", "re", "secrets",
                    "signal", "threading", "time", "httpx", "websockets"}
    for banned in ("/fapi/v1/order", "/fapi/v1/leverage", "/fapi/v1/marginType", "listenKey", "new_order"):
        assert banned not in src
