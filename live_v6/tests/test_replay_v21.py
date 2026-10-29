"""Slow replays of the research data through the LIVE engine under sizing v2.1 (994e138).

Why these tests exist: the old replay tests demanded an exact match with the research trade list, which was produced
with the pre-v2.1 sizing (a trade whose normal size is below the exchange minimum is SKIPPED). v2.1 instead enters the
minimum order (`qty_floor`, ≤ 3 % loss) and checks notional at ref −2 %, so on the $100 replay wallet the engine
legitimately takes more trades than the old CSV. The old CSV baseline is NOT regenerated. Instead:

  * v2.1 invariants (replay_invariants.py) hold for every entry of the default-sizing replay, and every entry that is
    not in the research list is explained: the FIRST divergence is a qty_floor (minimum-order) entry, and a later extra
    on the normal q0 path exists only because the extra minimum-order trades changed the wallet (cascade) or, for BTC,
    because v2.1 removed the bot-side $100 BTC floor (exchange minimum is 50);
  * with the old rule reproduced by legitimate settings (min_order_loss_cap=0 → no minimum-order entries,
    price_buffer=0 → minimum notional checked at ref as before v2.1, and for the 1m H7-T data the BTC exchange minimum
    set back to the old $100 floor in the simulated exchangeInfo) the replay matches the research trades exactly.
    (min_order_loss_cap=0 alone leaves exactly one 4h trade missing — pinned below, with the reason.)"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

from live_v6.sizing import SizingParams

from .replay_invariants import Entry, Recorder, check_entries

DATA = Path("/workspace/v6replay_data")
H4_OK = (DATA / "research_T_H7.csv").exists()
M1_OK = (DATA / "DOGEUSDT_1m.npz").exists()

DEFAULT = SizingParams()
OLD_RULE = SizingParams(min_order_loss_cap=0.0, price_buffer=0.0)     # in memory only; never the live setting
CAP0_ONLY = SizingParams(min_order_loss_cap=0.0)

_cache: dict = {}


@contextmanager
def _btc_floor(v):
    """Sim-only: BTC MIN_NOTIONAL in the simulated exchangeInfo (v2.1 uses the exchange's 50; ≤ 4d8d16c the bot floored 100)."""
    from live_v6.replay.sim_exchange import SimExchange
    orig = SimExchange.exchange_info
    if v is None:
        yield
        return

    def patched(self):
        info = copy.deepcopy(orig(self))
        for sy in info["symbols"]:
            if sy["symbol"] == "BTCUSDT":
                for f in sy["filters"]:
                    if f["filterType"] == "MIN_NOTIONAL":
                        f["notional"] = str(v)
        return info
    SimExchange.exchange_info = patched
    try:
        yield
    finally:
        SimExchange.exchange_info = orig


def _run_h4(p, btc=None):
    """4h replay (research tie order, research stop fill) with sizing params p → (compare result, entries, engine)."""
    if ("h4", p, btc) not in _cache:
        from live_v6.replay.replay import compare, run
        with Recorder() as rec, _btc_floor(btc):
            eng, ex, T = run(str(DATA), order="research", stop_fill="research", sizing=p)
        _cache["h4", p, btc] = (compare(eng, ex, T), rec.entries, eng)
    return _cache["h4", p, btc]


def _run_h7t(p, btc=None):
    """H7-T (1m) replay with sizing params p → (compare result, entries, engine)."""
    if ("h7t", p, btc) not in _cache:
        from live_v6.replay import replay_h7t as RH
        with Recorder() as rec, _btc_floor(btc):
            eng, ex, _ = RH.run(str(DATA), sizing=p)
        _cache["h7t", p, btc] = (RH.compare(eng, ex), rec.entries, eng)
    return _cache["h7t", p, btc]


def _invariants(runner):
    r, entries, _ = runner(DEFAULT)
    assert len(entries) == r["engine_trades"], "every engine trade must have a recorded sizing"
    assert check_entries(entries, DEFAULT) == []
    by_key = {(e.sym, e.entry_time): e for e in entries}
    extras = sorted(r["extra"], key=lambda k: k[1])
    assert extras, "default sizing is expected to enter minimum orders the research run skipped"
    # 1. the first divergence from research is a minimum-order entry (until then engine and research wallets are equal)
    first_floor = min(e.entry_time for e in entries if e.path == "qty_floor")
    assert by_key[extras[0]].path == "qty_floor" and extras[0][1] == first_floor, (extras[0], first_floor)
    # 2. every other extra is a qty_floor entry, or a q0 entry explained by wallet cascade (after the first minimum-order
    #    entry) or by the removed $100 BTC floor (BTC notional < 100)
    unexplained = []
    for k in extras:
        e = by_key[k]
        if e.path == "qty_floor":
            continue
        btc_floor_removed = e.sym == "BTCUSDT" and e.qty * e.ref < 100
        if not (btc_floor_removed or e.entry_time > first_floor):
            unexplained.append(k)
    assert unexplained == [], f"q0-path extras with no explanation: {unexplained}"
    assert any(e.path == "q0" for e in entries) and any(e.path == "qty_floor" for e in entries)


# ── fast: the checker itself must be able to fail ──
class _R:
    order_min_qty, min_notional, order_step = Decimal("0.001"), Decimal("20"), Decimal("0.001")


def _e(**kw):
    d = dict(sym="ETHUSDT", entry_time=1, wallet=Decimal(1000), ref=Decimal(1000), stop_dist=Decimal(40), stop_px=Decimal(960),
             qty=Decimal("0.125"), path="q0", risk_pct_used=0.5, q0=Decimal("0.125"), rules=_R(), open_syms=())
    d.update(kw)
    return Entry(**d)


def test_checker_accepts_a_legal_q0_entry():
    assert check_entries([_e()]) == []                       # 0.125 × 40 = 5.0 = 0.5 % ; + fees 0.125 → 5.125 ≤ 10


def _book(n, *, qty="0.125"):
    """n earlier entries (A, B, ...) that are all still open, each risking qty × 40 / 1000 of the wallet."""
    syms = "ABCDEFGH"[:n]
    return [_e(sym=s, entry_time=i, qty=Decimal(qty), q0=Decimal(qty), open_syms=tuple(syms[:i]),
               risk_pct_used=0.5 if i < 3 else 0.25) for i, s in enumerate(syms)]


@pytest.mark.parametrize("kw, frag", [
    (dict(qty=Decimal("0.126")), "q0 stop loss"),                                           # 5.04 > 0.5 % of 1000
    (dict(stop_px=Decimal(900), qty=Decimal("0.1")), "q0 stop loss"),                       # wider stop, same qty
    (dict(path="qty_floor", qty=Decimal("0.5"), q0=Decimal("0.125")), "q0 "),               # q0 was fine → no floor
    (dict(path="qty_floor", qty=Decimal("0.03"), q0=Decimal(0), stop_dist=Decimal(1000)), "min-order loss"),   # > 3 %
    (dict(path="nonsense"), "unknown path"),
])
def test_checker_flags_violations(kw, frag):
    bad = check_entries([_e(**kw)])
    assert any(frag in b for b in bad), bad


def test_checker_flags_missing_same_side_halving():
    # only when halving is configured (pre-6440290 rule); in memory only
    book = _book(3)
    late = _e(sym="Z", entry_time=9, open_syms=("A", "B", "C"), risk_pct_used=0.5)           # must be 0.25 with 3 open
    assert any("risk_pct_used" in b for b in check_entries(book + [late], SizingParams(same_side_halving_at=3)))


def test_checker_live_default_has_no_halving():
    # live default (6440290): no same-side halving, so a 4th entry at full 0.5 % is fine and a halved one is flagged
    assert SizingParams().same_side_halving_at is None
    book = _book(3)
    full = _e(sym="Z", entry_time=9, open_syms=("A", "B", "C"), risk_pct_used=0.5)
    assert not any("risk_pct_used" in b for b in check_entries(book + [full]))
    halved = _e(sym="Z", entry_time=9, open_syms=("A", "B", "C"), risk_pct_used=0.25,
                qty=Decimal("0.0625"), q0=Decimal("0.0625"))
    assert any("risk_pct_used" in b for b in check_entries(book + [halved]))


def test_checker_flags_open_risk_over_cap():
    # 3 × 0.5 % (+ halved 0.25 %s) stay under 2.5 %; piling on 0.25 % entries must eventually be flagged
    ok = _book(3)
    assert check_entries(ok) == []
    half = dict(qty=Decimal("0.0625"), q0=Decimal("0.0625"), risk_pct_used=0.25)
    book = ok + [_e(sym=s, entry_time=3 + i, open_syms=tuple("ABCDEFGH"[:3 + i]), **half) for i, s in enumerate("DEFGHIJKL")]
    bad = check_entries(book)
    assert any("open risk" in b and "q0" in b for b in bad), bad


# ── slow: replay invariants under v2.1 (default sizing) ──
@pytest.mark.slow
@pytest.mark.skipif(not H4_OK, reason="replay data not exported")
def test_replay_4h_v21_invariants():
    _invariants(_run_h4)


@pytest.mark.slow
@pytest.mark.skipif(not M1_OK, reason="1m replay data not exported")
def test_replay_h7t_v21_invariants():
    _invariants(_run_h7t)


# ── slow: exact match with the research trades when the pre-v2.1 skip rule is reproduced ──
@pytest.mark.slow
@pytest.mark.skipif(not H4_OK, reason="replay data not exported")
def test_replay_4h_old_rule_matches_research_trades_exactly():
    r, entries, _ = _run_h4(OLD_RULE)            # BTC at the exchange's 50: no 4h BTC entry sits between 50 and 100
    assert r["exact_match"], {k: r[k] for k in ("missing", "extra") if k in r} | {"diffs": r["diffs"][:3]}
    assert {e.path for e in entries} == {"q0"} and check_entries(entries, OLD_RULE) == []


@pytest.mark.slow
@pytest.mark.skipif(not M1_OK, reason="1m replay data not exported")
def test_replay_h7t_old_rule_matches_research_trades_exactly():
    r, entries, _ = _run_h7t(OLD_RULE, btc=100)   # 1m data has BTC entries of 50-100 USDT that the old $100 floor skipped
    assert r["exact_match"], {k: r[k] for k in ("missing", "extra") if k in r} | {"diffs": r["diffs"][:3]}
    assert {e.path for e in entries} == {"q0"} and check_entries(entries, OLD_RULE) == []


# ── slow: the one-trade gap of min_order_loss_cap=0 alone is the v2.1 price buffer, nothing else ──
@pytest.mark.slow
@pytest.mark.skipif(not H4_OK, reason="replay data not exported")
def test_replay_4h_cap0_only_gap_is_the_price_buffer():
    r, _, eng = _run_h4(CAP0_ONLY)
    gap = ("ETHUSDT", 1675310400000)                         # 2023-02-02 04:00 UTC
    assert r["missing"] == [gap] and r["extra"] == []
    # research took it: q0 0.012 ETH × 1671.93 = 20.06 ≥ minNotional 20 at the entry price; v2.1 checks at ref −2 % = 19.66 < 20
    ref, q0, mn = Decimal("1671.93"), Decimal("0.012"), Decimal(20)
    assert q0 * ref >= mn > q0 * ref * (1 - Decimal(str(DEFAULT.price_buffer)))
    why = [s for s in eng.meta["skip_log"] if s[1] == "ETHUSDT" and int(s[0]) // 14_400_000 * 14_400_000 == gap[1]]
    assert len(why) == 1 and why[0][2] == "min_order_risk_over_cap" and "q0=0.012" in why[0][3], why
    # nothing differs before the gap; every later difference is the wallet/qty cascade of the one missing trade
    assert r["diffs"] and min(d["key"][1] for d in r["diffs"]) > gap[1]
