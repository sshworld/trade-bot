"""Offline point-in-time fixtures, never invoke a trading client."""
import json
from copy import deepcopy
from contextlib import closing

import pytest

from live_v6.tools import breakout_shadow as b


# Align the replay to UTC minutes; settlement falls eight hours after this start.
BASE = 1_800_000_000_000
FUNDING = 8 * 3600_000


def observation(n, spot=100, perp=100, oi=1000, symbol="BTCUSDT"):
    now = BASE + n * b.MINUTE + 1000
    quote = lambda px: {"bid": px - .005, "ask": px + .005, "bid_qty": 100., "ask_qty": 100.}
    return {
        "schema": 1, "symbol": symbol, "started_ms": now-120, "received_ms": now,
        "receipts_ms": dict.fromkeys(("spot", "perp", "oi", "mark", "funds"), now-20),
        "perp_ms": now-80, "oi_ms": now-90, "mark_ms": now-90, "oi": oi, "spot": quote(spot),
        "perp": quote(perp), "next_funding_ms": BASE+FUNDING,
        "settlements": [{"ms": BASE-10000, "rate": .0001, "mark": 100.}],
    }


def long_rows(symbol="BTCUSDT"):
    # Breakout → retest → reconfirm → new quote entry → move through both targets → trailing exit.
    future = [(100.4, 100.2), (100.06, 100.04), (100.35, 100.18),
              (100.45, 100.23), (102, 102), (99.95, 99.95)]
    return [observation(i, symbol=symbol) for i in range(20)] + [
        observation(i, s, f, symbol=symbol) for i, (s, f) in enumerate(future, 20)]


def short_rows():
    future = [(100, 100.34), (100, 99.85), (100.02, 100), (99.95, 99.85),
              (99.9, 99.8), (98.6, 98.6), (100.6, 100.6)]
    return [observation(i) for i in range(20)] + [
        observation(i, s, f, 1009) for i, (s, f) in enumerate(future, 20)]


