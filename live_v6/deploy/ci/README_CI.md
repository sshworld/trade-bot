# CI/CD for live_v6 — PROPOSED, pending TA re-review (not on main, not enabled)

Pipeline (`github-workflow-deploy.yml` → to be placed at `.github/workflows/deploy.yml` on main after TA review):
`test` (offline pytest `-m "not testnet and not slow"` + pylint W0101; no secrets) → `resolve` (sha; dispatched sha must
be on main; ref must be main or `ta-pass-*`) → `deploy-testnet` (env `testnet`, canary unit `live_v6-citest`) → `gate`
(sha must carry a `ta-pass-*` tag and be on main) → `deploy-live` (env `live`, required reviewer **sshworld**).
Triggers: push to main, push of a `ta-pass-*` tag, workflow_dispatch(sha). Concurrency group `tradebot-deploy`.
All actions are pinned to commit SHAs (TA I). Commits that predate this pipeline (e.g. 0d82b19) have no
`deploy/ci/` and cannot be deployed by it — they are deployed by hand (DEPLOY.md).

## Files
| file | where it runs |
|---|---|
| `github-workflow-deploy.yml` | GitHub Actions |
| `gh_ssh_deploy.sh` | runner: `git archive <sha> live_v6` → ssh stdin `deploy <sha40> <sha256>` → `JOB <id>`; then polls `job <id>` |
| `ci_deploy_entry.sh` | VPS `/opt/tradebot/ci/` — SSH forced command, strict regex on SSH_ORIGINAL_COMMAND |
| `ci_job.sh` | VPS `/opt/tradebot/ci/` — starts the body detached (`systemd-run --collect`, unit `tradebot-ci-<target>`) |
| `ci_deploy.sh` | VPS `/opt/tradebot/ci/` — deploy / rollback / status body |
| `live_v6-citest.service` | VPS — TESTNET canary unit (user `tradebot-ci`, own app root/venv/state/env, capped) |
| `install_vps_ci.sh` | one-time manual installer / upgrader (VPS) |
| `../../tools/verify_stops.py` | installed as `/opt/tradebot/ci/verify_stops_testnet.py` |
| `drill_testnet_position.py` | VPS `/usr/local/lib/tradebot-ci/` — TA G drill: one real TESTNET position via the canary engine (testnet only) |
| `../../tools/verify_stops_live.py` | installed as `/opt/tradebot/verify_stops_live.py` (TA D; test: `tests/test_verify_stops_live.py`) |

The VPS copies of `ci_*.sh` and the verify scripts are installed by hand from a reviewed commit and are NOT updated
by deploys (pushed code cannot change the deployer).

## Approvals (TA C) — rule
* A live deploy is approved **only by 성헌 (sshworld), by hand, in the GitHub UI** ("Review deployments" on the run).
* **No bot ever approves a deployment**: no bot calls `POST /repos/…/actions/runs/{id}/pending_deployments`, the
  `gh run`/`gh api` equivalent, or clicks "Approve" in a browser — even though the bots push with a token of the
  sshworld account and the API would accept it. A bot that is asked to approve refuses and points to this rule.
* `ta-pass-*` tags are created by 성헌 (or on his explicit instruction for a specific sha that TA passed in writing).
* Environment `live`: `can_admins_bypass=false` (an admin token cannot skip the reviewer), `prevent_self_review=false`
  (must stay false while 성헌 is both the pusher and the only reviewer).
* Separate GitHub account for the bots: recommended by TA — **성헌's call** (only he can create it). Until then the
  ruleset below cannot technically stop a bot, because the bots act as the admin sshworld; the rule above is what
  binds them.

## GitHub settings (applied 2026-10-21, see evidence/)
* Ruleset `ta-pass-tags` (TA A): target tags `refs/tags/ta-pass-*`, rules creation + update + deletion +
  non_fast_forward; bypass = Repository admin only (= sshworld).
* Environments `testnet` and `live` (TA B): deployment ref policy = custom, `main` (branch) + `ta-pass-*` (tag) only, so
  a workflow_dispatch from any other branch cannot obtain `VPS_SSH_KEY`; the deploy jobs and `resolve` also refuse other
  refs. `live`: required reviewer sshworld, admin bypass off.
* Secrets (TA F): repo secrets `VPS_HOST`, `VPS_KNOWN_HOSTS` only; `VPS_SSH_KEY` exists ONLY as an environment secret
  (`live` = box `~/.ssh/tradebot_ci_live`, `testnet` = `~/.ssh/tradebot_ci_testnet`). There must never be a repo-level
  `VPS_SSH_KEY` (it would be the fallback when an environment has none).

## VPS SSH (TA F)
* `/root/.ssh/authorized_keys` CI lines:
  `restrict,command="/opt/tradebot/ci/ci_deploy_entry.sh live" ssh-ed25519 … tradebot_ci_live` (and `… testnet`).
  The target is bound to the key; the testnet key cannot touch live.
* sshd (`/etc/ssh/sshd_config.d/00-tradebot.conf`): `PermitRootLogin forced-commands-only`, `PasswordAuthentication no`.
  Root can only run the forced commands. Administration = user **`ops`** (box key `~/.ssh/tradebot_vps.pub`,
  passwordless sudo): `ssh ops@VPS`, then `sudo …` (e.g. emergency stop `sudo systemctl stop live_v6-live`).
  Fallback if SSH is ever broken: Vultr web console.
