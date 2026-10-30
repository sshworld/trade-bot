"""Daily-loss halt (user 2026-10-30, replaces the -25 % total-drawdown halt for qrmtf): equity (wallet + uPnL) at or
below 0.90 x the 00:00 UTC equity -> close all bot positions, 0 bot orders left, no new entries for 24 h from the trigger,
persisted in state, auto-resume after 24 h; one 🚨 on trigger and one ✅ on resume (live mode only)."""
import json
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from live_v6.tradelog import EventLog
from live_v6.notify import Notifier
from live_v6.strategies.qrmtf import QRMTF

DOGE, SOL = "DOGEUSDT", "SOLUSDT"
T0 = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc).timestamp()          # 10:00 KST, day baseline 2026-10-30
CFG = dict(halt_fraction=None, daily_loss_halt=0.10, income_interval_s=0)


def _eng(offline, t, tmp_path=None, **kw):
    eng = offline.engine(clock=lambda: t[0], **{**CFG, **kw})
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    if tmp_path is not None:
        eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    eng.startup()
    return eng


def _lines(tmp_path, kind):
    p = tmp_path / f"t_{kind}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _lose(offline, amt, t=None):
    # realised loss booked like Binance does (wallet + REALIZED_PNL income) so the ledger check stays quiet
    offline.inner.wallet -= D(amt)
    offline.inner.incomes.append({"type": "REALIZED_PNL", "amount": -D(amt), "time": int((t[0] if t else __import__("time").time()) * 1000),
                                  "symbol": DOGE, "tran_id": f"rp{len(offline.inner.incomes)}"})


def _alerts(eng):
    return [m for m in eng.tg.sent if m.startswith("🚨")]


def _bot_orders(offline):
    return [o for s in ("DOGEUSDT", "SOLUSDT", "XRPUSDT") for o in offline.inner.open_orders(s)]


@pytest.mark.parametrize("loss, halts", [("99.9", False), ("100", True)])   # baseline 1000: -9.99 % no, -10 % yes
def test_trigger_at_minus_10_not_9_9(offline, loss, halts):
    t = [T0]
    eng = _eng(offline, t)
    assert eng.meta["dl_day"] == "2026-10-30" and D(eng.meta["dl_base"]) == 1000
    _lose(offline, loss)
    eng.reconcile()
    assert bool(eng.meta.get("daily_halt")) is halts and eng.entries_allowed() is not halts
    assert len(_alerts(eng)) == (1 if halts else 0)


def test_no_total_drawdown_halt_when_off(offline):
    t = [T0]
    eng = _eng(offline, t)
    hit, _, thr = eng.drawdown_breached()
    assert not hit and thr is None                                       # halt_fraction None: -25 % rule removed


