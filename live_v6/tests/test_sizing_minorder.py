"""Min-order sizing (TA spec v2.1, 2026-10-26): q0 path / smallest-allowed-quantity path (`qty_floor`, loss ≤ 3% of
wallet), pure pre-order gate, fresh reads before every order, definitive-rejection order sequences. Offline only.
Real exchangeInfo filters of 2026-10-26 (fakes.FILTERS / EXTRA)."""
import ast
import copy
import dataclasses
import itertools
import logging
from decimal import Decimal
from pathlib import Path

import pytest

import live_v6
from live_v6.exchange import ExchangeUnavailable, OrderRejected, WouldTrigger, rules_from_info
from live_v6.rules import SymbolRules, ceil_to, floor_to
from live_v6.sizing import SizingParams, precheck_order, size_entry

from .conftest import unique_T
from .fakes import BRACKETS, EXTRA, FILTERS, FakeExchange
from .test_faults import alerts, close_calls

COINS = tuple(FILTERS)
PRICE = {s: Decimal(p) for s, p in {"BTCUSDT": "60000", "ETHUSDT": "3000", "SOLUSDT": "150", "BNBUSDT": "600",
                                    "XRPUSDT": "0.6", "DOGEUSDT": "0.15"}.items()}
INFO = FakeExchange().exchange_info()
R = rules_from_info(INFO, COINS)
P = SizingParams()
RT = 2 * Decimal("0.0005") + Decimal("0.0004") + Decimal("0.0003")        # spec v2.1 loss model: fees + slippages
KNOWN = {"qty_floor", "q0", "min_order_risk_over_cap", "total_risk_cap", "risk_cap_portfolio", "risk_cap", "margin",
         "bracket", "leverage", "liq_guard", "below_min_notional", "below_min_qty", "qty_zero", "qty_step", "max_qty",
         "percent_price", "tick", "stop_trigger", "filter_read_failed"}


def stop_for(s, ref, frac="0.03"):
    return floor_to(ref * (1 - Decimal(frac)), R[s].tick_size)


def gate(s, qty, ref, **kw):
    a = dict(lev=5, stop_px=stop_for(s, ref), available=10**6, mark=ref)
    a.update(kw)
    return precheck_order(R[s], a.get("brackets", BRACKETS[s]), qty, ref, a["lev"], a["stop_px"], a["available"], 1,
                          bid=a.get("bid"), mark=a["mark"])[0]


def loss_frac(s, qty, ref, dist, wallet):
    return float((qty * dist + qty * ref * RT) / wallet)


# ───────────────────────── pure gate: boundaries per coin ─────────────────────────
@pytest.mark.parametrize("s", COINS)
def test_boundary_min_qty_plus_minus_one_step(s):
    r = R[s]
    ref = Decimal(10) * r.min_notional / r.order_min_qty                # notional never the limiter here
    assert gate(s, r.order_min_qty, ref) is None
    assert gate(s, r.order_min_qty + r.order_step, ref) is None
    below = r.order_min_qty - r.order_step
    assert gate(s, below, ref) == ("qty_zero" if below <= 0 else "below_min_qty")
    assert gate(s, r.order_min_qty + r.order_step / 2, ref) == "qty_step"
    wide = [{"floor": 0.0, "cap": 1e30, "mmr": 0.005, "max_lev": 50}]
    assert gate(s, r.order_max_qty, PRICE[s], available=10**30, brackets=wide) is None
    assert gate(s, r.order_max_qty + r.order_step, PRICE[s], available=10**30, brackets=wide) == "max_qty"


@pytest.mark.parametrize("s", COINS)
def test_boundary_min_notional_plus_minus_one_tick(s):
    r = R[s]
    qty = ceil_to(r.min_notional / (PRICE[s] * Decimal("0.98")), r.order_step)
    exact = r.min_notional / (qty * Decimal("0.98"))
    ok = ceil_to(exact, r.tick_size)                                     # smallest tick price that passes
    assert gate(s, qty, ok) is None
    assert gate(s, qty, ok - r.tick_size) == "below_min_notional"
    assert gate(s, qty, ok + r.tick_size) is None
    assert gate(s, qty - r.order_step, ok) in ("below_min_notional", "qty_zero", "below_min_qty")


@pytest.mark.parametrize("s", COINS)
def test_boundary_margin_plus_minus_one_percent(s):
    ref = PRICE[s]
    qty = ceil_to(Decimal(200) / ref, R[s].order_step)
    lev = 10
    need = qty * ref / lev + qty * ref * Decimal("0.0010")
    edge = need / Decimal("0.9")
    assert gate(s, qty, ref, lev=lev, available=edge) is None
    assert gate(s, qty, ref, lev=lev, available=edge * Decimal("1.01")) is None
    assert gate(s, qty, ref, lev=lev, available=edge * Decimal("0.99")) == "margin"


@pytest.mark.parametrize("s", COINS)
def test_gate_other_labels_are_distinct(s):
    r, ref = R[s], PRICE[s]
    qty = ceil_to(Decimal(200) / ref, r.order_step)
    sp = stop_for(s, ref)
    assert gate(s, qty, ref) is None
    assert gate(s, qty, ref, stop_px=sp + r.tick_size / 2) == "tick"
    assert gate(s, qty, ref, stop_px=ref + r.tick_size) == "stop_trigger"              # would trigger at once (-2021)
    assert gate(s, qty, ref, bid=sp - r.tick_size, stop_px=sp) == "stop_trigger"       # bid fell through the stop
    sp1 = stop_for(s, ref, "0.01")
    assert gate(s, qty, ref, stop_px=sp1, mark=sp1 - r.tick_size) == "stop_trigger"    # mark already below the stop
    assert gate(s, qty, ref, lev=51) == "bracket"
    big = floor_to(Decimal(6e4) / ref, r.order_step) + r.order_step                    # > 50k notional tier (max 10x)
    assert gate(s, big, ref, lev=20, available=10**9) == "bracket"
    assert gate(s, qty, ref, mark=ref * r.pct_up * Decimal("0.99")) is None            # PERCENT_PRICE edge
    assert gate(s, qty, ref, mark=ref / r.pct_up / Decimal("1.01")) == "percent_price"
    assert gate(s, qty, ref, mark=ref / r.pct_down * Decimal("1.01")) == "percent_price"
    assert precheck_order(r, [], qty, ref, 5, sp, 10**6, mark=ref)[0] == "filter_read_failed"
    assert precheck_order(r, BRACKETS[s], qty, ref, 5, sp, 10**6, mark=None)[0] == "filter_read_failed"
    no_lot = dataclasses.replace(r, mkt_step_size=None)
    assert precheck_order(no_lot, BRACKETS[s], qty, ref, 5, sp, 10**6, mark=ref)[0] == "filter_read_failed"


