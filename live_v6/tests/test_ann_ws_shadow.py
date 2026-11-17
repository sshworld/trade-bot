"""Announcement WebSocket shadow logger: signing, push parsing, keepalive, reconnect, safety — offline (no network)."""
from __future__ import annotations

import ast
import errno
import hashlib
import hmac
import json
import logging
import os
import pathlib
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qsl, urlsplit
import warnings

import pytest

from live_v6.tools import ann_ws_shadow as S


@pytest.fixture(autouse=True)
def no_process_wide_log_hooks_left_behind(monkeypatch):
    """main() installs process-wide hooks (threading.excepthook, warnings into logging). What a test turned on is
    turned off after it - left on, logging.captureWarnings(True) is a no-op for every later test - and what was on
    before stays on."""
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    shown = warnings.showwarning
    yield
    if warnings.showwarning is not shown:
        logging.captureWarnings(False)


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


def test_parse_push_says_how_coarse_the_offset_of_its_corrected_lag_is():
    rec = S.parse_push(DOC_PUSH, 1753257633903.0, 108.0, 12.0, 240.04)
    assert rec["lag_ms"] == pytest.approx(2608.0) and rec["offset_rtt_ms"] == 240.0     # may be 120 ms off: says so
    assert S.parse_push(DOC_PUSH, 1753257633903.0, 40.0, 12.0)["offset_rtt_ms"] is None
    assert S.parse_push(DOC_PUSH, 1753257633903.0, None)["offset_rtt_ms"] is None


def test_short_keeps_a_small_value_as_it_is_and_logs_only_the_start_of_a_big_one():
    for value in (161, 0, -2.5, True, None, "Delisting", "", {"name": "X"}, [1, "a"]):
        assert S.short(value) == value and type(S.short(value)) is type(value)
    assert S.short("x" * 501) == "x" * 500 == "x" * S.FIELD_MAX
    assert S.short({"message": "m" * 1000}) == '{"message": "' + "m" * 487      # the start of its JSON text
    assert S.short(10 ** 600) == "1" + "0" * 499 and S.short(["가"] * 400, 8) == '["가", "가'


def test_a_row_stays_small_whatever_the_frame_holds():
    big = 1_000_000                                              # the socket accepts frames of up to 1 MiB
    data = {"catalogId": [7] * big, "catalogName": "c" * big, "publishDate": 1753257631403, "title": "t" * big,
            "body": "b" * big, **{f"k{i:04d}" + "x" * 500: 1 for i in range(300)}}
    rec = S.parse_push(json.dumps({"type": "DATA", "topic": "x" * big, "data": json.dumps(data)}),
                       1753257633903.0, 40.0, 12.0, 4.0)
    assert len(json.dumps(rec)) < 8000                           # rows of 1 MB would soon empty both 20 MiB files
    assert rec["lag_raw_ms"] == pytest.approx(2500.0) and rec["lag_ms"] == pytest.approx(2540.0)   # still measured
    assert rec["topic"] == "x" * 500 and rec["catalogName"] == "c" * 500
    assert rec["catalogId"] == ("[" + "7, " * 200)[:500]         # not a scalar: the start of its JSON text
    assert rec["title"] == "t" * S.TITLE_MAX and rec["title_len"] == big and rec["body_len"] == big
    assert rec["keys"][:3] == ["body", "catalogId", "catalogName"] and len(rec["keys"]) == S.KEYS_MAX == 30
    assert {len(k) for k in rec["keys"][3:]} == {S.KEY_MAX} == {100}
    plain = S.parse_push(DOC_PUSH, 1753257633903.0, 40.0)        # an ordinary push is logged exactly as before
    assert (plain["topic"], plain["catalogId"], plain["catalogName"]) == ("com_announcement_en", 161, "Delisting")
    assert plain["title"] == "Binance Will Delist AAA, BBB on 2025-07-25" and plain["title_len"] == len(plain["title"])
    assert plain["keys"] == sorted(json.loads(json.loads(DOC_PUSH)["data"]))


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

def test_measure_clock_uses_the_midpoint_of_the_fastest_sample(tmp_path):
    sh, _, clock = _shadow(tmp_path)
    rtts = iter([0.2, 0.006, 0.004, 0.005, 0.008])                # the first request opens the connection
    calls = []

    def http_get(url):
        assert url == S.TIME_URL
        rtt = next(rtts)
        clock.now += rtt
        calls.append(rtt)
        if rtt == 0.2:                                           # cold: the server stamps after the handshake, i.e.
            return {"serverTime": clock.now * 1000 + 55}         # at the END of the round trip (reads +100 ms too much)
        return {"serverTime": (clock.now - rtt / 2) * 1000 + 55}  # warm: symmetric legs; the server is 55 ms ahead

    sh._http_get = http_get
    sh.measure_clock()
    assert len(calls) == S.CLOCK_SAMPLES == 5
    assert sh.offset_ms == pytest.approx(55.0, abs=1e-3)         # not the lopsided 155 of the cold sample
    row = _drain(sh)[-1]
    assert row["k"] == "clock" and row["rtt_ms"] == pytest.approx(4.0) and row["n"] == 5
    assert sh._offset()[0] == pytest.approx(55.0, abs=1e-3)


def test_time_requests_share_one_kept_alive_connection(monkeypatch):
    import httpx
    made = []

    class Client:
        def __init__(self, **kw):
            made.append(kw)

        def get(self, url):
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"serverTime": 1}})()

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr(S, "_HTTP", None)
    assert S._http_get(S.TIME_URL) == {"serverTime": 1} and S._http_get(S.TIME_URL) == {"serverTime": 1}
    assert made == [{"timeout": 5.0, "follow_redirects": False}]    # one client, redirects never followed


def test_slow_time_request_is_not_used_and_an_old_offset_expires(tmp_path):
    sh, _, clock = _shadow(tmp_path)

    def slow(url):
        clock.now += 3.0
        return {"serverTime": 0}

    sh._http_get = slow
    sh.measure_clock()
    assert sh.offset_ms is None and _drain(sh)[-1]["skipped"] == "slow"
    sh.offset_ms, sh.offset_at, sh.offset_ref = 12.0, clock.now, 0.0
    clock.now += S.CLOCK_MAX_AGE_S + 1
    off, age = sh._offset()
    assert off is None and age > S.CLOCK_MAX_AGE_S               # lag_ms goes null instead of using a stale offset


# ───────────────────────── clock step: the wall clock moves, the monotonic clock does not ─────────────────────────

class Wall:
    """Wall clock for the step tests. It runs with the fake monotonic clock and can be stepped on its own, the way
    `date -s` or chrony's makestep move the system time. `true_ms` never steps: the time the exchange is on."""

    def __init__(self, mono, epoch=1_753_257_000.0):
        self.mono = mono
        self.shift = self.true_shift = epoch - mono.now

    def __call__(self):
        return self.mono.now + self.shift

    def true_ms(self):
        return (self.mono.now + self.true_shift) * 1000


SERVER_AHEAD_MS = 40.0


def _stepping(tmp_path):
    """Shadow on separate wall / monotonic clocks; the time endpoint answers in 4 ms, the server 40 ms ahead of the
    un-stepped wall clock. `script` is what the next connection will receive."""
    script = []
    sh, seen, clock = _shadow(tmp_path, script)
    sh.clock = wall = Wall(clock)

    def http_get(url):
        clock.now += 0.004
        return {"serverTime": wall.true_ms() - 2 + SERVER_AHEAD_MS}

    sh._http_get = http_get
    return sh, script, clock, wall


def _push_arriving_in_1s(wall, true_lag_ms=100.0):
    """A push the fake socket hands over one second from now, published `true_lag_ms` earlier on the exchange clock."""
    return json.dumps({"type": "DATA", "topic": S.TOPIC, "data": json.dumps(
        {"publishDate": wall.true_ms() + 1000 + SERVER_AHEAD_MS - true_lag_ms, "title": "Binance Will Delist AAA"})})


def _one_push(sh, script, wall):
    script[:] = [_push_arriving_in_1s(wall)]
    sh.run_once()
    rows = _drain(sh)
    (ann,) = [r for r in rows if r["k"] == "ann"]
    return ann, rows


@pytest.mark.parametrize("jump_s", [5.0, -5.0])
def test_a_wall_clock_step_voids_the_offset_is_logged_once_and_wakes_a_new_measurement(tmp_path, monkeypatch, jump_s):
    monkeypatch.setattr(S, "RECONNECT_S", 2.5)
    sh, script, clock, wall = _stepping(tmp_path)
    sh.measure_clock()
    _drain(sh)
    ann, _ = _one_push(sh, script, wall)
    assert ann["lag_raw_ms"] == pytest.approx(60.0, abs=0.2) and ann["lag_ms"] == pytest.approx(100.0, abs=0.2)
    assert ann["offset_rtt_ms"] == pytest.approx(4.0)            # ... with an offset that is good to 2 ms
    sh.clock_wake.clear()                                        # (set by the push itself: tested further down)

    wall.shift += jump_s                                         # date -s / makestep: only the wall clock moves
    ann, rows = _one_push(sh, script, wall)
    assert ann["lag_ms"] is None and ann["offset_ms"] is None    # NOT 100 +/- 5000 ms with a "fresh" offset
    assert ann["offset_age_s"] is None and ann["offset_rtt_ms"] is None
    assert ann["lag_raw_ms"] == pytest.approx(60.0 + jump_s * 1000, abs=0.2)     # the raw lag is still recorded
    steps = [r for r in rows if r["k"] == "clock" and r.get("event") == "step"]
    assert len(steps) == 1 and steps[0]["delta_ms"] == pytest.approx(jump_s * 1000, abs=0.2)
    assert rows.index(steps[0]) < rows.index(ann)                # the reason is in the file before the null lag
    assert sh.clock_wake.is_set()                                # the clock thread is asked to measure again now

    ann, rows = _one_push(sh, script, wall)                      # still void: null again, but no second step row
    assert ann["lag_ms"] is None and not [r for r in rows if r.get("event") == "step"]

    sh.measure_clock()                                           # what the woken clock thread does
    assert sh.offset_ms == pytest.approx(SERVER_AHEAD_MS - jump_s * 1000, abs=0.01)
    ann, rows = _one_push(sh, script, wall)
    assert ann["lag_ms"] == pytest.approx(100.0, abs=0.2)        # corrected lag is right again on the stepped clock
    assert not [r for r in rows if r.get("event") == "step"]


def test_a_shift_within_50_ms_or_both_clocks_running_on_is_not_a_step(tmp_path):
    sh, _, clock, wall = _stepping(tmp_path)
    sh.measure_clock()
    sample_age = clock.now - sh.offset_at
    clock.now += 1800.0                                          # half an hour passes on both clocks
    wall.shift += 0.049
    off, age = sh._offset()
    assert off == pytest.approx(SERVER_AHEAD_MS, abs=0.01) and age == pytest.approx(1800.0 + sample_age)
    assert not sh.clock_wake.is_set()
    wall.shift += 0.002                                          # 51 ms in total: more than CLOCK_STEP_S
    assert S.CLOCK_STEP_S == 0.05 and sh._offset() == (None, None) and sh.clock_wake.is_set()
    assert [r["delta_ms"] for r in _drain(sh) if r.get("event") == "step"] == [pytest.approx(51.0, abs=0.01)]


def test_an_offset_without_its_clock_reference_is_never_used(tmp_path):
    sh, _, clock = _shadow(tmp_path)
    sh.offset_ms, sh.offset_at = 12.0, clock.now                 # no offset_ref: a step could not be noticed
    assert sh._offset() == (None, None)


def test_a_stamp_taken_before_a_step_is_never_corrected_with_the_offset_measured_after_it(tmp_path):
    """The receive thread stamps a push, stalls, and meanwhile the clock is stepped AND measured again. The offset
    is valid now - but for the stepped clock, not for that stamp."""
    sh, _, clock, wall = _stepping(tmp_path)
    sh.measure_clock()
    stamp_wall, stamp_mono = wall(), clock.now                   # run_once: the receive stamp and the mono clock
    assert sh._offset(stamp_wall, stamp_mono)[0] == pytest.approx(SERVER_AHEAD_MS, abs=0.01)   # no step: fine
    wall.shift += 5.0
    assert sh._offset() == (None, None)                          # the clock thread notices ...
    sh.measure_clock()                                           # ... and has a new offset before the push is handled
    _drain(sh)
    assert sh._offset(stamp_wall, stamp_mono) == (None, None)    # not 100 + 5000 ms
    assert sh._offset()[0] == pytest.approx(SERVER_AHEAD_MS - 5000.0, abs=0.01)   # the new offset itself still holds
    assert not [r for r in _drain(sh) if r.get("event") == "step"]                # and no step is invented


def test_run_once_checks_the_offset_against_the_clocks_of_the_receive_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RECONNECT_S", 2.5)
    sh, script, clock, wall = _stepping(tmp_path)
    sh.measure_clock()
    seen, real = [], sh._correction

    def spy(*a):
        seen.append(a)
        return real(*a)

    sh._correction = spy
    ann, _ = _one_push(sh, script, wall)
    ((stamp_wall, stamp_mono),) = seen
    assert stamp_wall * 1000 == pytest.approx(ann["recv_ms"], abs=0.1)
    assert stamp_mono == pytest.approx(clock.now - 2.0)          # the mono clock at the receive, two timeouts ago


def test_the_age_of_an_offset_is_its_age_at_the_receive_stamp_not_when_the_push_gets_handled(tmp_path):
    sh, _, clock, wall = _stepping(tmp_path)
    sh.measure_clock()
    sample_age = clock.now - sh.offset_at
    clock.now += 10.0
    stamp = (wall(), clock.now)
    clock.now += 30.0                                            # the receive thread got to it half a minute later
    assert sh._offset(*stamp)[1] == pytest.approx(10.0 + sample_age) and sh._offset()[1] == pytest.approx(40.0 + sample_age)
    assert sh._correction(*stamp) == (pytest.approx(SERVER_AHEAD_MS, abs=0.01), pytest.approx(10.0 + sample_age),
                                      pytest.approx(4.0), _drain(sh)[-1]['sample_ms'])   # which clock line it is
    clock.now += S.CLOCK_MAX_AGE_S                               # too old now - but not at that stamp
    assert sh._correction() == (None, pytest.approx(S.CLOCK_MAX_AGE_S + 40.0 + sample_age), None, None)
    assert sh._offset(*stamp)[0] == pytest.approx(SERVER_AHEAD_MS, abs=0.01)


