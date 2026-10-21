"""TA review ci-deploy item D: tools/verify_stops_live.py (installed as /opt/tradebot/verify_stops_live.py) is
read-only (GET only, fapi.binance.com only), exits ≠0 on any API failure, and never prints the key or secret.
Fully offline: urllib.request.urlopen is replaced; no network, no real keys."""
import ast
import importlib.util
import io
import json
import pathlib
import socket
import urllib.error

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "tools" / "verify_stops_live.py"
KEY, SECRET = "TESTKEY_" + "k" * 56, "TESTSECRET_" + "s" * 53


def load():
    spec = importlib.util.spec_from_file_location("verify_stops_live_ut", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_exchange(positions=(), std=(), algo=()):
    data = {"/fapi/v3/positionRisk": list(positions), "/fapi/v1/symbolConfig": [{"symbol": "BTCUSDT", "marginType": "ISOLATED", "leverage": 3}],
            "/fapi/v1/openOrders": list(std), "/fapi/v1/openAlgoOrders": list(algo)}
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req)
        path = req.full_url.split("?")[0].removeprefix("https://fapi.binance.com")
        return Resp(json.dumps(data[path]).encode())
    return urlopen, calls


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", KEY)
    monkeypatch.setenv("BINANCE_API_SECRET", SECRET)
    return load()


def run(mod, monkeypatch, capsys, urlopen):
    monkeypatch.setattr(mod.urllib.request, "urlopen", urlopen)
    rc = mod.main()
    out = capsys.readouterr()
    assert KEY not in out.out + out.err and SECRET not in out.out + out.err
    assert "signature" not in out.out + out.err
    return rc, out.out


LONG = {"symbol": "BTCUSDT", "positionAmt": "0.010", "entryPrice": "100000", "markPrice": "101000"}


def test_flat_account_passes_and_uses_only_get_on_mainnet_host(mod, monkeypatch, capsys):
    urlopen, calls = fake_exchange()
    rc, out = run(mod, monkeypatch, capsys, urlopen)
    assert rc == 0 and json.loads(out)["pass"] is True
    assert len(calls) == 4
    for r in calls:
        assert r.get_method() == "GET" and r.data is None
        assert r.full_url.startswith("https://fapi.binance.com/fapi/")


def test_protected_position_passes(mod, monkeypatch, capsys):
    stop = {"symbol": "BTCUSDT", "type": "STOP_MARKET", "side": "SELL", "stopPrice": "97000", "origQty": "0",
            "closePosition": True, "reduceOnly": True}
    rc, out = run(mod, monkeypatch, capsys, fake_exchange([LONG], [stop])[0])
    assert rc == 0 and json.loads(out)["positions"][0]["protected"] is True


def test_algo_stop_counts(mod, monkeypatch, capsys):
    algo = {"symbol": "BTCUSDT", "orderType": "STOP_MARKET", "side": "SELL", "triggerPrice": "97000", "quantity": "0.010",
            "closePosition": "false", "reduceOnly": "true"}
    rc, _ = run(mod, monkeypatch, capsys, fake_exchange([LONG], (), [algo])[0])
    assert rc == 0


def test_unprotected_position_exits_1(mod, monkeypatch, capsys):
    wrong_side = {"symbol": "BTCUSDT", "type": "STOP_MARKET", "side": "BUY", "stopPrice": "97000", "closePosition": True}
    rc, out = run(mod, monkeypatch, capsys, fake_exchange([LONG], [wrong_side])[0])
    assert rc == 1 and json.loads(out)["pass"] is False


@pytest.mark.parametrize("exc", [
    urllib.error.HTTPError("https://fapi.binance.com/x?signature=abc", 401, "Unauthorized", {}, io.BytesIO(b'{"code":-2015}')),
    urllib.error.URLError("dns failure"),
    socket.timeout("timed out"),
    ConnectionResetError(104, "reset"),
])
def test_api_failure_exits_2_without_leaking(mod, monkeypatch, capsys, exc):
    def urlopen(req, timeout=None):
        raise exc
    rc, out = run(mod, monkeypatch, capsys, urlopen)
    assert rc == 2
    d = json.loads(out)
    assert d["pass"] is False and "fapi.binance.com" not in d["error"] and "?" not in d["error"]


def test_non_json_and_bad_shape_exit_2(mod, monkeypatch, capsys):
    rc, _ = run(mod, monkeypatch, capsys, lambda req, timeout=None: Resp(b"<html>maintenance</html>"))
    assert rc == 2
    rc, _ = run(mod, monkeypatch, capsys, lambda req, timeout=None: Resp(b'{"code":-1000,"msg":"x"}'))
    assert rc == 2


def test_missing_keys_exit_2(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    m = load()
    monkeypatch.setattr(m, "ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setattr(m.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network must not be touched"))
    assert m.main() == 2
    assert "keys unavailable" in capsys.readouterr().out


def test_source_is_get_only_and_never_prints_keys():
    src = SRC.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value.upper() not in ("POST", "PUT", "DELETE", "PATCH")
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print":
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            assert not names & {"k", "s", "key", "secret", "K", "S", "q", "req"}, ast.unparse(node)
    urlopens = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "urlopen"]
    assert len(urlopens) == 1                                  # one request path: _get
    assert 'method="GET"' in src and all(
        src.startswith("https://fapi.binance.com", i) for i in range(len(src)) if src.startswith("https://", i))
