"""Offline acceptance tests for measurement-only engine instrumentation."""
import copy
import builtins
import importlib
import json
import logging
import queue
import threading
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from live_v6 import runner
from live_v6.engine import V6Engine
from live_v6.events import Mark, Trade
from live_v6.notify import NullNotifier
from live_v6.store import MemoryStore

from .conftest import Backend
from .fakes import FakeExchange
from .test_bundle_v5 import _intent


class Clock:
    def __init__(self):
        self.mono_s = 0.0
        self.wall_s = 120.0

    def mono(self):
        return self.mono_s

    def wall(self):
        return self.wall_s

    def advance(self, sec):
        self.mono_s += sec
        self.wall_s += sec


@pytest.fixture
def sm(monkeypatch):
    module = importlib.import_module("live_v6.stallmeter")
    created, original_init = [], module.StallMeter.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(module.StallMeter, "__init__", init)
    yield module
    for meter in created:
        assert meter.close(timeout=2), "writer did not stop during test cleanup"


def started_meter(sm, *args, **kwargs):
    meter = sm.StallMeter(*args, **kwargs)
    meter.start()
    return meter


@pytest.fixture
def rig(sm, tmp_path):
    clock = Clock()
    path = tmp_path / "stall.jsonl"
    meter = started_meter(sm, path, mono=clock.mono, wall=clock.wall)
    return clock, meter, path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def flush(rig):
    clock, meter, path = rig
    clock.wall_s = (int(clock.wall_s) // 60 + 1) * 60
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    return rows(path)[-1]


def engine():
    return V6Engine(FakeExchange(), store=MemoryStore(), notifier=NullNotifier(), sleep=lambda _: None)


def test_queue_fifo_timing_length_timeout_and_empty(sm):
    clock = Clock()
    record = Mock()
    meter = SimpleNamespace(mono=clock.mono, record_wait=record)
    q = sm.TimedQueue(meter)
    first, second = object(), object()
    assert q.empty() and q.qsize() == 0
    q.put(first)
    clock.advance(0.25)
    q.put_nowait(second)
    clock.advance(0.75)
    assert q.qsize() == 2
    assert q.get(timeout=0.01) is first
    record.assert_called_with(1.0, 2)
    assert q.get_nowait() is second
    record.assert_called_with(0.75, 1)
    assert q.empty()
    with pytest.raises(queue.Empty):
        q.get_nowait()
    with pytest.raises(queue.Empty):
        q.get(timeout=0.001)
    with pytest.raises(ValueError):
        q.get(timeout=-1)
    assert record.call_count == 2
    # Queue locking, timeout and accounting stay in the standard library.
    for name in ("put", "put_nowait", "get", "get_nowait", "qsize", "empty", "task_done", "join"):
        assert getattr(sm.TimedQueue, name) is getattr(queue.Queue, name)


def test_queue_record_failure_and_bounded_task_accounting(sm):
    meter = SimpleNamespace(mono=lambda: 0.0, record_wait=Mock(side_effect=RuntimeError("record")))
    q = sm.TimedQueue(meter, maxsize=1)
    item = object()
    q.put(item)
    with pytest.raises(queue.Full):
        q.put_nowait(object())
    assert q.get_nowait() is item
    q.task_done()
    q.join()
    assert q.empty()


def test_queue_clock_failure_preserves_item(sm):
    meter = SimpleNamespace(mono=Mock(side_effect=RuntimeError("clock")), record_wait=Mock())
    q = sm.TimedQueue(meter)
    item = object()
    q.put(item)
    assert q.get_nowait() is item and q.empty()


def test_wrap_preserves_return_exception_identity_and_metadata(rig):
    clock, meter, _ = rig
    result, failure = object(), ValueError("original")

    def fn(value, *, fail=False):
        """Original documentation."""
        clock.advance(0.02)
        if fail:
            raise failure
        assert value is result
        return value

    wrapped = meter.wrap("work", fn, top=True)
    assert wrapped.__name__ == fn.__name__ and wrapped.__doc__ == fn.__doc__
    assert wrapped.__wrapped__ is fn
    assert wrapped(result) is result
    with pytest.raises(ValueError) as caught:
        wrapped(result, fail=True)
    assert caught.value is failure
    row = flush(rig)
    assert row["seg"]["work"] == {"n": 2, "sum_ms": 40.0, "max_ms": 20.0}


def test_wrap_measurement_failures_never_replace_result_or_exception(rig, monkeypatch):
    _, meter, _ = rig
    result, original = object(), ValueError("original")
    monkeypatch.setattr(meter, "_record_segment", Mock(side_effect=RuntimeError("record")))
    assert meter.wrap("return", lambda: result)() is result

    def fail():
        raise original

    with pytest.raises(ValueError) as caught:
        meter.wrap("raise", fail)()
    assert caught.value is original
    monkeypatch.setattr(meter, "mono", Mock(side_effect=RuntimeError("clock")))
    assert meter.wrap("clock", lambda: result)() is result
    with pytest.raises(ValueError) as caught:
        meter.wrap("clock", fail)()
    assert caught.value is original


def test_nested_busy_inner_and_top_three_even_without_top_flag(sm, rig):
    clock, meter, _ = rig
    sm.install(engine(), meter, [])
    short = meter.wrap("short", lambda: clock.advance(0.1))
    longest = meter.wrap("longest", lambda: clock.advance(0.3))

    def middle_fn():
        short()
        longest()

    middle = meter.wrap("middle", middle_fn)

    def outer_fn():
        clock.advance(0.1)
        middle()

    meter.wrap("outer", outer_fn, top=True)()
    meter.wrap("standalone", lambda: clock.advance(0.4))()
    meter.wrap("small", lambda: clock.advance(0.2), top=True)()
    meter.wrap("tiny", lambda: clock.advance(0.05))()
    row = flush(rig)
    assert row["busy_ms"] == 1150.0
    assert row["seg"]["middle"] == {"n": 1, "sum_ms": 400.0, "max_ms": 400.0}
    assert [x["label"] for x in row["top"]] == ["outer", "standalone", "small"]
    assert row["top"][0] == {"label": "outer", "start_ms": 120000, "dur_ms": 500.0, "inner": "middle"}
    assert row["top"][1]["inner"] is None


def test_background_calls_only_seg_and_install_thread_owns_depth(sm, rig):
    clock, meter, _ = rig
    # Constructed here, installed on another thread: ownership follows install.
    eng = engine()
    result = []

    def owner():
        sm.install(eng, meter, [])
        result.append(meter.wrap("owner", lambda: clock.advance(0.02))())

    thread = threading.Thread(target=owner)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive() and result == [None]
    meter.wrap("worker", lambda: clock.advance(0.03), top=True)()
    row = flush(rig)
    assert row["busy_ms"] == 20.0
    assert row["seg"]["worker@bg"] == {"n": 1, "sum_ms": 30.0, "max_ms": 30.0}
    assert "worker" not in row["seg"]
    assert [x["label"] for x in row["top"]] == ["owner"]


def test_flush_schema_nearest_rank_rounding_and_histogram_boundaries(rig):
    _, meter, path = rig
    samples = [0, 0.999, 1, 9.999, 10, 49.999, 50, 99.999, 100, 249.999,
               250, 499.999, 500, 999.999, 1000, 1999.999, 2000, 4999.999, 5000, 6000.123]
    for idx, ms in enumerate(samples):
        meter.record_wait(ms / 1000, idx + 1)
    meter.maybe_flush()
    assert not path.exists()
    row = flush(rig)
    assert set(row) == {"v", "t", "n_ev", "wait_ms", "wait_hist", "busy_ms", "qmax", "top", "seg", "flush_lag_s"}
    assert row["v"] == 1 and row["t"] == 120000 and row["n_ev"] == 20
    assert row["wait_ms"] == {"p50": 250.0, "p90": 5000.0, "p99": 6000.12, "max": 6000.12}
    assert row["wait_hist"] == dict.fromkeys(
        ("<1", "1-10", "10-50", "50-100", "100-250", "250-500", "500-1000", "1000-2000", "2000-5000", ">=5000"), 2)
    assert row["busy_ms"] == 0 and row["qmax"] == 20
    assert row["top"][0]["label"] == "hook:meter_flush" and row["top"][0]["dur_ms"] == 0
    assert row["seg"] == {"hook:meter_flush": {"n": 1, "sum_ms": 0.0, "max_ms": 0.0}}
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert len(rows(path)) == 1


def test_exact_ten_ms_is_left_closed(rig):
    _, meter, _ = rig
    meter.record_wait(0.010, 1)
    row = flush(rig)
    assert row["wait_hist"]["10-50"] == 1 and row["wait_hist"]["1-10"] == 0
    assert row["wait_ms"] == dict.fromkeys(("p50", "p90", "p99", "max"), 10.0)


def test_empty_minutes_including_gaps_and_backward_wall_clock(rig):
    clock, meter, path = rig
    clock.wall_s = 301
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert [r["t"] for r in rows(path)] == [120000, 180000, 240000]
    for row in rows(path):
        assert row["n_ev"] == row["qmax"] == row["busy_ms"] == 0
        assert set(row["wait_ms"].values()) == {None}
        assert sum(row["wait_hist"].values()) == 0
    clock.wall_s = 180
    meter.maybe_flush()
    clock.wall_s = 301
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert len(rows(path)) == 3


def test_cross_minute_segment_belongs_to_end_minute(rig):
    clock, meter, path = rig
    clock.wall_s = 179
    meter.wrap("cross", lambda: clock.advance(2))()
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert rows(path)[0]["seg"] == {} and rows(path)[0]["busy_ms"] == 1000.0
    row = flush(rig)
    assert row["t"] == 180000 and row["busy_ms"] == 1000.0
    assert row["top"][0]["start_ms"] == 179000


def test_rotation_keeps_one_backup(rig):
    clock, meter, path = rig
    meter.max_bytes = 1
    flush(rig)
    first = path.read_text()
    clock.wall_s += 60
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert path.with_name(path.name + ".1").read_text() == first
    second = path.read_text()
    clock.wall_s += 60
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert path.with_name(path.name + ".1").read_text() == second
    assert len(rows(path)) == 1
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name, path.name + ".1"]


