"""TA G drill helper — TESTNET ONLY. Opens ONE real Binance Futures TESTNET position through the canary bot's own
engine (V6Engine.enter: pre-armed exchange stop first, then the market entry, journaled in the canary state file), so
that the next CI deploy / disconnect drill runs with a real open position whose stop sits on the exchange.

Run by root on the VPS while live_v6-citest is STOPPED, inside the same sandbox as the canary unit:
  systemd-run --wait --pipe --collect -p User=tradebot-ci -p Group=tradebot-ci \
    -p EnvironmentFile=/etc/tradebot/citest.env -E LIVE_V6_NETWORK=testnet -E LIVE_V6_FORBID_MAINNET=1 \
    -E LIVE_V6_STRATEGY=h7t -E LIVE_V6_STATE=/var/lib/live_v6-citest/testnet.json \
    -E LIVE_V6_ALERT_LOG=/var/lib/live_v6-citest/alerts.jsonl -p WorkingDirectory=/opt/tradebot-ci-testnet/app/current \
    -p "InaccessiblePaths=-/etc/tradebot -/var/lib/live_v6-live -/opt/tradebot -/var/log/tradebot -/root" \
    -p ReadWritePaths=/var/lib/live_v6-citest -p ProtectSystem=strict \
    /opt/tradebot-ci-testnet/.venv/bin/python /usr/local/lib/tradebot-ci/drill_testnet_position.py DOGEUSDT
Refuses anything but the testnet URL. Never touches mainnet; prints no keys."""
import json
import os
import sys
from decimal import Decimal

assert os.environ.get("LIVE_V6_NETWORK") == "testnet" and os.environ.get("LIVE_V6_FORBID_MAINNET") == "1", "testnet only"
sys.path.insert(0, os.getcwd())
from live_v6.exchange import TESTNET_URL  # noqa: E402
from live_v6.runner import build  # noqa: E402

sym = sys.argv[1] if len(sys.argv) > 1 else "DOGEUSDT"
rest, eng = build("testnet")
assert rest.base_url.rstrip("/") == TESTNET_URL.rstrip("/"), "not the testnet host"
eng.startup()
px = rest.book(sym)["bid"]
tick = eng.rules[sym].tick_size
dist = (px * Decimal("0.03") / tick).quantize(Decimal(1)) * tick
T = int(eng.now_ms()) // 1000 * 1000
ok = eng.enter(sym, dist, T)
pos = rest.positions(eng.cfg.symbols)[sym]
stops = [{"type": o.get("type"), "side": o.get("side"), "stop": str(o.get("stop_price")), "closePosition": o["close_position"],
          "reduceOnly": o["reduce_only"], "cid": o["client_id"]} for o in rest.open_orders(sym)]
print(json.dumps({"entered": ok, "symbol": sym, "amt": str(pos["amt"]), "entry": str(pos["entry"]), "stop_dist": str(dist),
                  "journal": eng.st["pos"].get(sym, {}).get("cid"), "exchange_orders": stops,
                  "skip_log_tail": eng.meta.get("skip_log", [])[-1:]}, default=str))
sys.exit(0 if ok else 1)