def test_gate_is_pure():
    import inspect
    src = inspect.getsource(precheck_order)
    assert not any(w in src for w in ("self.", "open(", "requests", "httpx", "time.", "ex.", "log."))
    a = (R["BTCUSDT"], BRACKETS["BTCUSDT"], Decimal("0.001"), PRICE["BTCUSDT"], 5, stop_for("BTCUSDT", PRICE["BTCUSDT"]), 100)
    assert precheck_order(*a, mark=PRICE["BTCUSDT"]) == precheck_order(*a, mark=PRICE["BTCUSDT"])


# ───────────────────────── size_entry: path selection and the 3% boundary ─────────────────────────
@pytest.mark.parametrize("s", COINS)
def test_boundary_loss_cap_3pct_per_coin(s):
    ref = PRICE[s]
    atr = ref * Decimal("0.015")
    dist = ceil_to(2 * atr, R[s].tick_size)
    worst = ref * Decimal("0.98")
    q_min = max(ceil_to(R[s].min_notional / worst, R[s].order_step), ceil_to(R[s].order_min_qty, R[s].order_step))
    loss = q_min * dist + q_min * ref * RT
    edge = (loss / Decimal("0.03")).quantize(Decimal("0.01"), rounding="ROUND_UP")   # smallest wallet within 3%
    z = size_entry(R[s], BRACKETS[s], edge, edge, ref, dist, mark=ref)
    assert z.skip is None and z.path == "qty_floor" and z.qty == q_min and z.loss_frac <= 0.03 + 1e-12
    bad = edge - Decimal("0.01") * 2
    z = size_entry(R[s], BRACKETS[s], bad, bad, ref, dist, mark=ref)
    assert z.skip == "min_order_risk_over_cap" and "qty_zero" not in z.skip and z.loss_frac > 0.03
    assert "q0=" in z.detail and "3%" in z.detail


@pytest.mark.parametrize("s", COINS)
def test_q0_path_when_risk_sized_qty_is_allowed(s):
    ref = PRICE[s]
    dist = ceil_to(2 * ref * Decimal("0.01"), R[s].tick_size)
    z = size_entry(R[s], BRACKETS[s], 1000, 1000, ref, dist, mark=ref)
    q0 = floor_to(Decimal(1000) * Decimal("0.005") / dist, R[s].order_step)
    assert z.skip is None and z.path == "q0" and z.qty == q0 and z.loss_frac == 0.0
    assert z.risk_frac == pytest.approx(float(z.qty * dist / 1000))


def test_q0_inside_price_buffer_band_goes_to_min_qty_path_not_skip():
    s, ref = "BTCUSDT", Decimal("51000")                                # q0·ref ≥ 50 but q0·ref·0.98 < 50 at 0.001
    z = size_entry(R[s], BRACKETS[s], 100, 100, ref, Decimal("1000"), mark=ref)
    assert z.q0 == Decimal("0.0005") // Decimal("0.001") * Decimal("0.001") or z.q0 == 0
    assert z.skip is None and z.qty * ref * Decimal("0.98") >= 50


def test_min_qty_entry_is_the_smallest_allowed_quantity():
    for s in COINS:
        ref = PRICE[s]
        dist = ceil_to(2 * ref * Decimal("0.015"), R[s].tick_size)
        z = size_entry(R[s], BRACKETS[s], 150, 150, ref, dist, mark=ref)
        if z.skip is None and z.path == "qty_floor":
            smaller = z.qty - R[s].order_step
            assert smaller <= 0 or smaller < R[s].order_min_qty or smaller * ref * Decimal("0.98") < R[s].min_notional


def test_open_risk_sum_cap_5pct_for_min_qty_and_2_5pct_for_q0():
    s, ref, dist = "BTCUSDT", PRICE["BTCUSDT"], Decimal("1800")
    open_ok = [{"side": 1, "risk_frac": 0.03}]
    z = size_entry(R[s], BRACKETS[s], 100, 100, ref, dist, 1, open_ok, mark=ref)
    assert z.skip is None and z.path == "qty_floor"                     # 3% + 1.88% ≤ 5%
    z = size_entry(R[s], BRACKETS[s], 100, 100, ref, dist, 1, [{"side": 1, "risk_frac": 0.0313}], mark=ref)
    assert z.skip == "total_risk_cap" and "5.0%" in z.detail            # 3.13% + 1.88% > 5%
    z = size_entry(R["DOGEUSDT"], BRACKETS["DOGEUSDT"], 1000, 1000, PRICE["DOGEUSDT"], Decimal("0.009"), 1,
                   [{"side": 1, "risk_frac": 0.021}], mark=PRICE["DOGEUSDT"])
    assert z.skip == "risk_cap_portfolio"                               # q0 keeps today's 2.5% cap