def test_write_failure_warning_throttle_no_trace_and_recovery(sm, tmp_path, caplog):
    clock = Clock()
    parent = tmp_path / "missing"
    meter = started_meter(sm, parent / "stall.jsonl", mono=clock.mono, wall=clock.wall)
    with caplog.at_level(logging.WARNING, logger="live_v6.stallmeter"):
        for _ in range(3):
            clock.advance(60)
            meter.record_wait(0.01, 1)
            meter.maybe_flush()
            assert meter.drain(timeout=2)
        warnings = [r for r in caplog.records if r.name == "live_v6.stallmeter"]
        assert len(warnings) == 1
        assert "FileNotFoundError" in warnings[0].getMessage()
        assert warnings[0].levelno == logging.WARNING and warnings[0].exc_info is None
        clock.advance(3600)
        meter.maybe_flush()
        assert meter.drain(timeout=2)
        assert len([r for r in caplog.records if r.name == "live_v6.stallmeter"]) == 2
        parent.mkdir()
        clock.advance(60)
        meter.record_wait(0.02, 2)
        meter.maybe_flush()
        assert meter.drain(timeout=2)
        clock.advance(60)
        meter.maybe_flush()
        assert meter.drain(timeout=2)
    assert rows(parent / "stall.jsonl")[-1]["n_ev"] == 1
    assert "CRITICAL" not in caplog.text and "Traceback" not in caplog.text


def test_warning_sanitizes_exception_message(sm, tmp_path, caplog, monkeypatch):
    clock = Clock()
    meter = started_meter(sm, tmp_path / "stall.jsonl", mono=clock.mono, wall=clock.wall)
    monkeypatch.setattr("builtins.open", Mock(side_effect=OSError("CRITICAL\nTraceback bad disk")))
    clock.advance(60)
    with caplog.at_level(logging.WARNING, logger="live_v6.stallmeter"):
        meter.maybe_flush()
        assert meter.drain(timeout=2)
    assert len(caplog.records) == 1
    assert "CRITICAL" not in caplog.text and "Traceback" not in caplog.text
    assert caplog.records[0].exc_info is None and "OSError" in caplog.text
    assert "\n" not in caplog.records[0].getMessage()


def test_hourly_info_wait_distribution_and_culprit(rig, caplog):
    clock, meter, _ = rig
    with caplog.at_level(logging.INFO, logger="live_v6.stallmeter"):
        meter.wrap("reconcile", lambda: clock.advance(2))()
        meter.record_wait(2.0, 1)
        clock.advance(60)
        meter.maybe_flush()
        assert not [r for r in caplog.records if r.levelno == logging.INFO]
        clock.advance(3540)
        meter.maybe_flush()
        meter.maybe_flush()
        assert meter.drain(timeout=2)
    info = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info) == 1
    msg = info[0].getMessage()
    assert msg.startswith("stall 1h: ev=1 wait p50=2000.0ms p99=2000.0ms max=2000.0ms")
    assert "at 09:02:02 KST during reconcile" in msg
    assert "Traceback" not in msg and "CRITICAL" not in msg