* `/etc/tradebot/citest.env` (0640 root:tradebot-ci): testnet keys only. `/etc/tradebot/ci-alert-testnet.env`: a
  DUMMY `HEARTBEAT_URL` (local listener) so testnet drills never touch the live Healthchecks check.

## ci_deploy.sh guarantees
1. Never places orders, never flattens, never touches exchange stops (symlink swap + `systemctl restart`/`stop` only).
2. Window for PLANNED restarts (deploy, manual rollback): ≥15 min after a 4h UTC close and ≥20 min before the next;
   waits up to 45 min, else refuses (exit 3). The automatic reaction to a failed deploy never waits (TA E).
3. `verify-stops` exit 0 required BEFORE restart and BEFORE every rollback, else no restart (deploy: exit 5, nothing
   changed; failure path: stop + alert, exit 5).
4. Archive: regular files/dirs only (symlinks, hardlinks, devices refused), paths under `live_v6/`, no `..`.
5. Import check of the staged tree (tick() calls on_bar_close) in a transient sandbox before anything changes
   (exit 8): testnet = user `tradebot-ci` + canary venv, live = user `tradebot`; both no network, ProtectSystem=strict,
   `/etc/tradebot`, live state, `/opt/tradebot/app`, logs, `/root` inaccessible (TA K).
6. `TimeoutStopSec` of the unit checked (≥20 s, live = 30 s); no restart while `state.intents` is non-empty (waits
   30 s × 10, then refuses, exit 11).
7. State backup → `/root/ci-backups/<target>/` (last 30 kept). Releases in `$APP/<sha40>`, root-owned, read-only.
8. Strict post-restart verification (deploy AND rollback): unit active, no restart loop (NRestarts / MainPID stable
   45 s), state rewritten after restart, fresh `meta.health.ok`, `last_bar_close` = current boundary and all 6
   `last_open` = boundary − 4h, no Traceback/CRITICAL/모델 재구성 in the journal, stops verified again.
9. Pass → only `<marker>.pending` (TA R1; marker = `live`: `$APP/<release>/.ta_pass_verified`, testnet:
   `.citest_verified`). The marker itself is granted by the root timer `tradebot-ci-confirm.timer` (4h close + 5 min,
   `ci_deploy.sh confirm <target>`) once the FIRST REAL 4h close after the restart was processed: same MainPID and
   NRestarts as at deploy, `last_bar_close` = that close, all 6 `last_open` = close − 4h, fresh health, clean journal,
   stops verified. Otherwise the pending marker is revoked + `/fail` (the bot is not stopped by confirm). Until the
   marker exists the rollback target stays the previous marked release. A live deploy only happens for a
   gate-approved `ta-pass-*` commit after 성헌's approval, so the live marker = "TA PASS + live-verified + one real close".
10. Fail → **rollback only to the newest release whose marker is valid** (root-owned, sha matches dir), strictly
    verified → exit 9 + Healthchecks /fail notice. No marked release (exit 10), stops not verified (exit 5) or rollback
    not verified (exit 6) → `systemctl stop <unit>` + Healthchecks `/fail` (URL from the env file, never printed) +
    log + `CI_HALTED` file + non-zero exit (GitHub job fails). Exchange stops stay; nothing is closed (TA H).
    A rollback target that fails its own verification has its marker revoked too (TA R3): marker moved to
    `<marker>.revoked-<ts>`, reason appended to `.ta_pass_revoked` / `.citest_revoked`; only a fresh verified deploy
    (and its first real close) marks it again.
11. Idempotent: same full sha current + unit active → no-op. flock + one transient unit per target: one run at a time.
12. Detached (TA J): body runs in `systemd-run --collect` with output to `/var/log/tradebot/ci-jobs/<target>-<id>.log`;
    a dropped SSH session only stops the client's polling.
13. Heartbeat script is NOT installed (runbook §5 stays manual). `CI_SIMULATE_*` drills are refused for live.

## Live note (TA H)
Live releases on the VPS today: `0d82b19` (current, hand-deployed 2026-10-21 10:07:55 KST, `.ta_pass_verified`
present, tag `ta-pass-0d82b19`), `fae64af`, `93f208c`, `c3f6ee2` (no marker). The first CI live deploy therefore rolls
back only to `0d82b19`; `fae64af` (frozen-bar bug) can never be a rollback target. If 0d82b19 itself were the failing
release, the bot is stopped and /fail is sent instead.
After a CI halt the unit cannot start (TA R2): `ExecStartPre=+…` refuses while `$APP/CI_HALTED` exists — on `systemctl
start`, on `Restart=always` retries (every 10 s, each refused) and after a reboot. Live gets this via the drop-in
`/etc/systemd/system/live_v6-live.service.d/10-ci-halt-guard.conf` (installed with daemon-reload only; effective from
the next start). CI deploy/rollback refuse while halted (exit 13). CI never removes `CI_HALTED`. Ops recovery:
`sudo systemctl stop <unit>` (ends the retry loop) → investigate → `sudo rm <app>/CI_HALTED` → CI rollback/deploy.
Existing live marker on 0d82b19 predates R1 (hand deploy 10:07:55 KST); the same process (PID 12861) has since
processed the real 13:00 KST close for all 6 coins (status 13:16 KST: last_bar_close = boundary).
