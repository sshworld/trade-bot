#!/bin/bash
# Detached CI job runner (TA J). Installed ONCE, by hand, to /opt/tradebot/ci/ci_job.sh (root:root 0755).
#   ci_job.sh start <live|testnet> deploy <sha40> <tarfile> [--dry-run]   → prints "JOB <id>" and returns at once
#   ci_job.sh start <live|testnet> rollback [--dry-run]
#   ci_job.sh show  <live|testnet> <id>     → job log + "JOB_STATE running" | "JOB_STATE done rc=<n>"
#   ci_job.sh run   …                       (internal: the body, executed by systemd-run, never by an SSH session)
# The body runs in the transient unit tradebot-ci-<target> (one at a time per target; ci_deploy.sh also takes a
# global flock). Output goes ONLY to /var/log/tradebot/ci-jobs/<target>-<id>.log (+ ci-deploy.log); nothing is tied
# to the SSH session, so a dropped connection cannot kill a deploy half-way, and the failure path (rollback / stop +
# alert) always runs. CI_SIMULATE_* drill variables are passed through for the testnet target only (root use).
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
JOBS=/var/log/tradebot/ci-jobs
DEPLOY=/opt/tradebot/ci/ci_deploy.sh
MODE=${1:-}; TARGET=${2:-}
[[ "$TARGET" =~ ^(live|testnet)$ ]] || { echo "job: bad target" >&2; exit 2; }
mkdir -p "$JOBS"; chmod 750 "$JOBS"

case "$MODE" in
  start)
    shift 2
    ID=$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')
    SIM=()
    if [ "$TARGET" = testnet ]; then
      for v in CI_SIMULATE_VERIFY_FAIL CI_SIMULATE_STOPS_FAIL CI_SIMULATE_ROLLBACK_VERIFY_FAIL CI_STABLE_S CI_PRE_GAP CI_POST_GAP; do
        [ -n "${!v:-}" ] && SIM+=(-E "$v=${!v}")
      done
    fi
    : > "$JOBS/$TARGET-$ID.log"
    if ! systemd-run --quiet --collect --unit="tradebot-ci-$TARGET" -p KillMode=mixed -p TimeoutStopSec=600 \
         "${SIM[@]}" /opt/tradebot/ci/ci_job.sh run "$TARGET" "$ID" "$@" 2>>"$JOBS/$TARGET-$ID.log"; then
      echo "done rc=7" > "$JOBS/$TARGET-$ID.rc"
      echo "job: could not start (another job for $TARGET still running?)" >&2; exit 7
    fi
    echo "JOB $ID" ;;
  run)
    ID=${3:?}; shift 3
    LOG=$JOBS/$TARGET-$ID.log
    rc=0; "$DEPLOY" "$1" "$TARGET" "${@:2}" >>"$LOG" 2>&1 || rc=$?
    cat "$LOG" >> /var/log/tradebot/ci-deploy.log
    # the tarball upload is consumed by this job
    [ "$1" = deploy ] && [ -n "${3:-}" ] && case "$3" in /var/lib/tradebot-ci/uploads/*) rm -f "$3" ;; esac
    echo "done rc=$rc" > "$JOBS/$TARGET-$ID.rc"
    exit "$rc" ;;
  show)
    ID=${3:-}
    [[ "$ID" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$ ]] && [ -f "$JOBS/$TARGET-$ID.log" ] || { echo "job: unknown id" >&2; exit 2; }
    cat "$JOBS/$TARGET-$ID.log"
    if [ -f "$JOBS/$TARGET-$ID.rc" ]; then echo "JOB_STATE $(cat "$JOBS/$TARGET-$ID.rc")"; else echo "JOB_STATE running"; fi ;;
  *) echo "job: bad mode" >&2; exit 2 ;;
esac
