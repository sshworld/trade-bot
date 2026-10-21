import asyncio
import gzip
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from h15_logger import logger as L

T0 = 1_792_000_000_000 // L.MIN * L.MIN          # a minute boundary (2026-10)
PKG = Path(L.__file__).parent


def msg(sym, side, z, ap, t):
    return json.dumps({"stream": f"{sym.lower()}@forceOrder",
                       "data": {"e": "forceOrder", "E": t, "o": {"s": sym, "S": side, "z": str(z), "ap": str(ap), "T": t,
                                                                  "q": str(z), "p": str(ap), "X": "FILLED"}}})


def rows_by_sym(rows):
    return {r.split(",")[1]: r.split(",") for r in rows}


# ───────── accumulator ─────────
def test_sell_is_long_liq_notional_z_times_ap_one_row_per_symbol_zeros_included():
    m = L.Minutes()
    m.connected(T0 - 5_000)
    m.add_raw(msg("BTCUSDT", "SELL", 0.5, 60000, T0 + 1_000), T0 + 1_100)     # 30k LL
    m.add_raw(msg("BTCUSDT", "SELL", 0.1, 60000, T0 + 2_000), T0 + 2_100)     # 6k LL
    m.add_raw(msg("BTCUSDT", "BUY", 0.2, 60000, T0 + 3_000), T0 + 3_100)      # 12k SL
    m.add_raw(msg("DOGEUSDT", "BUY", 1000, 0.15, T0 + 59_999), T0 + 60_500)
    assert m.due(T0 + 61_999) == []                              # finalised only 2 s after the minute ends
    rows = m.due(T0 + 62_000)
    assert len(rows) == 6 and [r.split(",")[1] for r in rows] == list(L.SYMBOLS)
    r = rows_by_sym(rows)
    assert r["BTCUSDT"] == [str(T0), "BTCUSDT", "36000.00", "12000.00", "2", "1", "30000.00", "0"]
    assert r["DOGEUSDT"][2:6] == ["0.00", "150.00", "0", "1"]
    assert r["ETHUSDT"][2:] == ["0.00", "0.00", "0", "0", "0.00", "0"]


def test_only_fully_connected_minutes_written_gap_minutes_missing():
    m = L.Minutes()
    m.connected(T0 + 10_000)                     # first full minute = T0+60s
    m.disconnected(T0 + 150_000)                 # minute T0+120s only half covered
    m.connected(T0 + 200_000)                    # next full minute T0+240s
    rows = m.due(T0 + 5 * L.MIN + 2_000)
    assert sorted({int(r.split(",")[0]) for r in rows}) == [T0 + 60_000, T0 + 240_000]


def test_late_message_counted_not_rewritten():
    m = L.Minutes()
    m.connected(T0 - 1)
    m.due(T0 + 62_000)                                            # minute T0 written
    m.add_raw(msg("ETHUSDT", "SELL", 10, 3000, T0 + 30_000), T0 + 62_500)   # belongs to T0 → late
    m.add_raw(msg("ETHUSDT", "SELL", 1, 3000, T0 + 61_000), T0 + 62_600)
    r = rows_by_sym(m.due(T0 + 122_000))["ETHUSDT"]
    assert r[0] == str(T0 + 60_000) and r[2] == "3000.00" and r[7] == "1"
    assert rows_by_sym(m.due(T0 + 182_000))["ETHUSDT"][7] == "0"


def test_garbage_and_unknown_symbols_ignored_memory_bounded():
    m = L.Minutes(caps=L.Caps(max_open_minutes=3))
    m.connected(T0 - 1)
    m.add_raw("not json", T0)
    m.add_raw(json.dumps({"data": {"o": {}}}), T0)
    m.add_raw(msg("PEPEUSDT", "SELL", 1, 1, T0), T0)
    for k in range(10):
        m.add_raw(msg("BTCUSDT", "SELL", 1, 1, T0 + k * L.MIN), T0)
    assert m.bad == 3 and len(m.acc) == 3 and m.late["BTCUSDT"] == 7


