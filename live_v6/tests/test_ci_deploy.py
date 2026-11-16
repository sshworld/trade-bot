"""deploy/ci/ci_deploy.sh (VPS side of the main → live CI deploy), run against a fake world: CI_ROOT prefixes every path,
CI_TEST_BIN puts fake systemctl / journalctl / systemd-run / curl / flock / chown / sleep first on PATH. The fake
systemctl "restarts the bot" by reading <current release>/live_v6/fake_behavior and rewriting the state file the way
the real engine would (meta.health). No network, no root, no real unit is touched.

Branches covered: normal deploy · verification fails → rollback to the marked release · rollback fails → stop + CI_HALTED ·
no marked release → stop · pre-checks refuse with nothing changed (entry in flight, stops, unhealthy, import, stopped
unit, CI_HALTED) · persisted halt accepted · strategy mismatch never a rollback target · confirm (30 min marker) · adopt.
"""
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "ci" / "ci_deploy.sh"
OLD, NEW, OTHER = "a" * 40, "b" * 40, "c" * 40
UNIT = "live_v6-live"

FAKE_SYSTEMCTL = r'''
import json, os, sys, time
F = os.environ["FAKE_DIR"]; R = os.environ["CI_ROOT"]
APP = R + "/opt/tradebot/app"; STATE = R + "/var/lib/live_v6-live/mainnet.json"
def rd(n, d=""):
    try: return open(os.path.join(F, n)).read().strip()
    except FileNotFoundError: return d
def wr(n, v): open(os.path.join(F, n), "w").write(str(v))
a = sys.argv[1:]
open(os.path.join(F, "calls.log"), "a").write("systemctl " + " ".join(a) + "\n")
cmd = a[0]
def tick():                                     # the new bot process writes its state after it started
    beh = rd("behavior"); wr("tick", "0")
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    m = st.setdefault("meta", {})
    ok = beh in ("good", "traceback", "loop") and not m.get("halted")
    m["health"] = {"t": int(time.time() * 1000), "ok": ok, "blocks": [] if beh != "unhealthy" else ["bar_close_stale"]}
    st["intents"] = {}
    json.dump(st, open(STATE, "w"))
    if beh == "traceback":
        open(os.path.join(F, "journal." + rd("pid")), "a").write("Traceback (most recent call last):\n")
    if beh == "loop":
        wr("looping", "1")
if cmd == "is-active":
    s = rd("active", "inactive")
    if s == "active" and rd("tick") == "1":
        time.sleep(0.01); tick()
    print(s); sys.exit(0 if s == "active" else 3)
if cmd == "show":
    p = a[a.index("-p") + 1]
    if p == "NRestarts":
        n = int(rd("nrestarts", "0"))
        if rd("looping") == "1": n += 1; wr("nrestarts", n)
        print(n)
    elif p == "MainPID": print(rd("pid", "0") if rd("active") == "active" else "0")
    elif p == "TimeoutStopUSec": print(rd("timeout_stop", "30s"))
    else: print("")
    sys.exit(0)
if cmd == "stop":
    wr("active", "inactive"); sys.exit(0)
if cmd == "restart":
    beh = open(os.path.join(APP, "current", "live_v6", "fake_behavior")).read().strip()
    wr("looping", "0"); wr("tick", "0")
    if beh == "crash":
        wr("active", "activating"); sys.exit(0)
    if beh == "restart_fails":                  # systemctl restart errors; the OLD process keeps running and writing
        wr("tick", "1"); wr("behavior", "good"); sys.exit(1)
    pid = int(rd("pid", "100")) + 1
    wr("pid", pid); wr("active", "active"); wr("behavior", beh); wr("tick", "1")
    os.makedirs(f"{R}/proc/{pid}", exist_ok=True)
    open(f"{R}/proc/{pid}/environ", "wb").write(b"PATH=/usr/bin\0LIVE_V6_STRATEGY=" + rd("strategy").encode() + b"\0")
    sys.exit(0)
sys.exit(0)
'''
FAKE_JOURNALCTL = r'''
import os, sys
pid = next((x[5:] for x in sys.argv if x.startswith("_PID=")), None)
assert pid, "journal must be filtered by the process"
try: print(open(os.path.join(os.environ["FAKE_DIR"], "journal." + pid)).read(), end="")
except FileNotFoundError: pass
'''
FAKE_SYSTEMD_RUN = r'''
import os, sys
F = os.environ["FAKE_DIR"]
open(os.path.join(F, "calls.log"), "a").write("systemd-run " + sys.argv[-1] + "\n")
sys.exit(int(open(os.path.join(F, "import_rc")).read() or 0) if os.path.exists(os.path.join(F, "import_rc")) else 0)
'''
FAKE_CURL = r'''
import os, sys
F = os.environ["FAKE_DIR"]
cfg = sys.stdin.read() if "-K" in sys.argv else ""
open(os.path.join(F, "curl.log"), "a").write(json.dumps({"cfg": cfg, "args": sys.argv[1:]}) + "\n")
'''
FAKE_CHOWN = r'''
import os, sys
pat = os.path.join(os.environ["FAKE_DIR"], "chown_fail")    # test hook: fail for paths ending with this suffix
sys.exit(1 if os.path.exists(pat) and sys.argv[-1].endswith(open(pat).read().strip()) else 0)
'''
FAKE_STOPS = r'''
import json, os, sys
F = os.environ["FAKE_DIR"]
seq = os.path.join(F, "stops_seq")
if os.path.exists(seq):                         # one rc per call, last one repeats
    rcs = open(seq).read().split(); rc = int(rcs[0]); open(seq, "w").write(" ".join(rcs[1:] or rcs))
else:
    rc = int(open(os.path.join(F, "stops_rc")).read() or 0) if os.path.exists(os.path.join(F, "stops_rc")) else 0
print(json.dumps({"pass": rc == 0, "positions": [{"symbol": "BTCUSDT", "positionAmt": "0.01", "protected": rc == 0}]}))
sys.exit(rc)
'''


