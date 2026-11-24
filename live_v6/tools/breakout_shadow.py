"""Forward-only paper study of spot-led and futures-led breakouts. No account or order endpoints.

    python -m live_v6.tools.breakout_shadow collect --db shadow.sqlite3 --symbols BTCUSDT ETHUSDT
    python -m live_v6.tools.breakout_shadow report --db shadow.sqlite3
    python -m live_v6.tools.breakout_shadow export --db shadow.sqlite3 > observations.jsonl
    python -m live_v6.tools.breakout_shadow replay --db research.sqlite3 --input observations.jsonl

Public top-of-book snapshots, not historical candles. First observation per UTC minute, 20 consecutive
prior minutes, next-minute entry. Two exit policies share each entry, a 1 USDT initial stop-risk unit,
and the same observed costs. No portfolio compounding, exchange minimum-lot or queue-fill simulation.
Rules and cutoffs are research hypotheses frozen under RULE. Reports replay the immutable raw ledger.
"""
import argparse
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCHEMA = 1
RULE = "paired-breakout-v1"
MINUTE = 60000
LOOKBACK = 20
FEE = 0.0005
SLIP = 0.0002
SYMBOL = re.compile(r"[A-Z0-9]{2,22}USDT\Z")
SPOT = "https://api.binance.com/api/v3"
PERP = "https://fapi.binance.com/fapi/v1"


def utc_ms():
    return time.time_ns() // 1_000_000


def get_json(url):
    with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=8) as response:
        return json.load(response)


