"""Static guard (TA, live bug 2026-10-20): unreachable code in the live package fails the suite. The deployed fae64af had
`self.on_bar_close()` after `return` in healthy() — dead code, so 4h decisions never ran. Two independent checks:
a dependency-free AST walk (always runs) and pylint W0101 / W0102-free run (when pylint is installed: pip install pylint)."""
import ast
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
    pytest.importorskip("pylint")
    r = subprocess.run([sys.executable, "-m", "pylint", "--disable=all", "--enable=W0101", "--score=n", str(PKG)],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:]
