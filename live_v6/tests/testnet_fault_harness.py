"""Testnet fault cases 13 and 14. Not part of the offline suite.

Run on the VPS with the live service stopped and testnet keys in the environment:

    python -m live_v6.tests.testnet_fault_harness 13 OUTDIR
    python -m live_v6.tests.testnet_fault_harness 14 OUTDIR

Case 13 — quantity mismatch. The engine opens one DOGEUSDT long. A second REST client
then sells part of it (a phone-app order). Reconcile must stop new entries, alert once,
leave the journal unbooked, and keep an exchange stop on whatever is still open.

Case 14 — the -5% hard stop. Five binhv45 journal rows whose net after fees is -5% of the
wallet recorded at startup block the next entry, including before 30 trades. A restart of
the same state file stays blocked and does not alert again. A second state at -4.9% does
not block. No order is sent for the -4.9% check. The daily -10% halt is not touched.

Both cases use a private state file under OUTDIR and flatten DOGEUSDT before exiting.
"""
import json
import os
import sys
import time
from decimal import Decimal

for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "LIVE_V6_NETWORK", "LIVE_V6_MAINNET_ACK",
          "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "LIVE_V6_TG_TOKEN", "LIVE_V6_TG_CHAT"):
    os.environ.pop(k, None)
os.environ["LIVE_V6_FORBID_MAINNET"] = "1"


def _boot():
    from live_v6.engine import V6Engine
    from live_v6.exchange import TESTNET_URL, BinanceREST
    from live_v6.notify import NullNotifier
    from live_v6.runner import live_settings
    from live_v6.store import JsonStore
    from live_v6.strategies.binhv45 import BinHV45
    return V6Engine, TESTNET_URL, BinanceREST, NullNotifier, live_settings, JsonStore, BinHV45


