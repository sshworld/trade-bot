# 2026-10-21 needrestart: no automatic service restarts (TA OK 15:50 KST)

## Incident
- 15:23 KST (06:23 UTC) unattended-upgrades installed security updates `ca-certificates liblzma5 xz-utils`.
- needrestart then restarted services linking liblzma, including `live_v6-live` (PID 12861 -> 36258) and `live_v6-citest` (-> 36250). NRestarts stayed 0 (clean stop/start, not a crash).
- No positions or open orders at the time; no loss. State /var/lib/live_v6-live/mainnet.json: start_wallet 117.46733957, net_transfers 0, halted none, pos {}.

## Change (applied 15:5x KST)
New file `/etc/needrestart/conf.d/90-tradebot.conf` (before: absent, needrestart defaults):
```
$nrconf{restart} = "l";                        # before: default (restarts in unattended runs); after: list only
$nrconf{override_rc}{qr(^live_v6)} = 0;        # never restart bot units
$nrconf{override_rc}{qr(^heartbeat-ping)} = 0;
$nrconf{override_rc}{qr(^tradebot)} = 0;
$nrconf{override_rc}{qr(^ci-)} = 0;
```
`perl -c` syntax OK; `needrestart -b` lists pending (dbus, systemd-logind, unattended-upgrades) without restarting. Bot PIDs unchanged after the change (live 36258, citest 36250, NRestarts 0).

Checked, unchanged: `/etc/apt/apt.conf.d/52tradebot-unattended` already sets `Unattended-Upgrade::Automatic-Reboot "false";` and security-only origins.

## Ops rule
Patches that need a restart are applied by ops by hand, never within 15 min of a 4h close (KST 01/05/09/13/17/21). If a position is open, after the restart confirm the exchange stop (STOP_MARKET, MARK_PRICE, closePosition) still exists and matches the state file, then post one line in the room.