def _exe(path, body, py=True):
    path.write_text((f"#!{sys.executable}\nimport json\n" if py else "#!/bin/sh\n") + body)
    path.chmod(0o755)


class World:
    def __init__(self, tmp: Path):
        self.root = tmp / "root"
        self.bin = tmp / "bin"
        self.fake = tmp / "fake"
        for d in (self.root, self.bin, self.fake):
            d.mkdir()
        self.app = self.root / "opt/tradebot/app"
        self.state = self.root / "var/lib/live_v6-live/mainnet.json"
        self.state.parent.mkdir(parents=True)
        self.app.mkdir(parents=True)
        _exe(self.bin / "systemctl", FAKE_SYSTEMCTL)
        _exe(self.bin / "journalctl", FAKE_JOURNALCTL)
        _exe(self.bin / "systemd-run", FAKE_SYSTEMD_RUN)
        _exe(self.bin / "curl", FAKE_CURL)
        _exe(self.bin / "chown", FAKE_CHOWN)
        for n in ("flock", "sleep"):
            _exe(self.bin / n, "exit 0\n", py=False)
        stops = self.root / "opt/tradebot/verify_stops_live.py"
        stops.write_text("import json\n" + FAKE_STOPS)
        tg = self.root / "etc/tradebot"
        tg.mkdir(parents=True)
        (tg / "telegram.env").write_text("TELEGRAM_BOT_TOKEN=123:SECRETTOKEN\nTELEGRAM_CHAT_ID=42\n")
        (tg / "heartbeat.env").write_text("HEARTBEAT_URL=https://hc.example/u\n")
        self.set("strategy", "bundle_v5")
        self.set("active", "active")
        self.set("pid", "100")
        self.set("nrestarts", "0")
        self.proc(100)
        self.write_state()

    def set(self, name, value):
        (self.fake / name).write_text(str(value))

    def get(self, name, default=""):
        p = self.fake / name
        return p.read_text() if p.exists() else default

    def proc(self, pid):
        d = self.root / "proc" / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "environ").write_bytes(b"LIVE_V6_STRATEGY=" + self.get("strategy").encode() + b"\0")

    def write_state(self, ok=True, intents=None, halted=None, blocks=None, age_s=0):
        meta = {"health": {"t": int((time.time() - age_s) * 1000), "ok": ok, "blocks": blocks or []}}
        if halted:
            meta["halted"] = halted
        self.state.write_text(json.dumps({"meta": meta, "pos": {}, "intents": intents or {}, "strategy": {}}))

    def release(self, sha, behavior="good", marker=None, strategy="bundle_v5", verified_at="2026-11-01T00:00:00Z"):
        d = self.app / sha / "live_v6"
        d.mkdir(parents=True)
        (d / "fake_behavior").write_text(behavior)
        (self.app / sha / ".ci_complete").write_text(sha + "\n")
        if marker:
            (self.app / sha / marker).write_text(f"sha={sha}\ntarget=live\nstrategy={strategy}\nverified_at_utc={verified_at}\n")
        return sha

    def current(self, sha=None):
        if sha:
            (self.app / "current").symlink_to(self.app / sha)
        return os.path.basename(os.readlink(self.app / "current"))

    def tar(self, behavior="good", notes="abc1234 feat: one\ndef5678 fix: two\n", extra=None):
        p = self.fake.parent / "app.tar"
        with tarfile.open(p, "w") as t:
            def add(name, data=None):
                ti = tarfile.TarInfo(name)
                if data is None:
                    ti.type = tarfile.DIRTYPE
                    ti.mode = 0o755
                    t.addfile(ti)
                else:
                    b = data.encode()
                    ti.size = len(b)
                    ti.mode = 0o644
                    t.addfile(ti, io.BytesIO(b))
            add("live_v6")
            add("live_v6/__init__.py", "")
            add("live_v6/fake_behavior", behavior)
            if notes is not None:
                add("live_v6/.ci_release_notes", notes)
            for n, data in (extra or {}).items():
                add(n, data)
        return p

    def run(self, *args, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith("CI_")}
        e.update(CI_ROOT=str(self.root), CI_TEST_BIN=str(self.bin), FAKE_DIR=str(self.fake), CI_POLL_S="1",
                 CI_VERIFY_TIMEOUT="3", CI_STABLE_S="0", CI_INTENT_WAIT="0", CI_INTENT_TRIES="2", **env)
        r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=e, timeout=120)
        return r.returncode, r.stdout + r.stderr

    def deploy(self, sha=NEW, **kw):
        return self.run("deploy", "live", sha, str(self.tar(**kw)))

    def calls(self):
        return self.get("calls.log")

    def telegram(self):
        out = []
        for line in self.get("curl.log").splitlines():
            d = json.loads(line)
            if "api.telegram.org" in d["cfg"]:
                out.append(next(a[5:] for a in d["args"] if a.startswith("text=")))
        return out

    def healthchecks(self):
        return [json.loads(l) for l in self.get("curl.log").splitlines() if "hc.example" in json.loads(l)["cfg"]]