def finite_num(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite market observation")
    return number


def collect_one(symbol, get=get_json, clock=utc_ms):
    """Record local request window, exchange timestamps, both sides and their displayed quantities."""
    started = clock()
    query = "?" + urlencode({"symbol": symbol})
    sources = {
        "spot": SPOT + "/ticker/bookTicker" + query,
        "perp": PERP + "/ticker/bookTicker" + query,
        "oi": PERP + "/openInterest" + query,
        "mark": PERP + "/premiumIndex" + query,
        "funds": PERP + "/fundingRate" + query + "&limit=2",
    }
    def fetch(url):
        return get(url), clock()

    row = {"schema": SCHEMA, "symbol": symbol, "started_ms": started}
    source = None
    try:
        with ThreadPoolExecutor(max_workers=len(sources)) as workers:
            futures = {name: workers.submit(fetch, url) for name, url in sources.items()}
            values = {}
            for source, future in futures.items():
                values[source] = future.result()
        receipts = {name: item[1] for name, item in values.items()}
        row["receipts_ms"] = receipts
        for source in ("spot", "perp"):
            q = values[source][0]
            if q["symbol"] != symbol:
                raise ValueError("quote_symbol")
            row[source] = {k: finite_num(q[v]) for k, v in (
                ("bid", "bidPrice"), ("ask", "askPrice"), ("bid_qty", "bidQty"), ("ask_qty", "askQty"))}
        source = "derivatives"
        oi, mark, funds = (values[k][0] for k in ("oi", "mark", "funds"))
        if oi["symbol"] != symbol or mark["symbol"] != symbol or any(f["symbol"] != symbol for f in funds):
            raise ValueError("market_symbol")
        row.update(perp_ms=int(values["perp"][0]["time"]), oi=finite_num(oi["openInterest"]),
                   oi_ms=int(oi["time"]), mark_ms=int(mark["time"]), next_funding_ms=int(mark["nextFundingTime"]),
                   settlements=[{"ms": int(f["fundingTime"]), "rate": finite_num(f["fundingRate"]),
                                 "mark": finite_num(f["markPrice"])} for f in funds])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        row["error"] = f"public_fetch_{type(exc).__name__}"
        row["source"] = source
        if getattr(exc, "code", None) is not None:
            row["http_status"] = exc.code
    row["received_ms"] = clock()
    return row


def check_envelope(row):
    if not isinstance(row, dict) or row.get("schema") != SCHEMA:
        raise ValueError("unsupported observation schema")
    if not SYMBOL.fullmatch(str(row.get("symbol", ""))):
        raise ValueError("invalid USDⓈ-M symbol")
    for key in ("received_ms", "started_ms"):
        if type(row.get(key)) is not int or row[key] <= 0:
            raise ValueError(f"invalid {key}")


def quality(row):
    if row.get("error"):
        return "public_feed_error"
    now = row["received_ms"]
    try:
        if not 0 <= now - row["started_ms"] <= 8000:
            return "snapshot_skew"
        receipts = row["receipts_ms"]
        if not all(row["started_ms"] <= receipts[k] <= now for k in ("spot", "perp", "oi", "mark", "funds")):
            return "receipt_time"
        for src, key, limit in (("perp", "perp_ms", 8000), ("mark", "mark_ms", 15000), ("oi", "oi_ms", 90000)):
            if not -1000 <= receipts[src] - row[key] <= limit:
                return f"stale_exchange_{src}"
        for market in ("spot", "perp"):
            q = row[market]
            if not all(math.isfinite(q[k]) and q[k] > 0 for k in ("bid", "ask", "bid_qty", "ask_qty")):
                return "bad_quote"
            if not q["bid"] <= q["ask"] <= q["bid"] * 1.001:
                return "crossed_or_wide"
        funds = row["settlements"]
        if not math.isfinite(row["oi"]) or row["oi"] <= 0 or not isinstance(funds, list) or not funds:
            return "missing_derivatives"
        if any(type(f["ms"]) is not int or f["ms"] > receipts["funds"] or not math.isfinite(f["rate"])
               or not math.isfinite(f["mark"]) or f["mark"] <= 0 for f in funds):
            return "bad_settlement"
        if not 0 <= now - max(f["ms"] for f in funds) <= 24 * 3600_000:
            return "stale_funding"
        if type(row["next_funding_ms"]) is not int or not 0 < row["next_funding_ms"] - now <= 24 * 3600_000:
            return "funding_rollover"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "malformed_market_data"
    return None


def mid(row, market):
    q = row[market]
    return (q["bid"] + q["ask"]) / 2


@dataclass
class Setup:
    side: int
    level: float
    spot_level: float
    peak: float
    born: int
    tier: str
    phase: str = "breakout"


@dataclass
class Leg:
    policy: str
    side: int
    entry: float
    stop: float
    original_stop: float
    qty: float
    remaining: float
    target_r: float
    fraction: float
    best: float
    pnl: float
    took: bool = False
    done: bool = False

    def fill(self, qty, px):
        self.pnl += qty * (self.side * (px - self.entry) - FEE * px)
        self.remaining -= qty
        self.done = self.remaining <= self.qty * 1e-10

    def observe(self, row, age):
        q = row["perp"]
        px = q["bid"] if self.side > 0 else q["ask"]
        size = q["bid_qty"] if self.side > 0 else q["ask_qty"]
        executable = px * (1 - self.side * SLIP)
        distance = abs(self.original_stop - self.entry)
        self.best = max(self.best, px) if self.side > 0 else min(self.best, px)
        if self.side * (px - self.stop) <= 0 or age >= 60:
            if size < self.remaining:
                return "insufficient_exit_depth"
            self.fill(self.remaining, executable)
            return "stop" if self.side * (px - self.stop) <= 0 else "time"
        if not self.took and self.side * (px - self.entry) >= self.target_r * distance:
            cut = self.qty * self.fraction
            if size < cut:
                return "insufficient_exit_depth"
            self.fill(cut, executable)
            self.took = True
        if self.took:
            # Fee-aware breakeven and two initial risk distances behind the best observed quote.
            breakeven = self.entry * (1 + self.side * FEE) / (1 - self.side * FEE)
            levels = (self.stop, breakeven, self.best - self.side * 2 * distance)
            self.stop = (max if self.side > 0 else min)(levels)
        return None


@dataclass
class Cohort:
    setup: Setup
    entered: int
    last_ms: int
    next_funding: int
    legs: list


def enter(setup, row):
    side, q = setup.side, row["perp"]
    entry = (q["ask"] if side > 0 else q["bid"]) * (1 + side * SLIP)
    stop = setup.level * 0.997 if side > 0 else setup.peak * 1.001
    if side * (entry - stop) <= 0:
        return None, "invalidated_before_entry"
    distance = abs(entry - stop)
    stop_fill = stop * (1 - side * SLIP)
    qty = 1 / (abs(entry - stop_fill) + FEE * (entry + stop_fill))
    if qty > (q["ask_qty"] if side > 0 else q["bid_qty"]):
        return None, "insufficient_entry_depth"
    if distance / entry > 0.05:
        return None, "stop_too_wide"
    # Two paired exits on the same hypothetical exposure, never sum their PnL.
    policies = (("common", 1., .5), ("setup_specific", 2., .25) if side > 0 else ("setup_specific", .75, .65))
    legs = [Leg(name, side, entry, stop, stop, qty, qty, r, part, entry, -FEE * entry * qty)
            for name, r, part in policies]
    return Cohort(setup, row["received_ms"] // MINUTE, row["received_ms"], row["next_funding_ms"], legs), None


def start(history, row):
    level = max(mid(p, "perp") for p in history)
    spot_level = max(mid(p, "spot") for p in history)
    px = mid(row, "perp")
    future = px / level - 1
    spot = mid(row, "spot") / spot_level - 1
    if future < .001:
        return None
    minute = row["received_ms"] // MINUTE
    if spot >= .001 and spot >= future - .0002:
        return Setup(1, level, spot_level, px, minute, "strong" if spot - future >= .001 else "normal")
    oi_gain = row["oi"] / history[0]["oi"] - 1
    rate = max(row["settlements"], key=lambda item: item["ms"])["rate"]
    if future - spot >= .001 and oi_gain >= .002 and rate > 0:
        return Setup(-1, level, spot_level, px, minute,
                     "strong" if oi_gain >= .005 and future - spot >= .002 else "normal")
    return None


def advance(setup, row):
    """Each return/retest/confirmation requires a later observation, then a separate executable quote."""
    px, spot = mid(row, "perp"), mid(row, "spot")
    level = setup.level
    if row["received_ms"] // MINUTE - setup.born > 8:
        return "expired"
    setup.peak = max(setup.peak, px)
    if setup.side > 0:
        if px < level * .997 or spot < setup.spot_level * .997:
            return "invalidated"
        if setup.phase == "breakout" and px <= level * 1.0008:
            setup.phase = "retest"
        elif setup.phase == "retest" and px >= level * 1.001 and spot >= setup.spot_level * 1.001:
            return "confirmed"
    else:
        if spot >= setup.spot_level * 1.002:
            return "invalidated"
        if setup.phase == "breakout" and px <= level * .999:
            setup.phase = "below"
        elif setup.phase == "below" and px >= level * .9998:
            setup.phase = "retest"
        elif setup.phase == "retest" and px <= level * .999:
            return "confirmed"
    return "waiting"


@dataclass
class Series:
    history: deque = field(default_factory=lambda: deque(maxlen=LOOKBACK))
    minute: int = -1
    last_ms: int = 0
    last_issue: str | None = None
    setup: Setup | None = None
    cohort: Cohort | None = None
    next_entry: bool = False


def leg_record(symbol, cohort, leg, status, exit_ms=None):
    return dict(symbol=symbol, event_minute=cohort.setup.born, cluster=cohort.setup.born // 15,
                entry_minute=cohort.entered, side="long" if leg.side > 0 else "short",
                tier=cohort.setup.tier, policy=leg.policy, status=status,
                net_R=round(leg.pnl, 8) if leg.done else None, tp1_hit=leg.took, exit_ms=exit_ms,
                reached_1R=leg.side * (leg.best - leg.entry) >= abs(leg.original_stop - leg.entry))


def update_legs(symbol, cohort, row, trades):
    now = row["received_ms"]
    # All legs censored if the originally announced settlement became due but is missing.
    settlements = {f["ms"]: f for f in row["settlements"] if cohort.last_ms < f["ms"] <= now}
    # Some settlement records timestamp the matching millisecond just after the scheduled boundary.
    if cohort.next_funding <= now and not any(abs(ts - cohort.next_funding) <= 1000 for ts in settlements):
        return "missing_settlement"
    for leg in cohort.legs:
        if leg.done:
            continue
        for f in settlements.values():
            leg.pnl -= leg.side * leg.remaining * f["rate"] * f["mark"]
        outcome = leg.observe(row, now // MINUTE - cohort.entered)
        if outcome == "insufficient_exit_depth":
            return outcome
        if leg.done:
            trades.append(leg_record(symbol, cohort, leg, outcome, now))
    cohort.last_ms = now
    cohort.next_funding = row["next_funding_ms"]
    return None


def paired_exit_results(trades):
    """Complete pairs only; censored/open pairs remain visible, never silently fill them with zeros."""
    pairs = defaultdict(dict)
    for trade in trades:
        pairs[(trade["side"], trade["symbol"], trade["event_minute"])][trade["policy"]] = trade
    results = []
    for side in ("long", "short"):
        buckets = defaultdict(list)
        unresolved = 0
        for (direction, _, _), pair in pairs.items():
            if direction != side:
                continue
            common, specific = pair["common"], pair["setup_specific"]
            if common["net_R"] is None or specific["net_R"] is None:
                unresolved += 1
            else:
                buckets[common["cluster"]].append(specific["net_R"] - common["net_R"])
        means = [sum(values)/len(values) for values in buckets.values()]
        results.append(dict(side=side, completed_pairs=sum(map(len, buckets.values())), event_windows=len(means),
                            unresolved_pairs=unresolved, setup_minus_common_net_R=round(sum(means)/len(means), 5)
                            if means else None))
    return results


def study(rows, latest=None):
    markets, counters, trades = defaultdict(Series), Counter(), []
    def reset(symbol, s, reason):
        if s.cohort:
            for leg in s.cohort.legs:
                if not leg.done:
                    trades.append(leg_record(symbol, s.cohort, leg, "censored_" + reason))
        if s.setup:
            counters["setup_lost_" + reason] += 1
        s.setup, s.cohort, s.next_entry = None, None, False
        s.history.clear()

    for row in rows:
        symbol = row["symbol"]
        s = markets[symbol]
        minute = row["received_ms"] // MINUTE
        if minute == s.minute:
            counters["extra_same_minute"] += 1
            continue
        if s.minute >= 0 and minute != s.minute + 1:
            counters["gap_resets"] += 1
            reset(symbol, s, "gap")
        s.minute = minute
        bad = quality(row)
        s.last_ms, s.last_issue = row["received_ms"], bad
        if bad:
            counters[bad] += 1
            if bad == "public_feed_error" and row.get("source"):
                counters["feed_error_" + str(row["source"])] += 1
            reset(symbol, s, bad)
            continue
        counters["valid_minutes"] += 1
        if s.cohort:
            issue = update_legs(symbol, s.cohort, row, trades)
            if issue:
                counters[issue] += 1
                reset(symbol, s, issue)
            elif all(leg.done for leg in s.cohort.legs):
                s.cohort = None
        elif s.next_entry:
            s.cohort, fail = enter(s.setup, row)
            counters[fail or "entries"] += 1
            s.setup, s.next_entry = None, False
        elif s.setup:
            action = advance(s.setup, row)
            if action == "confirmed":
                counters["confirmed"] += 1
                s.next_entry = True
            elif action != "waiting":
                counters[action] += 1
                s.setup = None
        elif len(s.history) == LOOKBACK:
            s.setup = start(s.history, row)
            counters[("armed_long" if s.setup.side > 0 else "armed_short") if s.setup else "no_setup"] += 1
        else:
            counters["warmup_minutes"] += 1
        s.history.append(row)
    for symbol, s in markets.items():
        if s.cohort:
            trades.extend(leg_record(symbol, s.cohort, leg, "open") for leg in s.cohort.legs if not leg.done)
        if latest is not None:
            if s.last_issue:
                phase = s.last_issue
            elif s.cohort:
                phase = "paper_position"
            elif s.next_entry:
                phase = "await_next_quote"
            elif s.setup:
                phase = s.setup.phase
            else:
                phase = "warming_up" if len(s.history) < LOOKBACK else "watching"
            latest[symbol] = dict(last_minute_snapshot_ms=s.last_ms, lookback_samples=len(s.history), phase=phase)
    return counters, trades


def closed_drawdown(closed):
    """Peak to trough of cumulative closed net R; simultaneous closes form one observation."""
    if not closed:
        return None
    changes = defaultdict(float)
    for trade in closed:
        changes[trade["exit_ms"]] += trade["net_R"]
    equity = peak = worst = 0.0
    for when in sorted(changes):
        equity += changes[when]
        peak = max(equity, peak)
        worst = max(worst, peak - equity)
    return round(worst, 5)


def summarize(rows, details=False):
    latest = {}
    counters, trades = study(rows, latest)
    groups = []
    for policy in ("common", "setup_specific"):
        for side in ("long", "short"):
            for tier in ("normal", "strong"):
                subset = [t for t in trades if (t["policy"], t["side"], t["tier"]) == (policy, side, tier)]
                closed = [t for t in subset if t["net_R"] is not None]
                clusters = defaultdict(list)
                for t in closed:
                    clusters[t["cluster"]].append(t["net_R"])
                cluster_means = [sum(values) / len(values) for values in clusters.values()]
                groups.append(dict(policy=policy, side=side, tier=tier, closed=len(closed),
                                   event_windows=len(clusters), open=sum(t["status"] == "open" for t in subset),
                                   censored=sum(t["status"].startswith("censored_") for t in subset),
                                   tp1_then_loss=sum(t["tp1_hit"] and t["net_R"] < 0 for t in closed),
                                   reached_1R_then_loss=sum(t["reached_1R"] and t["net_R"] < 0 for t in closed),
                                   closed_drawdown_R=closed_drawdown(closed),
                                   worst_net_R=min((t["net_R"] for t in closed), default=None),
                                   cluster_mean_net_R=round(sum(cluster_means)/len(cluster_means), 5) if clusters else None))
    comparisons = []
    for normal, strong in zip(groups[::2], groups[1::2]):
        sufficient = min(normal["event_windows"], strong["event_windows"]) >= 30
        complete = not (normal["censored"] or strong["censored"] or normal["open"] or strong["open"])
        diff = None
        if normal["closed"] and strong["closed"]:
            diff = round(strong["cluster_mean_net_R"] - normal["cluster_mean_net_R"], 5)
        comparisons.append(dict(policy=normal["policy"], side=normal["side"],
                                strong_minus_normal_net_R=diff,
                                status="insufficient_windows" if not sufficient else
                                       "unresolved_paths" if not complete else "descriptive_only"))
    result = dict(rule=RULE, counts=dict(counters), latest=latest, equal_stop_risk_usdt=1, taker_fee_bps=FEE*10000,
                  adverse_slippage_bps=SLIP*10000, event_window_minutes=15, groups=groups,
                  strength_comparisons=comparisons, paired_exits=paired_exit_results(trades),
                  note="First sampled quote of each minute only; intraminute stops, gaps, queue position, lot filters "
                       "and actual fills are unobserved. This is not a portfolio equity curve. "
                       "Shared 15-minute windows are counted once per group. "
                       "Windows may remain correlated. Compare paired exits separately. Censored paths have unknown "
                       "PnL. Each tier needs 30 closed windows for descriptive review. No live sizing decision.")
    if details:
        result["trades"] = trades
    return result


def connect(path, purpose):
    conn = sqlite3.connect(path, timeout=15)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), purpose TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS observations (ms INTEGER, symbol TEXT, body TEXT, PRIMARY KEY(ms,symbol))")
            conn.execute("INSERT OR IGNORE INTO metadata VALUES(1,?)", (purpose,))
            if conn.execute("SELECT purpose FROM metadata").fetchone()[0] != purpose:
                raise ValueError("use separate databases for collected and replayed observations")
        return conn
    except BaseException:
        conn.close()
        raise


def store(conn, row):
    check_envelope(row)
    doc = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
    key = row["received_ms"], row["symbol"]
    inserted = conn.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?)", (*key, doc)).rowcount
    if not inserted and conn.execute("SELECT body FROM observations WHERE ms=? AND symbol=?", key).fetchone()[0] != doc:
        raise ValueError("conflicting observation for existing timestamp and symbol")
    return inserted


def read_rows(conn):
    return (json.loads(row[0]) for row in conn.execute("SELECT body FROM observations ORDER BY ms,symbol"))


def brief_report(result):
    counts = result["counts"]
    source = "공개 실시간 관측" if result["source"] == "public_forward" else "입력 자료 재생"
    lines = [f"쌍끌이 모의 연구 · {source} · {result['rule']}",
             f"유효 종목·분 {counts.get('valid_minutes', 0)}건 · 모의 진입 {counts.get('entries', 0)}건"]
    for symbol, state in result["latest"].items():
        age = state.get("age_seconds_at_report")
        stamp = f" · 마지막 관측 {age:g}초 전" if age is not None else ""
        phase = {"warming_up": "준비 중", "watching": "신호 관측 중", "paper_position": "모의 포지션 보유",
                 "await_next_quote": "다음 호가 대기", "stale_exchange_oi": "미결제약정 시각 불일치",
                 "stale_exchange_perp": "선물 호가 시각 불일치", "stale_exchange_mark": "마크 가격 시각 불일치",
                 "public_feed_error": "공개 데이터 수신 실패"}.get(state["phase"], state["phase"])
        lines.append(f"  {symbol} · {phase} · 연속 관측 {state['lookback_samples']}/{LOOKBACK}{stamp}")
    stale = sum(n for reason, n in counts.items() if reason.startswith("stale_exchange_"))
    if counts.get("gap_resets") or counts.get("public_feed_error") or stale:
        lines.append(f"  관측 공백으로 재시작 {counts.get('gap_resets', 0)}회 · 수신 오류 "
                     f"{counts.get('public_feed_error', 0)}건 · 시각 불일치로 제외 {stale}건")
    for pair in result["paired_exits"]:
        delta = pair["setup_minus_common_net_R"]
        effect = f"{delta:+.3f}R" if delta is not None else "아직 계산할 수 없음"
        lines.append(f"  {'롱' if pair['side'] == 'long' else '숏'} · 같은 진입에서 두 방식 모두 종료 "
                     f"{pair['completed_pairs']}건 · 전략별 익절의 순손익 차이 {effect}")
        tiers = {g["tier"]: g["event_windows"] for g in result["groups"]
                 if g["side"] == pair["side"] and g["policy"] == "common"}
        comp = next(c for c in result["strength_comparisons"] if c["policy"] == "common" and c["side"] == pair["side"])
        diff = comp["strong_minus_normal_net_R"]
        evidence = {"insufficient_windows": "표본 부족", "unresolved_paths": "미확정 거래 있음",
                    "descriptive_only": "기술 통계"}[comp["status"]]
        difference = "" if diff is None else f" · 강−보통 {diff:+.3f}R"
        lines.append(f"    공통 익절 · 강 {tiers['strong']}구간 / 보통 {tiers['normal']}구간{difference} · {evidence}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("collect", "replay", "report", "export"):
        p = subs.add_parser(cmd)
        p.add_argument("--db", required=True, type=Path)
        if cmd == "collect":
            p.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
            p.add_argument("--interval", type=float, default=60, help="seconds between sample starts")
            p.add_argument("--samples", type=int, help="number of rounds; default continuous")
        elif cmd == "replay":
            p.add_argument("--input", required=True, type=Path)
        elif cmd == "report":
            opts = p.add_mutually_exclusive_group()
            opts.add_argument("--details", action="store_true")
            opts.add_argument("--brief", action="store_true", help="간단한 한국어 요약")
    args = parser.parse_args(argv)
    if args.cmd in ("export", "report"):
        with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            if args.cmd == "export":
                for row in read_rows(conn):
                    print(json.dumps(row, separators=(",", ":")))
            else:
                result = summarize(read_rows(conn), args.details)
                result["source"] = conn.execute("SELECT purpose FROM metadata").fetchone()[0]
                if result["source"] == "public_forward":
                    for state in result["latest"].values():
                        state["age_seconds_at_report"] = round((utc_ms() - state["last_minute_snapshot_ms"]) / 1000, 1)
                print(brief_report(result) if args.brief else json.dumps(result, indent=2))
        return 0
    if args.cmd == "replay":
        added = 0
        with args.input.open() as source, closing(connect(args.db, "replay")) as conn, conn:
            for line in source:
                if line.strip():
                    added += store(conn, json.loads(line))
        print(json.dumps({"added": added}))
        return 0
    if not math.isfinite(args.interval) or args.interval <= 0 or (args.samples is not None and args.samples < 1):
        parser.error("interval and samples must be positive")
    if any(not SYMBOL.fullmatch(sym) for sym in args.symbols):
        parser.error("symbols must be uppercase USDT pairs")
    with closing(connect(args.db, "public_forward")) as conn:
        count = failures = 0
        while args.samples is None or count < args.samples:
            begin = time.monotonic()
            for sym in dict.fromkeys(args.symbols):
                row = collect_one(sym)
                with conn:
                    store(conn, row)
                reason = quality(row)
                failures += bool(reason)
                print(json.dumps(dict(symbol=sym, received_ms=row["received_ms"], result=reason or "observed")), flush=True)
            count += 1
            if args.samples is None or count < args.samples:
                if args.interval == 60:
                    # Default sampling stays inside each UTC minute despite variable request latency.
                    # Requests slower than a minute surface as gaps instead of backfilled observations.
                    time.sleep((MINUTE - utc_ms() % MINUTE + 1500) / 1000)
                else:
                    time.sleep(max(0, args.interval - (time.monotonic()-begin)))
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
