# H15 logger watchdog grace — 2026-10-26 (KST) — f137e7b (supersedes 4395078 / 8dbcea3 evidence) — OFFLINE ONLY, NOT DEPLOYED

Branch `h15-logger-grace` (based on the deployed `49d347a`). TA decisions 2026-10-26 implemented in `h15_logger/logger.py`.
No VPS change, no deploy, no live bot code touched (`git diff 49d347a..f137e7b --name-only` = README.md, logger.py, tests/test_logger.py + this file).
TA review 2026-10-26 required one fix before deploy approval (see "TA review fix"); done in `f137e7b`. The deploy sha is the **code commit `f137e7b`**; the evidence commit on top of it contains only this file.

## TA review fix (f137e7b)
If `Probe.oom_kills()` returns None **at logger start**, `base_oom` was None and the OOM harm check was silently off for the whole run (fails toward missing harm). Now `Watchdog.start()` raises `Stop` right after reading the baseline → `STOPPED` marker + exit 75, no connection made (same class as the other start-time read failures). A single failed read **during operation** is still skipped (`check()` ignores `oom is None`). Diff vs 8dbcea3: logger.py +2, README +1, tests +24/−2 (`test_oom_unreadable_counter_is_ignored` split in two).

## Why
2026-10-22 (and 10/26): any change of the live bot's MainPID stopped the logger with a `STOPPED` marker + exit 75, so a clean
`systemctl restart live_v6-live` deploy (PID 51227→60556, NRestarts stayed 0) ended collection until ops re-armed it
(gap 2026-10-22 → 2026-10-26 01:24 KST, 4 d 4 h 56 min). Design + rationale: `trade-bot-research/results/h15_logger_restart_2026-10-26.md`.

## Behaviour (TA final)
| event | result |
|---|---|
| bot goes inactive / new MainPID, then `active` again with new PID and **NRestarts unchanged** within **180 s** | survive: re-baseline PID, keep logging, one `bot_restart_rebaseline` row in `gaps.csv` |
| during a pending change | watchdog polls every **5 s** (30 s otherwise) |
| NRestarts rises (systemd crash-restart) | STOP (marker + exit 75) |
| system `oom_kill` counter (`/proc/vmstat`) rises | STOP |
| bot still not active after 180 s (`>=`) | STOP |
| more than 3 clean restarts in 24 h (3 ok, 4th stops; a restart exactly 24 h old no longer counts) | STOP (the 4th row is still written) |
| **at logger start the OOM counter is unreadable** (no baseline) | **STOP (marker + exit 75), no connection made**; one failed read while running is skipped |
| at logger start the bot is not active | retry every 5 s for 180 s, then STOP with marker + exit 75 (TA: marker, not exit 1) |
| unchanged | state unreadable 3×, 2-strike host pressure, data dir > 256 MB, free fs < 2048 MB, own RSS > 60 MB (exit 1) — all still enforced during the grace window |
| unchanged | `h15-logger.service` byte-identical (sha256 `f2fa5230…eb4e`): Nice=19, idle CPU/IO class, CPUWeight=10, CPUQuota=25 %, MemoryMax=100M … (existing unit test asserts them) |

`bot_restart_rebaseline` row: `kind,connect_ts_ms,disconnect_ts_ms,reason` = `bot_restart_rebaseline,<grace start>,<grace end>,pid OLD->NEW; NRestarts n; last_ok_ms X; restarts_24h k`.
start = first sighting of the change (watchdog saw bot not active), or — when a clean restart fell entirely between two 30 s ticks —
the last healthy check (`last_ok_ms`, ≤ 30 s earlier); end = the check that saw the bot active again. Liquidation rows written inside the window are kept
(grace only changes what `Watchdog.check()` returns; ws / tick / OI tasks keep running) → classify the interval as gap vs normal later.
Diff vs 49d347a: logger.py +74/−12 (Caps ×3 fields, `Probe.oom_kills`, `Watchdog`, 2 lines in `Logger`), README watchdog section + 1 ambiguity, tests.

