"""python -m live_v6 {run|check|resume|status|tgtest}  (network LIVE_V6_NETWORK, default testnet; strategy
LIVE_V6_STRATEGY = h7t (default) | v6_h7)."""
import json
import sys

from .runner import build, run


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "run"
    if cmd == "tgtest":                          # one real Telegram message (needs both env vars)
        from .notify import Notifier
        from .runner import tg_prefix
        n = Notifier(prefix=tg_prefix())
        if not n.configured:
            sys.exit("missing env: " + ", ".join(n.missing_env()))
        print("sent" if n.send("✅ live_v6 텔레그램 연결 테스트") else "send failed")
        return
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