def test_install_names_exist_instances_only_hooks_and_missing(sm, rig, caplog):
    _, meter, _ = rig
    eng = engine()
    names = [x if isinstance(x, str) else x[0] for x in sm.WRAP_ENGINE]
    assert set(names) == {"tick", "on_event", "startup", "reconcile", "on_bar_close", "reports",
                          "poll_postonly", "flush_queued", "breach_check", "sleep"}
    for name in names:
        assert callable(getattr(eng, name))
        if name != "sleep":
            assert callable(getattr(V6Engine, name))
    assert sm.WRAP_ATTR
    class_tick = V6Engine.tick
    other = engine()

    def poll():
        return "ok"

    hooks = [poll]
    wrapped = sm.install(eng, meter, hooks)
    assert hooks == [poll] and wrapped is not hooks and wrapped[0]() == "ok"
    assert wrapped[0].__wrapped__ is poll
    assert V6Engine.tick is class_tick and other.tick.__func__ is class_tick
    for name in names:
        assert name in vars(eng) and hasattr(getattr(eng, name), "__wrapped__")
    eng.sleep(0)
    eng.tg.send("test")
    eng.store.save(eng.st)
    row = flush(rig)
    assert {"hook:poll", "sleep", "tg_send", "store_save"} <= row["seg"].keys()
    with caplog.at_level(logging.WARNING, logger="live_v6.stallmeter"):
        assert sm.install(SimpleNamespace(), meter, []) == []
    assert "skip" in caplog.text.lower()
    assert all(r.exc_info is None and r.levelno == logging.WARNING for r in caplog.records
               if r.name == "live_v6.stallmeter")


@pytest.mark.parametrize("value", [None, "1", "", "false"])
def test_runner_enabled_default_path_and_hooks(sm, tmp_path, value):
    eng = engine()
    hook = Mock(__name__="poll")
    hooks = [hook]
    env = {} if value is None else {"LIVE_V6_STALL_METER": value}
    q, meter, wrapped = runner.make_loop_io(eng, "testnet", str(tmp_path / "state.json"), hooks, env)
    assert isinstance(q, sm.TimedQueue) and isinstance(meter, sm.StallMeter)
    assert str(meter.path) == str(tmp_path / "testnet_stall.jsonl")
    assert len(wrapped) == 2 and wrapped[0].__wrapped__ is hook
    assert wrapped[-1] == meter.maybe_flush and hooks == [hook]
    assert "tick" in vars(eng) and not (tmp_path / "testnet_stall.jsonl").exists()


def test_runner_disabled_keeps_original_queue_hooks_and_engine():
    eng = engine()
    hooks = [lambda: None]
    tick = eng.tick
    q, meter, out = runner.make_loop_io(eng, "mainnet", "state.json", hooks, {"LIVE_V6_STALL_METER": "0"})
    assert type(q) is queue.Queue and meter is None and out is hooks and eng.tick == tick


def test_runner_relative_path(sm):
    _, meter, _ = runner.make_loop_io(engine(), "mainnet", "state.json", [], {})
    assert str(meter.path) in ("./mainnet_stall.jsonl", "mainnet_stall.jsonl")


@pytest.mark.parametrize("enabled", [False, True])
def test_run_wires_queue_hooks_before_serve_and_default_state(sm, monkeypatch, enabled):
    eng = engine()
    eng.strategy.stream_intervals, eng.strategy.wants_trades = ("1m",), False
    streams = []
    command = SimpleNamespace(poll=lambda: None, stop=lambda: None)

    def stream(*args, q):
        obj = SimpleNamespace(name_=str(len(streams)), q=q, start=lambda: None, stop=lambda: None)
        streams.append(obj)
        return obj

    captured = []
    monkeypatch.setattr(runner, "setup_logging", lambda: None)
    monkeypatch.setattr(runner, "build", lambda _: (SimpleNamespace(base_url="unused"), eng))
    monkeypatch.setattr(runner, "ws_base_for", lambda _: "unused")
    monkeypatch.setattr(runner, "MarketStream", stream)
    monkeypatch.setattr(runner, "UserStream", stream)
    monkeypatch.setattr(runner.signal, "signal", lambda *a: None)
    monkeypatch.setattr("live_v6.tgcmd.maybe_start", lambda *a: command)
    monkeypatch.setattr(runner, "serve", lambda e, q, stop, hooks: captured.append((e, q, hooks)))
    monkeypatch.delenv("LIVE_V6_STATE", raising=False)
    monkeypatch.delenv("LIVE_V6_PAPER", raising=False)
    monkeypatch.setenv("LIVE_V6_STALL_METER", "1" if enabled else "0")
    runner.run("testnet")
    e, q, hooks = captured[0]
    assert e is eng and all(s.q is q for s in streams)
    assert isinstance(q, sm.TimedQueue) if enabled else type(q) is queue.Queue
    if enabled:
        meter = hooks[-1].__self__
        assert str(meter.path) == "/var/lib/live_v6/testnet_stall.jsonl"
        assert hooks[0].__wrapped__ is command.poll
    else:
        assert hooks == [command.poll]


def test_paper_branch_bypasses_meter(monkeypatch):
    called = []
    monkeypatch.setenv("LIVE_V6_PAPER", "1")
    monkeypatch.setenv("LIVE_V6_STRATEGY", "bundle_v5")
    monkeypatch.setattr("live_v6.bundle_paper.run_paper", lambda: called.append(True))
    monkeypatch.setattr(runner, "make_loop_io", Mock(side_effect=AssertionError("live instrumentation")))
    runner.run()
    assert called == [True]