## Offline tests (py3.13 venv, websockets 17.3, pytest 9.1.1, pylint 4.1.3 — `python -m pytest h15_logger/tests -q`)
**64 passed** (4395078/8dbcea3: 63; 49d347a: 39). Replaced: `refuses_start_if_bot_not_active`, `stops_if_live_bot_pid_restarts_or_state_change` (old rule).
Mapping to the required cases:
| case | test |
|---|---|
| 10/22 replay PID 51227→60556 survived | `test_replay_2026_10_22_clean_redeploy_pid_51227_to_60556_is_survived`, `test_clean_redeploy_between_ticks_logger_keeps_running_and_logs_row` (whole Logger) |
| return within grace | `test_bot_returns_inside_grace_with_new_pid_rebaselines_and_returns_to_30s_polling` |
| grace exceeded / 180 s boundary | `test_bot_back_exactly_at_180s_boundary_survives_but_still_down_at_180s_stops`, `test_watchdog_stops_if_live_bot_state_failed_forever`, `test_grace_exceeded_whole_logger_stops_with_marker_exit_75_and_keeps_written_data` |
| NRestarts rise | `test_nrestarts_rise_stops_at_once_even_if_bot_is_active_again[False/True]`, `test_nrestarts_unchanged_is_not_harm`, `test_watchdog_stop_ends_whole_process_with_marker` |
| 24 h cap 3 ok / 4 stops, window boundary | `test_restart_cap_three_in_24h_ok_fourth_stops`, `test_restart_cap_24h_window_boundary[86399/86400/86401]`, `test_fourth_restart_in_24h_stops_whole_logger_with_marker`, `test_two_quick_clean_restarts_each_rebaseline_and_count_twice` |
| OOM counter | `test_oom_counter_rise_stops_equal_does_not`, `test_oom_counter_rise_during_grace_also_stops`, `test_oom_unreadable_counter_during_operation_is_skipped_not_fatal` (was `…_is_ignored`), **`test_start_with_unreadable_oom_counter_stops_with_marker_exit_75`** (new: `Watchdog.start` raises Stop code 75 / reason names the OOM counter; whole `Logger.run()` returns 75, STOPPED marker written, no connection attempted), `test_probe_oom_kills_parses_proc_vmstat`, `test_probe_oom_kills_reads_this_host` |
| start-up with bot inactive | `test_start_bot_inactive_retries_180s_then_stops_with_marker_exit_75`, `test_logger_start_with_bot_inactive_writes_marker_exit_75_after_grace_and_stays_stopped`, `test_start_bot_comes_up_inside_grace_baselines_the_new_pid_without_gaps_row` |
| no data loss during grace (virtual-clock whole-Logger run: bot down ~100 s, every minute row present, each row's count == events sent in that minute) | `test_no_data_lost_during_grace_window_and_gaps_row_has_start_and_end` |
| row has start + end | same test (g0 ≈ 200–235 s, g1 ≈ 300–305 s after start, 0 < g1−g0 < 180 s) + `test_replay_…`, `test_bot_returns_inside_grace_…` |
| 5 s / 30 s polling, pressure/probe-failure still enforced in grace, defaults | `test_watchdog_polls_every_5s_…`, `test_host_pressure_and_caps_are_still_enforced_during_grace`, `test_unreadable_bot_state_3x_still_stops_during_grace`, `test_default_caps_are_the_ta_values` |
| unit file unchanged / low priority | `test_unit_file_priority_caps_and_isolation` (+ sha256 identical to 49d347a) |

## Mutation tests (each mutant applied to logger.py alone, full suite run, then restored; re-run on the final code, suite green 64/64, `git status` clean after)
| mutant | suite result | first failing named tests |
|---|---|---|
| M1a grace 180→120 s | 6 failed / 58 passed | `test_bot_back_exactly_at_180s_boundary_…`, `test_grace_exceeded_whole_logger_stops_…`, `test_start_bot_inactive_retries_180s_…`, `test_default_caps_are_the_ta_values` |
| M1b grace 180→300 s | 6 failed / 58 passed | same six |
| M2a cap `> 3` → `>= 3` | 5 failed / 59 passed | `test_restart_cap_three_in_24h_ok_fourth_stops`, `test_restart_cap_24h_window_boundary[86400-False]`, `test_fourth_restart_in_24h_stops_whole_logger_with_marker` |
| M2b cap value 3→4 | 4 failed / 60 passed | `test_restart_cap_three_in_24h_ok_fourth_stops`, `test_restart_cap_24h_window_boundary[86399-True]`, `test_default_caps_are_the_ta_values` |
| M3a NRestarts `!=` → `==` | 29 failed / 35 passed | `test_nrestarts_rise_stops_at_once_…`, `test_nrestarts_unchanged_is_not_harm`, `test_watchdog_stop_ends_whole_process_with_marker` … (every normal check now stops) |
| M3b NRestarts check removed | 4 failed / 60 passed | `test_nrestarts_rise_stops_at_once_even_if_bot_is_active_again[False/True]`, `test_replay_…`, `test_watchdog_stop_ends_whole_process_with_marker` |
| M4a OOM `>` → `>=` | 29 failed / 35 passed | `test_oom_counter_rise_stops_equal_does_not` (+ everything that runs equal counters) |
| M4b OOM `>` → `<` | 3 failed / 61 passed | `test_oom_counter_rise_stops_equal_does_not`, `test_oom_counter_rise_during_grace_also_stops`, `test_oom_unreadable_counter_during_operation_is_skipped_not_fatal` |
| M4c OOM check removed | 3 failed / 61 passed | same three |
| extra M5 grace expiry `>=` → `>` | 2 failed / 62 passed | `test_bot_back_exactly_at_180s_boundary_…`, `test_watchdog_stops_if_live_bot_state_failed_forever` |
| extra M6 24 h prune `<` → `<=` | 1 failed / 63 passed | `test_restart_cap_24h_window_boundary[86400-False]` |
| extra M7 pending poll 5 s → 30 s | 2 failed / 62 passed | `test_watchdog_polls_every_5s_…`, `test_bot_returns_inside_grace_…` |
| extra M8 start-up grace ignored | 3 failed / 61 passed | `test_start_bot_inactive_retries_180s_…` |
| extra M9 row start = end | 3 failed / 61 passed | `test_no_data_lost_during_grace_window_and_gaps_row_has_start_and_end` |
| extra M10 PID change stops again | 14 failed / 50 passed | `test_replay_2026_10_22_…` |
| **NEW M11 start-time OOM-unreadable check deleted** (`if self.base_oom is None:` → `if False:`) | **1 failed / 63 passed** | **`test_start_with_unreadable_oom_counter_stops_with_marker_exit_75`** (the only failure) |
A first run exposed one hanging test (M3: a logger-level test looped forever when the NRestarts check was mutated); fixed with a sleep-count guard (4395078).

## Hashes (offline)
| file | 49d347a = on the VPS today (read-only check 2026-10-26) | this branch |
|---|---|---|
| `h15_logger/logger.py` | `78fc65c56e683637726cb0d162c88a62b0c02cd912b5597d0a6b7904745b4cc1` | `0428017fb750b3e1e9f407776ca41abd99ae1b88a962fa8fd9ef337bcf3aa2a2` (f137e7b; 4395078 was `c51c2208…9410`, superseded) |
| `h15_logger/deploy/h15-logger.service` | `f2fa5230f93335158e0a6ebf6dd47fdac9823b453fb1242379ddc5f9abd8eb4e` | identical → **no daemon-reload needed** |

## Notes / deviations to review
* OOM check is **global** (`/proc/vmstat oom_kill`): any OOM kill on the host (e.g. an unrelated process) stops the logger; always on, not only in the grace window.
* The restart counter is in memory: a logger restart resets the 24 h count.
* Dropped from my earlier proposal (not in TA's list): "2 stable active reads" before re-baseline and a 600 s post-rebaseline pressure window.
* A bot deploy whose stop→active takes longer than 180 s stops the logger (by design).

## Deploy plan (LATER — TA approved deploy once this fix + evidence are posted; nothing below has been run)
1. **Gate / time**: TA approval of `f137e7b` given. Run outside every 4 h close ±15 min (KST 01/05/09/13/17/21 → no action 00:45–01:15, 04:45–05:15, 08:45–09:15, 12:45–13:15, 16:45–17:15, 20:45–21:15). Never overlap with a live-bot deploy (that would stop the logger only if the bot stays down > 180 s, but keep them apart anyway).
2. **Read-only pre-check** (ops via `/workspace/vps_ops.py`): `systemctl show h15-logger live_v6-live -p ActiveState -p MainPID -p NRestarts`; `cat /opt/h15-logger/RELEASE` = `49d347a`; `sha256sum /opt/h15-logger/app/h15_logger/logger.py` = `78fc65c5…4cc1` and the unit = `f2fa5230…eb4e`; `ls /var/lib/h15-logger` has no `STOPPED`; `grep oom_kill /proc/vmstat` readable; host MemAvailable/PSI normal; note the bot PID/NRestarts.
3. **Build**: `git archive f137e7b h15_logger/logger.py h15_logger/README.md h15_logger/tests/test_logger.py` → tar (record its sha256); upload to `/tmp/h15-grace-f137e7b/` on the VPS (sftp as `ops`); optionally run the 64 offline tests there if pytest exists. Expected `logger.py` sha256 = `0428017fb750b3e1e9f407776ca41abd99ae1b88a962fa8fd9ef337bcf3aa2a2`. (Evidence files are docs only and are not installed.)
4. **Backup**: `cp -a /opt/h15-logger/app /opt/h15-logger/app-49d347a` (root-owned, same convention as `app-36653c2`, `app-77469af`).
5. **Stop**: `systemctl stop h15-logger` (clean SIGTERM, no STOPPED marker; gap = stop→start, recorded by process_stop/connect rows).
6. **Install**: copy `logger.py`, `README.md`, `tests/test_logger.py` from the archive into `/opt/h15-logger/app/h15_logger/` (root:root, modes as existing), `echo f137e7b > /opt/h15-logger/RELEASE`. Unit file untouched, no daemon-reload.
7. **Full sha256 byte comparison**: `sha256sum` of each installed file on the VPS vs `git show f137e7b:<path> | sha256sum` locally — all three must match (`logger.py` = `0428017fb750b3e1e9f407776ca41abd99ae1b88a962fa8fd9ef337bcf3aa2a2`); unit still `f2fa5230…eb4e`. Any mismatch → rollback (9).
8. **Start**: `systemctl start h15-logger`. Verify within 2 min: ActiveState=active, NRestarts=0, journal `watchdog baseline: live bot pid <PID> NRestarts 0 oom_kill <n>` (n must be a number — otherwise the logger stops with the marker by design), `gaps.csv` process_start + connect rows, first `liq/` minute rows, limits read-back unchanged (Nice 19, CPUQuota 25 %, MemoryMax 100M, io idle), bot untouched (same PID/NRestarts), host PSI normal. Re-check after 30 min (RSS, rows continuous, no STOPPED, `quality.csv`).
9. **Rollback** (if anything differs or the logger misbehaves): `systemctl stop h15-logger`; `mv /opt/h15-logger/app /opt/h15-logger/app-f137e7b && mv /opt/h15-logger/app-49d347a /opt/h15-logger/app`; `echo 49d347a > /opt/h15-logger/RELEASE`; verify `logger.py` = `78fc65c5…4cc1`; `systemctl start h15-logger`. Older fallbacks: `app-77469af` (WS fix, without the quality.csv rule), `app-36653c2` (legacy URL, silent — do not use).
10. Post-deploy evidence note appended to this folder; report to TA.
