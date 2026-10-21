# CI/CD for live_v6 — PROPOSED, pending TA safety review (not on main, not enabled)

Pipeline (`github-workflow-deploy.yml` → to be placed at `.github/workflows/deploy.yml` on main after TA review):
`test` (offline pytest `-m "not testnet and not slow"` + pylint W0101; no secrets) → `resolve` (sha) →
`deploy-testnet` (env `testnet`, canary unit `live_v6-citest`) → `gate` (sha must carry a `ta-pass-*` tag and be on
main) → `deploy-live` (env `live`, required reviewer **sshworld**). Triggers: push to main, push of a `ta-pass-*` tag,
workflow_dispatch(sha). Concurrency group `tradebot-deploy` (never two deploys at once).

## Files
| file | where it runs |
|---|---|
| `github-workflow-deploy.yml` | GitHub Actions |
| `gh_ssh_deploy.sh` | runner: `git archive <sha> live_v6` → ssh stdin, `deploy <sha40> <sha256>` |
| `ci_deploy_entry.sh` | VPS `/opt/tradebot/ci/` — SSH forced command, strict regex on SSH_ORIGINAL_COMMAND |
| `ci_deploy.sh` | VPS `/opt/tradebot/ci/` — deploy / rollback / status |
| `live_v6-citest.service` | VPS — TESTNET canary unit (own app root, state, env; capped CPU/mem) |
| `install_vps_ci.sh` | one-time manual installer (VPS) |
| `../../tools/verify_stops.py` | installed as `/opt/tradebot/ci/verify_stops_testnet.py` |

The VPS copies of `ci_deploy*.sh` are installed by hand and are NOT updated by deploys (pushed code cannot change
the deployer).

## Keys / secrets (GitHub never holds Binance or Telegram keys)
* repo secrets: `VPS_HOST`, `VPS_KNOWN_HOSTS` (pinned ed25519 host key)
* env `live` secret `VPS_SSH_KEY` = box `~/.ssh/tradebot_ci_live`; env `testnet` secret `VPS_SSH_KEY` = `~/.ssh/tradebot_ci_testnet`
* VPS `/root/.ssh/authorized_keys`:
  `command="/opt/tradebot/ci/ci_deploy_entry.sh live|testnet",no-port-forwarding,no-pty,no-agent-forwarding,no-X11-forwarding,no-user-rc`
  — the target is bound to the key; the testnet key cannot touch live.
* `/etc/tradebot/citest.env` (0640 root:tradebot): testnet keys only.

## ci_deploy.sh guarantees
1. Never places orders, never flattens, never touches exchange stops (symlink swap + `systemctl restart` only).
2. Window: ≥15 min after a 4h UTC close and ≥20 min before the next; waits up to 45 min, else refuses (exit 3).
3. `verify-stops` exit 0 required BEFORE restart and BEFORE every rollback, else abort without restart (exit 5).
4. Import check of the staged tree (tick() calls on_bar_close) before anything changes (exit 8).
5. State backup → `/root/ci-backups/<target>/` (last 30 kept).
6. Post-restart: unit active, no restart loop (NRestarts / MainPID stable 45 s), state rewritten after restart,
   `meta.health.ok`, `last_bar_close` = current boundary and all 6 `last_open` = boundary − 4h, no
   Traceback/CRITICAL/모델 재구성 in the journal, stops verified again. Fail → automatic rollback to PREVIOUS (exit 9).
7. Idempotent: same sha current + unit active → no-op. flock: one run at a time.
8. Heartbeat script is NOT installed (runbook §5 stays manual after a verified restart).
9. `CI_SIMULATE_*` drills are refused for the live target.

## Live note
First live rollback target will be `fae64af` (frozen-bar bug: safe, but no entries) — rollback weak-verifies
(active + stable + no Traceback), because fae64af does not write `meta.health`.
