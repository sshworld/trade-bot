"""H15 liquidation logger — hypotheses_h15.md §6 + TA logger rules (2026-10-21).

* Public data only, NO API keys (refuses to start if a BINANCE_* key is in the environment), never root.
* ONE websocket, liquidations only: combined stream of the 6 live symbols' @forceOrder (spec §6 wording; see README
  "ambiguities" for why not !forceOrder@arr).
* No raw JSON stored: per (symbol, minute) accumulator → one CSV row per symbol per FULLY-CONNECTED minute
  (zeros included; a missing row = gap). Finalised 2 s after the minute ends; later messages only bump `late`.
* Open interest: REST /fapi/v1/openInterest, 6 symbols every 5 min (weight 6 / 5 min ≈ 0.05 % of 2400/min) and a
  round is skipped if the IP's X-MBX-USED-WEIGHT-1M is already ≥ 10 % of the limit.
* 429 / 418 (REST or websocket handshake) → write STOPPED marker, exit 75 (systemd RestartPreventExitStatus=75).
  The marker keeps it stopped across restarts until ops remove it.
* Own caps: RSS, data-dir size, filesystem free space. Watchdog stops the logger (marker + exit 75) if the live bot
  is affected: its MainPID / NRestarts / ActiveState change, MemAvailable low, CPU / memory pressure high.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import os
import random
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("h15_logger")

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
WS_URL = "wss://fstream.binance.com/stream?streams=" + "/".join(f"{s.lower()}@forceOrder" for s in SYMBOLS)
REST_BASE = "https://fapi.binance.com"
EXIT_STOPPED = 75          # "stay stopped": systemd RestartPreventExitStatus=75
EXIT_RESTARTABLE = 1       # e.g. own RSS cap hit → just a gap, systemd restarts with backoff
LIQ_HEADER = "minute_ts_ms,symbol,ll_usd,sl_usd,n_ll,n_sl,max_single_usd,late"
OI_HEADER = "poll_ts_ms,symbol,open_interest,exch_time_ms"
GAP_HEADER = "kind,connect_ts_ms,disconnect_ts_ms,reason"
MIN = 60_000


@dataclass
class Caps:
    late_ms: int = 2_000                 # spec §6: finalise a minute 2 s after its end
    rss_max_mb: float = 60.0             # own soft cap (systemd MemoryHigh=80M, MemoryMax=100M = spec hard cap)
    data_max_mb: float = 256.0           # whole data dir (~40 MB/yr gzipped expected)
    fs_min_free_mb: float = 2_048.0      # never fill the bot's disk
    mem_avail_min_mb: float = 150.0      # host MemAvailable floor (1 GB box)
    psi_cpu_avg60_max: float = 40.0      # /proc/pressure/cpu  "some avg60" %
    psi_mem_avg60_max: float = 5.0       # /proc/pressure/memory "some avg60" %
    load5_max: float = 3.0               # 1 vCPU (used only if PSI is unavailable)
    pressure_strikes: int = 2            # consecutive bad watchdog checks before stopping
    probe_fail_strikes: int = 3          # consecutive failures to read the bot's state → stop
    watchdog_s: float = 30.0
    oi_interval_s: int = 300
    ip_weight_limit: int = 2_400         # Binance futures REQUEST_WEIGHT / min / IP
    ip_weight_frac: float = 0.10         # TA: OI polling only while the IP is < 10 % of its weight
    ws_backoff_max_s: float = 300.0
    max_open_minutes: int = 10           # accumulator bound (memory cap)


class Stop(Exception):
    def __init__(self, reason: str, code: int = EXIT_STOPPED):
        super().__init__(reason)
        self.reason, self.code = reason, code


def utc_day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


# ───────── storage ─────────
class DailyCsv:
    """<dir>/<YYYY-MM-DD>.csv (UTC), header once, append + fsync; previous days gzipped (atomic)."""

    def __init__(self, directory: Path, header: str):
        self.dir, self.header, self.day, self.fh = Path(directory), header, None, None
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, ts_ms: int, lines: list[str]) -> None:
        if not lines:
            return
        day = utc_day(ts_ms)
        if day != self.day:
            self.close()
            self.day = day
            path = self.dir / f"{day}.csv"
            new = not path.exists() or path.stat().st_size == 0
            self.fh = open(path, "a", encoding="ascii")  # pylint: disable=consider-using-with
            if new:
                self.fh.write(self.header + "\n")
            self.gzip_old()
        self.fh.write("".join(l + "\n" for l in lines))
        self.fh.flush()
        os.fsync(self.fh.fileno())

    def gzip_old(self) -> None:
        for p in sorted(self.dir.glob("*.csv")):
            if p.stem >= (self.day or "9999"):
                continue
            tmp = p.with_suffix(".csv.gz.tmp")
            with open(p, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst, 64 * 1024)
            os.replace(tmp, p.with_suffix(".csv.gz"))
            p.unlink()

    def close(self) -> None:
        if self.fh:
            self.fh.close()
            self.fh = None


class GapLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            self.path.write_text(GAP_HEADER + "\n", encoding="ascii")

    def row(self, kind: str, t0: int, t1: int | str = "", reason: str = "") -> None:
        reason = reason.replace(",", ";").replace("\n", " ")[:200]
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"{kind},{t0},{t1},{reason}\n")
            f.flush()
            os.fsync(f.fileno())


# ───────── minute accumulator ─────────
class Minutes:
    def __init__(self, symbols=SYMBOLS, caps: Caps | None = None):
        self.symbols, self.caps = tuple(symbols), caps or Caps()
        self.acc: dict[int, dict[str, list]] = {}
        self.late = {s: 0 for s in self.symbols}
        self.sessions: list[list] = []          # [connect_ms, disconnect_ms | None]
        self.next_minute: int | None = None
        self.msgs = self.bad = 0

    def connected(self, ts: int) -> None:
        self.sessions.append([ts, None])
        if self.next_minute is None:
            self.next_minute = -(-ts // MIN) * MIN          # first full minute after the first connect

    def disconnected(self, ts: int) -> None:
        if self.sessions and self.sessions[-1][1] is None:
            self.sessions[-1][1] = ts

    def add_raw(self, raw: str | bytes, now_ms: int) -> None:
        try:
            d = json.loads(raw)
            o = d.get("data", d)["o"]
            sym, side = o["s"], o["S"]
            usd = float(o["z"]) * float(o["ap"])
            t = int(o["T"])
        except (ValueError, KeyError, TypeError, AttributeError):
            self.bad += 1
            return
        self.add(sym, side, usd, t, now_ms)

    def add(self, sym: str, side: str, usd: float, t: int, now_ms: int) -> None:
        if sym not in self.late or side not in ("SELL", "BUY"):
            self.bad += 1
            return
        self.msgs += 1
        m = t // MIN * MIN
        if self.next_minute is None or m < self.next_minute or m > now_ms + 2 * MIN:
            self.late[sym] += 1                              # already finalised (or absurd clock) → counted only
            return
        if m not in self.acc and len(self.acc) >= self.caps.max_open_minutes:
            self.late[sym] += 1
            return
        a = self.acc.setdefault(m, {}).setdefault(sym, [0.0, 0.0, 0, 0, 0.0])
        if side == "SELL":          # o.S = SELL → a LONG was liquidated (LL)
            a[0] += usd
            a[2] += 1
        else:
            a[1] += usd
            a[3] += 1
        a[4] = max(a[4], usd)

    def covered(self, m: int) -> bool:
        return any(c <= m and (d is None or d >= m + MIN) for c, d in self.sessions)

    def due(self, now_ms: int) -> list[str]:
        rows: list[str] = []
        while self.next_minute is not None and now_ms >= self.next_minute + MIN + self.caps.late_ms:
            m = self.next_minute
            a = self.acc.pop(m, {})
            if self.covered(m):
                for s in self.symbols:
                    ll, sl, nll, nsl, mx = a.get(s, (0.0, 0.0, 0, 0, 0.0))
                    rows.append(f"{m},{s},{ll:.2f},{sl:.2f},{nll},{nsl},{mx:.2f},{self.late[s]}")
                    self.late[s] = 0
            self.next_minute = m + MIN
        if self.next_minute is not None:
            self.sessions = [s for s in self.sessions if s[1] is None or s[1] >= self.next_minute]
        return rows


# ───────── REST (open interest) ─────────
def urllib_get(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": "h15-logger"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(4096)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), b""


class OiPoller:
    def __init__(self, writer: DailyCsv, caps: Caps, get=urllib_get, symbols=SYMBOLS):
        self.w, self.caps, self.get, self.symbols = writer, caps, get, tuple(symbols)
        self.used_weight: int | None = None
        self.rounds = self.skipped = self.errors = 0

    def budget(self) -> int:
        return int(self.caps.ip_weight_limit * self.caps.ip_weight_frac)

    async def poll_round(self, now_ms: int) -> int:
        """Returns rows written. Raises Stop on 429/418."""
        if self.used_weight is not None and self.used_weight >= self.budget():
            self.skipped += 1
            log.warning("OI round skipped: IP used weight %s >= %s (10%%)", self.used_weight, self.budget())
            self.used_weight = None                      # probe again next round
            return 0
        rows = []
        for s in self.symbols:
            st, hdr, body = await asyncio.to_thread(self.get, f"{REST_BASE}/fapi/v1/openInterest?symbol={s}")
            hdr = {k.lower(): v for k, v in (hdr or {}).items()}
            if st in (418, 429):
                raise Stop(f"REST HTTP {st} on openInterest (retry-after={hdr.get('retry-after', '?')})")
            try:
                self.used_weight = int(hdr.get("x-mbx-used-weight-1m"))
            except (TypeError, ValueError):
                pass
            if st != 200:
                self.errors += 1
                log.warning("OI %s HTTP %s", s, st)
                break                                    # no hammering on 5xx: rest of the round skipped
            try:
                d = json.loads(body)
                rows.append(f"{now_ms},{s},{d['openInterest']},{int(d['time'])}")
            except (ValueError, KeyError, TypeError):
                self.errors += 1
            if self.used_weight is not None and self.used_weight >= self.budget():
                break
        self.rounds += 1
        self.w.write(now_ms, rows)
        return len(rows)


# ───────── watchdog ─────────
class Probe:
    def __init__(self, bot_unit: str, data_dir: Path):
        self.bot_unit, self.data_dir = bot_unit, Path(data_dir)

    def bot(self) -> dict:
        r = subprocess.run(["systemctl", "show", self.bot_unit, "-p", "MainPID", "-p", "NRestarts", "-p", "ActiveState"],
                           capture_output=True, text=True, timeout=5, check=True)
        return dict(l.split("=", 1) for l in r.stdout.strip().splitlines() if "=" in l)

    @staticmethod
    def _psi(kind: str):
        try:
            for line in Path(f"/proc/pressure/{kind}").read_text(encoding="ascii").splitlines():
                if line.startswith("some"):
                    return float(dict(x.split("=") for x in line.split()[1:])["avg60"])
        except (OSError, ValueError, KeyError):
            return None
        return None

    def host(self) -> dict:
        mem = {l.split(":")[0]: l.split()[1] for l in Path("/proc/meminfo").read_text(encoding="ascii").splitlines()}
        rss = 0.0
        for l in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if l.startswith("VmRSS:"):
                rss = int(l.split()[1]) / 1024
        data = sum(p.stat().st_size for p in self.data_dir.rglob("*") if p.is_file()) / 2**20
        return {"mem_avail_mb": int(mem["MemAvailable"]) / 1024, "psi_cpu": self._psi("cpu"),
                "psi_mem": self._psi("memory"),
                "load5": float(Path("/proc/loadavg").read_text(encoding="ascii").split()[1]),
                "rss_mb": rss, "data_mb": data, "fs_free_mb": shutil.disk_usage(self.data_dir).free / 2**20}


@dataclass
class Watchdog:
    probe: "Probe"
    caps: Caps
    base: dict = field(default_factory=dict)
    strikes: int = 0
    probe_fails: int = 0

    def start(self) -> None:
        b = self.probe.bot()
        if b.get("ActiveState") != "active" or b.get("MainPID", "0") == "0":
            raise Stop(f"live bot not active at logger start ({b.get('ActiveState')}, pid {b.get('MainPID')})")
        self.base = {"MainPID": b["MainPID"], "NRestarts": b.get("NRestarts", "0")}
        log.info("watchdog baseline: live bot pid %s NRestarts %s", self.base["MainPID"], self.base["NRestarts"])

    def check(self) -> None:
        c = self.caps
        try:
            b = self.probe.bot()
            self.probe_fails = 0
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            self.probe_fails += 1
            if self.probe_fails >= c.probe_fail_strikes:
                raise Stop(f"cannot read live bot state {self.probe_fails}x: {type(e).__name__}") from e
            return
        if b.get("ActiveState") != "active" or b.get("MainPID") != self.base["MainPID"] \
                or b.get("NRestarts", "0") != self.base["NRestarts"]:
            raise Stop(f"live bot changed (state {b.get('ActiveState')}, pid {self.base['MainPID']}->{b.get('MainPID')}, "
                       f"NRestarts {self.base['NRestarts']}->{b.get('NRestarts')}) - logger stops itself")
        h = self.probe.host()
        if h["data_mb"] > c.data_max_mb:
            raise Stop(f"data dir {h['data_mb']:.1f} MB > cap {c.data_max_mb} MB")
        if h["fs_free_mb"] < c.fs_min_free_mb:
            raise Stop(f"filesystem free {h['fs_free_mb']:.0f} MB < {c.fs_min_free_mb} MB")
        if h["rss_mb"] > c.rss_max_mb:
            raise Stop(f"own RSS {h['rss_mb']:.1f} MB > {c.rss_max_mb} MB", EXIT_RESTARTABLE)
        bad = []
        if h["mem_avail_mb"] < c.mem_avail_min_mb:
            bad.append(f"MemAvailable {h['mem_avail_mb']:.0f} MB")
        if h["psi_cpu"] is not None and h["psi_cpu"] > c.psi_cpu_avg60_max:
            bad.append(f"cpu pressure {h['psi_cpu']}%")
        if h["psi_mem"] is not None and h["psi_mem"] > c.psi_mem_avg60_max:
            bad.append(f"memory pressure {h['psi_mem']}%")
        if h["psi_cpu"] is None and h["load5"] > c.load5_max:
            bad.append(f"load5 {h['load5']}")
        self.strikes = self.strikes + 1 if bad else 0
        if self.strikes >= c.pressure_strikes:
            raise Stop("host under pressure (bot may be affected): " + ", ".join(bad))


# ───────── the service ─────────
def default_connect(url: str):
    from websockets.asyncio.client import connect  # pylint: disable=import-outside-toplevel
    return connect(url, open_timeout=10, ping_interval=20, ping_timeout=20, close_timeout=5,
                   max_size=2**16, max_queue=64, compression=None, user_agent_header="h15-logger")


def handshake_status(e: BaseException):
    resp = getattr(e, "response", None)
    return getattr(resp, "status_code", None)


class Logger:
    def __init__(self, data_dir: Path, caps: Caps | None = None, *, probe=None, connect=default_connect,
                 get=urllib_get, now_ms=lambda: int(time.time() * 1000), oi=True, sleep=asyncio.sleep):
        self.dir, self.caps = Path(data_dir), caps or Caps()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.now_ms, self.connect, self.sleep = now_ms, connect, sleep
        self.marker = self.dir / "STOPPED"
        self.gaps = GapLog(self.dir / "gaps.csv")
        self.minutes = Minutes(SYMBOLS, self.caps)
        self.liq = DailyCsv(self.dir / "liq", LIQ_HEADER)
        self.oi = OiPoller(DailyCsv(self.dir / "oi", OI_HEADER), self.caps, get) if oi else None
        self.watchdog = Watchdog(probe or Probe("live_v6-live", self.dir), self.caps)
        self.rows = 0

    async def ws_loop(self) -> None:
        """connect → read; reconnect with exponential backoff + jitter; 429/418 on the handshake → Stop."""
        backoff = 1.0
        while True:
            reason, up = "closed by server", False
            try:
                async with self.connect(WS_URL) as ws:
                    up = True
                    t = self.now_ms()
                    self.minutes.connected(t)
                    self.gaps.row("connect", t)
                    backoff = 1.0
                    async for raw in ws:
                        self.minutes.add_raw(raw, self.now_ms())
            except Stop:
                raise
            except Exception as e:  # pylint: disable=broad-except
                code = handshake_status(e)
                if code in (418, 429):
                    raise Stop(f"websocket handshake HTTP {code}") from e
                reason = f"{type(e).__name__}{f' HTTP {code}' if code else ''}"
            finally:
                if up:
                    t = self.now_ms()
                    self.minutes.disconnected(t)
                    self.gaps.row("disconnect", self.minutes.sessions[-1][0] if self.minutes.sessions else t, t, reason)
            log.warning("websocket down (%s); reconnect in %.0fs", reason, backoff)
            await self.sleep(backoff * (1 + 0.2 * random.random()))
            backoff = min(backoff * 2, self.caps.ws_backoff_max_s)

    async def tick_loop(self, period: float = 0.5) -> None:
        last_report = 0
        while True:
            now = self.now_ms()
            rows = self.minutes.due(now)
            for i in range(0, len(rows), len(SYMBOLS)):            # one minute at a time (day rollover)
                chunk = rows[i:i + len(SYMBOLS)]
                self.liq.write(int(chunk[0].split(",", 1)[0]), chunk)
                self.rows += len(chunk)
            if now - last_report >= 600_000:
                last_report = now
                log.info("rows %d msgs %d bad %d oi rounds %s skipped %s", self.rows, self.minutes.msgs,
                         self.minutes.bad, self.oi and self.oi.rounds, self.oi and self.oi.skipped)
            await self.sleep(period)

    async def oi_loop(self) -> None:
        iv = self.caps.oi_interval_s * 1000
        while True:
            now = self.now_ms()
            nxt = (now // iv + 1) * iv + 7_000                  # 7 s after each 5-min boundary
            await self.sleep((nxt - now) / 1000)
            await self.oi.poll_round(self.now_ms())

    async def watchdog_loop(self) -> None:
        while True:
            await self.sleep(self.caps.watchdog_s)
            self.watchdog.check()

    async def run_async(self) -> int:
        tasks = []
        try:
            self.watchdog.start()
            coros = [self.ws_loop(), self.tick_loop(), self.watchdog_loop()] + ([self.oi_loop()] if self.oi else [])
            tasks = [asyncio.ensure_future(c) for c in coros]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for t in done:
                t.result()
            return 0
        except Stop as s:
            return self.stopped(s)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.liq.close()
            if self.oi:
                self.oi.w.close()

    def stopped(self, s: Stop) -> int:
        t = self.now_ms()
        log.error("STOP (exit %d): %s", s.code, s.reason)
        if s.code == EXIT_STOPPED:
            self.marker.write_text(f"{t} {s.reason}\nremove this file to allow a restart\n", encoding="utf-8")
        self.minutes.disconnected(t)
        self.gaps.row("process_stop", t, "", f"exit {s.code}: {s.reason}")
        return s.code

    def run(self) -> int:
        if self.marker.exists():
            log.error("STOPPED marker present (%s): %s", self.marker, self.marker.read_text(encoding="utf-8").splitlines()[0])
            return EXIT_STOPPED
        self.gaps.row("process_start", self.now_ms(), "", f"pid {os.getpid()}")
        return asyncio.run(self.run_async())


def preflight(env=None, uid=None) -> str | None:
    env = os.environ if env is None else env
    uid = os.getuid() if uid is None else uid
    if uid == 0:
        return "refusing to run as root (separate unix user required)"
    keys = [k for k in env if k.startswith("BINANCE_") or k in ("TELEGRAM_BOT_TOKEN", "HEARTBEAT_URL")]
    if keys:
        return "refusing: secrets in environment (public data only): " + ", ".join(sorted(keys))
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="h15_logger")
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--data", default="/var/lib/h15-logger")
    ap.add_argument("--bot-unit", default="live_v6-live")
    ap.add_argument("--no-oi", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    err = preflight()
    if err:
        log.error(err)
        return EXIT_STOPPED
    lg = Logger(Path(a.data), probe=Probe(a.bot_unit, Path(a.data)), oi=not a.no_oi)
    return lg.run()