@pytest.mark.parametrize("fastest_is_after_the_step", [False, True])
def test_an_offset_belongs_to_the_clock_of_the_sample_it_came_from_when_a_step_falls_into_the_measurement(
        tmp_path, fastest_is_after_the_step):
    """Five samples, the wall clock stepped between the 2nd and the 3rd. Whichever sample wins, its offset must
    never be applied to a stamp from the other side of the step - not even right after the measurement."""
    sh, _, clock, wall = _stepping(tmp_path)
    before, n = (wall(), clock.now), [0]

    def http_get(url):
        n[0] += 1
        rtt = 0.004 if (n[0] >= 3) == fastest_is_after_the_step else 0.008
        clock.now += rtt
        answer = {"serverTime": wall.true_ms() - rtt * 500 + SERVER_AHEAD_MS}
        if n[0] == 2:
            wall.shift += 5.0                                    # after the 2nd answer, before the 3rd request
        return answer

    sh._http_get = http_get
    sh.measure_clock()
    after = (wall(), clock.now)
    assert n[0] == S.CLOCK_SAMPLES and sh.offset_rtt_ms == pytest.approx(4.0)
    if fastest_is_after_the_step:                                # the offset is the stepped clock's ...
        assert sh._offset(*after)[0] == pytest.approx(SERVER_AHEAD_MS - 5000.0, abs=0.01)
        assert sh._offset(*before) == (None, None)               # ... and not for a stamp from before the step
        assert not [r for r in _drain(sh) if r.get("event") == "step"]
    else:                                                        # the offset is the old clock's: void at once
        assert sh.offset_ms == pytest.approx(SERVER_AHEAD_MS, abs=0.01)
        assert sh._offset(*after) == (None, None) and sh.clock_wake.is_set()      # NOT 40 ms on a clock 5 s off
        assert [r["delta_ms"] for r in _drain(sh) if r.get("event") == "step"] == [pytest.approx(5000.0, abs=0.01)]


def _run_clock_thread(sh, clock, until, plan=()):
    """clock_loop on the fake clock: a wait costs its whole timeout (nothing when its event is already set), `plan`
    = [(fake time, action)] runs while waiting, and the loop is stopped at fake time `until`. Returns the fake times
    at which a measurement started."""
    starts, real, plan = [], sh.measure_clock, sorted(plan, key=lambda p: p[0])

    def measure():
        starts.append(clock.now)
        real()

    def waiter(event):
        def wait(timeout=None):
            if not event.is_set():
                clock.now += timeout
            while plan and clock.now >= plan[0][0]:
                plan.pop(0)[1]()
            if clock.now >= until:
                sh.stop.set()
            return event.is_set()
        return wait

    sh.measure_clock = measure
    sh.stop.wait, sh.clock_wake.wait = waiter(sh.stop), waiter(sh.clock_wake)
    sh.clock_loop()
    return starts


def test_the_clock_thread_sees_a_step_on_a_quiet_stream_and_measures_again_at_once_but_never_in_a_burst(tmp_path):
    sh, _, clock, wall = _stepping(tmp_path)
    t0 = clock.now

    def step(by):
        wall.shift += by

    starts = _run_clock_thread(sh, clock, until=t0 + 1300.0,
                               plan=[(t0 + 300.0, lambda: step(5.0)), (t0 + 303.0, lambda: step(-5.0))])
    # start; right after the first step (no push needed to notice it); the second step 3 s later waits for the
    # 10 s floor; then the normal 15 min cadence again
    assert starts == pytest.approx([t0, t0 + 300.0, t0 + 300.0 + S.CLOCK_MIN_GAP_S, t0 + 310.0 + S.CLOCK_S], abs=1.5)
    assert S.CLOCK_MIN_GAP_S == 10.0 and S.CLOCK_POLL_S == 1.0
    rows = _drain(sh)
    assert [r["delta_ms"] for r in rows if r.get("event") == "step"] == [pytest.approx(5000.0, abs=0.2),
                                                                           pytest.approx(-5000.0, abs=0.2)]
    assert sum("offset_ms" in r for r in rows if r["k"] == "clock") == 4
    assert sh._offset()[0] == pytest.approx(SERVER_AHEAD_MS, abs=0.01)


def test_a_rate_limit_ban_is_not_cut_short_by_a_clock_step(tmp_path):
    sh, _, clock, wall = _stepping(tmp_path)
    t0, ok, calls = clock.now, sh._http_get, []

    def http_get(url):
        calls.append(clock.now)
        if len(calls) == S.CLOCK_SAMPLES + 1:                    # the second measurement is refused
            raise RuntimeError("Client error '429 Too Many Requests' for url 'https://fapi.binance.com/fapi/v1/time'")
        return ok(url)

    sh._http_get = http_get

    def step():
        wall.shift += 5.0

    starts = _run_clock_thread(sh, clock, until=t0 + 5000.0, plan=[(t0 + 1000.0, step)])
    assert starts == pytest.approx([t0, t0 + 900.0, t0 + 900.0 + 3600.0], abs=1.5)     # an hour away, step or not
    rows = _drain(sh)
    assert [r for r in rows if r.get("event") == "step"] and any("429" in r.get("error", "") for r in rows)


def test_clock_thread_ends_within_seconds_of_stop(tmp_path):
    sh, _, clock, _ = _stepping(tmp_path)
    t0 = clock.now
    assert _run_clock_thread(sh, clock, until=t0 + 5.0) == [t0]  # one measurement, then stop ends the 15 min wait
    assert clock.now < t0 + 10.0


def test_a_step_seen_while_receiving_wakes_the_real_sleeping_clock_thread(tmp_path, monkeypatch):
    """Real clocks, real threads, real Event waits (the tests above replace the waits): the clock thread, asleep
    for its 15 minutes, measures again within moments of a step that the receive side noticed."""
    monkeypatch.setattr(S, "CLOCK_MIN_GAP_S", 0.0)
    monkeypatch.setattr(S, "CLOCK_POLL_S", 60.0)                 # its own look-out is out of the picture here
    shift, done = [0.0], threading.Semaphore(0)

    def wall():
        return time.time() + shift[0]

    sh = S.Shadow("KEY", "SECRET", str(tmp_path / "out.jsonl"), clock=wall, mono=time.monotonic,
                  http_get=lambda url: {"serverTime": time.time() * 1000})      # the exchange does not step
    real = sh.measure_clock

    def measure():
        real()
        done.release()

    sh.measure_clock = measure
    t = threading.Thread(target=sh.clock_loop, daemon=True)
    t.start()
    try:
        assert done.acquire(timeout=20)                          # the measurement at start
        assert sh._offset()[0] == pytest.approx(0.0, abs=20.0)
        shift[0] = 5.0                                           # the system time is stepped
        assert sh._offset() == (None, None)                      # ... which the next push notices
        assert done.acquire(timeout=20)                          # woken: not 15 min and not 60 s later
        assert sh._offset()[0] == pytest.approx(-5000.0, abs=20.0)
    finally:
        sh.stop.set()
        sh.clock_wake.set()
        t.join(20)
    assert not t.is_alive()
    assert [r["delta_ms"] for r in _drain(sh) if r.get("event") == "step"] == [pytest.approx(5000.0, abs=20.0)]


# ───────────────────────── a measurement that fails: not 15 minutes without an offset ─────────────────────────

@pytest.mark.parametrize("how", ["error", "slow"])
def test_a_measurement_that_leaves_no_usable_offset_is_tried_again_after_a_minute_not_after_15(tmp_path, how):
    sh, _, clock, wall = _stepping(tmp_path)
    t0, ok, calls = clock.now, sh._http_get, []

    def http_get(url):
        calls.append(clock.now)
        if len(calls) == S.CLOCK_SAMPLES + 3 and how == "error":
            raise RuntimeError("ReadTimeout('timed out')")       # the 3rd of 5 requests: the measurement is given up
        if S.CLOCK_SAMPLES < len(calls) <= 2 * S.CLOCK_SAMPLES and how == "slow":
            clock.now += 0.3                                     # every request of that measurement: 304 ms
        return ok(url)

    sh._http_get = http_get

    def step():
        wall.shift += 5.0

    starts = _run_clock_thread(sh, clock, until=t0 + 1200.0, plan=[(t0 + 100.0, step)])
    # start; at once after the step - that one fails; a minute later (not 15: lag_ms is null all that time); then
    # the normal cadence
    assert starts == pytest.approx([t0, t0 + 100.0, t0 + 100.0 + S.CLOCK_RETRY_S, t0 + 160.0 + S.CLOCK_S], abs=3.0)
    assert S.CLOCK_RETRY_S == 60.0 and S.CLOCK_S == 900.0
    rows = [r for r in _drain(sh) if r["k"] == "clock"]
    kinds = ["offset" if "offset_ms" in r else r.get("event") or r.get("skipped") or "error" for r in rows]
    assert kinds == ["offset", "step", how, "offset", "offset"] and ("error" in rows[2]) == (how == "error")
    assert rows[3]["drift_ms"] is None                           # the step had voided the offset before it
    assert sh._offset()[0] == pytest.approx(SERVER_AHEAD_MS - 5000.0, abs=0.01)


def test_a_first_measurement_that_fails_is_tried_again_after_a_minute(tmp_path):
    sh, _, clock, _ = _stepping(tmp_path)
    t0, ok, calls = clock.now, sh._http_get, []

    def http_get(url):
        calls.append(clock.now)
        if len(calls) == 1:
            raise OSError("Temporary failure in name resolution")
        return ok(url)

    sh._http_get = http_get
    assert _run_clock_thread(sh, clock, until=t0 + 1000.0) == pytest.approx([t0, t0 + 60.0, t0 + 960.0], abs=1.5)


@pytest.mark.parametrize("refused", ["429 Too Many Requests", "418 I'm a teapot"])
def test_a_ban_is_an_hour_also_when_there_is_no_offset_to_correct_with(tmp_path, refused):
    sh, _, clock, _ = _stepping(tmp_path)
    t0, ok, calls = clock.now, sh._http_get, []

    def http_get(url):
        calls.append(clock.now)
        if len(calls) == 1:                                      # the very first request: no offset yet
            raise RuntimeError(f"Client error '{refused}' for url 'https://fapi.binance.com/fapi/v1/time'")
        return ok(url)

    sh._http_get = http_get
    starts = _run_clock_thread(sh, clock, until=t0 + 4000.0, plan=[(t0 + 500.0, sh.clock_wake.set)])
    assert starts == pytest.approx([t0, t0 + 3600.0], abs=1.5)   # not a minute later, and not when a push asks


def test_a_failed_measurement_keeps_the_15_minute_cadence_while_the_last_offset_is_still_good(tmp_path):
    sh, _, clock, _ = _stepping(tmp_path)
    t0, ok, calls = clock.now, sh._http_get, []

    def http_get(url):
        calls.append(clock.now)
        if len(calls) == S.CLOCK_SAMPLES + 1:
            raise RuntimeError("ReadTimeout('timed out')")
        return ok(url)

    sh._http_get = http_get
    assert _run_clock_thread(sh, clock, until=t0 + 2000.0) == pytest.approx([t0, t0 + 900.0, t0 + 1800.0], abs=1.5)
    assert sh._offset()[0] == pytest.approx(SERVER_AHEAD_MS, abs=0.01)


@pytest.mark.parametrize(("rtt", "used"), [(0.24, True), (0.26, False), (0.3, False), (0.9, False)])
def test_only_a_round_trip_of_a_quarter_second_or_less_gives_an_offset(tmp_path, rtt, used):
    sh, _, clock = _shadow(tmp_path)

    def http_get(url):
        clock.now += rtt
        return {"serverTime": (clock.now - rtt / 2) * 1000 + 55}

    sh._http_get = http_get
    sh.measure_clock()
    row = _drain(sh)[-1]
    assert S.CLOCK_MAX_RTT_S == 0.25 and row["rtt_ms"] == pytest.approx(rtt * 1000)
    if used:
        assert sh.offset_ms == pytest.approx(55.0, abs=1e-3) and sh.offset_rtt_ms == pytest.approx(rtt * 1000)
    else:
        assert sh.offset_ms is None and row["skipped"] == "slow" and sh._correction() == (None, None, None, None)


def test_a_row_says_how_coarse_the_measurement_behind_its_offset_was(tmp_path, monkeypatch):
    """An offset is accepted up to a round trip of 0.25 s, and then it can be 125 ms off. The clock line says so
    (rtt_ms) - and so does every announcement row that was corrected with it, without a join."""
    monkeypatch.setattr(S, "RECONNECT_S", 2.5)
    sh, script, clock, wall = _stepping(tmp_path)
    sh.measure_clock()                                           # a good one first: 4 ms
    ann, _ = _one_push(sh, script, wall)
    assert ann["lag_ms"] == pytest.approx(100.0, abs=0.2) and ann["offset_rtt_ms"] == pytest.approx(4.0)

    def http_get(url):                                           # then 240 ms, the server stamping at 95 % of it
        clock.now += 0.240
        return {"serverTime": wall.true_ms() - 12 + SERVER_AHEAD_MS}

    sh._http_get = http_get
    sh.measure_clock()
    row = _drain(sh)[-1]
    assert row["rtt_ms"] == pytest.approx(240.0) and row["offset_ms"] == pytest.approx(SERVER_AHEAD_MS + 108.0, abs=0.1)
    assert row["drift_ms"] == pytest.approx(108.0, abs=0.1)      # the clock did not move: the measurement is coarse
    ann, _ = _one_push(sh, script, wall)
    assert ann["lag_ms"] == pytest.approx(208.0, abs=0.2)        # true lag: 100 ms
    assert ann["offset_rtt_ms"] == pytest.approx(240.0)          # ... and the row itself says: good to 120 ms only


# ───────────────────────── what the step test cannot see: slewing, a VM paused from outside ─────────────────────────

def test_a_clock_line_says_how_far_its_offset_is_from_the_one_it_replaces(tmp_path):
    sh, _, clock, wall = _stepping(tmp_path)

    def measured():
        sh.measure_clock()
        return _drain(sh)[-1]

    assert measured()["drift_ms"] is None                        # nothing to compare with
    clock.now += 900.0
    assert measured()["drift_ms"] == pytest.approx(0.0, abs=0.01)
    wall.true_shift += 0.3                                       # the box lost 300 ms against the exchange, no step
    row = measured()
    assert row["drift_ms"] == pytest.approx(300.0, abs=0.01) and row["offset_ms"] == pytest.approx(340.0, abs=0.1)
    wall.shift += 5.0                                            # a step voids the offset: its own line says so
    assert sh._offset() == (None, None)
    assert measured()["drift_ms"] is None                        # ... and the next offset has nothing to drift from