def test_same_leverage_method_as_before_and_confirmed_value_is_final():
    s, ref, dist = "SOLUSDT", PRICE["SOLUSDT"], Decimal("4.5")
    a = size_entry(R[s], BRACKETS[s], 500, 500, ref, dist, mark=ref)
    b = size_entry(R[s], BRACKETS[s], 500, 500, ref, dist, mark=ref, fixed_lev=a.lev)
    assert a.skip is None and b.lev == a.lev and b.qty == a.qty
    assert size_entry(R[s], BRACKETS[s], 500, 500, ref, dist, mark=ref, fixed_lev=51).skip == "leverage"
    assert size_entry(R[s], BRACKETS[s], 500, 500, ref, dist, mark=ref, fixed_lev=a.lev + 1).skip in (
        "liq_guard", "leverage", None)


# ───────────────────────── property sweeps ─────────────────────────
def test_property_sweep_price_atr_wallet_all_coins():
    n_enter = n_skip = 0
    skips = set()
    for s, pf, af, w in itertools.product(COINS, (0.5, 0.75, 1, 1.25, 1.5), (0.3, 0.6, 1, 2, 3), (50, 100, 200, 400, 1000)):
        r = R[s]
        ref = ceil_to(PRICE[s] * Decimal(str(pf)), r.tick_size)
        dist = max(ceil_to(2 * ref * Decimal("0.012") * Decimal(str(af)), r.tick_size), r.tick_size)
        wallet = Decimal(w)
        z = size_entry(r, BRACKETS[s], wallet, wallet, ref, dist, mark=ref)
        if z.skip:
            n_skip += 1
            skips.add(z.skip)
            assert z.skip in KNOWN, z
            if z.skip == "min_order_risk_over_cap":
                q = max(ceil_to(r.min_notional / (ref * Decimal("0.98")), r.order_step), r.order_min_qty)
                assert loss_frac(s, q, ref, dist, wallet) > 0.03
            continue
        n_enter += 1
        q = z.qty
        assert q % r.order_step == 0 and r.order_min_qty <= q <= r.order_max_qty
        assert q * ref * Decimal("0.98") >= r.min_notional                       # even after a −2% move
        assert z.stop_px % r.tick_size == 0 and z.stop_px < ref
        assert q * ref / z.lev + q * ref * Decimal("0.001") <= wallet * Decimal("0.9") + Decimal("1e-9")
        assert precheck_order(r, BRACKETS[s], q, ref, z.lev, z.stop_px, wallet, mark=ref)[0] is None
        if z.path == "q0":
            assert z.risk_frac <= 0.0051 and q * dist * 1 <= wallet * Decimal("0.0051")
        else:
            assert z.loss_frac <= 0.03 + 1e-12 and loss_frac(s, q, ref, dist, wallet) <= 0.03 + 1e-12
            assert z.q0 < max(r.order_min_qty, ceil_to(r.min_notional / (ref * Decimal("0.98")), r.order_step)) \
                or z.q0 * ref * Decimal("0.98") < r.min_notional
    assert n_enter > 200 and n_skip >= 10 and "min_order_risk_over_cap" in skips, (n_enter, n_skip, skips)


def test_sweep_price_scale_changes_notional_not_rules():
    """Everything is derived from the current price and the exchange filters: ×0.5 / ×2 price moves the min qty the
    opposite way (no fixed price-based constant)."""
    s, r = "ETHUSDT", R["ETHUSDT"]
    qs = {}
    for pf in ("0.5", "1", "2"):
        ref = PRICE[s] * Decimal(pf)
        z = size_entry(r, BRACKETS[s], 100, 100, ref, ref * Decimal("0.03"), mark=ref)
        assert z.skip is None or z.skip == "min_order_risk_over_cap"
        qs[pf] = max(ceil_to(r.min_notional / (ref * Decimal("0.98")), r.order_step), r.order_min_qty)
    assert qs["0.5"] > qs["1"] > qs["2"] or qs["2"] == r.order_min_qty


def test_filter_values_drive_the_quantity():
    s, ref, dist = "SOLUSDT", PRICE["SOLUSDT"], Decimal("4.5")
    info = copy.deepcopy(INFO)
    base = size_entry(R[s], BRACKETS[s], 300, 300, ref, dist, mark=ref)
    sym = next(x for x in info["symbols"] if x["symbol"] == s)
    for f in sym["filters"]:
        if f["filterType"] == "MIN_NOTIONAL":
            f["notional"] = "50"
    big = size_entry(SymbolRules.from_exchange_info(info, s), BRACKETS[s], 300, 300, ref, dist, mark=ref)
    assert big.skip is None and big.qty > base.qty
    assert big.qty == ceil_to(Decimal(50) / (ref * Decimal("0.98")), Decimal("0.01"))


# ───────────────────────── no hard-coded price constants ─────────────────────────
def test_no_hardcoded_price_constants_in_sizing_path():
    root = Path(live_v6.__file__).parent
    ratios = {0, 1, 2, 3, 4, 5, 10, 100, 1000, 0.5, 0.25, 0.0004, 0.0003, 0.0005, 0.001, 0.0010, 0.005, 0.01, 0.02, 0.03,
              0.04, 0.05, 0.7, 0.9, 0.95, 0.99, 0.15, 1e-12, 1e-9, 1e-6, 0.2, 0.1, 0.0065, 0.005, 2.5, 6, 0.004, 0.025, 1.5, 7, 8, 9, 10.0}
    for fn in ("sizing.py", "rules.py"):
        tree = ast.parse((root / fn).read_text())
        bad = [(n.lineno, n.value) for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)
               and n.value not in ratios and not (isinstance(n.value, int) and abs(n.value) <= 100)]
        assert not bad, f"{fn}: unexplained numeric constants {bad}"
    for fn in ("sizing.py", "rules.py", "engine.py", "exchange.py"):
        assert "min_notional_floor" not in (root / fn).read_text(), fn
    from live_v6.engine import Settings
    assert not hasattr(Settings(), "min_notional_floor")
    assert [f for f in SizingParams.__dataclass_fields__ if "floor" in f or "usd" in f.lower() or "price" in f.lower()
            ] == ["price_buffer"]
    assert 0 < P.price_buffer < 0.1 and P.min_order_loss_cap == 0.03 and P.total_risk_cap == 0.05
    assert P.margin_use == 0.9 and P.risk_pct == 0.5 and P.portfolio_risk_cap == 0.025


