"""Running the suite must not rewrite the committed evidence in live_v6/reports/ (it used to: the testnet gate tests
wrote gate_sigkill_*.json / h7t_killed_after_entry.json there on every full run). Tests write evidence to the
`reports_dir` fixture: a tmp dir, or LIVE_V6_REPORTS_DIR when someone deliberately regenerates evidence."""
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
PKG_REPORTS = TESTS.parent / "reports"
WRITES_TO_COMMITTED = re.compile(r"""(ROOT\s*/\s*["']reports["']|^REPORTS\s*=)""", re.M)


def test_no_test_file_points_at_the_committed_reports_dir():
    bad = [p.name for p in sorted(TESTS.glob("*.py")) if p.name != Path(__file__).name
           and WRITES_TO_COMMITTED.search(p.read_text())]
    assert bad == [], f"write evidence via the reports_dir fixture instead: {bad}"


def test_reports_dir_fixture_is_not_the_committed_dir(reports_dir):
    assert reports_dir.is_dir() and reports_dir.resolve() != PKG_REPORTS.resolve()


def test_reports_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_V6_REPORTS_DIR", str(tmp_path / "ev"))
    from .conftest import resolve_reports_dir
    assert resolve_reports_dir(tmp_path / "unused") == tmp_path / "ev" and (tmp_path / "ev").is_dir()