def test_a_pause_that_stops_both_clocks_is_not_a_step_and_the_measurement_after_the_push_gives_it_away(
        tmp_path, monkeypatch):
    """A hypervisor pauses the VM for 0.3 s (or chrony slews 0.3 s away): wall clock and monotonic clock stay
    together, so nothing is voided and the corrected lag is a number that is 300 ms wrong. The file must hold what
    it takes to notice: every announcement asks for a measurement, and that one tells how far the offset moved."""
    monkeypatch.setattr(S, "RECONNECT_S", 2.5)
    sh, script, clock, wall = _stepping(tmp_path)
    sh.measure_clock()
    _drain(sh)
    clock.now += 30.0
    wall.true_shift += 0.3                                       # the exchange went on for 0.3 s, this box did not
    ann, rows = _one_push(sh, script, wall)
    assert ann["lag_ms"] == pytest.approx(-200.0, abs=0.2) and ann["lag_raw_ms"] == pytest.approx(-240.0, abs=0.2)
    assert ann["offset_ms"] == pytest.approx(SERVER_AHEAD_MS, abs=0.1)        # true lag: 100 ms. Wrong, and not null
    assert not [r for r in rows if r.get("event") == "step"]
    assert sh.clock_wake.is_set()                                # so: the push asks for a measurement ...
    sh.measure_clock()                                           # (what the woken clock thread does)
    (after,) = [r for r in _drain(sh) if r["k"] == "clock"]
    assert after["drift_ms"] == pytest.approx(300.0, abs=0.01)   # ... which says: do not trust the row before me
    assert ann["lag_raw_ms"] + after["offset_ms"] == pytest.approx(100.0, abs=0.3)    # the rule of the module text
    for needle in ("drift_ms", "SLEWING", "pauses the VM", "HOW TO USE lag_ms"):      # which has to state all this
        assert needle in S.__doc__, needle