def test_btc_100_usdt_floor_is_gone():
    r = SymbolRules.from_exchange_info(INFO, "BTCUSDT")
    assert r.min_notional == 50                                           # exchange value, no BTC-only 100


# ───────────────────────── engine: fresh reads, skips, qty_floor entry, rejection sequences ─────────────────────────
def _eng(offline, wallet=None, prices=None, **kw):
    if wallet is not None:
        offline.inner.wallet = Decimal(wallet)
    for k, v in (prices or {}).items():
        offline.inner.price[k] = Decimal(v)
    eng = offline.engine(**kw)
    eng.startup()
    assert eng.started and eng.entries_allowed(), eng.blocks
    return eng


def _no_state(eng, offline, sym="DOGEUSDT"):
    assert offline.inner.positions((sym,))[sym]["amt"] == 0
    assert not offline.inner.open_orders(sym), "pre-armed / any stop left on the exchange"
    assert not eng.st["intents"] and sym not in eng.st["pos"]


def _skips(eng):
    return [x[2] for x in eng.meta.get("skip_log", [])]


@pytest.mark.parametrize("mode,label", [
    ("exchange_info", "filter_read_failed"), ("brackets", "filter_read_failed"), ("book", "filter_read_failed"),
    ("mark_price", "filter_read_failed"), ("account", "filter_read_failed")])
def test_read_failure_skips_with_reason_and_places_nothing(offline, mode, label):
    eng = _eng(offline)
    offline.fx.inject(mode, "unavailable", times=20)
    assert not eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    last = eng.meta["skip_log"][-1]
    assert last[1] == "DOGEUSDT" and last[2] == label and ("Unavailable" in last[3] or mode in last[3]), last
    assert not [c for c in offline.fx.calls if c[0] in ("market", "stop")]
    _no_state(eng, offline)


def test_exchange_info_malformed_skips(offline):
    eng = _eng(offline)
    offline.fx.inject("exchange_info", lambda fn, *a, **k: {"symbols": []})
    assert not eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    assert eng.meta["skip_log"][-1][2] == "filter_read_failed"
    assert not [c for c in offline.fx.calls if c[0] in ("market", "stop")]


def test_every_order_rereads_filters_wallet_and_price(offline):
    eng = _eng(offline)
    assert eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    names = [c[0] for c in offline.fx.calls]
    first_market = names.index("market")
    pre = names[:first_market]
    assert pre.count("exchange_info") >= 3 and pre.count("brackets") >= 2 and pre.count("account") >= 2   # startup + 2 passes
    assert pre.count("book") >= 2 and pre.count("mark_price") >= 2
    last_info = max(i for i, n in enumerate(pre) if n == "exchange_info")
    assert last_info > (max(i for i, n in enumerate(pre) if n == "set_leverage") if "set_leverage" in pre else -1)


def test_second_pass_uses_changed_wallet_and_price(offline):
    """Wallet and price change between pass 1 and the order → qty follows the NEW values (nothing is cached)."""
    eng = _eng(offline, wallet="1000")
    seen = []
    orig = offline.inner.account

    def acct():
        a = orig()
        if any(c[0] == "set_leverage" for c in offline.fx.calls) or offline.inner.lev["DOGEUSDT"] != 20:
            a = dict(a, wallet=a["wallet"] / 2, available=a["available"] / 2, equity=a["equity"] / 2)
        seen.append(a["wallet"])
        return a
    offline.inner.account = acct
    first = {}
    offline.fx.inject("market", lambda fn, s, side, qty, *a, **k: (first.setdefault("q", qty), fn(s, side, qty, *a, **k))[1])
    assert eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    full = size_entry(R["DOGEUSDT"], BRACKETS["DOGEUSDT"], 1000, 1000, PRICE["DOGEUSDT"], Decimal("0.0045"), mark=PRICE["DOGEUSDT"])
    assert Decimal(first["q"]) <= full.qty and Decimal(first["q"]) > 0


def test_qty_floor_entry_end_to_end_btc_live_case(offline, caplog):
    """Live 10/21 23:35 BTC: wallet 117.47, ref 84134.3, stop 1562 → old: skip; new: min qty 0.001, loss ≈1.45%."""
    eng = _eng(offline, wallet="117.46733957", prices={"BTCUSDT": "84134.3"}, symbols=("BTCUSDT",),
               entry_order=("BTCUSDT",))
    with caplog.at_level(logging.INFO):
        assert eng.enter("BTCUSDT", Decimal("1562.0"), unique_T())
    assert offline.inner.positions(("BTCUSDT",))["BTCUSDT"]["amt"] == Decimal("0.001")
    j = eng.st["pos"]["BTCUSDT"]
    assert j["qty"] == "0.001" and offline.inner.open_orders("BTCUSDT")
    line = next(m for m in (r.getMessage() for r in caplog.records) if m.startswith("qty_floor BTCUSDT"))
    assert "0.001" in line and "1.4" in line and "3%" in line
    assert any("qty_floor" in m for m in eng.tg.sent) and eng.meta["floor_log"][-1][1] == "BTCUSDT"


