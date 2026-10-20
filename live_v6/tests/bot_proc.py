"""Real bot process for the SIGKILL go-live gate (TESTNET only). Opens positions on the given symbols through the
engine, prints READY, then runs the normal tick loop until it is killed. With --kill-mid-entry SYM the process
SIGKILLs ITSELF right after SYM's entry fill (before the closePosition upgrade) — the worst-case instant."""
import os
import signal
import sys
import time

for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "LIVE_V6_NETWORK", "LIVE_V6_MAINNET_ACK"):
    os.environ.pop(k, None)
os.environ["LIVE_V6_FORBID_MAINNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from decimal import Decimal  # noqa: E402

from live_v6.engine import Settings, V6Engine  # noqa: E402
from live_v6.exchange import TESTNET_URL, BinanceREST  # noqa: E402
from live_v6.notify import NullNotifier  # noqa: E402
from live_v6.store import JsonStore  # noqa: E402


class KillAfterEntry:
    def __init__(self, inner, sym):
        self.inner, self.sym = inner, sym

    def __getattr__(self, n):
        fn = getattr(self.inner, n)
        if n != "market":
            return fn

        def market(s, side, qty, cid, reduce_only=False):
            o = fn(s, side, qty, cid, reduce_only)
            if s == self.sym and not reduce_only:
                print("KILLING-SELF", s, flush=True)
                os.kill(os.getpid(), signal.SIGKILL)
            return o
        return market


def main():
    state, syms = sys.argv[1], sys.argv[2].split(",")
    kill_sym = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--kill-mid-entry" else None
    rest = BinanceREST(TESTNET_URL, os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"])
    ex = KillAfterEntry(rest, kill_sym) if kill_sym else rest
    eng = V6Engine(ex, Settings(symbols=("DOGEUSDT", "SOLUSDT", "XRPUSDT"), entry_order=("DOGEUSDT", "SOLUSDT", "XRPUSDT"),
                                cid_prefix="v6t", bootstrap_bars=60, income_interval_s=1e9),
                   store=JsonStore(state), notifier=NullNotifier())
    eng.on_bar_close = lambda *a, **k: None
    eng.startup()
    T = int(time.time()) * 1000
    for i, s in enumerate(syms):
        px = rest.book(s)["bid"]
        tick = eng.rules[s].tick_size
        dist = (px * Decimal("0.03") / tick).quantize(Decimal(1)) * tick
        assert eng.enter(s, dist, T + i * 1000), eng.meta.get("skip_log", [])[-1:]
    print("READY", flush=True)
    while True:
        eng.tick(force_reconcile=False)
        time.sleep(1)


main()
