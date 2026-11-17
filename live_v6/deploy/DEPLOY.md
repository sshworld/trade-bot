# Vultr Tokyo 1 GB Ubuntu — run note (NOT deployed)

Prerequisites (§8b): replay match ✅, testnet fault suite ✅, TA safety review, Binance API key **IP-restricted to the
VPS IP, withdrawals OFF, futures only**, 성헌 final OK. Mainnet needs BOTH env flags below, otherwise the client
refuses any non-testnet URL.

```bash
sudo apt update && sudo apt install -y python3-venv git chrony && sudo systemctl enable --now chrony
chronyc tracking                                   # clock offset ≪ 1 s (signed requests, 4h bar timing)
sudo useradd -r -m -d /opt/trade-bot bot && sudo mkdir -p /var/lib/live_v6 && sudo chown bot /var/lib/live_v6
sudo -u bot git clone <repo> /opt/trade-bot && cd /opt/trade-bot && git checkout live-v6
sudo -u bot python3 -m venv .venv && sudo -u bot .venv/bin/pip install httpx websockets
sudo install -m 600 -o bot /dev/null /etc/live_v6.env   # then edit (never commit / echo it):
#   LIVE_V6_NETWORK=testnet                        # mainnet only with LIVE_V6_MAINNET_ACK=real-money
#   BINANCE_TESTNET_API_KEY=…  BINANCE_TESTNET_API_SECRET=…     (mainnet: BINANCE_API_KEY / BINANCE_API_SECRET)
#   TELEGRAM_BOT_TOKEN=…  TELEGRAM_CHAT_ID=…
#   NEVER HEARTBEAT_URL here: it goes only into the external heartbeat_ping.sh env (/etc/tradebot/heartbeat.env);
#   in the bot env the in-process DeadMan would overwrite the external /fail every 60 s (TA review 950438b)
#     (Telegram is only ever used when LIVE_V6_NETWORK=mainnet; testnet writes the would-be messages to
#      LIVE_V6_ALERT_LOG, default /var/lib/live_v6/<network>_alerts.jsonl)
#   LIVE_V6_STRATEGY=h7t
#   LIVE_V6_STATE=/var/lib/live_v6/state.json
sudo -u bot env $(sudo cat /etc/live_v6.env | xargs) .venv/bin/python -m live_v6 check   # read-only: wallet + positions
sudo cp live_v6/deploy/live_v6.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now live_v6 && journalctl -u live_v6 -f
```
Go-live checks (mainnet host): `.venv/bin/python live_v6/tools/ws_check_mainnet.py --minutes 10` (read-only, new
routed ws URLs) and `LIVE_V6_NETWORK=mainnet .venv/bin/python -m live_v6 --telegram-check` (ONE confirmation message).
Operations: `python -m live_v6 status` (halt reason, positions, skips) · `python -m live_v6 resume` clears a halt
after review · testnet first for ≥ 1 full 4h cycle on the VPS · back up `/var/lib/live_v6/state.json`.

# bundle_v5 sizing (drop-in /etc/systemd/system/live_v6-live.service.d/30-strategy-bundle.conf)
#   Environment=LIVE_V6_BUNDLE_RISK_PCT=M:2,D:0,R:0,H:9   # % of the wallet risked per trade by component, 0 = off
#   Environment=LIVE_V6_BUNDLE_MARGIN=pooled              # no per-component margin budget (only with RISK_PCT)
#   Environment=LIVE_V6_BUNDLE_RISK_MULT=3.0              # legacy multiplier - KEEP this line (see below)
#   - Ratios only: no USDT amount is configured; exchange minimums come from the exchange filters.
#   - With RISK_PCT the multiplier is not applied. It stays for rollbacks: ci_deploy.sh switches the code only, and a
#     release from before RISK_PCT ignores it and would otherwise start at the default multiplier 6.
#   - A malformed or empty value refuses to start (never a silent fallback). Check what the process really got:
#       journalctl -u live_v6-live | grep "bundle sizing:"      sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value live_v6-live)/environ | grep BUNDLE
#   - A start with a different sizing than the previous run sends one Telegram notice (best effort).
#   - After a restart the daily store for H is rebuilt in the background minutes (journal: "daily store warm-up done");
#     until then a 00:00 UTC evaluation would block for minutes and its entry would be refused as late.
