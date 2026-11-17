"""Announcement WebSocket shadow logger: signing, push parsing, keepalive, reconnect, safety — offline (no network)."""
from __future__ import annotations

import ast
import errno
import hashlib
import hmac
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
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
    assert not sh.clock_wake.is_set()

    wall.shift += jump_s                                         # date -s / makestep: only the wall clock moves
    ann, rows = _one_push(sh, script, wall)
    assert ann["lag_ms"] is None and ann["offset_ms"] is None    # NOT 100 +/- 5000 ms with a "fresh" offset
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
    clock.now += 1800.0                                          # half an hour passes on both clocks
    wall.shift += 0.049
    off, age = sh._offset()
    assert off == pytest.approx(SERVER_AHEAD_MS, abs=0.01) and age == pytest.approx(1800.0)
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
    seen, real = [], sh._offset

    def spy(*a):
        seen.append(a)
        return real(*a)

    sh._offset = spy
    ann, _ = _one_push(sh, script, wall)
    ((stamp_wall, stamp_mono),) = seen
    assert stamp_wall * 1000 == pytest.approx(ann["recv_ms"], abs=0.1)
    assert stamp_mono == pytest.approx(clock.now - 2.0)          # the mono clock at the receive, two timeouts ago


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
    assert mods <= {"__future__", "argparse", "hashlib", "hmac", "json", "logging", "os", "queue", "re", "secrets",
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
                "InaccessiblePaths", "ProtectProc", "ProcSubset", "MemoryMax", "CPUQuota"},
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
    # the bot's group must not open the trading keys or the bot state; no "-": a missing path fails the start
    assert svc["InaccessiblePaths"].split() == ["/etc/tradebot", "/var/lib/live_v6-live", *hidden]
    assert svc["EnvironmentFile"] == env_file                    # exactly one, and not optional ("-" prefix)
    assert svc["StateDirectory"] == stem
    assert svc["ExecStart"] == (f"/opt/tradebot/.venv/bin/python -m live_v6.tools.{module} "
                                f"--out /var/lib/{stem}/{module}.jsonl")
    assert int(svc["TimeoutStopSec"]) >= 10
    for needle in ("systemd-analyze verify", "systemd-analyze security", f"/var/lib/private/{stem}",
                   "DynamicUser", "EnvironmentFile", "Migrate", "Verify", "Remove"):
        assert needle in header, needle
    return header, svc


def test_binance_logger_unit_runs_isolated_from_the_bot():
    _, svc = check_logger_unit("tradebot-ann-shadow.service", module="ann_ws_shadow",
                               env_file="/etc/tradebot/live.env")
    assert svc["TimeoutStopSec"] == "10"


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