@pytest.fixture
def w(tmp_path):
    w = World(tmp_path)
    w.release(OLD, "good", marker=".ci_verified")
    w.current(OLD)
    return w


def nothing_changed(w, out):
    assert w.current() == OLD, out
    assert "systemctl restart" not in w.calls() and "systemctl stop" not in w.calls(), out
    assert not (w.app / "CI_HALTED").exists()


# ── happy path ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_deploy_ok_swaps_restarts_pending_marker_and_telegram_release_notes(w):
    rc, out = w.deploy()
    assert rc == 0, out
    assert w.current() == NEW
    assert "systemctl restart live_v6-live" in w.calls()
    assert (w.app / NEW / ".ci_verified.pending").exists() and not (w.app / NEW / ".ci_verified").exists()
    pend = (w.app / NEW / ".ci_verified.pending").read_text()
    assert "strategy=bundle_v5" in pend and "pid=101" in pend
    assert list((w.root / "root/ci-backups/live").iterdir()), "state backup"
    tg = w.telegram()
    assert len(tg) == 1 and "배포 완료" in tg[0] and "- abc1234 feat: one" in tg[0] and "- def5678 fix: two" in tg[0]
    # the token reaches curl only through stdin (-K -), never argv / the job log
    assert "SECRETTOKEN" not in out
    assert all("SECRETTOKEN" not in a for l in w.get("curl.log").splitlines() for a in json.loads(l)["args"])
    assert "bundle_v5" in w.calls().split("systemd-run ")[-1]      # import check gets the unit's strategy