def test_exchange_calls_state_and_store_unchanged(sm, tmp_path, monkeypatch):
    # Freeze FakeExchange's fill timestamps too, so state and call arguments compare exactly.
    monkeypatch.setattr("time.time", lambda: 1_800_000_000.0)
    outputs = []
    for enabled in (False, True):
        folder = tmp_path / str(enabled)
        folder.mkdir()
        backend = Backend("offline", FakeExchange(), tmp=folder)
        eng = backend.engine(clock=lambda: 1_800_000_000.0, take_profit=False)
        if enabled:
            meter = started_meter(sm, folder / "stall.jsonl")
            hooks = sm.install(eng, meter, [])
            q = sm.TimedQueue(meter)
        else:
            hooks, q = [], queue.Queue()
        eng.startup()
        assert eng.started and eng.entries_allowed()
        eng.execute([_intent(eng)])
        assert backend.amt("DOGEUSDT") == 100 and backend.stops("DOGEUSDT")
        eng.execute([{"type": "stop", "sym": "DOGEUSDT", "stop_px": 0.145}])
        assert backend.stops("DOGEUSDT")[0]["stop_price"] == Decimal("0.145")
        eng.execute([{"type": "exit", "sym": "DOGEUSDT", "reason": "bundle_time"}])
        runner.loop_once(eng, q, clock=lambda: 1_800_000_000.0, block=False, hooks=hooks)
        assert backend.amt("DOGEUSDT") == 0 and "DOGEUSDT" not in eng.st["pos"]
        assert backend.inner.open_orders("DOGEUSDT") == []
        outputs.append(copy.deepcopy((backend.fx.calls, eng.st, eng.store.load(), backend.inner.orders)))
    assert outputs[0] == outputs[1]


def test_meter_build_failure_falls_back_to_plain_queue(sm, monkeypatch, caplog):
    eng = engine()
    tick = eng.tick
    hooks = [lambda: None]
    monkeypatch.setattr(sm, "StallMeter", Mock(side_effect=OSError("boom CRITICAL\nTraceback")))
    with caplog.at_level(logging.WARNING, logger="live_v6.runner"):
        q, meter, out = runner.make_loop_io(eng, "mainnet", "state.json", hooks, {})
    assert type(q) is queue.Queue and meter is None and out is hooks and eng.tick == tick
    recs = [r for r in caplog.records if r.name == "live_v6.runner"]
    assert len(recs) == 1 and recs[0].levelno == logging.WARNING and recs[0].exc_info is None
    assert "CRITICAL" not in recs[0].getMessage() and "Traceback" not in recs[0].getMessage()
    assert "\n" not in recs[0].getMessage()