def test_only_an_announcement_asks_for_a_measurement_other_frames_do_not(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RECONNECT_S", 2.5)
    sh, script, _, wall = _stepping(tmp_path)
    sh.measure_clock()
    script[:] = ["not json", json.dumps({"type": "COMMAND", "data": "SUCCESS", "subType": "SUBSCRIBE"})]
    sh.run_once()
    assert not sh.clock_wake.is_set() and [r["k"] for r in _drain(sh)] == ["clock", "conn", "other", "other", "conn"]
    _one_push(sh, script, wall)
    assert sh.clock_wake.is_set()


def test_a_measurement_asked_for_by_a_push_comes_at_once_but_never_within_10_s_of_the_last_one(tmp_path):
    sh, _, clock, _ = _stepping(tmp_path)
    t0 = clock.now
    starts = _run_clock_thread(sh, clock, until=t0 + 1300.0,     # what run_once does after an announcement row
                               plan=[(t0 + 300.0, sh.clock_wake.set), (t0 + 303.0, sh.clock_wake.set)])
    assert starts == pytest.approx([t0, t0 + 300.0, t0 + 300.0 + S.CLOCK_MIN_GAP_S, t0 + 310.0 + S.CLOCK_S], abs=1.5)
    rows = _drain(sh)
    assert [r.get("drift_ms", "-") for r in rows] == [None] + [pytest.approx(0.0, abs=0.01)] * 3      # no step rows


def test_a_push_during_a_rate_limit_ban_does_not_cut_the_ban_short(tmp_path):
    sh, _, clock, _ = _stepping(tmp_path)
    t0, ok, calls = clock.now, sh._http_get, []

    def http_get(url):
        calls.append(clock.now)
        if len(calls) == S.CLOCK_SAMPLES + 1:
            raise RuntimeError("Client error '418 I'm a teapot' for url 'https://fapi.binance.com/fapi/v1/time'")
        return ok(url)

    sh._http_get = http_get
    starts = _run_clock_thread(sh, clock, until=t0 + 5000.0, plan=[(t0 + 1000.0, sh.clock_wake.set)])
    assert starts == pytest.approx([t0, t0 + 900.0, t0 + 900.0 + 3600.0], abs=1.5)


def test_the_measurement_after_an_announcement_follows_it_within_moments_on_real_threads(tmp_path, monkeypatch):
    """Real clocks, real threads, the real clock_loop and run_once. The box is 300 ms behind the exchange without
    any step (the exchange is moved here; the box's own two clocks stay together): the announcement row is wrong by
    300 ms, and the clock line that follows it within moments - not 15 minutes later - shows it."""
    monkeypatch.setattr(S, "CLOCK_MIN_GAP_S", 0.0)
    monkeypatch.setattr(S, "CLOCK_POLL_S", 60.0)
    monkeypatch.setattr(S, "RECONNECT_S", 0.3)
    behind, done = [0.0], threading.Semaphore(0)

    def server_ms():
        return (time.time() + behind[0]) * 1000

    class WS(FakeWS):
        def __init__(self):
            self.sent = False

        def recv(self, timeout=None):
            if self.sent:
                time.sleep(0.02)
                raise TimeoutError
            self.sent = True
            return json.dumps({"type": "DATA", "topic": S.TOPIC, "data": json.dumps(
                {"publishDate": server_ms() - 100.0, "title": "Binance Will Delist AAA"})})

    sh = S.Shadow("KEY", "SECRET", str(tmp_path / "out.jsonl"), connect=lambda url, **kw: WS(),
                  http_get=lambda url: {"serverTime": server_ms()})
    real = sh.measure_clock

    def measure():
        real()
        done.release()

    sh.measure_clock = measure
    t = threading.Thread(target=sh.clock_loop, daemon=True)
    t.start()
    try:
        assert done.acquire(timeout=20)                          # the measurement at start: offset 0
        behind[0] = 0.3
        sh.run_once()                                            # one push, published 100 ms before it arrives
        assert done.acquire(timeout=20)                          # woken by the push
    finally:
        sh.stop.set()
        sh.clock_wake.set()
        t.join(20)
    rows = _drain(sh)
    (ann,) = [r for r in rows if r["k"] == "ann"]
    after = [r for r in rows[rows.index(ann):] if r["k"] == "clock"][0]
    assert ann["lag_ms"] == pytest.approx(-200.0, abs=30.0)      # 300 ms wrong, and nothing in the row says so
    assert after["drift_ms"] == pytest.approx(300.0, abs=30.0) and 0.0 <= after["t"] - ann["t"] < 5.0
    assert ann["lag_raw_ms"] + after["offset_ms"] == pytest.approx(100.0, abs=30.0)


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


def _file_lines(sh):
    return [x for x in pathlib.Path(sh.out_path).read_bytes().split(b"\n") if x]


def test_a_lone_surrogate_in_a_title_is_logged_and_does_not_stop_the_writer(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    bad = "Binance Will Delist \ud800 AAA"                        # JSON may carry "\ud800"; UTF-8 cannot encode it
    raw = json.dumps({"type": "DATA", "topic": S.TOPIC, "data": json.dumps({"publishDate": 1, "title": bad})})
    rec = S.parse_push(raw, 2.0, None)
    assert rec["title"] == bad
    sh.write(rec)
    sh.write(dict(k="conn", event="open"))
    sh.stop.set()
    sh.writer_loop()                                             # used to die here with UnicodeEncodeError
    pathlib.Path(sh.out_path).read_bytes().decode("utf-8")       # the file itself stays valid UTF-8
    rows = [json.loads(x) for x in _file_lines(sh)]
    assert [r["k"] for r in rows] == ["ann", "conn"] and rows[0]["title"] == bad      # and loads back unchanged
    assert sh.write_failed == 0


def test_text_that_is_not_a_surrogate_stays_readable_in_the_file(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    sh._append(json.dumps(dict(title="업비트 – 上場"), ensure_ascii=False) + "\n")
    assert "업비트 – 上場" in pathlib.Path(sh.out_path).read_text(encoding="utf-8")


def test_writer_survives_any_exception_and_reports_the_lost_records_in_the_file(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    real, seen = sh._append, []

    def flaky(line):
        seen.append(line)
        if len(seen) <= 2:
            raise ValueError("not an OSError")                   # anything but OSError used to end the thread
        real(line)

    sh._append = flaky
    for i in range(4):
        sh.write(dict(k="x", i=i))
    sh.stop.set()
    sh.writer_loop()
    rows = [json.loads(x) for x in _file_lines(sh)]
    # records 0 and 1 are gone; the gap is stated where it is, then the stream goes on
    assert [(r["k"], r.get("i")) for r in rows] == [("writer", None), ("x", 2), ("x", 3)]
    assert rows[0]["event"] == "lost" and rows[0]["n"] == 2 and rows[0]["total"] == 2 and "t" in rows[0]
    assert sh.write_failed == 2


def test_the_stopped_row_carries_the_number_of_unwritten_records(tmp_path):
    sh, _, _ = _shadow(tmp_path)

    def refused(url, **k):
        raise OSError("refused")

    sh._connect = refused
    sh.write_failed = 3
    _run_with_waits(sh, 1)
    last = _drain(sh)[-1]
    assert last["event"] == "stopped" and last["write_failed"] == 3 and last["dropped"] == 0


def test_only_a_disk_error_makes_the_writer_pause_any_other_failure_goes_straight_on(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    errors, pauses = [ValueError("a bad record"), OSError(errno.ENOSPC, "No space left on device")], []

    def failing(line):
        raise errors.pop(0)

    sh._append = failing
    sh.stop.wait = pauses.append                                 # (the loop itself waits on the queue, not on this)
    sh.write(dict(k="x", i=0))
    sh.write(dict(k="x", i=1))
    sh.stop.set()
    sh.writer_loop()
    assert pauses == [30.0] and errors == [] and sh.write_failed == 2     # one pause: for the full disk only


def test_records_that_find_the_queue_full_are_counted_and_the_file_says_so(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    sh.q = queue.Queue(maxsize=3)                                # (10 000 in real life: the writer is stuck for long)
    for i in range(10):
        sh.write(dict(k="x", i=i))                               # never blocks, never raises: this is the receive loop
    assert sh.dropped == 7 and sh.q.qsize() == 3
    sh.stop.set()
    sh.writer_loop()
    for i in range(10, 15):
        sh.write(dict(k="x", i=i))
    sh.writer_loop()
    rows = [json.loads(x) for x in _file_lines(sh)]
    assert [(r.get("event"), r.get("n"), r.get("total"), r.get("i")) for r in rows] == [
        ("dropped", 7, 7, None), (None, None, None, 0), (None, None, None, 1), (None, None, None, 2),
        ("dropped", 2, 9, None), (None, None, None, 10), (None, None, None, 11), (None, None, None, 12)]
    assert all(r["k"] == "writer" and "t" in r for r in rows if r.get("event")) and sh.dropped == 9
    assert sh.write_failed == 0                                  # a different loss: these never got to the writer


def test_rows_enqueued_after_stop_still_reach_the_file_the_stopped_row_last(tmp_path):
    """SIGTERM while recv() is under way: the writer sees stop and an empty queue and would be gone - before the
    push that this recv() still returns, and before the "stopped" row. Real writer thread, the real run()."""
    sh, _, clock = _shadow(tmp_path)
    sh.clock_loop = lambda: None
    left, real_loop = threading.Event(), sh.writer_loop

    def writer_loop():
        real_loop()
        left.set()

    sh.writer_loop = writer_loop

    class WS(FakeWS):
        def recv(self, timeout=None):
            sh.stop.set()                                        # the signal handler, while this recv() waits
            assert left.wait(10)                                 # the writer: stop is set, queue empty -> loop left
            return DOC_PUSH                                      # ... and only now the push comes in

    sh._connect = lambda url, **kw: WS([], clock)
    sh.run()
    rows = [json.loads(x) for x in _file_lines(sh)]
    assert [(r["k"], r.get("event")) for r in rows] == [("conn", "open"), ("ann", None), ("conn", "stopped")]
    assert rows[-1]["dropped"] == 0 and rows[-1]["write_failed"] == 0 and sh.q.empty()


def test_run_ends_with_the_stopped_row_even_when_it_ends_with_an_exception(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    sh.clock_loop = lambda: None

    def run_once():
        raise Fatal()                                            # not an Exception: run() does not catch it

    sh.run_once = run_once
    with pytest.raises(Fatal):
        sh.run()
    assert [json.loads(x)["event"] for x in _file_lines(sh)] == ["stopped"] and sh.stop.is_set()


def test_sigterm_ends_the_real_process_with_status_0_and_the_stopped_row_in_the_file(tmp_path):
    """No mock but the socket: the child runs the real run() with its real threads, gets SIGTERM while it waits in
    recv() - as `systemctl stop` sends it - and must leave a complete file behind."""
    out = tmp_path / "out.jsonl"
    script = (
        "import signal, sys, threading, time\n"
        "from live_v6.tools import ann_ws_shadow as S\n"
        "class WS:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): return False\n"
        "    def ping(self, data=None):\n"
        "        ev = threading.Event(); ev.set(); return ev\n"
        "    def recv(self, timeout=None):\n"
        "        time.sleep(timeout); raise TimeoutError\n"
        "sh = S.Shadow('K', 'S', sys.argv[1], connect=lambda url, **kw: WS(),\n"
        "              http_get=lambda url: {'serverTime': time.time() * 1000})\n"
        "signal.signal(signal.SIGTERM, lambda *_: sh.stop.set())\n"       # as main() does
        "sh.run()\n")
    p = subprocess.Popen([sys.executable, "-c", script, str(out)], stderr=subprocess.PIPE, text=True,
                         cwd=pathlib.Path(S.__file__).parents[2])
    try:
        deadline = time.monotonic() + 20
        while not (out.exists() and b'"open"' in out.read_bytes()):       # connected: it is inside recv() now
            if time.monotonic() > deadline or p.poll() is not None:
                p.kill()
                pytest.fail("the child never connected: " + p.communicate()[1][-2000:])
            time.sleep(0.02)
        time.sleep(0.3)
        p.send_signal(signal.SIGTERM)
        try:
            code = p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
            code = "still running 20 s after SIGTERM"
        assert code == 0, p.communicate()[1][-2000:]
    finally:
        if p.poll() is None:
            p.kill()
        p.communicate()
    rows = [json.loads(x) for x in out.read_bytes().split(b"\n") if x]
    assert rows[-1]["event"] == "stopped" and rows[-1]["dropped"] == 0 and rows[-1]["write_failed"] == 0
    assert [r.get("event") for r in rows if r["k"] == "conn"] == ["open", "stopped"]


def test_a_record_torn_by_a_full_disk_is_closed_before_the_next_one(tmp_path, monkeypatch):
    sh, _, _ = _shadow(tmp_path)
    sh.write(dict(k="ann", title="first"))
    sh.write(dict(k="ann", title="second"))
    real, calls = os.write, []

    def write(fd, data):
        calls.append(len(data))
        if len(calls) == 1:
            return real(fd, data[:10])                           # a short write: only part of the record fits ...
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device")   # ... then the disk is full
        return real(fd, data)

    monkeypatch.setattr(os, "write", write)
    sh.stop.set()                                                # (a set stop also skips the 30 s pause)
    sh.writer_loop()
    lines = _file_lines(sh)
    assert lines[0] == b'{"k": "ann'                             # the torn record stays, on a line of its own
    rows = [json.loads(x) for x in lines[1:]]                    # every later line parses by itself
    assert [(r["k"], r.get("title"), r.get("n")) for r in rows] == [("writer", None, 1), ("ann", "second", None)]
    assert sh.write_failed == 1
    assert pathlib.Path(sh.out_path).read_bytes().endswith(b"}\n")


def test_the_first_record_after_a_restart_does_not_join_a_torn_last_line(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    pathlib.Path(sh.out_path).write_bytes(b'{"k": "conn"}\n{"k": "ann", "tit')        # killed in the middle of a write
    sh._append('{"k": "clock"}\n')
    sh._append('{"k": "x"}\n')                                   # after a complete line: no blank line in between
    assert pathlib.Path(sh.out_path).read_bytes() == b'{"k": "conn"}\n{"k": "ann", "tit\n{"k": "clock"}\n{"k": "x"}\n'


def _rows_that_parse(lines):
    """The reading rule of the module text: line by line, a line that does not parse is skipped."""
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:                                       # (UnicodeDecodeError is one)
            pass
    return rows


def test_a_line_torn_inside_a_character_is_skipped_by_a_reader_that_follows_the_module_text(tmp_path, monkeypatch):
    sh, _, _ = _shadow(tmp_path)
    sh.write(dict(k="ann", title="업비트 신규 거래지원 안내"))
    sh.write(dict(k="ann", title="다음 공지"))
    real, calls = os.write, []

    def write(fd, data):
        calls.append(len(data))
        if len(calls) == 1:
            return real(fd, data[:24])                           # ends after the first of the three bytes of "업"
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(fd, data)

    monkeypatch.setattr(os, "write", write)
    sh.stop.set()
    sh.writer_loop()
    raw = pathlib.Path(sh.out_path).read_bytes()
    assert raw.split(b"\n")[0] == b'{"k": "ann", "title": "\xec'
    with pytest.raises(UnicodeDecodeError):                      # the FILE is not valid UTF-8 any more: reading it
        with open(sh.out_path, encoding="utf-8") as f:           # as text fails before there is a line to skip
            list(f)
    expected = [("writer", None, 1), ("ann", "다음 공지", None)]
    assert [(r["k"], r.get("title"), r.get("n")) for r in _rows_that_parse(raw.split(b"\n"))] == expected
    with open(sh.out_path, encoding="utf-8", errors="replace") as f:
        assert [(r["k"], r.get("title"), r.get("n")) for r in _rows_that_parse(f)] == expected
    assert "as BYTES" in S.__doc__ and 'errors="replace"' in S.__doc__ and "UnicodeDecodeError" in S.__doc__


class Fatal(BaseException):
    """What `except Exception` does not catch."""


def test_a_normal_stop_does_not_take_the_exit_path(tmp_path, monkeypatch):
    sh, _, _ = _shadow(tmp_path)
    codes = []
    monkeypatch.setattr(S.os, "_exit", codes.append)
    sh.write(dict(k="x"))
    sh.stop.set()
    sh.writer_loop()
    assert codes == [] and len(_file_lines(sh)) == 1


def test_a_dying_writer_thread_takes_the_exit_path(tmp_path, monkeypatch):
    sh, _, _ = _shadow(tmp_path)
    codes = []
    monkeypatch.setattr(S.os, "_exit", codes.append)

    def append(line):
        raise Fatal()

    sh._append = append
    sh.write(dict(k="x"))
    t = threading.Thread(target=sh.writer_loop)
    t.start()
    t.join(10)
    assert not t.is_alive() and codes == [S.EXIT_WRITER_DEAD] and S.EXIT_WRITER_DEAD not in (0, None)


class Unprintable(Exception):
    """An exception that cannot even be turned into text."""

    def __str__(self):
        raise Unprintable()


def test_an_exception_that_cannot_be_printed_costs_one_record_not_the_writer_thread(tmp_path, monkeypatch, caplog):
    sh, _, _ = _shadow(tmp_path)
    codes, real, n = [], sh._append, [0]
    monkeypatch.setattr(S.os, "_exit", codes.append)

    def append(line):
        n[0] += 1
        if n[0] == 1:
            raise Unprintable()
        real(line)

    sh._append = append
    sh.write(dict(k="x", i=0))
    sh.write(dict(k="x", i=1))
    sh.stop.set()
    sh.writer_loop()                                             # used to end here, without the exit: alive and silent
    rows = [json.loads(x) for x in _file_lines(sh)]
    assert codes == [] and [(r["k"], r.get("n"), r.get("i")) for r in rows] == [("writer", 1, None), ("x", None, 1)]
    assert "write failed: Unprintable" in caplog.text


def test_a_log_call_that_fails_does_not_end_the_writer_thread_either(tmp_path, monkeypatch):
    sh, _, _ = _shadow(tmp_path)
    codes, real, n = [], sh._append, [0]
    monkeypatch.setattr(S.os, "_exit", codes.append)

    def warning(*a, **k):
        raise RuntimeError("logging is broken")

    monkeypatch.setattr(S.log, "warning", warning)

    def append(line):
        n[0] += 1
        if n[0] == 1:
            raise ValueError("a bad record")
        real(line)

    sh._append = append
    sh.write(dict(k="x", i=0))
    sh.write(dict(k="x", i=1))
    sh.stop.set()
    sh.writer_loop()
    assert codes == [] and [json.loads(x).get("i") for x in _file_lines(sh)] == [None, 1] and sh.write_failed == 1


@pytest.mark.parametrize("broken", ["the log call", "the text of the exception"])
def test_nothing_stands_between_a_dying_writer_thread_and_the_exit(tmp_path, monkeypatch, broken):
    """The exit is what makes systemd start a new logger. It must not depend on being able to SAY why."""
    sh, _, _ = _shadow(tmp_path)
    codes = []
    monkeypatch.setattr(S.os, "_exit", codes.append)

    class Dying(BaseException):
        def __str__(self):
            if broken == "the text of the exception":
                raise Dying()
            return "dying"

    def critical(*a, **k):
        raise RuntimeError("logging is broken")

    if broken == "the log call":
        monkeypatch.setattr(S.log, "critical", critical)

    def append(line):
        raise Dying()

    sh._append = append
    sh.write(dict(k="x"))
    try:
        sh.writer_loop()
    except BaseException:  # noqa: BLE001  only because os._exit is a mock here: the real one does not return
        pass
    assert codes == [S.EXIT_WRITER_DEAD]


def test_a_dead_writer_thread_ends_the_real_process_with_a_failure_code(tmp_path):
    """No mock: a child process whose main thread is busy elsewhere must still END, non-zero, when its writer thread
    dies - otherwise it would look alive to systemd (Restart=always never fires) while nothing is logged any more."""
    script = (
        "import sys, threading, time\n"
        "from live_v6.tools import ann_ws_shadow as S\n"
        "class Fatal(BaseException): pass\n"
        "def append(line): raise Fatal()\n"
        "sh = S.Shadow('K', 'S', sys.argv[1])\n"
        "sh._append = append\n"
        "sh.write(dict(k='x'))\n"
        "threading.Thread(target=sh.writer_loop, name='ann-writer', daemon=True).start()\n"
        "time.sleep(60)\n"                                       # the receive loop, blocked in recv / a long backoff
        "sys.exit(0)\n")
    r = subprocess.run([sys.executable, "-c", script, str(tmp_path / "out.jsonl")], capture_output=True, text=True,
                       timeout=30, cwd=pathlib.Path(S.__file__).parents[2])
    assert r.returncode == S.EXIT_WRITER_DEAD == 70, r.stderr[-2000:]
    assert "writer thread died" in r.stderr


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
    assert mods <= {"__future__", "argparse", "hashlib", "hmac", "json", "logging", "math", "os", "queue", "re", "secrets",
                    "signal", "threading", "time", "httpx", "websockets"}
    for banned in ("/fapi/v1/order", "/fapi/v1/leverage", "/fapi/v1/marginType", "listenKey", "new_order"):
        assert banned not in src


# ───────────────────────── systemd units (parsed here; systemd itself only runs on the server) ──────────────────────

DEPLOY = pathlib.Path(S.__file__).parents[1] / "deploy"
# Every directive the logger units may use. Each one was looked up in the systemd 255 manual (the server's version):
# systemd.unit(5), systemd.service(5), systemd.exec(5), systemd.kill(5), systemd.resource-control(5). A directive
# that is not listed here - a typo, or User= / ReadWritePaths= / BindPaths= coming back - fails the parse.
UNIT_DIRECTIVES = {
    "Unit": {"Description", "After", "Wants"},
    "Service": {"DynamicUser", "SupplementaryGroups", "WorkingDirectory", "EnvironmentFile", "Environment",
                "ExecStart", "Restart", "RestartSec", "KillSignal", "TimeoutStopSec", "StateDirectory",
                "StateDirectoryMode", "UMask", "NoNewPrivileges", "ProtectSystem", "ProtectHome", "PrivateTmp",
                "PrivateDevices", "ProtectKernelTunables", "ProtectControlGroups", "RestrictAddressFamilies",
                "InaccessiblePaths", "ProtectProc", "ProcSubset", "MemoryMax", "CPUQuota", "CPUQuotaPeriodSec"},
    "Install": {"WantedBy"},
}
ISOLATION = {
    # a UID of its own (no /proc/<bot pid>/environ, no signals to the bot); the bot's group only to read the code
    "DynamicUser": "yes", "SupplementaryGroups": "tradebot", "ProtectProc": "invisible", "ProcSubset": "pid",
    # kept from the first version of the units
    "StateDirectoryMode": "0700", "UMask": "0077", "NoNewPrivileges": "true", "ProtectSystem": "strict",
    "ProtectHome": "true", "PrivateTmp": "true", "PrivateDevices": "true", "ProtectKernelTunables": "true",
    "ProtectControlGroups": "true", "RestrictAddressFamilies": "AF_INET AF_INET6", "MemoryMax": "200M",
    "CPUQuota": "20%", "Restart": "always", "RestartSec": "30", "KillSignal": "SIGTERM",
    # the cap is counted per second: with the default 100 ms period 20 ms of work freezes the process for the rest
    # of the period, and a push that arrives then is stamped late (seen on the server: 53 times in 4 h)
    "CPUQuotaPeriodSec": "1s",
    "WorkingDirectory": "/opt/tradebot/app/current", "Environment": "WEBSOCKETS_MAX_REDIRECTS=1",
}


def unit_file(path):
    """(header comment, {section: {directive: [values]}}) of a unit file. Strict on purpose: a line that is not a
    comment, a blank, a [Section] or a plain `Directive=value` with a directive from UNIT_DIRECTIVES fails."""
    header, sections, name = [], {}, None
    for n, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8").splitlines(), 1):
        where = f"{path}:{n}: {line!r}"
        if line.startswith("#"):
            if name is None:
                header.append(line)
            continue
        if not line:
            continue
        assert line == line.strip() and not line.endswith("\\"), where
        if line.startswith("["):
            name = line[1:-1]
            assert line.endswith("]") and name in UNIT_DIRECTIVES and name not in sections, where
            sections[name] = {}
            continue
        key, eq, value = line.partition("=")
        assert name is not None and eq and value and value == value.strip(), where
        assert key in UNIT_DIRECTIVES[name], where
        sections[name].setdefault(key, []).append(value)
    return "\n".join(header), sections


def check_logger_unit(name, *, module, env_file, hidden=()):
    """What both logger units must guarantee. Returns (header comment, [Service] settings) for unit-specific checks."""
    stem = name.removesuffix(".service")
    # without User= the dynamic user is named after the unit, which only works for a valid user name (systemd.exec)
    assert name.endswith(".service") and re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", stem)
    header, unit = unit_file(DEPLOY / name)
    assert set(unit) == {"Unit", "Service", "Install"} and unit["Install"] == {"WantedBy": ["multi-user.target"]}
    assert all(len(v) == 1 for v in unit["Service"].values()), "a directive is given twice"
    svc = {k: v[0] for k, v in unit["Service"].items()}
    for key, value in ISOLATION.items():
        assert svc.get(key) == value, key
    # the bot's group must not open the trading keys or the bot state; no "-": a missing path fails the start.
    # Nor the bot's alert log and the CI logs (the directory the CI import sandbox denies too); with "-": that
    # directory was not checked on the server, and a logger that does not start measures nothing
    assert svc["InaccessiblePaths"].split() == ["/etc/tradebot", "/var/lib/live_v6-live", "-/var/log/tradebot",
                                                "-/var/lib/live_v6", *hidden]
    # accurate time first; the box syncs with systemd-timesyncd, so no unit of one particular NTP daemon is named
    assert unit["Unit"]["After"] == ["network-online.target time-sync.target"]
    assert svc["EnvironmentFile"] == env_file                    # exactly one, and not optional ("-" prefix)
    assert svc["StateDirectory"] == stem
    assert svc["ExecStart"] == (f"/opt/tradebot/.venv/bin/python -m live_v6.tools.{module} "
                                f"--out /var/lib/{stem}/{module}.jsonl")
    # a stop during a connection attempt: open_timeout 10 s, then close_timeout 3 s and the two waits of _shutdown
    assert int(svc["TimeoutStopSec"]) > 10 + 3 + S.STOP_CLOCK_S + S.STOP_WRITER_S
    assert 10 > 1 + 3 + S.STOP_CLOCK_S + S.STOP_WRITER_S                               # the usual stop: recv 1 s
    for needle in ("systemd-analyze verify", "systemd-analyze security", f"/var/lib/private/{stem}",
                   "DynamicUser", "EnvironmentFile", "Migrate", "Verify", "Remove", "/var/log/tradebot"):
        assert needle in header, needle
    return header, svc


def test_binance_logger_unit_runs_isolated_from_the_bot():
    _, svc = check_logger_unit("tradebot-ann-shadow.service", module="ann_ws_shadow",
                               env_file="/etc/tradebot/live.env")
    assert svc["TimeoutStopSec"] == "20"


def test_binance_logger_unit_does_not_claim_that_the_logger_is_kept_from_the_trading_keys():
    """It is handed the bot's own env file. The unit hides the bot's key FILE; the key pair is in the logger."""
    text = (DEPLOY / "tradebot-ann-shadow.service").read_text(encoding="utf-8")
    header, unit = unit_file(DEPLOY / "tradebot-ann-shadow.service")
    assert unit["Service"]["EnvironmentFile"] == ["/etc/tradebot/live.env"]
    assert 'os.environ["BINANCE_API_KEY"]' in pathlib.Path(S.__file__).read_text(encoding="utf-8")
    assert "keys and state are not even readable" not in text and "is the only writable place" not in text
    for needle in ("does NOT do", "BINANCE_API_KEY / BINANCE_API_SECRET into the environment of this process",
                   "the bot's UID can change what this unit runs"):
        assert needle in header, needle
    comment = [line for line in text.splitlines() if line.startswith("# isolation:")]
    assert len(comment) == 1 and "/tmp" in comment[0] and "PrivateTmp" in comment[0]


@pytest.mark.parametrize("line", ["User=tradebot", "Group=tradebot", "ReadWritePaths=/var/lib/live_v6-live",
                                  "BindPaths=/etc/tradebot", "ProtectProcs=invisible", "ProcSubset = pid",
                                  "ExecStart=/bin/true \\", "NoNewPrivileges="])
def test_unit_parser_refuses_unknown_misspelt_or_malformed_directives(tmp_path, line):
    unit = tmp_path / "x.service"
    unit.write_text("# header\n[Service]\nDynamicUser=yes\n" + line + "\n")
    with pytest.raises(AssertionError):
        unit_file(unit)
    unit.write_text("# header\n[Service]\nDynamicUser=yes\n")
    assert unit_file(unit) == ("# header", {"Service": {"DynamicUser": ["yes"]}})


# Review 2 regressions: F1--F6, fake transports only.
@pytest.mark.parametrize('nested', [False, True])
def test_f1_redacts_frames_before_cut_and_keeps_json(tmp_path, monkeypatch, nested):
    monkeypatch.setattr(S, 'RECONNECT_S', 3)
    sh, _, clock = _shadow(tmp_path)
    sh.key, sh.secret = 'fake-key-"quoted"-tail', 'fake-secret-\\slash-tail'
    data = dict(title='x' * 490 + sh.key + ' ' + sh.secret, catalogName=sh.secret,
                publishDate=1, note=sh.key)
    raw = json.dumps(dict(type='DATA', data=json.dumps(data) if nested else data))
    sh._connect = lambda *a, **kw: FakeWS([raw, 'x' * 290 + sh.secret], clock)
    sh.run_once()
    rows = _drain(sh)
    ann = next(r for r in rows if r['k'] == 'ann')
    assert '[REDACTED]' in ann['title'] and 'fake-key-' not in ann['title']
    assert ann['catalogName'] == '[REDACTED]'
    assert 'fake-secret-' not in next(r['raw'] for r in rows if r['k'] == 'other')
    for r in rows:
        sh.write(r)
    sh.stop.set()
    sh.writer_loop()
    for line in _file_lines(sh):
        json.loads(line)
        assert b'fake-key-' not in line and b'fake-secret-' not in line


def test_f1_common_queue_and_final_file_boundary(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    sh.write(dict(k='future', nested={sh.key: [sh.secret, '/sapi/wss?x=1&signature=abc123&tail=ok']}))
    queued = _drain(sh)[0]
    text = json.dumps(queued)
    assert sh.key not in text and sh.secret not in text and 'abc123' not in text
    # Bypass write(): future producers must still meet the writer's final boundary.
    sh.q.put(dict(k='future', title=sh.secret, detail='signature=abc123'))
    sh.stop.set()
    sh.writer_loop()
    line = _file_lines(sh)[0]
    assert json.loads(line)['title'] == '[REDACTED]'
    assert b'abc123' not in line


@pytest.mark.parametrize('kind', ['conn', 'clock'])
def test_f1_error_redaction_precedes_scrub_truncation(tmp_path, kind):
    sh, _, _ = _shadow(tmp_path)
    def fail(*a, **kw):
        raise RuntimeError('x' * 280 + sh.secret + ' ' + sh.key + ' /sapi/wss?signature=abc123')
    if kind == 'conn':
        sh._connect = fail
        _run_with_waits(sh, 1)
    else:
        sh._http_get = fail
        sh._clock_sleep = lambda *a: sh.stop.set()
        sh.clock_loop()
    row = next(r for r in _drain(sh) if r['k'] == kind and ('error' in r or r.get('event') == 'error'))
    text = json.dumps(row)
    assert sh.secret not in text and sh.key not in text and 'abc123' not in text
    assert 'SECR' not in text and '[REDAC' in text  # truncating the harmless marker is safe


def _assert_main_log_filter(module, cls, monkeypatch, tmp_path, env_prefix):
    import io
    import logging
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    root.handlers[:] = [handler]
    monkeypatch.setenv(env_prefix[0], 'fake-log-key')
    monkeypatch.setenv(env_prefix[1], 'fake-log-secret')
    monkeypatch.setattr(module.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(S, '_connect_no_redirect', lambda: None)
    def run(self):
        for name in ('live_v6.ann_ws_shadow', 'httpx', 'websockets.client'):
            try:
                raise RuntimeError(self.secret + ' eyJ.a.b')
            except RuntimeError:
                logging.getLogger(name).warning('key=%s /sapi/wss?signature=abc123', self.key, exc_info=True)
    monkeypatch.setattr(cls, 'run', run)
    monkeypatch.setattr(threading, 'excepthook', threading.excepthook)    # main() installs its own: put back after
    old_mask = os.umask(0o077)
    try:
        assert module.main(['--out', str(tmp_path / 'log')]) == 0
        assert threading.excepthook is S._log_thread_exception            # a thread's end goes through the filter
        thread = threading.Thread(target=lambda: (_ for _ in ()).throw(RuntimeError('fake-log-secret in a thread')))
        thread.start()
        thread.join()
        warnings.warn('fake-log-key in a warning')                         # captured into logging by main()
    finally:
        logging.captureWarnings(False)
        root.handlers[:] = old_handlers
        os.umask(old_mask)
    output = stream.getvalue()
    assert 'fake-log-key' not in output and 'fake-log-secret' not in output and 'abc123' not in output
    assert '[REDACTED]' in output and '[REDACTED] in a thread' in output and '[REDACTED] in a warning' in output
    if cls is not S.Shadow:
        assert 'eyJ.a.b' not in output


def test_f1_main_filters_all_root_handler_logs(tmp_path, monkeypatch):
    _assert_main_log_filter(S, S.Shadow, monkeypatch, tmp_path, ('BINANCE_API_KEY', 'BINANCE_API_SECRET'))


@pytest.mark.parametrize('failure', ['size', 'rotate'])
def test_f2_rotation_or_stat_failure_loses_row_and_recovers(tmp_path, monkeypatch, failure):
    sh, _, _ = _shadow(tmp_path)
    path = pathlib.Path(sh.out_path)
    path.write_text('old\n')
    monkeypatch.setattr(S, 'MAX_FILE_BYTES', 2)
    real_size, real_replace = os.path.getsize, os.replace
    def refuse(*a):
        raise PermissionError(errno.EACCES, 'offline denied')
    monkeypatch.setattr(os.path, 'getsize', refuse if failure == 'size' else real_size)
    monkeypatch.setattr(os, 'replace', refuse if failure == 'rotate' else real_replace)
    waits = []
    sh.stop.wait = waits.append
    sh.write(dict(k='must_be_lost'))
    sh.stop.set()
    sh.writer_loop()
    assert path.read_text() == 'old\n' and sh.write_failed == 1 and waits == [30.0]
    monkeypatch.setattr(os.path, 'getsize', real_size)
    monkeypatch.setattr(os, 'replace', real_replace)
    monkeypatch.setattr(S, 'MAX_FILE_BYTES', 10000)
    sh.write(dict(k='recovered'))
    sh.writer_loop()
    rows = [json.loads(x) for x in _file_lines(sh)[1:]]
    assert [(r['k'], r.get('event'), r.get('n')) for r in rows] == [('writer', 'lost', 1), ('recovered', None, None)]


def test_f2_missing_file_is_normal_first_append(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    sh._append('{}\n')
    assert _file_lines(sh) == [b'{}']


def test_f3_selected_sample_midpoint_is_the_offset_age_origin(tmp_path):
    sh, _, clock = _shadow(tmp_path)
    start = clock.now
    rtts = iter([.004, .01, .02, .03, .04])
    def get(url):
        rtt = next(rtts)
        clock.now += rtt
        return dict(serverTime=(clock.now - rtt / 2) * 1000)
    sh._http_get = get
    sh.measure_clock()
    row = _drain(sh)[0]
    assert row['sample_ms'] == pytest.approx((start + .002) * 1000)
    assert sh.offset_at == pytest.approx(start + .002)
    assert sh._offset()[1] == pytest.approx(clock.now - start - .002)


def test_f3_push_during_measurement_gets_a_genuinely_later_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'RECONNECT_S', .001)
    sh, _, clock, wall = _stepping(tmp_path)
    sh.offset_ms, sh.offset_at, sh.offset_ref, sh.offset_rtt_ms = 0, clock.now, wall() - clock.now, 4
    n = [0]
    def get(url):
        n[0] += 1
        if n[0] == 2:
            wall.true_shift += .3  # both local clocks lost 300 ms; no step
            raw = json.dumps(dict(type='DATA', data=dict(title='notice', publishDate=wall.true_ms() + 900)))
            sh._connect = lambda *a, **kw: FakeWS([raw], clock)
            sh.run_once()
        rtt = .004 if n[0] % 5 == 1 else .008
        clock.now += rtt
        return dict(serverTime=wall.true_ms() - rtt * 500)
    sh._http_get = get
    starts = _run_clock_thread(sh, clock, until=clock.now + 30)
    rows = _drain(sh)
    ann = next(r for r in rows if r['k'] == 'ann')
    assert ann['lag_ms'] == pytest.approx(-200, abs=.1)  # true lag: 100 ms
    clocks = [r for r in rows if r['k'] == 'clock' and 'offset_ms' in r]
    assert len(starts) == len(clocks) == 2 and starts[1] - starts[0] >= 10
    assert rows.index(ann) < rows.index(clocks[0])  # written later, sampled BEFORE the announcement
    assert clocks[0]['sample_ms'] < ann['recv_ms'] < clocks[1]['sample_ms']
    assert clocks[0]['offset_ms'] == pytest.approx(0, abs=.01)
    assert clocks[1]['offset_ms'] == pytest.approx(300, abs=.01)
    for phrase in ('sample_ms', 'recv_ms', 'Never pick one of them'):
        assert phrase in S.__doc__


def _assert_recv_wait(module, sh, clock, raw, monkeypatch):
    import builtins
    expected_stamp, calls = [False], []
    original_clock, original_mono = sh.clock, sh.mono
    def wall():
        if expected_stamp[0]:
            expected_stamp[0] = False
            calls.append('stamp')
        return original_clock()
    def mono():
        assert not expected_stamp[0], 'monotonic read ran before receive stamp'
        return original_mono()
    sh.clock, sh.mono = wall, mono
    class WS:
        def __enter__(self):
            self.n = 0
            return self
        def __exit__(self, *a):
            pass
        def send(self, message):
            pass
        def recv(self, timeout):
            self.n += 1
            if self.n == 1:
                clock.now += .020
            else:
                sh.stop.set()  # second frame was already buffered
            expected_stamp[0] = True
            return raw
    sh._connect = lambda *a, **kw: WS()
    original_parse = module.parse_push
    def parse(*a, **kw):
        assert not expected_stamp[0]
        clock.now += .065  # processing the previous frame delays the buffered frame
        return original_parse(*a, **kw)
    monkeypatch.setattr(module, 'parse_push', parse)
    def forbidden(*a, **kw):
        raise AssertionError('receive thread must not read/write files')
    monkeypatch.setattr(builtins, 'open', forbidden)
    monkeypatch.setattr(os, 'open', forbidden)
    sh.run_once()
    rows = [r for r in _drain(sh) if r['k'] in ('ann', 'upbit_ann')]
    assert calls == ['stamp', 'stamp']
    assert [r['recv_wait_ms'] for r in rows] == [20.0, 0.0]
    assert rows[1]['recv_ms'] - rows[0]['recv_ms'] == pytest.approx(65)


def test_f4_recv_wait_marks_buffered_frames_and_stamps_before_work(tmp_path, monkeypatch):
    sh, _, clock = _shadow(tmp_path)
    _assert_recv_wait(S, sh, clock, DOC_PUSH, monkeypatch)


@pytest.mark.parametrize(('membership', 'stats', 'expected'), [
    ('0::/system.slice/offline.service\n', 'usage_usec 123\nnr_throttled 53\nthrottled_usec 12345\n', (53, 12.345)),
    ('0::/\n', 'nr_throttled 0\nthrottled_usec 0\n', (0, 0.0)),
    ('2:cpu:/other\n0::/a:b\n', 'nr_throttled 7\nthrottled_usec 2000\n', (7, 2.0)),
    (None, None, (None, None)),
    ('2:cpu:/legacy\n', '', (None, None)),
    ('0::/a\n', None, (None, None)),
    ('0::/a\n', 'nr_throttled broken\nthrottled_usec 3\n', (None, None)),
    ('0::/a\n', 'nr_throttled 3\n', (None, None)),
    ('0::/a\n', 'nr_throttled -1\nthrottled_usec 3\n', (None, None)),
])
def test_f4_cgroup_counters_are_clock_thread_only_and_optional(tmp_path, monkeypatch, membership, stats, expected):
    import builtins
    sh, _, _ = _shadow(tmp_path)
    group_file, stat_file = tmp_path / 'cgroup', tmp_path / 'cpu.stat'
    group_file.write_text(membership or '')
    stat_file.write_text(stats or '')
    original = builtins.open
    seen = []
    def fake_open(path, *a, **kw):
        assert threading.current_thread().name == 'offline-clock'
        seen.append(str(path))
        if str(path) == '/proc/self/cgroup' and membership is not None:
            return original(group_file, *a, **kw)
        suffix = next((line[3:] for line in (membership or '').splitlines() if line.startswith('0::')), None)
        if suffix is not None and str(path) == '/sys/fs/cgroup' + suffix.rstrip('/') + '/cpu.stat' and stats is not None:
            return original(stat_file, *a, **kw)
        raise FileNotFoundError(path)
    monkeypatch.setattr(builtins, 'open', fake_open)
    t = threading.Thread(target=sh.measure_clock, name='offline-clock')
    t.start()
    t.join(5)
    assert not t.is_alive()
    row = _drain(sh)[0]
    assert (row['throttled_n'], row['throttled_ms']) == expected
    assert seen and 'offset_ms' in row


@pytest.mark.parametrize('value', ['1e999', '-1e999', 'NaN', '9' * 600, '"123"', 'true'],
                         ids=['positive-overflow', 'negative-overflow', 'nan', 'huge-int', 'string', 'bool'])
def test_f5_bad_publish_date_keeps_row_with_null_lags(tmp_path, monkeypatch, value):
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    raw = '{"type":"DATA","data":{"title":"notice","publishDate":' + value + '}}'
    sh, _, _ = _shadow(tmp_path, [raw])
    sh.offset_ms, sh.offset_at, sh.offset_ref = 0, 1000, 0
    sh.run_once()
    ann = next(r for r in _drain(sh) if r['k'] == 'ann')
    assert [ann[k] for k in ('publish_ms', 'lag_raw_ms', 'lag_ms')] == [None, None, None]
    sh.write(ann)
    sh.stop.set()
    sh.writer_loop()
    for line in _file_lines(sh):
        json.loads(line, parse_constant=lambda x: pytest.fail('non-finite JSON: ' + x))


def test_f5_writer_replaces_only_nonfinite_values_and_uses_strict_json(tmp_path, monkeypatch):
    sh, _, _ = _shadow(tmp_path)
    original, seen = S.json.dumps, []
    def dumps(*a, **kw):
        seen.append(kw.get('allow_nan'))
        return original(*a, **kw)
    monkeypatch.setattr(S.json, 'dumps', dumps)
    sh.q.put(dict(k='future', nested=[float('inf'), dict(x=float('nan')), float('-inf'), 3.0], title='keep'))
    sh.stop.set()
    sh.writer_loop()
    row = json.loads(_file_lines(sh)[0], parse_constant=lambda x: pytest.fail(x))
    assert row == dict(k='future', nested=[None, dict(x=None), None, 3.0], title='keep')
    assert seen and all(value is False for value in seen)
    assert sh.write_failed == 0


@pytest.mark.parametrize('stop_at', [1, 3, 5])
def test_f6_stop_between_samples_emits_no_clock_row(tmp_path, stop_at):
    sh, _, clock = _shadow(tmp_path)
    calls = []
    def get(url):
        calls.append(url)
        clock.now += .004
        if len(calls) == stop_at:
            sh.stop.set()
        return dict(serverTime=clock.now * 1000)
    sh._http_get = get
    sh.measure_clock()
    assert len(calls) == stop_at and _drain(sh) == [] and sh.offset_ms is None


def test_f6_writes_after_producers_done_are_counted_not_enqueued(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    sh._producers_done.set()
    sh.write(dict(k='clock', offset_ms=1))
    assert sh.q.empty() and sh.dropped == 1


def test_f6_clock_request_outliving_shutdown_cannot_follow_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'STOP_CLOCK_S', .01)
    sh, _, _ = _shadow(tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def get(url):
        entered.set()
        assert release.wait(5)
        return dict(serverTime=1)
    sh._http_get = get
    def clock_loop():
        try:
            sh.measure_clock()
        finally:
            finished.set()
    sh.clock_loop = clock_loop
    def once():
        assert entered.wait(5)
        sh.stop.set()
    sh.run_once = once
    try:
        sh.run()
    finally:
        release.set()
    assert finished.wait(5)
    assert sh.q.empty()
    rows = [json.loads(x) for x in _file_lines(sh)]
    assert [r.get('event') for r in rows] == ['stopped']


def test_f1_writer_error_is_redacted_before_journal_truncation(tmp_path, caplog):
    sh, _, _ = _shadow(tmp_path)
    def append(line):
        raise ValueError('x' * 284 + sh.secret + ' trailing')
    sh._append = append
    sh.write(dict(k='future'))
    sh.stop.set()
    sh.writer_loop()
    assert 'SECR' not in caplog.text and '[RED' in caplog.text


@pytest.mark.parametrize('prefix', ['/sapi/wss?x=1&', 'wss://api.binance.com/sapi/wss?x=1&', ''])
def test_f1_signature_values_redacted_in_valid_json(tmp_path, prefix):
    sh, _, _ = _shadow(tmp_path)
    sh.write(dict(k='future', detail=prefix + 'signature=abc123&tail=ok'))
    queued = _drain(sh)[0]
    assert queued['detail'] == prefix + 'signature=[REDACTED]&tail=ok'
    sh.q.put(queued)
    sh.stop.set()
    sh.writer_loop()
    row = json.loads(_file_lines(sh)[0])
    assert row['detail'] == queued['detail']


@pytest.mark.parametrize('nested', [False, True])
def test_f1_json_escaping_cannot_turn_public_quote_into_a_secret_match(tmp_path, monkeypatch, nested):
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, clock = _shadow(tmp_path)
    sh.secret = 'fake-escape-\\'
    title = 'fake-escape-"still public'
    data = dict(title=title, publishDate=1)
    raw = json.dumps(dict(type='DATA', data=json.dumps(data) if nested else data))
    sh._connect = lambda *a, **kw: FakeWS([raw], clock)
    sh.run_once()
    ann = next(r for r in _drain(sh) if r['k'] == 'ann')
    assert ann['title'] == title
    sh.q.put(dict(k='future', title=title, hidden=sh.secret))
    sh.stop.set()
    sh.writer_loop()
    row = json.loads(_file_lines(sh)[0])
    assert row['title'] == title and row['hidden'] == '[REDACTED]'


def test_f1_final_redaction_leaves_json_numeric_tokens_intact(tmp_path):
    sh, _, _ = _shadow(tmp_path)
    sh.secret = '123'
    sh.q.put(dict(k='future', n=123, title='123'))
    sh.stop.set()
    sh.writer_loop()
    assert json.loads(_file_lines(sh)[0]) == dict(k='future', n=123, title='[REDACTED]')


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'utf-32'])
def test_f1_binary_json_encodings_keep_redaction_and_ann_rows(tmp_path, monkeypatch, encoding):
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, clock = _shadow(tmp_path)
    raw = json.dumps(dict(type='DATA', data=dict(title='x' * 490 + sh.secret, publishDate=1))).encode(encoding)
    sh._connect = lambda *a, **kw: FakeWS([raw], clock)
    sh.run_once()
    ann = next(r for r in _drain(sh) if r['k'] == 'ann')
    assert ann['title'] == 'x' * 490 + '[REDACTED]'


def test_f1_invalid_binary_json_stays_an_other_row(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    raw = b'{"type":"DATA","data":{"title":"\xff","publishDate":1}}'
    sh, _, _ = _shadow(tmp_path, [raw])
    sh.run_once()
    rows = _drain(sh)
    assert not any(r['k'] == 'ann' for r in rows)
    # logged as text (the byte that is not UTF-8 replaced), never as a bytes repr that nothing could redact in
    assert (next(r['raw'] for r in rows if r['k'] == 'other')
            == '{"type":"DATA","data":{"title":"\ufffd","publishDate":1}}')


# ───────────────────────── review 2 of 0ec0d61: what the fixes keep true ─────────────────────────

FAKE_KEY = "FAKEKEYa2jQ" + "k" * 53                     # 64 characters, like a real key - and fake
FAKE_SECRET = "FAKESECRETzz" + "s" * 52


def _timed(fn):
    started = time.perf_counter()
    fn()
    return time.perf_counter() - started


def _node_tree_frame(nodes, title="Binance Will Delist AAA"):
    """A push whose body is a JSON node tree (as the CMS may send it): `nodes` paragraphs, ~150 bytes each."""
    node = {"node": "element", "tag": "p", "child": [{"node": "text", "text": "Binance will delist AAA."}]}
    body = json.dumps({"node": "root", "child": [node] * nodes})
    data = dict(catalogId=161, catalogName="Delisting", publishDate=1, title=title, body=body)
    return json.dumps(dict(type="DATA", topic=S.TOPIC, data=json.dumps(data)))


def _unescape(text):
    """What a reader can do with a logged text: undo JSON / repr escapes as often as they appear, drop NULs."""
    for _ in range(4):
        text = text.replace("\\\\", "\\").replace("\\x00", "").replace("\x00", "")
        text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), text)
    return text


def _has_piece_of(text, secret, n=6):
    return any(secret[i:i + n] in text for i in range(len(secret) - n + 1))


@pytest.mark.parametrize("frame", ["node tree", "short strings", "short strings, one to mask"])
def test_redacting_a_frame_costs_no_more_than_a_few_parses_of_it(tmp_path, frame):
    """Between the stamp and the queue everything runs on the receive thread. 0ec0d61 decoded, redacted and re-encoded
    every string of a frame and built its patterns again for each: 0.28 s for a frame of 3000 nodes (parsing it:
    1.8 ms), 2.5 s for 1 MiB of short strings. A frame with nothing to mask is now passed on after a few scans; in
    one that holds something, only the strings that hold it are decoded."""
    sh, _, _ = _shadow(tmp_path)
    sh.key, sh.secret = FAKE_KEY, FAKE_SECRET
    if frame == "node tree":
        raw = _node_tree_frame(3000)                                         # 456 KB
    else:
        title = "notice" if frame == "short strings" else "notice " + FAKE_KEY
        raw = json.dumps(dict(type="DATA", data=json.dumps(dict(title=title, body=json.dumps(["ab"] * 90_000)))))
    assert len(raw) > 400_000
    parse = min(_timed(lambda: json.loads(json.loads(raw)["data"])) for _ in range(3))
    redact = min(_timed(lambda: sh.redact_json(raw)) for _ in range(3))
    if FAKE_KEY in raw:
        assert redact < 20 * parse + 0.005, (redact, parse)
    else:                                                    # nothing to mask: a few scans, not a walk over its strings
        assert redact < 4 * parse + 0.002, (redact, parse)
        assert sh.redact_json(raw) is raw                    # ... and handed on as it is, not taken apart and rebuilt
    assert (FAKE_KEY in raw) == (sh.redact_json(raw) != raw) and FAKE_KEY not in sh.redact_json(raw)


def test_the_redaction_patterns_are_built_once_per_set_of_secrets(tmp_path, monkeypatch):
    sh, _, _ = _shadow(tmp_path)
    built = sh._patterns()
    sh.redact("x")
    sh.redact_json('{"a": "b", "c": ["KEY", "SECRET"]}')
    assert sh._patterns() is built
    sh.key = "OTHERKEY"                                      # a secret changed: built again, and used at once
    assert sh._patterns() is not built and sh.redact("OTHERKEY KEY") == "[REDACTED] KEY"
    monkeypatch.setattr(S, "RECONNECT_S", 2)
    sh.run_once()                                            # a new signature at every connection attempt
    assert sh._signature and sh.redact(sh._signature) == "[REDACTED]"


def _json_literal(rng, value):
    """`value` as a JSON string literal, each character spelled at random: as itself where JSON allows it, as a
    \\u escape (either case of hex), or as a short escape."""
    out = ['"']
    for ch in value:
        r = rng.random()
        if ch in '"\\':
            out.append("\\" + ch if r < .7 else "\\u%04x" % ord(ch))
        elif ch < " ":                                       # (as it is: not strict JSON, a server may send it)
            out.append("\\u%04x" % ord(ch) if r < .4 else json.dumps(ch)[1:-1] if r < .8 else ch)
        elif ch == "/" and r < .3:
            out.append("\\/")
        elif r < .08:
            out.append(("\\u%04x" if rng.random() < .5 else "\\u%04X") % ord(ch))
        else:
            out.append(ch)
    return "".join(out) + '"'


def _fuzz_json(rng, needles, depth=0):
    """A JSON text whose keys and strings are made of `needles` and filler; some strings are JSON texts again (as
    the DATA of a push is), spelled with escapes of their own."""
    filler = ["x", " ", "é", "가", '"', "\\", "/", "\n", "{", "[", "AbC", "=", ":", "'", "%3D", "0f"]

    def string():
        if depth < 2 and rng.random() < .25:
            return _fuzz_json(rng, needles, depth + 1)
        return "".join(rng.choice(needles if rng.random() < .3 else filler) for _ in range(rng.randrange(7)))

    def value():
        kind = rng.random()
        if kind < .6:
            return _json_literal(rng, string())
        if kind < .8:
            return "[" + ", ".join(_json_literal(rng, string()) for _ in range(rng.randrange(3))) + "]"
        return str(rng.choice([0, 1.5, -3, 123]))

    items = [f"{_json_literal(rng, string())}: {value()}" for _ in range(rng.randrange(1, 5))]
    return "{" + ", ".join(items) + "}"


def _assert_shortcut_changes_nothing(sh, needles, n=3000, seed=20261117):
    """redact_json with its shortcuts must give exactly what decoding and redacting every string gives."""
    import random
    rng = random.Random(seed)
    slow = type(sh).__new__(type(sh))
    slow.__dict__.update(sh.__dict__)
    slow._clean_as_is = lambda text, patterns=None: False                 # every string decoded and redacted
    skipped = 0
    for _ in range(n):
        text = _fuzz_json(rng, needles)
        fast = sh.redact_json(text)
        assert fast == slow.redact_json(text), text
        skipped += fast == text
        try:                                                               # still one JSON text, and strict JSON
            json.loads(text)                                               # when it came as strict JSON
        except ValueError:
            json.loads(fast, strict=False)
        else:
            json.loads(fast)
    assert 0 < skipped < n                                                 # both kinds of text were tried


def test_the_shortcut_of_redact_json_changes_nothing_on_random_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RECONNECT_S", 2)
    sh, _, _ = _shadow(tmp_path)
    sh.key, sh.secret = FAKE_KEY[:20], FAKE_SECRET[:20]
    sh.run_once()                                                          # the signature of a connection, too
    needles = [sh.key, sh.secret, sh.key[:7], sh.secret[5:], sh._signature, sh._signature[:20], "signature",
               "SIGNATURE=", "Signature%3D", '"signature": "', "signature: ", "ab12" * 5, "deadbeef", "sIgNaTuRe=0f",
               "\u017fignature=0f", "s\u0131gnature=0f"]                    # (case folding beyond ASCII: not a match)
    _assert_shortcut_changes_nothing(sh, needles)


@pytest.mark.parametrize("spelling", ["escaped", "utf-16", "utf-32", "utf-16 cut short",
                                      "escaped, in a string JSON cannot read", "escaped twice, in such a string"])
def test_an_unknown_frame_is_logged_masked_whatever_its_spelling(tmp_path, monkeypatch, spelling):
    """0ec0d61 masked only the plain spellings in an `other` row (scrub(raw)): a key spelled with \\u escapes, or a
    UTF-16 / UTF-32 frame (logged as a bytes repr, a NUL between every two characters), went to the file.
    Cross-review of the fix: a string with an escape JSON does not know (\\q) is not decoded by redact_json - the
    frame stays invalid, an `other` row - and a key spelled with \\u escapes in it (once or nested) still went."""
    monkeypatch.setattr(S, "RECONNECT_S", 2)
    sh, _, clock = _shadow(tmp_path)
    sh.key = FAKE_KEY
    text = json.dumps({"type": "PONG", "echo": "x" * 10 + FAKE_KEY})        # not an announcement
    escaped = "".join("\\u%04x" % ord(c) for c in FAKE_KEY)
    if spelling == "escaped":
        raw = text.replace(FAKE_KEY, escaped)
    elif spelling.startswith("escaped"):
        twice = spelling.startswith("escaped twice")
        raw = text.replace(FAKE_KEY, escaped.replace("\\", "\\\\") if twice else escaped).replace('"}', ' \\q"}')
        with pytest.raises(ValueError):
            json.loads(raw)
    elif spelling == "utf-16 cut short":
        raw = text.encode("utf-16") + b"\x00"                               # odd length: not UTF-16 any more
    else:
        raw = text.encode(spelling)
    sh._connect = lambda *a, **kw: FakeWS([raw], clock)
    sh.run_once()
    other = next(r["raw"] for r in _drain(sh) if r["k"] == "other")
    assert "PONG" in other and "[REDACTED]" in other
    assert not _has_piece_of(_unescape(other), FAKE_KEY), other


def test_what_ends_main_a_thread_or_a_warning_reaches_stderr_masked(tmp_path):
    """The redaction sits in the logging handlers. 0ec0d61's main() did not catch what ended run(), and an exception
    whose repr() fails (run() logs repr(e)) went to stderr - the journal - as a traceback with the key in it; so did
    an exception that ended a thread, and a warning. Real child processes, both loggers."""
    script = (
        "import sys, threading, warnings\n"
        "from live_v6.tools import ann_ws_shadow as S, upbit_ann_ws_shadow as U\n"
        "mod, cls = (S, S.Shadow) if sys.argv[2] == 'binance' else (U, U.UpbitShadow)\n"
        "class Evil(RuntimeError):\n"
        "    def __repr__(self): raise ValueError('no repr')\n"
        "    def __str__(self): return 'reflected ' + KEYS[0]\n"
        "KEYS = []\n"
        "def run(self):\n"
        "    KEYS.append(self.key)\n"
        "    t = threading.Thread(target=lambda: (_ for _ in ()).throw(RuntimeError('thread ' + self.key)))\n"
        "    t.start(); t.join()\n"
        "    warnings.warn('warned ' + self.key)\n"
        "    try:\n"
        "        raise Evil()\n"
        "    except Evil as e:\n"
        "        self.write(dict(k='conn', event='error', detail=self.scrub(repr(e))))\n"
        "cls.run = run\n"
        "mod.signal.signal = lambda *a: None\n"
        "S._connect_no_redirect = lambda: None\n"
        "sys.exit(mod.main(['--out', sys.argv[1]]))\n")
    for which, names in (("binance", ("BINANCE_API_KEY", "BINANCE_API_SECRET")),
                         ("upbit", ("UPBIT_ACCESS_KEY", "UPBIT_SECRET_KEY"))):
        env = dict(os.environ, **{names[0]: "FAKEstderrKEY" + "q" * 27, names[1]: "FAKEstderrSECRET" + "w" * 24})
        r = subprocess.run([sys.executable, "-c", script, str(tmp_path / f"{which}.jsonl"), which], env=env,
                           capture_output=True, text=True, timeout=60, cwd=pathlib.Path(S.__file__).parents[2])
        assert r.returncode == 1, r.stderr[-2000:]                          # ended by an exception: not 0
        assert "FAKEstderr" not in r.stderr, r.stderr[-3000:]
        for logged in ("thread [REDACTED]", "warned [REDACTED]", "shadow stopped: ValueError"):
            assert logged in r.stderr, (which, r.stderr[-3000:])


def test_a_string_with_a_raw_control_character_is_still_looked_into(tmp_path, monkeypatch):
    """Not strict JSON (a raw line break inside a string), so the frame becomes an `other` row - and a key spelled
    with \\u escapes in that string must not stay in the row. Masking does not make the frame strict JSON either
    (parse_push reads a frame the same, whether it held a secret or not)."""
    monkeypatch.setattr(S, "RECONNECT_S", 2)
    escaped = "".join("\\u%04x" % ord(c) for c in FAKE_KEY)
    raw = '{"type": "PONG", "echo": "line\nbreak ' + escaped + '"}'
    sh, _, _ = _shadow(tmp_path, [raw])
    sh.key = FAKE_KEY
    with pytest.raises(ValueError):
        json.loads(sh.redact_json(raw))
    sh.run_once()
    other = next(r["raw"] for r in _drain(sh) if r["k"] == "other")
    assert "[REDACTED]" in other and not _has_piece_of(_unescape(other), FAKE_KEY), other


@pytest.mark.parametrize("text", [
    "signature={sig}", "Signature={sig}", "SIGNATURE={sig}", "next=%2Fsapi%2Fwss%3Ftimestamp%3D1%26signature%3D{sig}",
    '{{"signature": "{sig}"}}', '{{"signature":"{sig}"}}', "('signature', '{sig}')", "signature: {sig}",
    "https://api.binance.com/sapi/wss?random=1&signature={sig}&x=1"])
def test_a_signature_value_is_masked_however_it_is_written(tmp_path, text):
    sh, _, _ = _shadow(tmp_path)
    sig = "ab12" * 16                                        # HMAC-SHA256 in hex: 64 characters
    out = sh.redact(text.format(sig=sig))
    assert "[REDACTED]" in out and not _has_piece_of(out, sig, 4), out


@pytest.mark.parametrize("prose", ["API update: signature=HMAC-SHA256 now required", "signature: a new feature",
                                   "Signature, faced by the bad cafe", "e-signature=feature"])
def test_public_text_about_signatures_is_left_as_it_is(tmp_path, prose):
    sh, _, _ = _shadow(tmp_path)
    assert sh.redact(prose) == prose


def test_the_signature_of_this_connection_is_masked_wherever_it_shows_up(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RECONNECT_S", 2)
    sh, seen, _ = _shadow(tmp_path)
    sh.run_once()
    sig = seen["urls"][-1].rsplit("signature=", 1)[1]
    assert sh._signature == sig and len(sig) == 64
    for text in (f"the server said {sig}.", json.dumps({"sig": sig}), repr(RuntimeError(("signature", sig)))):
        assert sig[:8] not in sh.redact(text), text
    escaped = json.dumps({"t": "x"}).replace("x", "".join("\\u%04x" % ord(c) for c in sig))
    assert sig[:8] not in _unescape(sh.redact_json(escaped))


def test_text_with_nothing_to_mask_reaches_the_row_and_the_file_exactly_as_it_came(tmp_path, monkeypatch):
    """0ec0d61 re-encoded every string it decoded: an escape in a JSON-looking title came out decoded ("\\u0041" as
    "A") and body_len counted the decoded body; public text after "signature=" was masked."""
    monkeypatch.setattr(S, "RECONNECT_S", 2)
    title = '{"a":"\\u0041"} API update: signature=HMAC-SHA256 now required'
    body = '["\\/", "\\u00e9"]'
    raw = json.dumps(dict(type="DATA", data=json.dumps(dict(title=title, body=body, publishDate=1))))
    sh, _, _ = _shadow(tmp_path, [raw])
    sh.run_once()
    ann = next(r for r in _drain(sh) if r["k"] == "ann")
    assert ann["title"] == title and ann["title_len"] == len(title) and ann["body_len"] == len(body)
    assert json.loads(sh._json_line(dict(k="x", title='{"a":"\\u0041"}', body=body))) == \
        dict(k="x", title='{"a":"\\u0041"}', body=body)                    # the writer boundary leaves it too
    assert "title_len and body_len count the masked text" in S.__doc__


def test_a_deeply_nested_string_stops_neither_the_receive_loop_nor_the_writer(tmp_path, monkeypatch):
    """json.loads raises RecursionError, not ValueError, on deep nesting: 0ec0d61 let it out of run_once (the
    connection was dropped) and out of the writer's last redaction (the row was lost)."""
    monkeypatch.setattr(S, "RECONNECT_S", 2)
    deep = "[" * 50_000 + "]" * 50_000 + " " + FAKE_KEY       # something to mask in it: it is decoded
    raw = json.dumps(dict(type="DATA", data=json.dumps(dict(title=deep, publishDate=1))))
    sh, _, _ = _shadow(tmp_path, [raw])
    sh.key = FAKE_KEY
    sh.run_once()                                             # returns: the planned reconnect, no exception
    rows = _drain(sh)
    ann = next(r for r in rows if r["k"] == "ann")
    assert ann["title_len"] == len(deep) - len(FAKE_KEY) + len("[REDACTED]")
    assert rows[-1]["event"] == "planned_reconnect"
    sh.q.put(dict(k="future", title=deep))
    sh.stop.set()
    sh.writer_loop()
    assert sh.write_failed == 0 and FAKE_KEY.encode() not in pathlib.Path(sh.out_path).read_bytes()


def test_the_connection_logs_through_a_logger_that_never_prints_frames(tmp_path, monkeypatch, caplog):
    """websockets prints a frame at DEBUG cut to its start and end, BEFORE any handler sees it: a key cut in half is
    not recognised by the redaction. The connection gets a logger of its own that stays at INFO - also when the root
    logger is at DEBUG - and still passes errors on to the (redacting) root handlers."""
    from websockets.client import ClientProtocol
    from websockets.uri import parse_uri
    monkeypatch.setattr(S, "RECONNECT_S", 2)
    sh, seen, _ = _shadow(tmp_path)
    with caplog.at_level(logging.DEBUG):
        sh.run_once()
        logger = seen["kw"]["logger"]
        assert not logger.isEnabledFor(logging.DEBUG) and logger.isEnabledFor(logging.INFO)
        assert logger.propagate and not logger.disabled
        assert ClientProtocol(parse_uri(S.WS_BASE), logger=logger).debug is False     # frames are not logged


@pytest.mark.parametrize("key", ["KEY\"dq'sq" + "k" * 30, "KEY\x01\x7f" + "k" * 30, "KEY\u200b\u2028" + "k" * 30,
                                 "KEY\\bs" + "k" * 30, "KEY'only" + "k" * 30])
def test_a_key_is_masked_in_the_repr_of_an_exception_too(tmp_path, key):
    """Error rows and log lines show repr(): Python escapes differently than JSON
    (\\' \\x01 \\u200b, the other quote)."""
    sh, _, _ = _shadow(tmp_path)
    sh.key = key
    for shown in (repr(RuntimeError(key)), repr(RuntimeError("a'b\"" + key)), "%r" % key, ascii(key),
                  str(OSError(2, "x", key)), repr(OSError(2, "x", key + '"\'')), json.dumps([key])):
        assert "k" * 30 not in sh.redact(shown), shown


# ── HOW TO USE lag_ms, done by a reader the way the module text says it ──

def _doc_reader(rows, ann, tol=20.0, follow_ms=11_000.0):
    """'accept' when the module text says lag_ms stands, otherwise why not."""
    if ann["lag_ms"] is None:
        return "no lag"
    valid = [r for r in rows if r["k"] == "clock" and r.get("offset_ms") is not None]
    recv = ann["recv_ms"]
    before = [c for c in valid if c["sample_ms"] + c["rtt_ms"] / 2 < recv]
    used = [c for c in valid if c["sample_ms"] == ann["offset_sample_ms"]]
    after = [c for c in valid if c["sample_ms"] - c["rtt_ms"] / 2 > recv]
    if not (before and used and after):
        return "missing"
    b, u, a = max(before, key=lambda c: c["sample_ms"]), used[0], min(after, key=lambda c: c["sample_ms"])
    if a["sample_ms"] - recv > follow_ms:
        return "late"
    span = [c for c in valid if min(b["sample_ms"], u["sample_ms"]) <= c["sample_ms"] <= a["sample_ms"]]
    lines = [rows.index(c) for c in span]
    if any(r.get("event") == "step" for r in rows[min(lines):max(lines) + 1]):
        return "step"
    if len({c.get("throttled_n") for c in span}) > 1:
        return "throttled"
    offsets = [ann["offset_ms"]] + [c["offset_ms"] for c in span]
    return "accept" if max(offsets) - min(offsets) <= tol else "reject"


TRUE_LAG_MS = 100.0


def _first_measurement(sh, clock, wall):
    """One measurement on the clock as it is: offset 0."""
    def get(url):
        clock.now += .004
        return dict(serverTime=wall.true_ms() - 2)
    sh._http_get = get
    sh.measure_clock()


def _push_inside_a_measurement(tmp_path, monkeypatch, shift_before_s, shift_at_request_s):
    """Both local clocks lose 300 ms (no step: a slew, a VM pause) before the measurement or during its second
    request, and the push comes in during that second request. The first request is the fastest one."""
    monkeypatch.setattr(S, "RECONNECT_S", .001)
    sh, _, clock, wall = _stepping(tmp_path)
    _first_measurement(sh, clock, wall)
    clock.now += 600
    wall.true_shift += shift_before_s
    n = [0]

    def get(url):
        n[0] += 1
        if n[0] == 2:
            wall.true_shift += shift_at_request_s
            raw = json.dumps(dict(type="DATA", data=dict(title="notice", publishDate=wall.true_ms() + 900)))
            sh._connect = lambda *a, **kw: FakeWS([raw], clock)
            sh.run_once()
        rtt = .004 if n[0] % 5 == 1 else .008
        clock.now += rtt
        return dict(serverTime=wall.true_ms() - rtt * 500)
    sh._http_get = get
    _run_clock_thread(sh, clock, until=clock.now + 30)
    rows = _drain(sh)
    return rows, next(r for r in rows if r["k"] == "ann")


@pytest.mark.parametrize(("before_s", "at_request_s"), [(.3, 0), (0, .3)])
def test_a_wrong_lag_ms_of_a_push_inside_a_measurement_is_never_accepted(tmp_path, monkeypatch, before_s, at_request_s):
    """Review 2, finding 9/15 (and test 0): the row is corrected with the offset installed at its stamp (the one
    before the measurement), lag_ms is 300 ms wrong. The rule of 0ec0d61 compared the measurement it took for
    'before' (the running one, whose fastest sample came first) with the one after: equal, so it accepted the row.
    The row now names its measurement (offset_sample_ms), and its own offset has to agree as well."""
    rows, ann = _push_inside_a_measurement(tmp_path, monkeypatch, before_s, at_request_s)
    assert ann["lag_ms"] == pytest.approx(TRUE_LAG_MS - 300, abs=.2)        # wrong by 300 ms
    clocks = [r for r in rows if r["k"] == "clock" and r.get("offset_ms") is not None]
    assert ann["offset_sample_ms"] == clocks[0]["sample_ms"]                # the measurement before the push
    assert ann["offset_age_s"] == pytest.approx((ann["recv_ms"] - clocks[0]["sample_ms"]) / 1000, abs=.06)
    after = min(c["sample_ms"] - c["rtt_ms"] / 2 for c in clocks if c["sample_ms"] - c["rtt_ms"] / 2 > ann["recv_ms"])
    assert 10_000 < after - ann["recv_ms"] < 11_000                          # "a little more than 10 s"
    assert _doc_reader(rows, ann) == "reject"
    assert _doc_reader(rows, ann, follow_ms=10_000) == "late"               # a reader that waits for less: left out


def test_a_measurement_whose_request_straddles_the_stamp_is_neither_before_nor_after(tmp_path, monkeypatch):
    """Review 2, finding 13: the server stamps its time, the VM is paused 300 ms, the push is stamped right after the
    pause, then the answer is handled - the midpoint of that request lies after the stamp, its offset is from
    before the pause. Taken as 'after' by its midpoint, it agreed with 'before' and the wrong lag was accepted."""
    monkeypatch.setattr(S, "RECONNECT_S", .0001)
    sh, _, clock, wall = _stepping(tmp_path)
    _first_measurement(sh, clock, wall)
    clock.now += 600

    class QuickWS(FakeWS):
        def recv(self, timeout=None):
            self.clock.now += .0005
            if not self.script:
                raise TimeoutError
            return self.script.pop(0)
    n = [0]

    def get(url):
        n[0] += 1
        if n[0] == 1:
            clock.now += .001
            server = wall.true_ms()                                         # the server stamps before the pause
            wall.true_shift += .3                                           # the pause
            raw = json.dumps(dict(type="DATA", data=dict(title="notice",
                                                         publishDate=wall.true_ms() + .5 - TRUE_LAG_MS)))
            sh._connect = lambda *a, **kw: QuickWS([raw], clock)
            sh.run_once()
            clock.now += .004 - .0015
            return dict(serverTime=server)
        clock.now += .008
        return dict(serverTime=wall.true_ms() - 4)
    sh._http_get = get
    _run_clock_thread(sh, clock, until=clock.now + 30)
    rows = _drain(sh)
    ann = next(r for r in rows if r["k"] == "ann")
    assert ann["lag_ms"] == pytest.approx(TRUE_LAG_MS - 300, abs=.6)
    straddling = [r for r in rows if r["k"] == "clock" and r.get("offset_ms") is not None][1]
    assert straddling["sample_ms"] - straddling["rtt_ms"] / 2 < ann["recv_ms"] < straddling["sample_ms"]
    assert _doc_reader(rows, ann) in ("reject", "late")
    assert _doc_reader(rows, ann, follow_ms=60_000) == "reject"


def test_an_offset_installed_between_the_stamp_and_the_correction_is_caught(tmp_path, monkeypatch):
    """Review 2, test C: the receive thread stalls between its stamp and _correction; meanwhile both clocks lose
    300 ms and a measurement completes. The row carries that NEW offset, offset_age_s 0.0 (clamped)."""
    monkeypatch.setattr(S, "RECONNECT_S", .001)
    sh, _, clock, wall = _stepping(tmp_path)
    _first_measurement(sh, clock, wall)
    clock.now += 600

    def get(url):
        clock.now += .004
        return dict(serverTime=wall.true_ms() - 2)
    real = sh._correction

    def stalled(*a):
        wall.true_shift += .3
        sh._http_get = get
        sh.measure_clock()
        return real(*a)
    sh._correction = stalled
    raw = json.dumps(dict(type="DATA", data=dict(title="notice", publishDate=wall.true_ms() + 1000 - TRUE_LAG_MS)))
    sh._connect = lambda *a, **kw: FakeWS([raw], clock)
    sh.run_once()
    sh._correction = real
    clock.now += 10
    sh.measure_clock()
    rows = _drain(sh)
    ann = next(r for r in rows if r["k"] == "ann")
    assert ann["offset_age_s"] == 0.0 and ann["offset_sample_ms"] > ann["recv_ms"]
    assert _doc_reader(rows, ann) == "reject"


def test_an_ordinary_push_is_accepted_with_the_right_lag(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RECONNECT_S", .001)
    sh, _, clock, wall = _stepping(tmp_path)
    _first_measurement(sh, clock, wall)
    clock.now += 600
    raw = json.dumps(dict(type="DATA", data=dict(title="notice", publishDate=wall.true_ms() + 1000 - TRUE_LAG_MS)))
    sh._connect = lambda *a, **kw: FakeWS([raw], clock)
    sh.run_once()
    clock.now += .001
    sh._http_get = lambda url: (setattr(clock, "now", clock.now + .004), dict(serverTime=wall.true_ms() - 2))[1]
    _run_clock_thread(sh, clock, until=clock.now + 5)
    rows = _drain(sh)
    ann = next(r for r in rows if r["k"] == "ann")
    assert ann["lag_ms"] == pytest.approx(TRUE_LAG_MS, abs=.2) and ann["offset_sample_ms"] is not None
    assert _doc_reader(rows, ann) == "accept"


def test_a_row_without_an_offset_names_no_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "RECONNECT_S", 2)
    sh, _, _ = _shadow(tmp_path, [DOC_PUSH])
    sh.run_once()
    ann = next(r for r in _drain(sh) if r["k"] == "ann")
    assert ann["offset_ms"] is None and ann["offset_sample_ms"] is None


def test_the_module_text_says_how_to_read_rows_and_waits_without_the_claims_review_2_disproved():
    doc = S.__doc__
    for phrase in ("offset_sample_ms", "sample_ms + rtt_ms/2 < recv_ms", "sample_ms - rtt_ms/2 > recv_ms",
                   "Comparing BEFORE with\nAFTER alone is NOT enough", "a little more than 10 s",
                   "not how long the frame waited", "no lower bound", "title_len and body_len count the masked text",
                   "open_timeout bounds neither the lookup", "a backlog of thousands of rows can take",
                   "thousands of rows behind"):
        assert phrase in doc + S.Shadow._shutdown.__doc__, phrase
    for claim in ("10 s at most after a burst", "roughly below 1 ms", "as early as the previous row's receive stamp"):
        assert claim not in doc, claim


def test_the_stopped_row_waits_for_room_in_a_full_queue(tmp_path, monkeypatch):
    """Review 2, finding 19: the stopped row went in with put_nowait, and a full queue cost it - the file then ended
    like after a crash. It now waits for the writer (within the same STOP_WRITER_S as before)."""
    sh, _, _ = _shadow(tmp_path)
    sh.q = queue.Queue(maxsize=3)
    for i in range(3):
        sh.write(dict(k="x", i=i))

    def behind():                                            # the writer takes its next record only in 0.2 s
        time.sleep(.2)
        sh._writer_worker()
    writer = threading.Thread(target=behind, daemon=True)
    writer.start()
    clock_thread = threading.Thread(target=lambda: None)
    clock_thread.start()
    sh._shutdown(writer, clock_thread)
    rows = [json.loads(x) for x in _file_lines(sh)]
    assert [r.get("i", r.get("event")) for r in rows] == [0, 1, 2, "stopped"] and sh.dropped == 0
    assert not writer.is_alive()


def test_a_stuck_writer_costs_the_stopped_row_but_not_the_stop_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STOP_WRITER_S", .3)
    sh, _, _ = _shadow(tmp_path)
    sh.q = queue.Queue(maxsize=1)
    sh.write(dict(k="x"))

    class Stuck:                                             # a writer thread that never takes anything
        def join(self, timeout=None):
            time.sleep(timeout)

    class Done:
        def join(self, timeout=None):
            pass
    started = time.monotonic()
    sh._shutdown(Stuck(), Done())
    took = time.monotonic() - started
    assert sh.dropped == 1 and .3 <= took < .55              # waiting for room and for the writer: STOP_WRITER_S, once


@pytest.mark.parametrize("server_time", ["NaN", "Infinity", "-Infinity", "1e999", float("inf"), float("nan")])
def test_a_server_time_that_is_not_a_finite_number_is_an_error_not_an_offset(tmp_path, server_time):
    """Review 2, finding 20: float("NaN") is nan - it was stored as a valid offset (its clock line looked like a
    normal one with offset_ms null, and the next try came after 15 min instead of 1)."""
    sh, _, clock = _shadow(tmp_path)
    sh._http_get = lambda url: {"serverTime": server_time}
    waits = []
    sh._clock_sleep = lambda wait, floor: (waits.append(wait), sh.stop.set())
    sh.clock_loop()
    (row,) = _drain(sh)
    assert "error" in row and "not a finite number" in row["error"] and "offset_ms" not in row
    assert sh.offset_ms is None and waits == [S.CLOCK_RETRY_S]


def test_the_log_filter_never_raises_into_the_code_that_logs(tmp_path, capsys):
    """Review 2, finding 22: a filter that raises raises into whoever logged (logging catches errors of a handler's
    emit, not of its filters). A malformed call of some library is logged with its arguments, redacted; a record
    that cannot be redacted at all is replaced, never let through as it is."""
    import io
    sh, _, _ = _shadow(tmp_path)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(S.RedactingFilter(sh.redact))
    lg = logging.Logger("review2.filter")
    lg.addHandler(handler)
    lg.warning("two args %s %s", "KEY")                      # one argument short
    lg.warning("fine %s", "SECRET")

    def broken(text):
        raise RuntimeError("cannot")
    handler.filters[0].redact = broken
    lg.warning("never shown %s", "KEY")
    lines = stream.getvalue().splitlines()
    assert lines[0] == "two args %s %s ('[REDACTED]',)" and lines[1] == "fine [REDACTED]"
    assert lines[2] == "[log record dropped: it could not be redacted]" and "KEY" not in stream.getvalue()


@pytest.mark.parametrize("levels", [1, 2])
def test_a_key_spelled_with_escapes_in_a_log_message_is_masked(tmp_path, levels):
    """Cross-review of the fix: the log filter masks a message as text, and nothing decodes it - a key spelled
    \\u0046\\u0041... in a message or in an exception's text (once, or nested) went to the journal as it was."""
    import io
    sh, _, _ = _shadow(tmp_path)
    sh.key = FAKE_KEY
    escaped = "".join("\\u%04x" % ord(c) for c in FAKE_KEY)
    if levels == 2:
        escaped = escaped.replace("\\", "\\\\")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(S.RedactingFilter(sh.redact))
    lg = logging.Logger("crossreview.escapes")
    lg.addHandler(handler)
    lg.warning("server said %s", escaped)
    try:
        raise RuntimeError("echo " + escaped)
    except RuntimeError:
        lg.error("failed", exc_info=True)
    out = stream.getvalue()
    assert out.count("[REDACTED]") >= 2 and not _has_piece_of(_unescape(out), FAKE_KEY), out
    assert sh.redact("C:\\new\\table " + "\\u0041") == "C:\\new\\table \\u0041"   # nothing hidden: as it came


@pytest.mark.parametrize("case", ["shows at one level only", "nested deeper than the passes", "surrogate pair"])
def test_redact_undoes_escapes_one_level_at_a_time(tmp_path, case):
    """Cross-review of the fix, second round: the escapes were undone all at once and only the end was masked. A key
    that showed at one level - after a backslash - and lost its first letter to the next level (a backslash and
    "nKEY..." become a line break and "KEY...") stayed; so did a key nested deeper than the passes go, and one
    with a character outside the BMP that was written as a surrogate pair."""
    bs = chr(92)
    sh, _, _ = _shadow(tmp_path)
    if case == "shows at one level only":
        sh.key = "nKEYabc123" + "z" * 20
        text = bs + "u005c" + bs + "u006e" + sh.key[1:]          # one level down: a backslash, then the key
    elif case == "nested deeper than the passes":
        sh.key = "KEY-abcdef012345" + "z" * 20
        text = bs + "u004b" + sh.key[1:]
        for _ in range(S.UNESCAPE_PASSES + 1):
            text = text.replace(bs, bs + "u005c")
    else:
        sh.key = "abc" + chr(0x1F600) + "def" + "z" * 20
        text = bs + "u0061bc" + bs + "ud83d" + bs + "ude00def" + "z" * 20
    out = level = sh.redact(text)
    assert "[REDACTED]" in out, out
    for _ in range(S.UNESCAPE_PASSES + 4):                       # however far a reader undoes it: no key
        assert sh.key not in level and sh.key[1:] not in level, (out, level)
        level = S._unescaped_once(level)