def _note(out, *parts):
    line = time.strftime("%H:%M:%S") + " " + " ".join(str(p) for p in parts)
    print(line, flush=True)
    with open(os.path.join(out, "harness.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _engine(out, name, BinanceREST, TESTNET_URL, V6Engine, NullNotifier, live_settings, JsonStore, BinHV45):
    key, sec = os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"]
    rest = BinanceREST(TESTNET_URL, key, sec)
    manual = BinanceREST(TESTNET_URL, key, sec)
    cfg = live_settings("binhv45").__dict__.copy()
    cfg["symbols"] = ("DOGEUSDT",)
    cfg["entry_order"] = ("DOGEUSDT",)
    cfg["cid_prefix"] = "v6t"
    cfg["income_interval_s"] = 1e9
    n = NullNotifier()
    path = os.path.join(out, name)
    eng = V6Engine(rest, live_settings("binhv45", **{k: cfg[k] for k in (
        "symbols", "entry_order", "cid_prefix", "income_interval_s")}),
                   store=JsonStore(path), notifier=n, strategy=BinHV45())
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    return rest, manual, eng, n, path


def _flatten(manual, note):
    sym = "DOGEUSDT"
    try:
        amt = manual.positions((sym,))[sym]["amt"]
    except Exception as e:  # noqa: BLE001 — cleanup must report and continue
        note("flatten position read failed", e)
        return
    if amt != 0:
        try:
            manual.market(sym, "SELL" if amt > 0 else "BUY", abs(amt), f"v6tclean{int(time.time())}", True)
        except Exception as e:  # noqa: BLE001
            note("flatten market failed", e)
    try:
        orders = manual.open_orders(sym)
    except Exception as e:  # noqa: BLE001
        note("flatten orders read failed", e)
        return
    for o in orders:
        try:
            manual.cancel(sym, o)
        except Exception as e:  # noqa: BLE001
            note("flatten cancel failed", o.get("client_id"), e)


def case13(out):
    """Manual partial close: one alert, entries halted, journal not rewritten, stop still on the book."""
    V6Engine, TESTNET_URL, BinanceREST, NullNotifier, live_settings, JsonStore, BinHV45 = _boot()
    rest, manual, eng, n, _path = _engine(
        out, "case13.json", BinanceREST, TESTNET_URL, V6Engine, NullNotifier, live_settings, JsonStore, BinHV45)
    sym = "DOGEUSDT"
    try:
        eng.startup()
        px = rest.book(sym)["bid"]
        tick = eng.rules[sym].tick_size
        dist = (px * Decimal("0.0075") / tick).quantize(Decimal(1)) * tick
        assert eng.enter(sym, dist, int(time.time()) * 1000), eng.meta.get("skip_log", [])[-1:]
        for _ in range(10):
            eng.reconcile()
            if sym in eng.st["pos"]:
                break
            time.sleep(0.5)
        j = eng.st["pos"][sym]
        qty = Decimal(j["qty"])
        step = eng.rules[sym].step_size
        cut = (qty / 2).quantize(step)
        if cut <= 0 or cut >= qty:
            cut = step
        _note(out, "case13 open", qty, "manual sell", cut, "stop", j["stop_px"])
        manual.market(sym, "SELL", cut, f"phone13{int(time.time())}", True)
        for _ in range(6):
            eng.reconcile()
        alerts = [m for m in n.sent if "수량 불일치" in m]
        left = manual.positions((sym,))[sym]["amt"]
        stops = [o for o in manual.open_orders(sym) if str(o.get("type") or "").startswith("STOP")]
        report = {
            "case": 13, "alerts": len(alerts), "qty_guard": bool(eng.meta.get("qty_guard")),
            "journal_qty": eng.st["pos"].get(sym, {}).get("qty"), "exchange_amt": str(left),
            "booked_trades": len(eng.meta.get("trades") or []), "stops": len(stops),
            "entries_blocked": "qty_guard" in eng.blocks,
        }
        _note(out, json.dumps(report, ensure_ascii=False))
        assert report["alerts"] == 1, report
        assert report["qty_guard"] and report["entries_blocked"], report
        assert report["journal_qty"] == str(qty) or Decimal(report["journal_qty"]) == qty, report
        assert report["booked_trades"] == 0, report
        if left != 0:
            assert stops, report
        eng.enter(sym, dist, int(time.time()) * 1000 + 1000)
        assert len([m for m in n.sent if "수량 불일치" in m]) == 1
        _note(out, "case13 PASS")
    finally:
        _flatten(manual, lambda *a: _note(out, *a))


def case14(out):
    """-5% of the startup wallet halts at trade 5. -4.9% does not. Restart keeps the halt and the one alert."""
    V6Engine, TESTNET_URL, BinanceREST, NullNotifier, live_settings, JsonStore, BinHV45 = _boot()
    _rest, manual, eng, n, path = _engine(
        out, "case14.json", BinanceREST, TESTNET_URL, V6Engine, NullNotifier, live_settings, JsonStore, BinHV45)
    sym = "DOGEUSDT"
    try:
        eng.startup()
        base = Decimal(eng.meta["start_wallet"])
        anc = eng.meta["restart_gate_anchor"]["t_ms"]
        line = base * Decimal("0.05")
        eng.meta["trades"] = [{"net": "0", "fees": "0", "closed_ms": anc + i, "strategy": "binhv45"} for i in range(1, 5)]
        eng.meta["trades"].append({"net": str(-line), "fees": "0.01", "closed_ms": anc + 5, "strategy": "binhv45"})
        px = _rest.book(sym)["bid"]
        tick = eng.rules[sym].tick_size
        dist = (px * Decimal("0.0075") / tick).quantize(Decimal(1)) * tick
        limit = eng.rules[sym].price(px * Decimal("0.99"), "down")
        assert eng.enter(sym, dist, int(time.time()) * 1000, limit_px=limit) is False
        assert "loss_halt" in eng.blocks and "restart_gate" not in eng.blocks
        assert eng.meta["loss_halt"]["n"] == 5
        assert len([m for m in n.sent if "누적 손실" in m]) == 1
        assert not _rest.open_orders(sym)
        eng.save()
        n2 = NullNotifier()
        eng2 = V6Engine(_rest, eng.cfg, store=JsonStore(path), notifier=n2, strategy=BinHV45())
        eng2.on_bar_close = eng2.bar_guard = lambda *a, **k: None
        eng2.startup()
        assert eng2.meta.get("loss_halt")
        assert eng2.enter(sym, dist, int(time.time()) * 1000 + 1000, limit_px=limit) is False
        assert "loss_halt" in eng2.blocks
        assert not [m for m in n2.sent if "누적 손실" in m]
        # -4.9% on a fresh state file: the check itself must not block, and this branch sends no order.
        n3 = NullNotifier()
        eng3 = V6Engine(_rest, eng.cfg, store=JsonStore(os.path.join(out, "case14-under.json")),
                        notifier=n3, strategy=BinHV45())
        eng3.on_bar_close = eng3.bar_guard = lambda *a, **k: None
        eng3.startup()
        almost = Decimal(eng3.meta["start_wallet"]) * Decimal("0.049")
        a3 = eng3.meta["restart_gate_anchor"]["t_ms"]
        eng3.meta["trades"] = [{"net": "0", "fees": "0", "closed_ms": a3 + i, "strategy": "binhv45"} for i in range(1, 5)]
        eng3.meta["trades"].append({"net": str(-almost), "fees": "0.01", "closed_ms": a3 + 5, "strategy": "binhv45"})
        assert eng3._loss_halt_block() is False and "loss_halt" not in eng3.blocks
        _note(out, "case14 PASS", "base", base, "line", line)
    finally:
        _flatten(manual, lambda *a: _note(out, *a))


def main(argv):
    if len(argv) != 3 or argv[1] not in ("13", "14"):
        print("usage: python -m live_v6.tests.testnet_fault_harness 13|14 OUTDIR", file=sys.stderr)
        return 2
    if not (os.getenv("BINANCE_TESTNET_API_KEY") and os.getenv("BINANCE_TESTNET_API_SECRET")):
        print("BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET are required", file=sys.stderr)
        return 2
    out = argv[2]
    os.makedirs(out, exist_ok=True)
    {"13": case13, "14": case14}[argv[1]](out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