def test_dry_run_changes_nothing(w):
    rc, out = w.run("deploy", "live", NEW, str(w.tar()), "--dry-run")
    assert rc == 0, out
    nothing_changed(w, out)
    assert not (w.app / NEW).exists() and "DRY-RUN would" in out


def test_same_sha_already_running_is_noop(w):
    rc, out = w.deploy(sha=OLD)
    assert rc == 0 and "no-op" in out
    nothing_changed(w, out)


# ── failure after restart ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("behavior", ["unhealthy", "crash", "traceback", "loop", "restart_fails"])
def test_verification_fails_rolls_back_to_marked_release(w, behavior):
    rc, out = w.deploy(behavior=behavior)
    assert rc == 9, out
    assert w.current() == OLD
    assert w.calls().count("systemctl restart live_v6-live") == 2           # deploy + rollback
    assert "systemctl stop" not in w.calls() and not (w.app / "CI_HALTED").exists()
    assert (w.app / NEW / ".ci_revoked").exists() and not (w.app / NEW / ".ci_verified.pending").exists()
    assert (w.app / OLD / ".ci_verified").exists()                          # the good target keeps its marker
    tg = w.telegram()
    assert len(tg) == 1 and "배포 실패 → 롤백 완료" in tg[0]
    assert w.healthchecks()                                                 # Healthchecks /fail as well


def test_rollback_also_fails_stops_bot_and_halts(w):
    (w.app / OLD / "live_v6" / "fake_behavior").write_text("unhealthy")
    rc, out = w.deploy(behavior="unhealthy")
    assert rc == 6, out
    assert "systemctl stop live_v6-live" in w.calls() and w.get("active") == "inactive"
    assert (w.app / "CI_HALTED").exists()
    assert (w.app / OLD / ".ci_revoked").exists() and not (w.app / OLD / ".ci_verified").exists()
    tg = w.telegram()
    assert len(tg) == 1 and "봇 정지" in tg[0] and "거래소 손절은 그대로" in tg[0]
    # a halted target refuses every further deploy / rollback until ops removes CI_HALTED by hand
    rc, out = w.deploy(sha=OTHER)
    assert rc == 13, out


def test_no_marked_release_stops_bot(w):
    (w.app / OLD / ".ci_verified").unlink()
    rc, out = w.deploy(behavior="unhealthy")
    assert rc == 10, out
    assert w.get("active") == "inactive" and (w.app / "CI_HALTED").exists()


def test_old_v1_marker_and_other_strategy_are_never_rollback_targets(w):
    (w.app / OLD / ".ci_verified").unlink()
    (w.app / OLD / ".ta_pass_verified").write_text(f"sha={OLD}\n")             # v1 (H7-T era) marker: ignored
    w.release(OTHER, "good", marker=".ci_verified", strategy="h7t", verified_at="2026-11-10T00:00:00Z")
    rc, out = w.deploy(behavior="unhealthy")
    assert rc == 10, out
    assert w.current() == NEW and w.get("active") == "inactive"               # stopped on the failed release, not swapped


def test_rollback_picks_newest_marked_release_of_the_same_strategy(w):
    w.release(OTHER, "good", marker=".ci_verified", verified_at="2026-11-10T00:00:00Z")
    rc, out = w.deploy(behavior="unhealthy")
    assert rc == 9, out
    assert w.current() == OTHER


# ── pre-checks: refuse, nothing changed ────────────────────────────────────────────────────────────────────────────
def test_entry_in_flight_refuses(w):
    w.write_state(intents={"v6x1": {"sym": "BTCUSDT"}})
    rc, out = w.deploy()
    assert rc == 11, out
    nothing_changed(w, out)
    assert "배포 보류" in w.telegram()[0]


def test_resting_postonly_entry_refuses(w):
    w.write_state(intents={"v6x2": {"sym": "ETHUSDT", "pending": {"ocid": "x", "placed_ms": 1}}})
    rc, out = w.deploy()
    assert rc == 11 and "postonly_pending=1" in out, out
    nothing_changed(w, out)


def test_stops_not_verified_refuses(w):
    w.set("stops_rc", "1")
    rc, out = w.deploy()
    assert rc == 5, out
    nothing_changed(w, out)