# ───────── storage ─────────
def test_daily_csv_header_append_and_gzip_previous_day(tmp_path):
    w = L.DailyCsv(tmp_path, L.LIQ_HEADER)
    day1 = 1_791_935_940_000            # 23:59 UTC
    w.write(day1, ["a"])
    w.write(day1, ["b"])
    w.write(day1 + 60_000, ["c"])       # next UTC day
    w.close()
    gz = list(tmp_path.glob("*.csv.gz"))
    assert len(gz) == 1 and gzip.open(gz[0], "rt").read() == L.LIQ_HEADER + "\na\nb\n"
    assert (tmp_path / f"{L.utc_day(day1 + 60_000)}.csv").read_text() == L.LIQ_HEADER + "\nc\n"
    w2 = L.DailyCsv(tmp_path, L.LIQ_HEADER)         # restart same day: no second header
    w2.write(day1 + 120_000, ["d"])
    w2.close()
    assert (tmp_path / f"{L.utc_day(day1 + 60_000)}.csv").read_text().count("minute_ts_ms") == 1


# ───────── OI polling: weight budget + 429/418 ─────────
class FakeRest:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def __call__(self, url, timeout=10.0):
        self.calls.append(url)
        st, w = self.script.pop(0) if self.script else (200, 5)
        return st, {"X-MBX-USED-WEIGHT-1M": str(w), "Retry-After": "60"}, json.dumps(
            {"symbol": url.rsplit("=", 1)[1], "openInterest": "123.4", "time": T0}).encode()


def test_oi_round_writes_six_rows_weight_well_under_10pct(tmp_path):
    rest = FakeRest([])
    p = L.OiPoller(L.DailyCsv(tmp_path, L.OI_HEADER), L.Caps(), rest)
    assert asyncio.run(p.poll_round(T0)) == 6 and len(rest.calls) == 6
    assert 6 / 5 < 0.10 * L.Caps().ip_weight_limit       # 1.2 weight/min vs 240 budget
    p.w.close()
    assert len((tmp_path / f"{L.utc_day(T0)}.csv").read_text().splitlines()) == 7


def test_oi_skips_round_when_ip_weight_at_10pct_then_probes_again(tmp_path):
    rest = FakeRest([(200, 5), (200, 240)])                     # IP at 240 = 10 % of 2400
    p = L.OiPoller(L.DailyCsv(tmp_path, L.OI_HEADER), L.Caps(), rest)
    assert asyncio.run(p.poll_round(T0)) == 2 and len(rest.calls) == 2   # stopped mid-round
    assert asyncio.run(p.poll_round(T0 + 300_000)) == 0 and len(rest.calls) == 2 and p.skipped == 1
    assert asyncio.run(p.poll_round(T0 + 600_000)) == 6


@pytest.mark.parametrize("code", [429, 418])
def test_oi_429_418_stops(tmp_path, code):
    rest = FakeRest([(200, 5), (code, 5)])
    p = L.OiPoller(L.DailyCsv(tmp_path, L.OI_HEADER), L.Caps(), rest)
    with pytest.raises(L.Stop) as e:
        asyncio.run(p.poll_round(T0))
    assert e.value.code == L.EXIT_STOPPED and str(code) in e.value.reason and len(rest.calls) == 2


def test_oi_5xx_ends_round_without_hammering(tmp_path):
    rest = FakeRest([(503, 5)])
    p = L.OiPoller(L.DailyCsv(tmp_path, L.OI_HEADER), L.Caps(), rest)
    assert asyncio.run(p.poll_round(T0)) == 0 and len(rest.calls) == 1 and p.errors == 1


