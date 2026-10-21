"""Static guard (TA, live bug 2026-10-20): unreachable code in the live package fails the suite. The deployed fae64af had
`self.on_bar_close()` after `return` in healthy() — dead code, so 4h decisions never ran. Two independent checks:
a dependency-free AST walk (always runs) and pylint W0101 / W0102-free run (pylint from live_v6/requirements-dev.txt; skipped only if absent and LIVE_V6_REQUIRE_PYLINT != 1)."""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _sources():
    return [p for p in PKG.rglob("*.py") if "tests" not in p.parts and "__pycache__" not in p.parts]


def unreachable(tree) -> list[int]:
    out = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for i, st in enumerate(block[:-1]):
                if isinstance(st, TERMINAL):
                    out.append(block[i + 1].lineno)
                    break
        for h in getattr(node, "handlers", []) or []:
            for i, st in enumerate(h.body[:-1]):
                if isinstance(st, TERMINAL):
                    out.append(h.body[i + 1].lineno)
                    break
    return out


def test_detector_catches_the_live_bug_shape():
    src = "class E:\n def healthy(self):\n  return True\n  self.on_bar_close()\n"
    assert unreachable(ast.parse(src)) == [4]


def test_no_unreachable_code_in_live_package():
    bad = {str(p.relative_to(PKG)): ln for p in _sources() if (ln := unreachable(ast.parse(p.read_text(), str(p))))}
    assert not bad, f"unreachable statements (file: lines): {bad}"


def test_pylint_w0101_unreachable():
    # pylint is in requirements-dev.txt. LIVE_V6_REQUIRE_PYLINT=1 (pre-deploy / CI) turns a missing pylint into a FAILURE
    # instead of a silent skip (TA review 950438b, condition c).
    if os.getenv("LIVE_V6_REQUIRE_PYLINT") == "1":
        import pylint  # noqa: F401  pylint: disable=import-outside-toplevel,unused-import
    else:
        pytest.importorskip("pylint")
    r = subprocess.run([sys.executable, "-m", "pylint", "--disable=all", "--enable=W0101", "--score=n", str(PKG)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:]