@pytest.mark.parametrize("state", [dict(ok=False, blocks=["bar_close_stale"]), dict(age_s=600)])
def test_unhealthy_or_stale_bot_refuses(w, state):
    w.write_state(**state)
    rc, out = w.deploy()
    assert rc == 15, out
    nothing_changed(w, out)


def test_stopped_unit_is_never_started_by_ci(w):
    w.set("active", "inactive")
    rc, out = w.deploy()
    assert rc == 15, out
    nothing_changed(w, out)


def test_import_check_failure_refuses(w):
    w.set("import_rc", "1")
    rc, out = w.deploy()
    assert rc == 8, out
    nothing_changed(w, out)


def test_archive_outside_live_v6_refused(w):
    rc, out = w.deploy(extra={"etc/evil": "x"})
    assert rc == 2, out
    nothing_changed(w, out)


def test_persisted_halt_is_accepted_when_unchanged(w):
    w.write_state(ok=False, halted="daily_loss: 자산 90 ≤ 91")                 # healthy() is false by design while halted
    rc, out = w.deploy()
    assert rc == 0, out
    assert w.current() == NEW


# ── confirm (timer) ────────────────────────────────────────────────────────────────────────────────────────────────
def test_confirm_grants_marker_only_after_30_min(w):
    assert w.deploy()[0] == 0
    rc, out = w.run("confirm", "live")
    assert rc == 0 and "< 1800s" in out
    assert not (w.app / NEW / ".ci_verified").exists()
    rc, out = w.run("confirm", "live", CI_CONFIRM_AFTER="0")
    assert rc == 0, out
    m = (w.app / NEW / ".ci_verified").read_text()
    assert f"sha={NEW}" in m and "strategy=bundle_v5" in m
    assert not (w.app / NEW / ".ci_verified.pending").exists()


def test_confirm_revokes_when_the_process_changed(w):
    assert w.deploy()[0] == 0
    w.set("pid", "555")
    rc, out = w.run("confirm", "live", CI_CONFIRM_AFTER="0")
    assert rc == 14, out
    assert (w.app / NEW / ".ci_revoked").exists() and not (w.app / NEW / ".ci_verified").exists()
    assert w.get("active") == "active"                                        # confirm never stops the bot


def test_confirm_retries_soft_failure_until_deadline(w):
    assert w.deploy()[0] == 0
    w.write_state(ok=False, blocks=["stream_down"])
    rc, out = w.run("confirm", "live", CI_CONFIRM_AFTER="0")
    assert rc == 0 and "retrying" in out, out
    assert (w.app / NEW / ".ci_verified.pending").exists()
    rc, out = w.run("confirm", "live", CI_CONFIRM_AFTER="0", CI_CONFIRM_DEADLINE="0")
    assert rc == 14, out


# ── manual: rollback / adopt ───────────────────────────────────────────────────────────────────────────────────────
def test_manual_rollback_and_adopt(w):
    assert w.deploy()[0] == 0
    rc, out = w.run("rollback", "live")
    assert rc == 0, out
    assert w.current() == OLD
    # adopt: ops marks the running hand-deployed release (7-char dir) as a rollback target
    (w.app / "current").unlink()
    w.release("d" * 7, "good")
    (w.app / ("d" * 7) / ".ci_complete").unlink()
    w.current("d" * 7)
    rc, out = w.run("adopt", "live", "d" * 40)
    assert rc == 0, out
    assert "strategy=bundle_v5" in (w.app / ("d" * 7) / ".ci_verified").read_text()
    rc, out = w.run("adopt", "live", "e" * 40)
    assert rc == 2, out


def test_unexpected_abort_after_the_swap_still_alerts(w):
    w.set("chown_fail", ".ci_verified.pending.tmp")              # set -e abort while writing the pending marker
    rc, out = w.deploy()
    assert rc != 0 and "UNEXPECTED exit" in out, out
    tg = w.telegram()
    assert len(tg) == 1 and "비정상 종료" in tg[0]
    assert w.healthchecks()


def test_status_is_read_only(w):
    rc, out = w.run("status", "live")
    assert rc == 0, out
    assert f"current={OLD} sha={OLD}" in out and "strategy=bundle_v5" in out
    assert "systemctl restart" not in w.calls()