def test_unrealised_loss_counts_and_closes_all_leaving_0_orders(offline, tmp_path):
    t = [T0]
    eng = _eng(offline, t, tmp_path)
    eng.strategy.entry_scores = lambda sym, ms: "big_n -72.0 mid +5.0 fast -3.0 | 1w -3.0 1d -15.0"
    assert eng.enter(DOGE, offline.stop_dist(DOGE), int(t[0] * 1000) // 60000 * 60000)
    assert eng.enter(SOL, offline.stop_dist(SOL), int(t[0] * 1000) // 60000 * 60000 + 60000)
    assert _bot_orders(offline)
    _lose(offline, 97)                                                   # -9.7 % realised elsewhere today
    q, j = offline.amt(DOGE), eng.st["pos"][DOGE]
    offline.inner.price[DOGE] = D(j["entry_px"]) - D(4) / q              # + ~-4 USDT unrealised on DOGE, above its stop
    assert offline.inner.price[DOGE] > D(j["stop_px"])
    eng.reconcile()
    assert str(eng.meta["halted"]).startswith("daily_loss") and not eng.entries_allowed()
    assert offline.amt(DOGE) == 0 and offline.amt(SOL) == 0 and not eng.st["pos"]
    assert _bot_orders(offline) == []                                    # 0 residual orders
    (a,) = _alerts(eng)
    assert "일일 손실 −10%" in a and "DOGE 롱 실현 -" in a and "SOL 롱 실현" in a and "big_n -72.0" in a
    dh = eng.meta["daily_halt"]
    assert dh["until_ms"] - dh["trigger_ms"] == 24 * 3600 * 1000 and D(dh["day_start_equity"]) == 1000
    (h,) = [r for r in _lines(tmp_path, "daily") if r.get("event") == "halt"]
    assert h["halt_reason"] == "daily_loss" and h["trigger_time"] == dh["trigger_ms"]
    assert D(h["day_start_equity"]) == 1000 and D(h["equity_at_trigger"]) <= 900
    assert {r["reason"] for r in eng.meta["trades"]} == {"daily_loss_halt"}
    T = int(t[0] * 1000) // 60000 * 60000 + 120000
    assert not eng.enter(DOGE, offline.stop_dist(DOGE), T)               # no new entries


def test_short_side_label(offline):
    t = [T0]
    eng = _eng(offline, t, enable_short=True)
    assert eng.enter(DOGE, offline.stop_dist(DOGE), int(t[0] * 1000) // 60000 * 60000, side=-1)
    _lose(offline, 97)
    j = eng.st["pos"][DOGE]
    offline.inner.price[DOGE] = D(j["entry_px"]) + D(4) / abs(offline.amt(DOGE))
    assert offline.inner.price[DOGE] < D(j["stop_px"])
    eng.reconcile()
    (a,) = _alerts(eng)
    assert "DOGE 숏 실현" in a


def test_persists_through_restart_and_resumes_after_24h(offline):
    t = [T0]
    eng = _eng(offline, t)
    _lose(offline, 150)
    eng.reconcile()
    trig = eng.meta["daily_halt"]["trigger_ms"]
    t[0] += 3600
    eng2 = _eng(offline, t)                                              # restart: still halted, no new 🚨
    assert not eng2.entries_allowed() and eng2.meta["daily_halt"]["trigger_ms"] == trig and not _alerts(eng2)
    t[0] = trig / 1000 + 24 * 3600 - 1
    eng2.reconcile()
    assert not eng2.entries_allowed()
    t[0] += 1
    eng2.reconcile()
    assert eng2.entries_allowed() and "daily_halt" not in eng2.meta
    assert sum(1 for m in eng2.tg.sent if m.startswith("✅ 일일 손실 중단 해제")) == 1
    eng2.reconcile()                                                     # the new day baseline is the equity now (850)
    assert D(eng2.meta["dl_base"]) == 850 and not eng2.meta.get("daily_halt")


def test_day_rollover_resets_baseline(offline):
    t = [datetime(2026, 10, 30, 23, 59, 0, tzinfo=timezone.utc).timestamp()]
    eng = _eng(offline, t)
    _lose(offline, 60, t)                                        # -6 % today
    eng.reconcile()
    t[0] += 120                                                          # 00:01 UTC = 09:01 KST: new day
    eng.reconcile()
    assert eng.meta["dl_day"] == "2026-10-31" and D(eng.meta["dl_base"]) == 940
    _lose(offline, 60, t)                                        # -12 % vs yesterday, -6.4 % vs today
    eng.reconcile()
    assert not eng.meta.get("daily_halt") and eng.entries_allowed(), (eng.blocks, eng.meta.get("halted"))
    _lose(offline, 34, t)                                        # 846 = 0.9 x 940
    eng.reconcile()
    assert eng.meta.get("daily_halt")


def test_withdrawal_is_not_a_daily_loss(offline):
    t = [T0]
    eng = _eng(offline, t)
    offline.inner.wallet -= D(300)
    offline.inner.incomes.append({"type": "TRANSFER", "amount": D(-300), "time": int(__import__("time").time() * 1000) + 1,
                                  "symbol": "", "tran_id": "trw"})
    eng.reconcile()
    assert not eng.meta.get("daily_halt") and eng.entries_allowed()


def test_distance_to_halt_is_to_todays_line(offline, tmp_path):
    t = [T0]
    eng = _eng(offline, t, tmp_path)
    _lose(offline, 50)
    eng.reconcile()
    r = eng._daily_rec("2026-10-30", int(t[0] * 1000))
    assert D(r["distance_to_halt"]) == ((D(950) - D(900)) / D(950) * 100).quantize(D("0.01"))


@pytest.mark.parametrize("mode, want", [("testnet", 0), ("null", 0), ("live", 2)])
def test_telegram_only_in_live_mode(offline, mode, want):
    posts, t = [], [T0]
    eng = _eng(offline, t)
    eng.tg = Notifier("tok", "chat", mode=mode, post=lambda url, data, timeout: posts.append(data["text"]))
    _lose(offline, 100)
    eng.reconcile()
    t[0] += 24 * 3600
    eng.reconcile()
    assert len(posts) == want, (mode, posts)
    if want:
        assert posts[0].startswith("🚨 일일 손실") and posts[1].startswith("✅ 일일 손실 중단 해제")


def test_qrmtf_entry_scores_from_records_and_log(tmp_path):
    rec = {"T": 1_000_000, "sym": DOGE, "kind": "entry", "side": -1, "big_n": -72.04, "mid": 5.0, "fast": -3.0,
           "tf": {"1m": {"contrib": -1.0}, "1w": {"contrib": -3.0}, "1d": {"contrib": -15.0}}}
    s = QRMTF()
    s.records = [dict(rec, kind="near_miss", T=1_050_000), rec]
    assert s.entry_scores(DOGE, 1_020_000) == "big_n -72.0 mid +5.0 fast -3.0 | 1w -3.0 1d -15.0 1m -1.0"
    assert s.entry_scores(SOL, 1_020_000) is None and s.entry_scores(DOGE, 1_000_000 + 700_000) is None
    p = tmp_path / "sig.jsonl"
    p.write_text(json.dumps(rec) + "\n")
    s2 = QRMTF(log_path=str(p))                                          # after a restart: read from the signal log
    assert s2.entry_scores(DOGE, 1_020_000).startswith("big_n -72.0")


def test_first_baseline_backs_out_todays_realised_income(offline):
    """First start mid-day: baseline = equity now minus today's (00:00 UTC) non-transfer income."""
    t = [T0]
    day0 = int(datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    _lose(offline, "30", [day0 / 1000 + 60])                   # lost 30 after 00:00 UTC, before the bot started
    offline.inner.incomes.append({"type": "REALIZED_PNL", "amount": -D(5), "time": day0 - 60000, "symbol": DOGE,
                                  "tran_id": "yesterday"})      # yesterday: not counted
    eng = _eng(offline, t)
    assert eng.meta["dl_day"] == "2026-10-30" and D(eng.meta["dl_base"]) == 1000