def test_min_qty_loss_over_3pct_skips_without_orders(offline):
    eng = _eng(offline, wallet="40", prices={"BTCUSDT": "84134.3"}, symbols=("BTCUSDT",), entry_order=("BTCUSDT",))
    assert not eng.enter("BTCUSDT", Decimal("1562.0"), unique_T())      # 0.001 × 1562 = 1.56 + fees > 3% of 40
    z = eng.meta["skip_log"][-1]
    assert z[2] == "min_order_risk_over_cap" and "3%" in z[3], z
    assert not [c for c in offline.fx.calls if c[0] in ("market", "stop")]


@pytest.mark.parametrize("code,msg", [(-4164, "Order's notional must be no smaller than 5 (unless reduce only)"),
                                      (-2019, "Margin is insufficient."), (-1013, "Filter failure: LOT_SIZE"),
                                      (-1013, "Filter failure: MARKET_LOT_SIZE"), (-2021, "Order would immediately trigger."),
                                      (-4003, "Quantity less than zero.")])
def test_entry_rejected_cancels_prearm_and_leaves_no_state(offline, code, msg):
    eng = _eng(offline)

    def reject(fn, s, side, qty, cid, reduce_only=False, **k):
        if reduce_only:
            return fn(s, side, qty, cid, reduce_only, **k)
        raise OrderRejected(code, msg)
    offline.fx.inject("market", reject, times=1)
    assert not eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    names = [c[0] for c in offline.fx.calls]
    assert names.index("stop") < names.index("market") < len(names) - names[::-1].index("cancel")   # pre-arm → entry → cancel
    assert eng.meta["skip_log"][-1][2] == "entry_rejected"
    assert any("진입 주문 거절" in m for m in eng.tg.sent)
    _no_state(eng, offline)
    assert not close_calls(offline)                                       # nothing was open → nothing to flatten
    offline.assert_safe()
    # the next signal (new bar) works again — no leftover state blocked the coin
    assert eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    offline.assert_safe()


@pytest.mark.parametrize("exc", [WouldTrigger(-2021, "Order would immediately trigger."),
                                 OrderRejected(-1013, "Filter failure: PRICE_FILTER"),
                                 OrderRejected(-4130, "An open stop order is existing.")])
def test_prearm_rejected_means_no_entry(offline, exc):
    eng = _eng(offline)

    def boom(fn, *a, **k):
        raise exc
    offline.fx.inject("stop", boom, times=1)
    assert not eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    assert eng.meta["skip_log"][-1][2] == "stop_prearm"
    assert not [c for c in offline.fx.calls if c[0] == "market"]
    _no_state(eng, offline)


@pytest.mark.parametrize("exc", [WouldTrigger(-2021, "Order would immediately trigger."),
                                 OrderRejected(-1013, "Filter failure: PRICE_FILTER"),
                                 OrderRejected(-4509, "TIF GTE can only be used with open positions.")])
