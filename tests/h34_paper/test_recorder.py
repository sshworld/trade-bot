import csv
import glob
import json
import os
import re

import pytest

from h34_paper import core, feed as F
from h34_paper.core import MS15, LOCK_TS_MS
from h34_paper.engine import Limits
from h34_paper.recorder import Recorder, Ledger, load_config, kst_iso, BAR_GRACE_MS
from h34_paper.rules import resolve
from helpers import FakeFeed, flat_bars

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONF = os.path.join(ROOT, "h34_paper", "deploy", "h34_paper.json")


def test_static_no_order_endpoint_no_key_no_secret():
    """The recorder package may only talk to the public klines/time endpoints and must hold no credential."""
    src = ""
    for p in glob.glob(os.path.join(ROOT, "h34_paper", "*.py")):
        if os.path.basename(p) in ("history.py", "screen.py"):          # offline research helpers, not imported by the recorder
            continue
        src += open(p).read() + "\n"
    assert F.ALLOWED_PATHS == {"/fapi/v1/klines", "/fapi/v1/time"}
    for bad in ("/fapi/v1/order", "/fapi/v1/leverage", "/fapi/v2/account", "/fapi/v1/listenKey", "newOrder", "X-MBX-APIKEY",
                "api_secret", "API_SECRET", "hmac", "signature=", "testnet"):
        assert bad not in src, bad
    assert not re.search(r"os\.environ(\.get|\[)[^\n]*(KEY|SECRET|TOKEN)", src)
    imports = set(re.findall(r"^(?:from|import) ([\w\.]+)", src, re.M))
    assert not {i for i in imports if i.split(".")[0] in ("requests", "websocket", "websockets", "aiohttp", "ccxt", "binance")}


def test_http_refuses_non_allowlisted_paths():
    h = F.PublicHttp(opener=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")))
    for path in ("/fapi/v1/order", "/fapi/v2/balance", "/fapi/v1/klines/../order", "/sapi/v1/capital/config/getall"):
        with pytest.raises(PermissionError):
            h.get(path)


def test_http_sends_no_key_header_and_parses_klines():
    seen = {}

    class R:
        def __init__(self, body):
            self.body = body
        def read(self):
            return self.body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def opener(req, timeout):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["url"] = req.full_url
        return R(json.dumps([[1, "1.5", "2", "1", "1.8", "10", 2, "0", 0, "0", "0", "0"]]).encode())
    rows = F.parse_klines(F.PublicHttp(opener=opener).get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "15m", "limit": 1}))
    assert rows == [(1, 1.5, 2.0, 1.0, 1.8)]
    assert set(seen["headers"]) <= {"user-agent"} and seen["url"].startswith("https://fapi.binance.com/fapi/v1/klines?")


def test_config_loads_and_only_h34b_is_on():
    cfg, rules, off, limits = load_config(CONF)
    assert [r.name for r in rules] == ["H34-B", "H34-B-S"]
    assert "H32" in off and "H38-LONG" in off
    assert limits == Limits(per_coin=1, max_concurrent=3, max_open_risk=0.06, one_stop_loss=0.02, daily_loss_cap=0.05)
    assert cfg["lock_ts_ms"] == LOCK_TS_MS and kst_iso(LOCK_TS_MS) == "2026-10-28 15:03:00"


def test_ledger_is_idempotent_and_writes_csv(tmp_path):
    L = Ledger(str(tmp_path))
    rec = {"strategy": "H34-B", "symbol": "BTCUSDT", "side": "long", "signal_close_ms": LOCK_TS_MS + 1, "entry_bar_open_ms": LOCK_TS_MS + 1,
           "exit_ms": LOCK_TS_MS + 5, "exit_reason": "target", "entry_px": 1.0, "exit_px": 1.1, "r_c015": 0.5, "r_c030": 0.4,
           "net_ret_c015": 0.003, "net_ret_c030": 0.002, "size_mult": 3.0, "stop_pct": 0.005, "recorded_after_close_s": 200.0}
    assert L.emit("trade", "k1", rec, 1) and not L.emit("trade", "k1", rec, 2)
    assert L.n_trades == 1
    L2 = Ledger(str(tmp_path))                                           # restart: still knows k1
    assert not L2.emit("trade", "k1", rec, 3) and L2.n_trades == 1
    rows = list(csv.DictReader(open(tmp_path / "trades.csv")))
    assert len(rows) == 1 and rows[0]["rule"] == "H34-B" and rows[0]["r_c030"] == "0.40000"
    assert json.loads(open(tmp_path / "trades.jsonl").read())["late"] is True      # 200 s after the close > 90 s


