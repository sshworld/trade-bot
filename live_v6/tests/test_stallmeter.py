"""Offline acceptance tests for measurement-only engine instrumentation."""
import copy
import importlib
import json
import logging
import queue
import threading
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from live_v6 import runner
from live_v6.engine import V6Engine
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
def sm():
    return importlib.import_module("live_v6.stallmeter")


@pytest.fixture
def rig(sm, tmp_path):
    clock = Clock()
    path = tmp_path / "stall.jsonl"
    meter = sm.StallMeter(path, mono=clock.mono, wall=clock.wall)
    return clock, meter, path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def flush(rig):
    clock, meter, path = rig
    clock.wall_s = (int(clock.wall_s) // 60 + 1) * 60
    meter.maybe_flush()
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
    assert set(row) == {"v", "t", "n_ev", "wait_ms", "wait_hist", "busy_ms", "qmax", "top", "seg"}
    assert row["v"] == 1 and row["t"] == 120000 and row["n_ev"] == 20
    assert row["wait_ms"] == {"p50": 250.0, "p90": 5000.0, "p99": 6000.12, "max": 6000.12}
    assert row["wait_hist"] == dict.fromkeys(
        ("<1", "1-10", "10-50", "50-100", "100-250", "250-500", "500-1000", "1000-2000", "2000-5000", ">=5000"), 2)
    assert row["busy_ms"] == 0 and row["qmax"] == 20 and row["top"] == [] and row["seg"] == {}
    meter.maybe_flush()
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
    assert [r["t"] for r in rows(path)] == [120000, 180000, 240000]
    for row in rows(path):
        assert row["n_ev"] == row["qmax"] == row["busy_ms"] == 0
        assert set(row["wait_ms"].values()) == {None}
        assert sum(row["wait_hist"].values()) == 0
    clock.wall_s = 180
    meter.maybe_flush()
    clock.wall_s = 301
    meter.maybe_flush()
    assert len(rows(path)) == 3


def test_cross_minute_segment_belongs_to_end_minute(rig):
    clock, meter, path = rig
    clock.wall_s = 179
    meter.wrap("cross", lambda: clock.advance(2))()
    meter.maybe_flush()
    assert rows(path)[0]["seg"] == {} and rows(path)[0]["busy_ms"] == 0
    row = flush(rig)
    assert row["t"] == 180000 and row["busy_ms"] == 2000.0
    assert row["top"][0]["start_ms"] == 179000


def test_rotation_keeps_one_backup(rig):
    clock, meter, path = rig
    meter.max_bytes = 1
    flush(rig)
    first = path.read_text()
    clock.wall_s += 60
    meter.maybe_flush()
    assert path.with_name(path.name + ".1").read_text() == first
    second = path.read_text()
    clock.wall_s += 60
    meter.maybe_flush()
    assert path.with_name(path.name + ".1").read_text() == second
    assert len(rows(path)) == 1
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name, path.name + ".1"]


def test_write_failure_warning_throttle_no_trace_and_recovery(sm, tmp_path, caplog):
    clock = Clock()
    parent = tmp_path / "missing"
    meter = sm.StallMeter(parent / "stall.jsonl", mono=clock.mono, wall=clock.wall)
    with caplog.at_level(logging.WARNING, logger="live_v6.stallmeter"):
        for _ in range(3):
            clock.advance(60)
            meter.record_wait(0.01, 1)
            meter.maybe_flush()
        warnings = [r for r in caplog.records if r.name == "live_v6.stallmeter"]
        assert len(warnings) == 1
        assert "FileNotFoundError" in warnings[0].getMessage()
        assert warnings[0].levelno == logging.WARNING and warnings[0].exc_info is None
        clock.advance(3600)
        meter.maybe_flush()
        assert len([r for r in caplog.records if r.name == "live_v6.stallmeter"]) == 2
        parent.mkdir()
        clock.advance(60)
        meter.record_wait(0.02, 2)
        meter.maybe_flush()
        clock.advance(60)
        meter.maybe_flush()
    assert rows(parent / "stall.jsonl")[-1]["n_ev"] == 1
    assert "CRITICAL" not in caplog.text and "Traceback" not in caplog.text


def test_warning_sanitizes_exception_message(sm, tmp_path, caplog, monkeypatch):
    clock = Clock()
    meter = sm.StallMeter(tmp_path / "stall.jsonl", mono=clock.mono, wall=clock.wall)
    monkeypatch.setattr("builtins.open", Mock(side_effect=OSError("CRITICAL\nTraceback bad disk")))
    clock.advance(60)
    with caplog.at_level(logging.WARNING, logger="live_v6.stallmeter"):
        meter.maybe_flush()
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
            meter = sm.StallMeter(folder / "stall.jsonl")
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
    monkeypatch.setattr(sm, "StallMeter", Mock(side_effect=OSError("boom CRITICAL")))
    with caplog.at_level(logging.WARNING, logger="live_v6.runner"):
        q, meter, out = runner.make_loop_io(eng, "mainnet", "state.json", hooks, {})
    assert type(q) is queue.Queue and meter is None and out is hooks and eng.tick == tick
    recs = [r for r in caplog.records if r.name == "live_v6.runner"]
    assert len(recs) == 1 and recs[0].levelno == logging.WARNING and recs[0].exc_info is None


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
    out = rows(path)
    assert len(out) == sm.MAX_CATCHUP_MIN
    assert out[-1]["t"] == (int(clock.wall_s) // 60 - 1) * 60000