def test_entry_fills_but_stop_rejected_flattens_everything_and_alerts(offline, exc):
    eng = _eng(offline)

    def only_close_position(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise exc
        return fn(s, side, trigger, cid, qty=qty, **k)
    offline.fx.inject("stop", only_close_position, times=10)
    assert not eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    assert offline.inner.positions(("DOGEUSDT",))["DOGEUSDT"]["amt"] == 0, "half/naked position left"
    assert not offline.inner.open_orders("DOGEUSDT")
    assert any("손절 거절" in m for m in alerts(eng)), eng.tg.sent
    assert len(close_calls(offline)) == 1 and not eng.st["intents"] and "DOGEUSDT" not in eng.st["pos"]
    offline.assert_safe()


def test_stop_unknown_outcome_keeps_prearm_so_position_is_never_naked(offline):
    eng = _eng(offline)
    offline.fx.inject("stop", lambda fn, s, side, trigger, cid, qty=None, **k:
                      (_ for _ in ()).throw(ExchangeUnavailable("down")) if qty is None else fn(s, side, trigger, cid, qty=qty, **k),
                      times=10)
    eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    amt = offline.inner.positions(("DOGEUSDT",))["DOGEUSDT"]["amt"]
    assert amt == 0 or offline.stops("DOGEUSDT"), "position without any exchange stop"
    offline.assert_safe()


# ── TA (b): bounded confirmation of the protective stop after an unknown placement outcome ──
# Exact window in the code (engine.Settings): stop_attempts = 3, stop_retry_delay_s = 3.0 s. Round 1 = _upgrade_stop (3 closePosition
# attempts, sleeps between them) → pre-arm verified via open_orders → round 2 = protect()/ensure_stop (3 attempts, same delay).
# Still no confirmed stop after that → this position is flattened in full + 🚨. Nothing waits for api_dead_s (300 s, flatten-all).
def _cp_stop_attempts(offline):
    return [c for c in offline.fx.calls if c[0] == "stop" and not str(c[1][3]).endswith("p")]   # pre-arm cid ends in 'p' 


def _closeposition_down(offline):
    def f(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise ExchangeUnavailable("down")
        return fn(s, side, trigger, cid, qty=qty, **k)
    offline.fx.inject("stop", f, times=100)


def _sleeps(eng):
    rec = []
    eng.sleep = rec.append
    return rec


def test_stop_window_constants_are_the_documented_ones():
    from live_v6.engine import Settings
    assert (Settings().stop_attempts, Settings().stop_retry_delay_s) == (3, 3.0)


def test_unknown_stop_outcome_with_prearm_verified_keeps_it_and_does_not_flatten(offline):
    eng = _eng(offline)
    sl = _sleeps(eng)
    _closeposition_down(offline)
    eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    assert offline.inner.positions(("DOGEUSDT",))["DOGEUSDT"]["amt"] != 0
    assert offline.stops("DOGEUSDT"), "verified pre-arm must stay"
    assert not close_calls(offline) and not alerts(eng)
    assert len(_cp_stop_attempts(offline)) == eng.cfg.stop_attempts
    assert sum(sl) <= (eng.cfg.stop_attempts - 1) * eng.cfg.stop_retry_delay_s       # ≤ 6 s of waiting
    offline.assert_safe()


@pytest.mark.parametrize("how", ["reads_fail", "prearm_gone"])
def test_unconfirmed_stop_after_the_bounded_window_flattens_in_full_with_alert(offline, how):
    eng = _eng(offline)
    sl = _sleeps(eng)
    _closeposition_down(offline)

    def entered_not_closed():
        mk = [c for c in offline.fx.calls if c[0] == "market"]
        return bool(mk) and not any(len(c) > 1 and len(c[1]) > 4 and c[1][4] for c in mk)

    def oo(fn, sym):
        if not entered_not_closed():
            return fn(sym)
        if how == "reads_fail":
            raise ExchangeUnavailable("read down")
        return [o for o in fn(sym) if not o["client_id"].endswith("p")]          # pre-arm not visible
    offline.fx.inject("open_orders", oo, times=1000)
    eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    assert offline.inner.positions(("DOGEUSDT",))["DOGEUSDT"]["amt"] == 0, "must be flattened, not left unconfirmed"
    assert any("손절 미확인" in m for m in alerts(eng)), eng.tg.sent
    assert len(close_calls(offline)) == 1                                           # one single full exit
    assert len(_cp_stop_attempts(offline)) <= 2 * eng.cfg.stop_attempts              # bounded: 2 rounds × 3
    assert sum(sl) <= 2 * (eng.cfg.stop_attempts - 1) * eng.cfg.stop_retry_delay_s   # ≤ 12 s of waiting in total


def test_no_alias_label_strings_in_emitted_skip_reasons(offline, caplog):
    """TA (a): only the spec names reach skip records / logs / notifier; aliases live in comments only."""
    import re
    alias = re.compile(r"(?<![A-Za-z_])(loss_cap|open_risk_cap)(?![A-Za-z_])")
    seen = set()
    scen = [dict(wallet="20", prices={}),                                    # min-qty path, cap exceeded
            dict(wallet="1000", prices={}),                                   # normal q0 entry
            dict(wallet="100", prices={"DOGEUSDT": "0.0045"})]
    with caplog.at_level("DEBUG"):
        for sc in scen:
            eng = _eng(offline, wallet=sc["wallet"], prices=sc["prices"])
            eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
            eng.enter("DOGEUSDT", Decimal("0.0045") * 80, unique_T())          # huge stop distance → other labels
            for x in eng.meta.get("skip_log", []):
                seen.add(x[2])
                assert not alias.search(" ".join(map(str, x))), x
            assert not any(alias.search(m) for m in eng.tg.sent)
    assert not alias.search(caplog.text)
    # every label the sizing path can emit, driven through size_entry directly
    for sym in COINS:
        r = R[sym]
        for w in (5, 30, 1000):
            for f in (0.2, 1, 5):
                dist = max(ceil_to(PRICE[sym] * Decimal("0.024") * Decimal(str(f)), r.tick_size), r.tick_size)
                z = size_entry(r, BRACKETS[sym], Decimal(w), Decimal(w), PRICE[sym], dist, mark=PRICE[sym])
                if z.skip:
                    seen.add(z.skip)
                    assert not alias.search(z.skip + " " + z.detail), z
    assert "min_order_risk_over_cap" in seen and seen <= KNOWN, seen
    for f in ("sizing.py", "engine.py"):              # no alias string LITERAL anywhere in the code (comments are fine)
        src = (Path(__file__).parent.parent / f).read_text()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                assert not alias.search(n.value), (f, n.value)


def test_q0_zero_goes_to_min_qty_path_and_is_not_labelled_qty_zero():
    s = "BTCUSDT"
    r = R[s]
    z = size_entry(r, BRACKETS[s], Decimal("20"), Decimal("20"), PRICE[s], PRICE[s] * Decimal("0.03"), mark=PRICE[s])
    assert z.q0 == 0 and z.skip == "min_order_risk_over_cap" and "q0=0 " in z.detail and "qty_zero" not in z.detail, z


def test_qty_zero_only_when_min_qty_path_is_unreachable():
    import dataclasses
    s = "BTCUSDT"
    r = dataclasses.replace(R[s], min_qty=Decimal(0), min_notional=Decimal(0), mkt_min_qty=Decimal(0))
    z = size_entry(r, BRACKETS[s], Decimal("20"), Decimal("20"), PRICE[s], PRICE[s] * Decimal("0.03"), mark=PRICE[s])
    assert z.skip == "qty_zero", z


# ───────────────────────── exact-boundary killers (mutation round, 2026-10-26) ─────────────────────────
# Float tolerance of the cap compares is 1e-12 (`> cap + 1e-12`), so "<=" vs "<" can only be told apart AT cap + 1e-12:
# the helpers below build inputs whose float sum equals that value bit-for-bit.
import math  # noqa: E402

TOL = 1e-12


def _exact_open(rf: float, target: float) -> float:
    """open-risk value o with o + rf == target in float arithmetic (search the neighbouring floats)."""
    o = target - rf
    for _ in range(64):
        if 0 + o + rf == target:
            return o
        o = math.nextafter(o, math.inf if o + rf < target else -math.inf)
    raise AssertionError("no float o with o + rf == target")


def test_cap_3pct_exact_boundary_enters_and_tolerance_edge_enters_just_above_skips():
    s, ref = "BTCUSDT", PRICE["BTCUSDT"]
    dist = Decimal("1800")
    worst = ref * Decimal("0.98")
    q_min = max(ceil_to(R[s].min_notional / worst, R[s].order_step), ceil_to(R[s].order_min_qty, R[s].order_step))
    p = SizingParams()
    loss = q_min * dist + q_min * ref * (2 * Decimal("0.0005") + Decimal(str(p.entry_slippage)) + Decimal(str(p.stop_slippage)))
    for target, ok in ((0.03, True), (0.03 + TOL, True), (0.03 + 5 * TOL, False), (0.03 - 1e-6, True), (0.03 + 1e-6, False)):
        wallet = loss / Decimal(target)                                   # loss_frac == target to ~1e-27 relative
        z = size_entry(R[s], BRACKETS[s], wallet, wallet, ref, dist, mark=ref)
        assert (z.skip is None) is ok, (target, z.skip, z.loss_frac)
        if z.skip is None:
            assert z.path == "qty_floor"
        else:
            assert z.skip == "min_order_risk_over_cap"
    wallet = loss / Decimal(0.03 + TOL)
    assert size_entry(R[s], BRACKETS[s], wallet, wallet, ref, dist, mark=ref).loss_frac == 0.03 + TOL   # the edge really is hit


@pytest.mark.parametrize("path", ["qty_floor", "q0"])
def test_open_risk_cap_exact_boundaries_5pct_and_2_5pct(path):
    if path == "qty_floor":
        s, ref, dist, wallet, cap, label = "BTCUSDT", PRICE["BTCUSDT"], Decimal("1800"), 100, 0.05, "total_risk_cap"
    else:
        s, ref, dist, wallet, cap, label = "DOGEUSDT", PRICE["DOGEUSDT"], Decimal("0.009"), 1000, 0.025, "risk_cap_portfolio"
    z0 = size_entry(R[s], BRACKETS[s], wallet, wallet, ref, dist, mark=ref)
    assert z0.skip is None and z0.path == path and z0.cap_frac == cap
    rf = z0.risk_frac
    def run(open_risk):
        return size_entry(R[s], BRACKETS[s], wallet, wallet, ref, dist, 1, [{"side": 1, "risk_frac": open_risk}], mark=ref)
    assert run(cap - rf).skip is None                                   # sum == cap exactly → allowed (≤)
    assert run(cap - rf - 1e-4).skip is None
    z = run(cap - rf + 1e-6)                                            # a hair over → skipped with the spec label
    assert z.skip == label and z.skip not in ("loss_cap", "open_risk_cap")
    assert run(cap - rf + 1e-3).skip == label                           # a loosened cap (cap + 1e-3) would let this in
    assert run(_exact_open(rf, cap + TOL)).skip is None                 # tolerance edge: sum == cap + 1e-12 → allowed
    assert run(_exact_open(rf, cap + 3 * TOL)).skip == label


def test_min_notional_equality_is_allowed_in_precheck_and_q0_path():
    """qty·worst == minNotional exactly (buffer 50% keeps the decimal math exact): allowed by `<`, rejected by `<=`;
    q0·worst == minNotional stays on the q0 path (`>=`), not qty_floor."""
    s, ref = "BTCUSDT", Decimal("100000")
    p = SizingParams(price_buffer=0.5)
    r = R[s]
    qty = Decimal("0.001")                                              # 0.001 × 100000 × 0.5 == 50 == minNotional
    assert qty * ref * Decimal("0.5") == r.min_notional
    args = (r, BRACKETS[s], qty, ref, 5, stop_for(s, ref), 10**6, 1)
    assert precheck_order(*args, mark=ref, p=p)[0] is None
    assert precheck_order(r, BRACKETS[s], qty, ref - r.tick_size, 5, stop_for(s, ref), 10**6, 1, mark=ref, p=p)[0] == "below_min_notional"
    z = size_entry(r, BRACKETS[s], 1000, 1000, ref, Decimal("3000"), mark=ref, p=p)
    assert z.q0 == qty and z.path == "q0" and z.qty == qty and z.skip is None, z


@pytest.mark.parametrize("delta,skipped", [(0.0, False), (1e-12, False), (5e-4, True)])
def test_engine_second_pass_open_risk_guard_boundary(offline, monkeypatch, delta, skipped):
    """The engine re-checks Σ open risk + new ≤ cap on the second pass (defence behind size_entry's identical check).
    size_entry is stubbed to hand back a risk_frac of cap + delta so that guard itself is what decides."""
    import live_v6.engine as engmod
    real = engmod.size_entry

    def stub(*a, **k):
        z = real(*a, **k)
        return dataclasses.replace(z, risk_frac=z.cap_frac + delta) if (k.get("fixed_lev") and z.skip is None) else z
    monkeypatch.setattr(engmod, "size_entry", stub)
    eng = _eng(offline, wallet="1000")
    ok = eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    last = eng.meta["skip_log"][-1][2] if eng.meta.get("skip_log") else None
    assert ok is (not skipped), (ok, last)
    if skipped:
        assert last == "risk_cap_portfolio"
        assert offline.inner.positions(("DOGEUSDT",))["DOGEUSDT"]["amt"] == 0
        assert not [c for c in offline.fx.calls if c[0] == "market"]


# ───────────── orphan pre-arm after an entry rejection whose cancel FAILED (TA condition 1, 2026-10-26) ─────────────
def _reject_entry_and_fail_cancel(offline, cancel_failures=1):
    """Entry definitively rejected (-4164) AND the pre-arm cancel fails (`_cancel_quiet` only logs) → orphan pre-arm."""
    eng = _eng(offline)

    def reject(fn, s, side, qty, cid, reduce_only=False, **k):
        if reduce_only:
            return fn(s, side, qty, cid, reduce_only, **k)
        raise OrderRejected(-4164, "Order's notional must be no smaller than 5")
    offline.fx.inject("market", reject, times=1)
    offline.fx.inject("cancel", "unavailable", times=cancel_failures)
    assert not eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    assert eng.meta["skip_log"][-1][2] == "entry_rejected" and not eng.st["intents"]
    orphans = [o for o in offline.inner.open_orders("DOGEUSDT") if o["client_id"].endswith("p")]
    assert len(orphans) == 1 and orphans[0]["reduce_only"] and not orphans[0]["close_position"]    # the orphan exists
    return eng, orphans[0]


def test_orphan_prearm_after_failed_cancel_is_removed_by_reconcile_when_flat(offline):
    eng, orphan = _reject_entry_and_fail_cancel(offline, cancel_failures=3)
    mine = offline.inner.stop("DOGEUSDT", "SELL", Decimal("0.10"), "my_hedge_p", qty=Decimal(1))     # user's own order, not ours
    eng.reconcile()                                  # cancel fails again (3 injected failures: 1 in enter, 2 here)
    eng.reconcile()
    eng.reconcile()                                  # API healthy again → removed
    assert [o["id"] for o in offline.inner.open_orders("DOGEUSDT")] == [mine["id"]]      # only the orphan was removed
    assert offline.amt("DOGEUSDT") == 0 and not eng.st["pos"] and not eng.st["intents"] and not eng.st["unknown"]
    assert eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())      # the coin trades normally afterwards
    offline.assert_safe()


def test_orphan_prearm_never_becomes_the_stop_of_a_manual_position_in_the_same_coin(offline):
    """A user opens a manual DOGE position (with his own stop) while the orphan bot pre-arm is still live: the bot's
    orphan must be cancelled, the manual position and the manual stop must be left exactly as they are."""
    eng, orphan = _reject_entry_and_fail_cancel(offline)
    offline.inner.open_position_raw("DOGEUSDT", 1)                   # manual position, smaller than the orphan's qty
    manual = offline.inner.stop("DOGEUSDT", "SELL", Decimal("0.10"), "web_manual_stop")        # his own closePosition stop
    manual2 = offline.inner.stop("DOGEUSDT", "SELL", Decimal("0.12"), "my_hedge_p", qty=Decimal(1))   # his reduceOnly stop, id also ends in "p"
    eng.reconcile()
    left = {o["client_id"]: o for o in offline.inner.open_orders("DOGEUSDT")}
    assert set(left) == {"web_manual_stop", "my_hedge_p"}, left       # orphan gone, BOTH manual orders untouched (no prefix → not ours)
    assert left["my_hedge_p"]["id"] == manual2["id"]
    assert left["web_manual_stop"]["id"] == manual["id"] and left["web_manual_stop"]["stop_price"] == Decimal("0.10")
    assert offline.amt("DOGEUSDT") == 1 and not close_calls(offline)  # manual position untouched, nothing closed
    u = eng.st["unknown"]["DOGEUSDT"]
    assert u["stop_cid"] == "web_manual_stop" and Decimal(u["stop_px"]) == Decimal("0.10")      # protection = HIS stop


def test_unresolved_entry_keeps_its_prearm_through_a_flat_reconcile(offline):
    """Counter-test of the cleanup: entry outcome unknown (intent kept, order status unreadable) → the pre-arm is NOT an
    orphan and a flat-account reconcile must leave it alone; once the intent resolves it is cleaned."""
    eng = _eng(offline)
    offline.fx.inject("market", "unavailable", times=1)
    offline.fx.inject("get_order", "unavailable", times=50)
    eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    assert eng.st["intents"]
    eng.reconcile()
    assert eng.st["intents"] and [o["client_id"] for o in offline.inner.open_orders("DOGEUSDT")] == [f"{c}p" for c in eng.st["intents"]]
    offline.fx.clear()
    eng.reconcile()
    assert not eng.st["intents"] and not offline.inner.open_orders("DOGEUSDT") and offline.amt("DOGEUSDT") == 0


def test_orphan_prearm_stays_until_the_bot_has_its_own_stop_for_an_unowned_position(offline):
    """If the bot cannot place its own unknown-position stop yet, the orphan is not cancelled (never leave a position
    with NO stop because of cleanup); it is removed as soon as the bot's own stop is confirmed."""
    eng, orphan = _reject_entry_and_fail_cancel(offline)
    offline.inner.open_position_raw("DOGEUSDT", 1)
    offline.fx.inject("stop", "unavailable", times=1)
    eng.reconcile()
    assert [o["client_id"] for o in offline.inner.open_orders("DOGEUSDT")] == [orphan["client_id"]]
    eng.reconcile()
    left = offline.inner.open_orders("DOGEUSDT")
    assert len(left) == 1 and left[0]["close_position"] and left[0]["client_id"].startswith("v6tDOGEu")


def test_orphan_prearm_is_not_adopted_as_protection_of_a_manual_position_without_stop(offline):
    eng, orphan = _reject_entry_and_fail_cancel(offline)
    offline.inner.open_position_raw("DOGEUSDT", 1)                   # manual, no stop of his own
    eng.reconcile()
    left = offline.inner.open_orders("DOGEUSDT")
    assert orphan["client_id"] not in [o["client_id"] for o in left]  # orphan cancelled, NOT adopted as "existing stop"
    assert len(left) == 1 and left[0]["close_position"] and left[0]["client_id"].startswith("v6tDOGEu")   # bot's own unknown-position stop
    assert eng.st["unknown"]["DOGEUSDT"]["stop_cid"] == left[0]["client_id"]
    assert offline.amt("DOGEUSDT") == 1 and not close_calls(offline)


def test_exit_is_one_full_reduce_only_order(offline):
    eng = _eng(offline, wallet="1000")
    assert eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    amt = offline.inner.positions(("DOGEUSDT",))["DOGEUSDT"]["amt"]
    assert eng.close("DOGEUSDT", "test")
    assert offline.inner.positions(("DOGEUSDT",))["DOGEUSDT"]["amt"] == 0
    cc = close_calls(offline)
    assert len(cc) == 1 and Decimal(str(cc[0][1][2])) == amt
    assert len([c for c in offline.fx.calls if c[0] == "market" and not (len(c[1]) > 4 and c[1][4])]) == 1   # one entry