def test_r2_import_failure_fallback_log_is_sanitized(monkeypatch, caplog):
    original_import = builtins.__import__

    def import_module(name, *args, **kwargs):
        if name == "stallmeter":
            raise ImportError("CRITICAL\nTraceback unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_module)
    with caplog.at_level(logging.WARNING, logger="live_v6.runner"):
        q, meter, _ = runner.make_loop_io(engine(), "testnet", "state.json", [], {})
    assert type(q) is queue.Queue and meter is None
    recs = [r for r in caplog.records if r.name == "live_v6.runner"]
    assert len(recs) == 1 and recs[0].exc_info is None
    assert "CRITICAL" not in recs[0].getMessage() and "Traceback" not in recs[0].getMessage()
    assert "\n" not in recs[0].getMessage()


def test_run_hook_without_name_is_wrapped(sm, monkeypatch):
    eng = engine()
    eng.strategy.stream_intervals, eng.strategy.wants_trades = ("1m",), False

    class Poller:
        def __call__(self):
            return None

    command = SimpleNamespace(poll=Poller(), stop=lambda: None)
    captured = []
    stream = lambda *a, q: SimpleNamespace(name_="s", q=q, start=lambda: None, stop=lambda: None)  # noqa: E731
    monkeypatch.setattr(runner, "setup_logging", lambda: None)
    monkeypatch.setattr(runner, "build", lambda _: (SimpleNamespace(base_url="unused"), eng))
    monkeypatch.setattr(runner, "ws_base_for", lambda _: "unused")
    monkeypatch.setattr(runner, "MarketStream", stream)
    monkeypatch.setattr(runner, "UserStream", stream)
    monkeypatch.setattr(runner.signal, "signal", lambda *a: None)
    monkeypatch.setattr("live_v6.tgcmd.maybe_start", lambda *a: command)
    monkeypatch.setattr(runner, "serve", lambda e, q, stop, hooks: captured.append(hooks))
    monkeypatch.delenv("LIVE_V6_PAPER", raising=False)
    monkeypatch.setenv("LIVE_V6_STALL_METER", "1")
    runner.run("testnet")
    hooks = captured[0]
    assert hooks[0].__wrapped__ is command.poll and hooks[0]() is None


def test_forward_clock_step_writes_at_most_one_day_of_rows(rig, sm):
    clock, meter, path = rig
    clock.wall_s += 3 * 86400            # e.g. NTP step after a long suspend
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    out = rows(path)
    assert len(out) == 1 and out[0]["gap_min"] == sm.MAX_CATCHUP_MIN
    assert out[0]["t"] == (int(clock.wall_s) // 60 - sm.MAX_CATCHUP_MIN) * 60000


def test_r1_writer_is_daemon_and_flush_never_waits_for_disk(sm, tmp_path):
    clock, entered, release = Clock(), threading.Event(), threading.Event()
    calls = []

    def slow_write(row):
        calls.append((threading.get_ident(), row))
        entered.set()
        assert release.wait(2)

    meter = sm.StallMeter(tmp_path / "stall.jsonl", mono=clock.mono, wall=clock.wall, writer=slow_write)
    assert meter._writer_thread is None
    assert meter._write_queue.maxsize == 2000
    meter.start()
    clock.advance(60)
    try:
        meter.maybe_flush()
        assert entered.wait(1)
        assert meter._writer_thread.daemon and calls[0][0] != threading.get_ident()
        assert not meter.drain(timeout=0.01)
    finally:
        release.set()
    assert meter.drain(timeout=2)
    assert calls[0][1]["t"] == 120000


def test_r1_full_writer_queue_drops_without_blocking_and_reports_next_row(sm, tmp_path):
    clock, entered, release = Clock(), threading.Event(), threading.Event()
    written = []

    def slow_write(row):
        entered.set()
        assert release.wait(5)
        written.append(row)

    meter = started_meter(sm, tmp_path / "stall.jsonl", mono=clock.mono, wall=clock.wall,
                          writer=slow_write, log_every_s=float("inf"))
    clock.advance(60)
    try:
        meter.maybe_flush()
        assert entered.wait(1)
        for _ in range(2001):
            meter.record_wait(0.01, 1)
            clock.advance(60)
            meter.maybe_flush()
        assert meter._write_queue.qsize() == 2000 and meter.dropped_rows == 1
    finally:
        release.set()
    assert meter.drain(timeout=5)
    clock.advance(60)
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert written[-1]["dropped_rows"] == 1 and meter.dropped_rows == 0
    assert all("dropped_rows" not in r for r in written[:-1])


def test_r1_long_empty_gaps_compact_but_content_minutes_survive(rig):
    clock, meter, path = rig
    clock.advance(6 * 60)
    meter.record_wait(0.01, 1)
    clock.advance(7 * 60)
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    out = rows(path)
    assert len(out) == 3
    assert out[0] == {"v": 1, "t": 120000, "gap_min": 6, "flush_lag_s": 720.0}
    assert out[1]["t"] == 480000 and out[1]["n_ev"] == 1
    assert out[2] == {"v": 1, "t": 540000, "gap_min": 6, "flush_lag_s": 300.0}


def test_r3_samples_bounded_deterministic_with_exact_counts_max_and_hist(sm, tmp_path, caplog):
    snapshots = []
    for repeat in range(2):
        clock, written = Clock(), []
        meter = started_meter(sm, tmp_path / f"{repeat}.jsonl", mono=clock.mono, wall=clock.wall, writer=written.append)
        for idx in range(200_000):
            meter.record_wait(10_000.0 if idx == 0 else (idx % 1000) / 1000, 2)
        bucket = meter._buckets[2]
        assert len(bucket.waits) <= 20_000 and len(meter._hour_waits) <= 20_000
        snapshots.append((list(bucket.waits), list(meter._hour_waits)))
        clock.advance(3600)
        with caplog.at_level(logging.INFO, logger="live_v6.stallmeter"):
            meter.maybe_flush()
            assert meter.drain(timeout=2)
        row = written[0]
        assert row["n_ev"] == 200_000 and row["wait_ms"]["max"] == 10_000_000.0
        assert row["sampled"] is True and sum(row["wait_hist"].values()) == 200_000
        assert row["wait_hist"][">=5000"] == 1
    assert snapshots[0] == snapshots[1]
    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(info) == 2 and all("ev=200000 " in msg and "max=10000000.0ms" in msg for msg in info)


@pytest.mark.parametrize("fail_at", [4, 12, 13])
def test_r4_partial_install_rolls_back_all_instance_attributes(sm, tmp_path, monkeypatch, fail_at):
    eng = engine()
    # Exercise restoration of existing instance overrides as well as delattr
    # for methods previously inherited from the class.
    eng.tick, eng.tg.send, eng.store.save = eng.tick, eng.tg.send, eng.store.save
    objects = (eng, eng.tg, eng.store)
    before = [dict(vars(obj)) for obj in objects]
    original_wrap, calls = sm.StallMeter.wrap, []

    def flaky_wrap(self, *args, **kwargs):
        if args[0] == "hook:meter_flush":
            return original_wrap(self, *args, **kwargs)
        calls.append(args[0])
        if len(calls) == fail_at:
            raise MemoryError("partial install")
        return original_wrap(self, *args, **kwargs)

    monkeypatch.setattr(sm.StallMeter, "wrap", flaky_wrap)
    hooks = [lambda: None]
    q, meter, out = runner.make_loop_io(eng, "testnet", str(tmp_path / "state.json"), hooks, {})
    assert type(q) is queue.Queue and meter is None and out is hooks
    assert [dict(vars(obj)) for obj in objects] == before


def test_r5_long_stall_survives_recent_event_eviction(rig, sm, caplog):
    clock, meter, _ = rig
    q = sm.TimedQueue(meter)
    for idx in range(200):
        q.put(idx)
    meter.wrap("tick", lambda: clock.advance(10))()
    event = meter.wrap("on_event", lambda: clock.advance(0.01))
    for idx in range(200):
        assert q.get_nowait() == idx
        event()
    assert len(meter._recent) == 128
    clock.advance(3600)
    with caplog.at_level(logging.INFO, logger="live_v6.stallmeter"):
        meter.maybe_flush()
        assert meter.drain(timeout=2)
    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(info) == 1 and info[0].endswith("during tick")
    assert meter._long_recent.maxlen == 1024


def test_r5_flush_itself_is_an_outer_measured_segment(rig, monkeypatch):
    clock, meter, _ = rig
    enqueue = meter._enqueue

    def slow_enqueue(row):
        clock.advance(0.025)
        enqueue(row)

    monkeypatch.setattr(meter, "_enqueue", slow_enqueue)
    flush(rig)
    row = flush(rig)
    assert row["seg"]["hook:meter_flush"]["n"] == 1
    assert row["seg"]["hook:meter_flush"]["sum_ms"] == 25.0
    assert row["busy_ms"] == 25.0
    assert row["top"][0]["label"] == "hook:meter_flush"


def test_r6_busy_split_across_three_minutes_top_stays_in_completion_minute(rig):
    clock, meter, path = rig
    clock.wall_s = 150.0
    meter.wrap("tick", lambda: clock.advance(120))()
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    final = flush(rig)
    out = rows(path)
    assert [r["t"] for r in out] == [120000, 180000, 240000]
    assert [r["busy_ms"] for r in out] == [30000.0, 60000.0, 30000.0]
    assert [r["flush_lag_s"] for r in out] == [90.0, 30.0, 0.0]
    assert out[0]["top"] == out[1]["top"] == []
    assert final["top"][0]["label"] == "tick" and final["top"][0]["dur_ms"] == 120000.0
    assert final["seg"]["tick"]["sum_ms"] == 120000.0


def test_r6_flush_lag_rounded_and_backward_folded_sample_flagged(rig):
    clock, meter, path = rig
    clock.wall_s = 181.26
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert rows(path)[0]["flush_lag_s"] == 1.3
    assert "clock_back" not in rows(path)[0]
    clock.wall_s = 125
    meter.record_wait(0.02, 1)
    clock.wall_s = 240
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    last = rows(path)[-1]
    assert last["t"] == 180000 and last["n_ev"] == 1 and last["clock_back"] is True


def test_r6_each_row_uses_its_own_creation_wall_time(rig, monkeypatch):
    clock, meter, path = rig
    meter.record_wait(0.01, 1)
    clock.advance(60)
    meter.record_wait(0.01, 1)
    clock.advance(60)
    enqueue = meter._enqueue

    def slow_enqueue(row):
        clock.advance(0.2)
        enqueue(row)

    monkeypatch.setattr(meter, "_enqueue", slow_enqueue)
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert [r["flush_lag_s"] for r in rows(path)] == [60.0, 0.2]


@pytest.mark.parametrize("exit_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("where", ["put", "get", "prepare", "record", "log", "flush"])
def test_r7_measurement_exit_exceptions_propagate(sm, rig, monkeypatch, exit_type, where):
    clock, meter, _ = rig
    original = exit_type("stop")
    fail = Mock(side_effect=original)
    fn = Mock(return_value="result")
    if where == "put":
        q = sm.TimedQueue(SimpleNamespace(mono=fail))
        invoke = lambda: q.put("item")
    elif where == "get":
        q = sm.TimedQueue(SimpleNamespace(mono=lambda: 0.0, record_wait=fail))
        q.put("item")
        invoke = q.get_nowait
    elif where == "prepare":
        monkeypatch.setattr(meter, "mono", fail)
        invoke = meter.wrap("work", fn)
    elif where == "record":
        monkeypatch.setattr(meter, "_record_segment", fail)
        invoke = meter.wrap("work", fn)
    elif where == "log":
        monkeypatch.setattr(sm.log, "log", fail)
        invoke = lambda: sm._safe_log(logging.WARNING, "test")
    else:
        monkeypatch.setattr(meter, "_enqueue", fail)
        clock.advance(60)
        invoke = meter.maybe_flush
    with pytest.raises(exit_type) as caught:
        invoke()
    assert caught.value is original
    if where == "prepare":
        fn.assert_not_called()
    if where == "record":
        fn.assert_called_once_with()


@pytest.mark.parametrize("exit_type", [KeyboardInterrupt, SystemExit])
def test_r7_original_function_exit_identity_still_preserved(rig, exit_type):
    _, meter, _ = rig
    original = exit_type("original")
    with pytest.raises(exit_type) as caught:
        meter.wrap("work", Mock(side_effect=original))()
    assert caught.value is original


def test_r8_operating_loop_events_minute_flush_calls_and_state_unchanged(sm, tmp_path, monkeypatch):
    outputs = []
    writer_threads, written = [], []
    engine_thread = threading.get_ident()
    for enabled in (False, True):
        clock = Clock()
        clock.wall_s = 1_800_000_000.0
        monkeypatch.setattr("time.time", clock.wall)
        folder = tmp_path / str(enabled)
        folder.mkdir()
        backend = Backend("offline", FakeExchange(), tmp=folder)
        eng = backend.engine(clock=clock.wall, take_profit=False)
        completed = queue.Queue()

        def write_row(row):
            writer_threads.append(threading.get_ident())
            completed.put(row)

        if enabled:
            meter = started_meter(sm, folder / "stall.jsonl", mono=clock.mono, wall=clock.wall)
            monkeypatch.setattr(meter, "_write", write_row)
            q = sm.TimedQueue(meter)
            hooks = sm.install(eng, meter, []) + [meter.maybe_flush]
        else:
            q, hooks = queue.Queue(), []
        eng.startup()
        assert eng.started and eng.entries_allowed()
        eng.execute([_intent(eng)])
        states = []
        for step in range(4):
            for _ in range(3):
                q.put(Mark("DOGEUSDT", Decimal("0.15"), int(clock.wall() * 1000)))
                q.put(Trade("DOGEUSDT", Decimal("0.15"), Decimal(1), int(clock.wall() * 1000)))
            clock.advance(60)
            runner.loop_once(eng, q, clock=clock.wall, block=False, hooks=hooks)
            assert q.empty()
            if enabled:
                written.append(completed.get(timeout=2))
            if step == 1:
                eng.execute([{"type": "stop", "sym": "DOGEUSDT", "stop_px": 0.145}])
            if step == 2:
                eng.execute([{"type": "exit", "sym": "DOGEUSDT", "reason": "bundle_time"}])
            states.append(copy.deepcopy((eng.st, eng.store.load())))
        if enabled:
            clock.advance(60)
            meter.maybe_flush()
            written.append(completed.get(timeout=2))
        assert backend.amt("DOGEUSDT") == 0 and "DOGEUSDT" not in eng.st["pos"]
        outputs.append(copy.deepcopy((backend.fx.calls, eng.st, eng.store.load(), states)))
    assert outputs[0] == outputs[1]
    assert len(written) == 5 and sum(row["n_ev"] for row in written) == 24
    assert sum(row["seg"].get("on_event", {}).get("n", 0) for row in written) == 24
    assert all(thread != engine_thread for thread in writer_threads)


def test_w1_flush_starts_no_thread_and_logs_only_on_writer(sm, tmp_path, monkeypatch, caplog):
    _, meter, _ = runner.make_loop_io(engine(), "testnet", str(tmp_path / "state.json"), [], {})
    clock = Clock()
    meter.mono, meter.wall, meter._next_minute, meter._last_log = clock.mono, clock.wall, 2, 0
    monkeypatch.setattr(meter, "_write", lambda row: None)
    owner, starts, logs, handler_threads = threading.get_ident(), [], [], []
    original_start = threading.Thread.start
    original_log, original_low_log = logging.Logger.log, logging.Logger._log

    def trace_start(self, *args, **kwargs):
        starts.append(threading.get_ident())
        return original_start(self, *args, **kwargs)

    def trace_log(self, *args, **kwargs):
        if self.name == "live_v6.stallmeter":
            logs.append(threading.get_ident())
        return original_log(self, *args, **kwargs)

    def trace_low_log(self, *args, **kwargs):
        if self.name == "live_v6.stallmeter":
            logs.append(threading.get_ident())
        return original_low_log(self, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, "start", trace_start)
    monkeypatch.setattr(logging.Logger, "log", trace_log)
    monkeypatch.setattr(logging.Logger, "_log", trace_low_log)
    clock.advance(3600)

    class SlowHandler(logging.Handler):
        def emit(self, record):
            handler_threads.append(threading.get_ident())
            time.sleep(0.5)

    handler = SlowHandler()
    sm.log.addHandler(handler)
    try:
        with caplog.at_level(logging.INFO, logger="live_v6.stallmeter"):
            started = time.monotonic()
            meter.maybe_flush()
            elapsed = time.monotonic() - started
            assert meter.drain(timeout=2)
    finally:
        sm.log.removeHandler(handler)
    assert elapsed < 0.05, f"engine flush blocked for {elapsed:.3f}s"
    assert not starts
    assert logs and all(thread != owner for thread in logs)
    assert handler_threads and all(thread != owner for thread in handler_threads)


def test_w1_start_once_and_worker_get_waits_without_timeout(sm, tmp_path, monkeypatch):
    meter = sm.StallMeter(tmp_path / "stall.jsonl")
    got, calls = threading.Event(), []
    original_get, original_start = meter._write_queue.get, threading.Thread.start
    starts = []

    def get(*args, **kwargs):
        calls.append((args, kwargs))
        got.set()
        return original_get(*args, **kwargs)

    def start(self, *args, **kwargs):
        starts.append(self)
        return original_start(self, *args, **kwargs)

    monkeypatch.setattr(meter._write_queue, "get", get)
    monkeypatch.setattr(threading.Thread, "start", start)
    meter.start()
    meter.start()
    assert got.wait(1)
    assert len(starts) == 1 and meter._writer_thread.daemon
    assert calls == [((), {})]


def test_w1_start_failure_falls_back_without_install(sm, tmp_path, monkeypatch, caplog):
    eng = engine()
    before = dict(vars(eng))
    monkeypatch.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("start unavailable")))
    with caplog.at_level(logging.WARNING, logger="live_v6.runner"):
        q, meter, hooks = runner.make_loop_io(eng, "testnet", str(tmp_path / "state.json"), [], {})
    assert type(q) is queue.Queue and meter is None and hooks == []
    assert vars(eng) == before
    assert "start unavailable" in caplog.text


def test_w2_setattr_third_failure_fallback_restores_every_instance(sm, tmp_path, monkeypatch, caplog):
    eng = engine()
    objects = (eng, eng.tg, eng.store)
    before = [dict(vars(obj)) for obj in objects]
    original, changes = builtins.setattr, []

    def setattr_fail(obj, name, value):
        changes.append(name)
        if len(changes) == 3:
            raise MemoryError("third setattr")
        return original(obj, name, value)

    monkeypatch.setattr(sm, "setattr", setattr_fail, raising=False)
    with caplog.at_level(logging.WARNING, logger="live_v6.runner"):
        q, meter, _ = runner.make_loop_io(eng, "testnet", str(tmp_path / "state.json"), [], {})
    assert type(q) is queue.Queue and meter is None
    assert [dict(vars(obj)) for obj in objects] == before
    assert "third setattr" in caplog.text


def test_w2_failed_rollback_item_does_not_stop_other_restores(sm, rig, monkeypatch):
    _, meter, _ = rig
    eng = engine()
    failure, restores = MemoryError("original install failure"), []
    original_wrap, original_delete = meter.wrap, builtins.delattr

    def wrap(label, *args, **kwargs):
        if label == "reconcile":
            raise failure
        return original_wrap(label, *args, **kwargs)

    def delete(obj, name):
        restores.append(name)
        if name == "startup":
            raise RuntimeError("cannot remove startup")
        return original_delete(obj, name)

    monkeypatch.setattr(meter, "wrap", wrap)
    monkeypatch.setattr(sm, "delattr", delete, raising=False)
    with pytest.raises(MemoryError) as caught:
        sm.install(eng, meter, [])
    assert caught.value is failure
    assert restores == ["startup", "on_event", "tick"]
    assert "on_event" not in vars(eng) and "tick" not in vars(eng)


def test_w2_run_late_hook_wrap_failure_keeps_original_hook_and_flush(sm, tmp_path, monkeypatch):
    eng = engine()
    eng.strategy.stream_intervals, eng.strategy.wants_trades = ("1m",), False
    polled, captured = [], []
    command = SimpleNamespace(poll=lambda: polled.append(True), stop=lambda: None)
    original_wrap = sm.StallMeter.wrap

    def wrap(self, label, *args, **kwargs):
        if label.startswith("hook:") and label != "hook:meter_flush":
            raise MemoryError("late hook")
        return original_wrap(self, label, *args, **kwargs)

    def serve(eng, q, stop, hooks):
        captured.extend(hooks)
        for hook in hooks:
            hook()

    stream = lambda *a, q: SimpleNamespace(name_="s", start=lambda: None, stop=lambda: None)
    monkeypatch.setattr(sm.StallMeter, "wrap", wrap)
    monkeypatch.setattr(runner, "setup_logging", lambda: None)
    monkeypatch.setattr(runner, "build", lambda _: (SimpleNamespace(base_url="unused"), eng))
    monkeypatch.setattr(runner, "ws_base_for", lambda _: "unused")
    monkeypatch.setattr(runner, "MarketStream", stream)
    monkeypatch.setattr(runner, "UserStream", stream)
    monkeypatch.setattr(runner.signal, "signal", lambda *args: None)
    monkeypatch.setattr("live_v6.tgcmd.maybe_start", lambda *args: command)
    monkeypatch.setattr(runner, "serve", serve)
    monkeypatch.setenv("LIVE_V6_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("LIVE_V6_STALL_METER", "1")
    monkeypatch.delenv("LIVE_V6_PAPER", raising=False)
    runner.run("testnet")
    assert captured[0] is command.poll and polled == [True]
    assert len(captured) == 2 and captured[-1].__name__ == "maybe_flush"


def test_w3_writer_survives_processing_and_warning_failures(sm, tmp_path, monkeypatch):
    attempts, written, warnings = [], [], []

    def write(row):
        attempts.append(row)
        if len(attempts) <= 3:
            raise OSError("disk failed")
        written.append(row)

    def warn(error):
        warnings.append(error)
        raise RuntimeError("warning failed too")

    meter = started_meter(sm, tmp_path / "stall.jsonl", writer=write)
    monkeypatch.setattr(meter, "_warn_write", warn)
    for seq in range(4):
        meter._enqueue({"seq": seq})
    assert meter.drain(timeout=1)
    assert meter._writer_thread.is_alive()
    assert len(warnings) == 3 and written == [{"seq": 3}]


def test_w3_writer_get_failure_is_contained(sm, tmp_path, monkeypatch):
    meter = sm.StallMeter(tmp_path / "stall.jsonl", writer=lambda row: None)
    original_get, attempts = meter._write_queue.get, []

    def get():
        attempts.append(True)
        if len(attempts) <= 2:
            raise RuntimeError("get failed")
        return original_get()

    monkeypatch.setattr(meter._write_queue, "get", get)
    monkeypatch.setattr(meter, "_warn_write", Mock(side_effect=RuntimeError("warning failed")))
    meter.start()
    meter._enqueue({"v": 1})
    assert meter.drain(timeout=1) and meter._writer_thread.is_alive()
    assert len(attempts) >= 3


@pytest.mark.parametrize("dead", [False, True])
def test_w3_enqueue_without_live_writer_drops_and_never_restarts(sm, tmp_path, monkeypatch, dead):
    meter = sm.StallMeter(tmp_path / "stall.jsonl")
    if dead:
        thread = threading.Thread(target=lambda: None)
        thread.start()
        thread.join()
        meter._writer_thread = thread
    monkeypatch.setattr(threading.Thread, "start", Mock(side_effect=AssertionError("restart from enqueue")))
    meter._enqueue({"v": 1})
    meter._enqueue({"v": 1})
    assert meter._write_queue.empty() and meter.dropped_rows == 2


def test_w3_one_row_build_failure_keeps_remaining_prepared_minutes(rig, sm, monkeypatch):
    clock, meter, path = rig
    for _ in range(3):
        meter.record_wait(0.01, 1)
        clock.advance(60)
    original = sm._Bucket.row

    def row(self, minute, wall):
        if minute == 3:
            raise MemoryError("middle row")
        return original(self, minute, wall)

    monkeypatch.setattr(sm._Bucket, "row", row)
    meter.maybe_flush()
    assert meter.drain(timeout=1)
    out = rows(path)
    assert [r["t"] for r in out] == [120000, 240000]
    assert out[-1]["dropped_rows"] == 1


def test_w4_ten_thousand_segment_minutes_bound_buckets_and_report_drops(sm, tmp_path):
    clock, written = Clock(), []
    meter = started_meter(sm, tmp_path / "stall.jsonl", mono=clock.mono, wall=clock.wall, writer=written.append)
    tick = meter.wrap("tick", lambda: None)
    for _ in range(10_000):
        tick()
        clock.advance(60)
    assert len(meter._buckets) <= 1500
    assert min(meter._buckets) == 8502 and max(meter._buckets) == 10001
    assert meter.dropped_buckets == 8500
    assert all(bucket.rng is None for bucket in meter._buckets.values())
    meter.maybe_flush()
    assert meter.drain(timeout=2)
    assert written[0]["dropped_buckets"] == 8500 and meter.dropped_buckets == 0
    assert all("dropped_buckets" not in row for row in written[1:])


def test_w4_bucket_rng_allocated_only_after_reservoir_limit(sm):
    bucket = sm._Bucket()
    assert bucket.rng is None
    for _ in range(20_000):
        bucket.add_wait(1.0)
    assert bucket.rng is None
    bucket.add_wait(1.0)
    assert bucket.rng is not None and len(bucket.waits) == 20_000


@pytest.mark.parametrize("start,elapsed,finish,discontinuous", [
    (150.0, 120.0, 210.0, True),
    (179.999, 0.002, 179.9995, False),
    (150.0, 120.0, 330.0, True),
])
def test_w5_clock_corrections_never_attribute_busy_to_future_minutes(rig, start, elapsed, finish, discontinuous):
    clock, meter, _ = rig
    clock.wall_s = start

    def corrected_clock():
        clock.mono_s += elapsed
        clock.wall_s = finish

    meter.wrap("tick", corrected_clock)()
    completion_minute = int(finish // 60)
    assert not any(bucket.busy_ms > 0 for minute, bucket in meter._buckets.items() if minute > completion_minute)
    completed = meter._buckets[completion_minute]
    assert completed.clock_back is discontinuous
    if discontinuous:
        assert completed.busy_ms == elapsed * 1000
        assert sum(bucket.busy_ms for minute, bucket in meter._buckets.items() if minute != completion_minute) == 0
    else:
        assert completed.busy_ms == pytest.approx(0.5)


def test_w7_thirteen_hundred_events_keep_tick_cause_and_hour_heap_resets(rig, sm, caplog):
    clock, meter, _ = rig
    q = sm.TimedQueue(meter)
    for idx in range(1300):
        q.put(idx)
    meter.wrap("tick", lambda: clock.advance(10))()
    on_event = meter.wrap("on_event", lambda: clock.advance(0.011))
    for idx in range(1300):
        assert q.get_nowait() == idx
        on_event()
    assert len(meter._recent) == 128 and len(meter._long_recent) == 1024
    retained = list(getattr(meter, "_hour_longest", []))
    clock.advance(3600)
    with caplog.at_level(logging.INFO, logger="live_v6.stallmeter"):
        meter._hourly()
        assert meter.drain(timeout=2)
    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(info) == 1 and info[0].endswith("during tick")
    assert len(retained) == 256 and max(item[0] for item in retained) == 10000.0
    assert meter._hour_longest == []


# ── round-4 regressions (narrow engine-safety review) ──
def test_r4_draining_backlog_rescans_attribution_only_on_material_new_maxima(rig, sm, monkeypatch, caplog):
    """A draining FIFO backlog makes every wait a slightly larger maximum. The overlap scan (~1,400 segments)
    must not run per event, and the cause must stay the stall that built the backlog."""
    clock, meter, _ = rig
    scans = []
    real_chain = sm.chain
    monkeypatch.setattr(sm, "chain", lambda *a: (scans.append(1), real_chain(*a))[1])
    q = sm.TimedQueue(meter)
    for idx in range(5000):
        q.put(idx)
    meter.wrap("tick", lambda: clock.advance(10))()
    on_event = meter.wrap("on_event", lambda: clock.advance(0.011))
    for idx in range(5000):
        assert q.get_nowait() == idx
        on_event()
    assert len(scans) <= 20, len(scans)                      # ~9 material maxima from 10 s to 65 s, not 5,000
    clock.advance(3600)
    with caplog.at_level(logging.INFO, logger="live_v6.stallmeter"):
        meter._hourly()
        assert meter.drain(timeout=2)
    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(info) == 1 and info[0].endswith("during tick"), info
    assert "max=" in info[0] and "max=64989.0ms" in info[0], info   # the exact maximum is still reported


def test_r4_failed_stack_pop_never_replaces_the_wrapped_result(rig, sm):
    clock, meter, _ = rig

    class BadPop(list):
        def pop(self, *a):
            raise MemoryError("pop")

    meter._stack = BadPop()
    assert meter.wrap("tick", lambda: 42)() == 42
    err = ValueError("original")

    def boom():
        raise err
    with pytest.raises(ValueError) as caught:
        meter.wrap("on_event", boom)()
    assert caught.value is err


def test_r4_hourly_percentiles_are_computed_on_the_writer_not_the_engine(rig, sm, monkeypatch):
    clock, meter, _ = rig
    callers, real = [], sm._percentiles
    monkeypatch.setattr(sm, "_percentiles", lambda samples: (callers.append(threading.get_ident()), real(samples))[1])
    q = sm.TimedQueue(meter)
    q.put(1)
    clock.advance(0.5)
    q.get_nowait()
    clock.advance(3600)
    engine = threading.get_ident()
    meter._hourly()
    assert engine not in callers, "hourly sort ran on the engine thread"
    assert meter.drain(timeout=2)
    assert callers and all(c != engine for c in callers)
