"""Summarize a bundle decision JSONL by KST signal day. Input is local and read-only."""
import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

from live_v6.tradelog import KST

DATA_REASONS = {"invalid_minutes", "missing_atr", "missing_mark", "no_data", "no_filters",
                "R_invalid", "D_window", "insufficient_universe"}
ORDERED_STAGES = ("book_skip", "intent", "engine_skip", "submit_attempt", "order_ack", "order_rejected",
                  "order_unknown", "no_fill_observed", "order_unfilled", "fill")
TERMINAL = {"no_fill_observed", "order_unfilled", "order_rejected", "fill"}


def summarize(path, day, *, now=None):
    """Replay records idempotently. An old signal resolved later belongs to its original day."""
    now = now or datetime.now(KST)
    start = int(datetime.combine(day, time.min, tzinfo=KST).timestamp()) // 60
    stop = start + 1440
    # Count only elapsed minutes on an in-progress day.
    expected = max(0, min(stop, int(now.timestamp()) // 60) - start)
    completed, retries, candidates = {}, {}, defaultdict(list)
    invalid = 0
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            try:
                r = json.loads(line)
                minute, stage = r["minute"], r["stage"]
                if not isinstance(minute, int) or not isinstance(stage, str):
                    raise ValueError()
                if not start <= minute < stop:
                    continue
                if stage == "minute_complete":
                    if (not isinstance(r["checks"], list) or not isinstance(r["enabled"], list)
                            or not isinstance(r["schedule"], str) or not isinstance(r["macro_due"], int)
                            or not all(isinstance(c, dict) and isinstance(c.get("comp"), str)
                                       and isinstance(c.get("why"), str) for c in r["checks"])):
                        raise ValueError()
                    completed[minute] = r
                elif stage == "minute_retry":
                    retries[minute] = str(r["reason"])
                elif stage in ORDERED_STAGES and isinstance(r["cid"], str):
                    if r.get("reason") is not None and not isinstance(r["reason"], str):
                        raise ValueError()
                    candidates[r["cid"]].append(r)
            except (KeyError, TypeError, ValueError):
                invalid += 1

    stages, checks, reasons, calendar, d_poll = Counter(), Counter(), Counter(), Counter(), Counter()
    open_intents = []
    scheduled, idle = Counter(), 0
    for r in completed.values():
        minute = r["minute"]
        if "M" in r["enabled"]:
            scheduled["M_macro_events"] += r["macro_due"]
        if "R" in r["enabled"] and minute % 5 == 0:
            scheduled["R_five_minute_windows"] += 1
        if "H" in r["enabled"] and minute % 1440 == 0:
            scheduled["H_daily_windows"] += 1
        d_state = str(r.get("d_last_poll", "unknown"))
        if "D" in r["enabled"]:
            d_poll[d_state] += 1
        if (not r["checks"] and ("M" not in r["enabled"] or r["schedule"] == "loaded")
                and ("D" not in r["enabled"] or d_state == "succeeded")):
            idle += 1
        if "M" in r["enabled"]:
            calendar[r["schedule"]] += 1
        for c in r["checks"]:
            reason = c.get("why") or ""
            if reason in ("announcement", "late_detect"):
                reasons[reason] += 1
                continue
            if reason == "no_filters":
                # This is the final metadata gate after an existing positive signal.
                reasons[reason] += 1
                continue
            phase = ("signal" if c.get("signal") else
                     "data_unavailable" if reason in DATA_REASONS else "no_signal")
            checks[f"{c['comp']}.{phase}"] += 1
            if reason:
                reasons[reason] += 1
    confirmed_orders = 0
    for cid, rows in candidates.items():
        seen = {r["stage"] for r in rows}
        stages.update(seen)
        confirmed_orders += bool(seen.intersection({"fill", "order_ack"}))
        reasons.update({r["reason"] for r in rows if r.get("reason")})
        if seen.intersection({"intent", "submit_attempt", "order_unknown", "order_ack"}) and not seen.intersection(TERMINAL):
            if seen.intersection({"order_ack", "order_unknown", "submit_attempt"}) or "engine_skip" not in seen:
                open_intents.append(dict(cid=cid, stage=rows[-1]["stage"], reason=rows[-1].get("reason")))
    end = start + expected
    return {
        "date_kst": day.isoformat(),
        "elapsed_minutes": expected,
        "completed_minutes": len(completed),
        "unobserved_elapsed_minutes": expected - sum(m < end for m in completed.keys() | retries.keys()),
        "retried_minutes": len(retries),
        "pending_retry_minutes": {str(m): reason for m, reason in retries.items() if m not in completed},
        "macro_calendar_minutes": dict(calendar),
        "announcement_last_poll_on_completed_minutes": dict(d_poll),
        "scheduled_windows_on_completed_minutes": dict(scheduled),
        "completed_minutes_without_check_and_calendar_ok": idle,
        "checks": dict(sorted(checks.items())),
        "distinct_candidates_by_stage": {s: stages[s] for s in ORDERED_STAGES},
        "confirmed_order_candidates": confirmed_orders,
        "observed_reasons": dict(reasons.most_common()),
        "no_terminal_observation": open_intents,
        "invalid_lines_in_input": invalid,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="쌍끌이 평가·주문 단계별 건수 (KST 신호 발생일 기준)")
    p.add_argument("decisions", type=Path, help="예: mainnet_decisions.jsonl")
    p.add_argument("--day", type=date.fromisoformat, default=datetime.now(KST).date())
    args = p.parse_args(argv)
    try:
        report = summarize(args.decisions, args.day)
    except OSError as e:
        p.exit(2, f"관측 파일을 읽을 수 없습니다: {e}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