# ───────── whole process ─────────
class FakeProbe:
    def __init__(self, bot=None, host=None):
        self.b = bot or {"ActiveState": "active", "MainPID": "36258", "NRestarts": "0"}
        self.h = host or {"mem_avail_mb": 500, "psi_cpu": 1.0, "psi_mem": 0.0, "load5": 0.1, "rss_mb": 25,
                          "data_mb": 1, "fs_free_mb": 17_000}
        self.fail = 0

    def bot(self):
        if self.fail:
            self.fail -= 1
            raise subprocess.CalledProcessError(1, "systemctl")
        return dict(self.b)

    def host(self):
        return dict(self.h)


class HandshakeRejected(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.response = SimpleNamespace(status_code=code)


@pytest.mark.parametrize("code", [429, 418])
def test_ws_handshake_429_418_stops_writes_marker_and_stays_stopped(tmp_path, code):
    attempts = []

    def connect(url):
        attempts.append(url)
        raise HandshakeRejected(code)

    lg = L.Logger(tmp_path, probe=FakeProbe(), connect=connect, oi=False, now_ms=lambda: T0)
    assert lg.run() == L.EXIT_STOPPED and len(attempts) == 1
    assert (tmp_path / "STOPPED").exists() and f"HTTP {code}" in (tmp_path / "STOPPED").read_text()
    assert "process_stop" in (tmp_path / "gaps.csv").read_text()
    lg2 = L.Logger(tmp_path, probe=FakeProbe(), connect=connect, oi=False, now_ms=lambda: T0)
    assert lg2.run() == L.EXIT_STOPPED and len(attempts) == 1           # marker → no new connection at all


class Silent:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(0.01)
        raise StopAsyncIteration


def test_rest_429_stops_whole_process(tmp_path):
    clock = {"t": T0}

    async def sleep(d):
        clock["t"] += int(d * 1000)
        await asyncio.sleep(0)

    lg = L.Logger(tmp_path, L.Caps(watchdog_s=10_000), probe=FakeProbe(), connect=lambda u: Silent(),
                  get=FakeRest([(429, 5)]), now_ms=lambda: clock["t"], sleep=sleep)
    assert lg.run() == L.EXIT_STOPPED and "openInterest" in (tmp_path / "STOPPED").read_text()


def test_watchdog_stop_ends_whole_process_with_marker(tmp_path):
    p = FakeProbe()

    async def sleep(d):
        p.b["MainPID"] = "99999"                 # live bot restarted
        await asyncio.sleep(0)

    lg = L.Logger(tmp_path, probe=p, connect=lambda u: Silent(), oi=False, now_ms=lambda: T0, sleep=sleep)
    assert lg.run() == L.EXIT_STOPPED and "live bot changed" in (tmp_path / "STOPPED").read_text()


def test_ws_reconnects_with_backoff_and_logs_sessions(tmp_path):
    sleeps, n = [], {"c": 0}

    class Conn:
        def __init__(self, msgs):
            self.msgs = msgs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.msgs:
                return self.msgs.pop(0)
            raise ConnectionResetError("reset")

    def connect(url):
        n["c"] += 1
        if n["c"] in (2, 3):
            raise OSError("dns")
        return Conn([msg("BTCUSDT", "SELL", 1, 1, T0 + 70_000)])

    async def sleep(d):
        sleeps.append(d)
        if len(sleeps) >= 4:
            raise L.Stop("test end", 0)

    lg = L.Logger(tmp_path, probe=FakeProbe(), connect=connect, oi=False, now_ms=lambda: T0, sleep=sleep)
    with pytest.raises(L.Stop):
        asyncio.run(lg.ws_loop())
    assert 1 <= sleeps[0] < 1.3 and 2 <= sleeps[1] < 2.5 and 4 <= sleeps[2] < 4.9 and 1 <= sleeps[3] < 1.3
    g = (tmp_path / "gaps.csv").read_text()
    assert g.count("\nconnect,") == 2 and g.count("\ndisconnect,") == 2
    assert "ConnectionResetError" in g and lg.minutes.msgs == 2


def test_tick_loop_writes_daily_csv_rows(tmp_path):
    clock = {"t": T0 - 1_000}

    async def sleep(d):
        clock["t"] += int(d * 1000)
        if clock["t"] > T0 + 3 * L.MIN + 5_000:
            raise L.Stop("test end", 0)

    lg = L.Logger(tmp_path, probe=FakeProbe(), oi=False, now_ms=lambda: clock["t"], sleep=sleep)
    lg.minutes.connected(T0 - 1_000)
    lg.minutes.add_raw(msg("SOLUSDT", "SELL", 10, 150, T0 + 61_000), T0 + 61_100)
    with pytest.raises(L.Stop):
        asyncio.run(lg.tick_loop())
    lg.liq.close()
    lines = (tmp_path / "liq" / f"{L.utc_day(T0)}.csv").read_text().splitlines()
    assert lines[0] == L.LIQ_HEADER and len(lines) == 1 + 3 * 6 and lg.rows == 18
    assert f"{T0 + 60_000},SOLUSDT,1500.00,0.00,1,0,1500.00,0" in lines


# ───────── watchdog: the live bot comes first ─────────
def wd(probe, **caps):
    w = L.Watchdog(probe, L.Caps(**caps))
    w.start()
    return w


def test_watchdog_refuses_start_if_bot_not_active():
    with pytest.raises(L.Stop):
        wd(FakeProbe(bot={"ActiveState": "activating", "MainPID": "0", "NRestarts": "0"}))


@pytest.mark.parametrize("change", [{"MainPID": "40000"}, {"NRestarts": "1"}, {"ActiveState": "failed"}])
def test_watchdog_stops_if_live_bot_pid_restarts_or_state_change(change):
    p = FakeProbe()
    w = wd(p)
    w.check()
    p.b.update(change)
    with pytest.raises(L.Stop) as e:
        w.check()
    assert e.value.code == L.EXIT_STOPPED and "live bot changed" in e.value.reason


@pytest.mark.parametrize("key,val", [("mem_avail_mb", 100), ("psi_cpu", 60.0), ("psi_mem", 9.0)])
def test_watchdog_stops_on_host_pressure_after_two_strikes(key, val):
    p = FakeProbe()
    w = wd(p)
    p.h[key] = val
    w.check()                                   # one strike: tolerated
    with pytest.raises(L.Stop) as e:
        w.check()
    assert e.value.code == L.EXIT_STOPPED and "pressure" in e.value.reason


def test_watchdog_pressure_strikes_reset_when_recovered():
    p = FakeProbe()
    w = wd(p)
    p.h["psi_cpu"] = 60.0
    w.check()
    p.h["psi_cpu"] = 1.0
    w.check()
    p.h["psi_cpu"] = 60.0
    w.check()


@pytest.mark.parametrize("key,val,code", [("data_mb", 300, 75), ("fs_free_mb", 1000, 75), ("rss_mb", 70, 1)])
def test_watchdog_own_caps(key, val, code):
    p = FakeProbe()
    w = wd(p)
    p.h[key] = val
    with pytest.raises(L.Stop) as e:
        w.check()
    assert e.value.code == code


def test_watchdog_stops_if_bot_state_unreadable_3x():
    p = FakeProbe()
    w = wd(p)
    p.fail = 3
    w.check()
    w.check()
    with pytest.raises(L.Stop):
        w.check()


def test_rss_cap_exit_is_restartable_no_marker(tmp_path):
    lg = L.Logger(tmp_path, probe=FakeProbe(), oi=False, now_ms=lambda: T0)
    assert lg.stopped(L.Stop("rss", L.EXIT_RESTARTABLE)) == 1 and not (tmp_path / "STOPPED").exists()


# ───────── preflight / unit / static ─────────
def test_preflight_refuses_root_and_any_secret():
    assert "root" in L.preflight({}, uid=0)
    assert "BINANCE_API_KEY" in L.preflight({"BINANCE_API_KEY": "x"}, uid=1000)
    assert "TELEGRAM_BOT_TOKEN" in L.preflight({"TELEGRAM_BOT_TOKEN": "x"}, uid=1000)
    assert L.preflight({"PATH": "/bin"}, uid=1000) is None


def test_ws_url_is_six_forceorder_streams_only():
    assert L.WS_URL.startswith("wss://fstream.binance.com/market/stream?streams=")  # routed path; legacy /stream is silent
    streams = L.WS_URL.split("=", 1)[1].split("/")
    assert streams == [f"{s.lower()}@forceOrder" for s in L.SYMBOLS] and len(streams) == 6


def test_no_key_or_signed_endpoint_in_code():
    src = (PKG / "logger.py").read_text()
    for bad in ("X-MBX-APIKEY", "signature=", "/fapi/v1/order", "listenKey", "testnet"):
        assert bad not in src


def test_unit_file_priority_caps_and_isolation():
    u = (PKG / "deploy" / "h15-logger.service").read_text()
    for need in ("User=h15log", "Nice=19", "CPUWeight=10", "IOWeight=10", "MemoryMax=100M", "MemoryHigh=80M",
                 "MemorySwapMax=0", "OOMScoreAdjust=1000", "CPUSchedulingPolicy=idle", "IOSchedulingClass=idle",
                 "RestartPreventExitStatus=75", "StateDirectory=h15-logger", "ProtectSystem=strict",
                 "NoNewPrivileges=true", "ExecStart=/opt/h15-logger/.venv/bin/python -m h15_logger run"):
        assert need in u, need
    assert "EnvironmentFile" not in u and "/opt/tradebot" not in u and "/etc/tradebot" not in u


def test_pylint_errors_and_unreachable():
    pytest.importorskip("pylint")
    r = subprocess.run([sys.executable, "-m", "pylint", "--disable=all", "--enable=E,W0101,W0102", "--score=n",
                        str(PKG / "logger.py")], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout


# ───────── collection quality (TA rule 2026-10-22): hourly event counts + 60-min silence WARNING ─────────
H0 = (T0 // L.HOUR + 1) * L.HOUR                 # an hour boundary (UTC)


def qrows(path):
    lines = (path / "quality.csv").read_text().splitlines()
    assert lines[0] == L.QUALITY_HEADER
    return [dict(zip(L.QUALITY_HEADER.split(","), l.split(","))) for l in lines[1:]]


def test_quality_hourly_rows_per_coin_counts_valid_minutes_partial_first_hour(tmp_path):
    m = L.Minutes()
    q = L.Quality(tmp_path / "quality.csv", m, L.Caps())
    start = H0 - 30 * L.MIN
    q.start(start)
    m.connected(start)
    m.add_raw(msg("BTCUSDT", "SELL", 1, 60000, H0 - 10 * L.MIN), H0 - 10 * L.MIN + 100)
    m.add_raw(msg("BTCUSDT", "BUY", 1, 60000, H0 - 9 * L.MIN), H0 - 9 * L.MIN + 100)
    m.add_raw(msg("DOGEUSDT", "BUY", 100, 0.2, H0 - 5 * L.MIN), H0 - 5 * L.MIN + 100)
    m.add_raw(msg("ETHUSDT", "SELL", 1, 3000, H0 + 5 * L.MIN), H0 + 5 * L.MIN + 100)     # next hour
    m.add_raw("garbage", H0 - 1)                                                       # not an event
    for k in range(30):
        q.valid_minute(start + k * L.MIN)
    assert q.tick(H0 + 2_999) == []                    # waits until the hour's last minute can be finalised
    (r,) = [dict(zip(L.QUALITY_HEADER.split(","), x.split(","))) for x in q.tick(H0 + 3_000)]
    assert (r["hour_start_ms"], r["hour_end_ms"], r["events"], r["BTCUSDT"], r["DOGEUSDT"], r["ETHUSDT"]) == \
        (str(start), str(H0), "3", "2", "1", "0")
    assert (r["valid_minutes"], r["silence_warning"], r["partial"]) == ("30", "0", "1")
    q.tick(H0 + L.HOUR + 3_000)
    rows = qrows(tmp_path)
    assert len(rows) == 2 and rows[1]["events"] == "1" and rows[1]["ETHUSDT"] == "1" and rows[1]["partial"] == "0"
    assert rows[1]["valid_minutes"] == "0" and m.received == {}                       # nothing kept in RAM


def test_quality_zero_events_60_min_warns_once_per_hour_and_flags_row(tmp_path, caplog):
    m = L.Minutes()
    q = L.Quality(tmp_path / "quality.csv", m, L.Caps())
    q.start(H0)
    caplog.set_level("WARNING", logger="h15_logger")
    q.tick(H0 + L.HOUR - 1)
    assert q.warnings == 0                              # 59:59.999 silent → not yet
    q.tick(H0 + L.HOUR)
    q.tick(H0 + L.HOUR + 30_000)
    assert q.warnings == 1 and sum("0 liquidation events received for 60 min" in r.message for r in caplog.records) == 1
    q.tick(H0 + 2 * L.HOUR + 3_000)                    # still silent 60 min after the first warning → again
    assert q.warnings == 2
    rows = qrows(tmp_path)
    assert [(r["events"], r["silence_warning"]) for r in rows] == [("0", "0"), ("0", "1")]


def test_quality_event_resets_silence_clock(tmp_path):
    m = L.Minutes()
    q = L.Quality(tmp_path / "quality.csv", m, L.Caps())
    q.start(H0)
    m.connected(H0)
    m.add_raw(msg("XRPUSDT", "SELL", 100, 0.5, H0 + 50 * L.MIN), H0 + 50 * L.MIN)
    q.tick(H0 + 109 * L.MIN)
    assert q.warnings == 0
    q.tick(H0 + 110 * L.MIN)
    assert q.warnings == 1


def test_quality_late_message_counts_as_received(tmp_path):
    m = L.Minutes()
    q = L.Quality(tmp_path / "quality.csv", m, L.Caps())
    q.start(H0)
    m.connected(H0)
    m.due(H0 + 10 * L.MIN)                              # minutes finalised
    m.add_raw(msg("BNBUSDT", "BUY", 1, 600, H0 + 1 * L.MIN), H0 + 10 * L.MIN)  # late for its row, still received
    q.tick(H0 + L.HOUR + 3_000)
    assert qrows(tmp_path)[0]["BNBUSDT"] == "1"


def test_quality_close_writes_partial_hour_and_logger_wires_it(tmp_path):
    clock = {"t": H0 - 2 * L.MIN - 1_000}

    async def sleep(d):
        clock["t"] += int(d * 1000)
        if clock["t"] > H0 + 4 * L.MIN:
            raise L.Stop("test end", 0)

    lg = L.Logger(tmp_path, probe=FakeProbe(), oi=False, now_ms=lambda: clock["t"], sleep=sleep)
    lg.quality.start(clock["t"])
    lg.minutes.connected(clock["t"])
    lg.minutes.add_raw(msg("SOLUSDT", "SELL", 10, 150, H0 - 30_000), H0 - 29_000)
    with pytest.raises(L.Stop):
        asyncio.run(lg.tick_loop())
    lg.quality.close(clock["t"])
    rows = qrows(tmp_path)
    assert [(r["events"], r["SOLUSDT"], r["valid_minutes"], r["partial"]) for r in rows] == \
        [("1", "1", "2", "1"), ("0", "0", "3", "1")]     # connected 1 s before H0-2min → H0-2min, H0-1min valid
    assert rows[0]["hour_end_ms"] == str(H0) and rows[1]["hour_start_ms"] == str(H0)
