"""python -m live_v6 {run|check|resume|status|--telegram-check}  (network LIVE_V6_NETWORK, default testnet; strategy
LIVE_V6_STRATEGY = h7t (default) | v6_h7)."""
import json
import sys

from .runner import build, run


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "run"
    if cmd in ("--telegram-check", "telegram-check"):   # go-live: ONE real confirmation message, live mode only
        from .runner import make_notifier, telegram_check
        sys.exit(telegram_check(make_notifier()))
    if cmd == "run":
        run()
    elif cmd == "check":                         # read-only: account + positions, never orders
        rest, eng = build()
        a = rest.account()
        print(json.dumps({"network": rest.base_url, "wallet": str(a["wallet"]), "available": str(a["available"]),
                          "positions": {s: str(p["amt"]) for s, p in rest.positions(eng.cfg.symbols).items()}}))
    elif cmd == "resume":
        _, eng = build()
        eng.resume()
        print("halt cleared")
    elif cmd == "status":
        _, eng = build()
        print(json.dumps({"halted": eng.meta.get("halted"), "positions": eng.st["pos"],
                          "skips": eng.meta.get("skips", {})}, indent=1, default=str))
    else:
        sys.exit(__doc__)


main(sys.argv)