@pytest.mark.parametrize(("rows", "side", "entry"), [(long_rows, "long", 23), (short_rows, "short", 24)])
def test_retest_separate_next_quote_and_costed_exits(rows, side, entry):
    data = rows()
    counts, records = b.study(data[:entry])
    assert counts["confirmed"] == 1 and not records and not counts["entries"]
    counts, records = b.study(data)
    assert counts["entries"] == 1
    assert len(records) == 2
    assert {t["entry_minute"] for t in records} == {BASE // b.MINUTE + entry}
    assert all(t["side"] == side and t["tier"] == "strong" and t["tp1_hit"] for t in records)
    assert records[0]["net_R"] != records[1]["net_R"]
    assert all(t["status"] == "stop" for t in records)
    # A cheaper, apparently favourable entry on the confirmation tick may not be used.
    altered = deepcopy(data)
    altered[entry]["perp"] = observation(entry, perp=103 if side == "long" else 98)["perp"]
    assert b.study(altered)[1] != records


def test_future_funding_or_sparse_clock_cannot_supply_a_signal():
    data = long_rows()
    data[20]["settlements"][0]["ms"] = data[20]["received_ms"] + 100
    counts, records = b.study(data)
    assert counts["bad_settlement"] == 1 and not records
    data = long_rows()
    counts, records = b.study(data[:24] + data[25:])
    assert counts["gap_resets"] == 1
    assert all(r["net_R"] is None and r["status"] == "censored_gap" for r in records)
    assert len(records) == 2


def test_shared_market_move_is_one_event_window_per_tier():
    first, second = long_rows(), long_rows("ETHUSDT")
    data = sorted(first + second, key=lambda r: r["received_ms"])
    result = b.summarize(data)
    group, = [g for g in result["groups"] if (g["policy"], g["side"], g["tier"]) == ("common", "long", "strong")]
    assert (group["closed"], group["event_windows"]) == (2, 1)
    comparisons = result["strength_comparisons"]
    assert all(g["status"] == "insufficient_windows" and g["strong_minus_normal_net_R"] is None
               for g in comparisons)
    exits, = [p for p in result["paired_exits"] if p["side"] == "long"]
    assert (exits["completed_pairs"], exits["event_windows"], exits["unresolved_pairs"]) == (2, 1, 0)


def test_paired_comparison_keeps_path_lost_after_one_branch_closed():
    rows = long_rows()
    rows[24] = observation(24, spot=101, perp=101)
    rows[25] = observation(25, spot=100.3, perp=100.3)
    rows.append(observation(28))
    result = b.summarize(rows)
    assert sum(g["closed"] for g in result["groups"]) == 1
    pair, = [p for p in result["paired_exits"] if p["side"] == "long"]
    assert (pair["unresolved_pairs"], pair["completed_pairs"], pair["setup_minus_common_net_R"]) == (1, 0, None)


@pytest.mark.parametrize(("factory", "entry", "direction"), [(long_rows, 23, -1), (short_rows, 24, 1)])
def test_funding_once_at_settlement_on_the_remaining_quantity(factory, entry, direction):
    baseline = factory()
    data = deepcopy(baseline)
    settlement = BASE + (entry + 1) * b.MINUTE
    for row in data[:entry+1]:
        row["next_funding_ms"] = settlement
    for row in data[entry+1:]:
        row["settlements"].append({"ms": settlement, "rate": .01, "mark": 100.})
    _, outcomes = b.study(data)
    _, controls = b.study(baseline)
    for outcome, control in zip(outcomes, controls):
        assert direction * (outcome["net_R"] - control["net_R"]) > 0
    data[entry+1]["settlements"].pop()
    _, outcomes = b.study(data)
    assert [t["status"] for t in outcomes] == ["censored_missing_settlement"]*2


def test_entry_depth_and_exit_depth_are_not_free_fills():
    data = long_rows()
    data[23]["perp"]["ask_qty"] = .00001
    counts, trades = b.study(data)
    assert counts["insufficient_entry_depth"] == 1 and not trades
    data = long_rows()
    data[24]["perp"]["bid_qty"] = .00001
    counts, trades = b.study(data)
    assert counts["insufficient_exit_depth"] == 1
    assert len(trades) == 2 and all(t["net_R"] is None for t in trades)


def test_cli_replay_idempotent_export_and_live_db_isolation(tmp_path, capsys):
    path = tmp_path / "replay.sqlite3"
    source = tmp_path / "observations.jsonl"
    data = long_rows()
    source.write_text("".join(json.dumps(row)+"\n" for row in data))
    args = ["replay", "--db", str(path), "--input", str(source)]
    assert b.main(args) == 0
    assert json.loads(capsys.readouterr().out)["added"] == len(data)
    assert b.main(args) == 0
    assert json.loads(capsys.readouterr().out)["added"] == 0
    assert b.main(["report", "--db", str(path), "--details"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["entries"] == 1 and result["source"] == "replay"
    assert b.main(["export", "--db", str(path)]) == 0
    assert [json.loads(l) for l in capsys.readouterr().out.splitlines()] == data
    with pytest.raises(ValueError, match="separate"):
        b.connect(path, "public_forward")
    with closing(b.connect(path, "replay")) as conn:
        row = deepcopy(data[0]); row["oi"] += 1
        with pytest.raises(ValueError, match="conflicting"):
            b.store(conn, row)


def test_mock_public_collection_without_trading_or_secret():
    row = observation(0)
    now = row["received_ms"]
    calls = []
    def public(url):
        calls.append(url)
        if "bookTicker" in url:
            return dict(symbol="BTCUSDT", bidPrice="99.995", askPrice="100.005", bidQty="10", askQty="10", time=now)
        if "openInterest" in url:
            return dict(symbol="BTCUSDT", time=now, openInterest="1000")
        if "premiumIndex" in url:
            return dict(symbol="BTCUSDT", time=now, nextFundingTime=now+FUNDING)
        assert "fundingRate" in url
        return [dict(symbol="BTCUSDT", fundingTime=now-1, markPrice="100", fundingRate="0.0001")]
    observed = b.collect_one("BTCUSDT", public, lambda: now)
    assert len(calls) == 5 and b.quality(observed) is None
    assert all(url.startswith((b.SPOT, b.PERP)) for url in calls)
    def unavailable(_url):
        raise OSError("unavailable")
    assert b.quality(b.collect_one("BTCUSDT", unavailable, lambda: now)) == "public_feed_error"


def test_drawdown_uses_cohort_exit_time_and_aggregates_simultaneous_closes():
    trades = [{"exit_ms": when, "net_R": net} for when, net in [(3, -2), (1, 3), (2, -3), (2, 2)]]
    assert b.closed_drawdown(trades) == 3
    assert b.closed_drawdown([]) is None
    setup = b.Setup(1, 100, 100, 101, 0, "normal")
    cohort, why = b.enter(setup, observation(0, spot=101., perp=101.))
    assert not why
    leg = cohort.legs[1]  # long setup-specific first profit target is at +2R
    one_r = abs(leg.entry - leg.original_stop)
    leg.observe(observation(1, spot=101., perp=leg.entry + 1.2 * one_r), 1)
    assert not leg.took
    leg.observe(observation(2, spot=99., perp=leg.original_stop - .1), 2)
    result = b.leg_record("BTCUSDT", cohort, leg, "stop", 2 * b.MINUTE)
    assert result["reached_1R"] and not result["tp1_hit"] and result["net_R"] < 0


def test_stale_open_interest_is_visible_and_cannot_seed_a_position():
    rows = long_rows()[:22]
    rows[-1]["oi_ms"] -= 12 * b.MINUTE
    result = b.summarize(rows)
    result["source"] = "replay"
    assert result["counts"]["stale_exchange_oi"] == 1
    assert result["latest"]["BTCUSDT"]["lookback_samples"] == 0
    assert result["counts"].get("entries", 0) == 0
    text = b.brief_report(result)
    assert "미결제약정 시각 불일치" in text and "강 0구간 / 보통 0구간" in text