def _mk_recorder(tmp, feed, cfg_over=None, limits=None):
    cfg, rules, off, lim = load_config(CONF)
    cfg.update(cfg_over or {})
    return Recorder(cfg, rules, off, limits or lim, str(tmp), feed)


def _flat_src(t0, n15=1700, n1h=520, nd=320):
    z = lambda t, px: (t, px, px, px, px)
    return {(s, "15m"): [z(t0 + i * MS15, 100.0) for i in range(n15)] for s in core.COINS} | \
           {(s, "1h"): [z(t0 + i * core.MS1H, 100.0) for i in range(n1h)] for s in core.COINS} | \
           {("BTCUSDT", "1d"): [z(t0 - 300 * core.MS1D + i * core.MS1D, 100.0) for i in range(nd + 400)]}


def test_starts_at_first_bar_closed_after_lock_and_waits_for_forming_data(tmp_path):
    t_lock_bar = (LOCK_TS_MS // MS15) * MS15
    src = _flat_src(t_lock_bar - 1600 * MS15)
    feed = FakeFeed(src, t_lock_bar + 10 * MS15 + 5000)
    rec = _mk_recorder(tmp_path, feed)
    assert rec.next_T == t_lock_bar                                       # the 15:00-15:15 bar closes at 15:15 > 15:03 lock
    assert kst_iso(rec.next_T + MS15) == "2026-10-28 15:15:00"
    n = rec.run_once()
    assert n == 10 or n == 11                                             # processed only closed bars with their next open present
    assert rec.next_T <= t_lock_bar + 11 * MS15
    st = json.load(open(tmp_path / "state.json"))
    assert st["next_T"] == rec.next_T
    assert json.load(open(tmp_path / "status.json"))["lag_s"] >= 0


def test_no_processing_before_bar_closes_and_grace_then_gap_logged(tmp_path):
    t_lock_bar = (LOCK_TS_MS // MS15) * MS15
    src = _flat_src(t_lock_bar - 1600 * MS15)
    # clock just after the close of the first bar, but the next bar's open is not yet published (feed lag)
    drop = {(s, "15m", t_lock_bar + MS15) for s in core.COINS}
    feed = FakeFeed(src, t_lock_bar + MS15 + 3000, drop=drop)
    rec = _mk_recorder(tmp_path, feed)
    assert rec.run_once() == 0                                            # waits (within grace)
    feed.t = t_lock_bar + MS15 + BAR_GRACE_MS + 1000
    assert rec.run_once() == 1                                            # grace over: processed, gap recorded not guessed
    assert rec.next_T == t_lock_bar + MS15


def test_catch_up_window_exceeded_is_logged_not_silent(tmp_path):
    t_lock_bar = (LOCK_TS_MS // MS15) * MS15
    src = _flat_src(t_lock_bar + 20 * 86_400_000 - 1700 * MS15, n15=1700)
    feed = FakeFeed(src, t_lock_bar + 20 * 86_400_000)                    # recorder only starts 20 days after the lock
    rec = _mk_recorder(tmp_path, feed)
    rec.run_once()
    ev = [json.loads(l) for l in open(tmp_path / "events.jsonl")]
    assert any(e["event"] == "catch_up_window_exceeded" for e in ev)


def test_service_unit_is_low_priority_isolated_and_credential_free():
    u = open(os.path.join(ROOT, "h34_paper", "deploy", "h34-paper-recorder.service")).read()
    code = "\n".join(l for l in u.splitlines() if not l.lstrip().startswith("#"))
    for must in ("Nice=19", "CPUSchedulingPolicy=idle", "IOSchedulingClass=idle", "CPUWeight=1", "MemoryMax=", "OOMScoreAdjust=900",
                 "NoNewPrivileges=true", "ProtectSystem=strict", "User=h34paper", "StateDirectory=h34_paper"):
        assert must in code, must
    assert "EnvironmentFile" not in code and "live_v6" not in code and "h15" not in code
    assert "Requires=" not in code and "BindsTo=" not in code
    assert "/var/lib/live_v6" not in code and "WorkingDirectory=/opt/h34-paper" in code


def test_recorder_import_is_stdlib_only():
    import subprocess, sys
    out = subprocess.run([sys.executable, "-c", "import sys, h34_paper.recorder, h34_paper.feed, h34_paper.engine; "
                          "bad = [m for m in ('pandas','numpy','pyarrow','httpx','requests') if m in sys.modules]; print(bad)"],
                         capture_output=True, text=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT})
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
