# H100 funding carry v1.1: spot long + equal-notional futures short (3x), per-coin slot simulator.
# Rule source: TA lock prereg-lock-h100-funding-v1_1.md (89752618a943) and QR spec v1.1 (088ddd8c5c68).
# Safety rules R1/R3/R4 (ops-safety-rules-v1-2026-10-29.md) are modelled as explicit order/leg state.
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

EPS = 1e-12


@dataclass(frozen=True)
class Params:
    n_mean: int = 9               # last 9 prints = 3 days at 8h
    entry_mean: float = 0.00015   # >= 0.015%/8h
    entry_last: float = 0.00010   # last print >= 0.010%
    exit_mean: float = 0.00005    # mean < 0.005%
    exit_last: float = -0.00010   # last print < -0.010%
    x_frac: float = 0.75          # X = 0.75 C (spot X, short notional X, margin X/3)
    lev: float = 3.0
    sl: float = 0.20              # short SL at entry * 1.20
    tp: float = 0.20              # short TP at entry * 0.80
    liq: float = 0.31             # liquidation at entry * 1.31 (spec value, see SPEC_NOTES)


@dataclass(frozen=True)
class Costs:
    spot_fee: float = 0.0010
    fut_fee: float = 0.0005
    slip: float = 0.0002
    sl_extra_slip: float = 0.0010
    mult: float = 1.0

    @property
    def spot_side(self):
        return (self.spot_fee + self.slip) * self.mult

    @property
    def fut_side(self):
        return (self.fut_fee + self.slip) * self.mult


def entry_signal(last9, p):
    return len(last9) >= p.n_mean and float(np.mean(last9)) >= p.entry_mean - EPS and float(last9[-1]) >= p.entry_last - EPS


def exit_signal(last9, p):
    return float(np.mean(last9)) < p.exit_mean - EPS or float(last9[-1]) < p.exit_last - EPS


@dataclass
class CoinResult:
    eq_close: pd.Series
    eq_worst: pd.Series
    fut_held: pd.Series
    spot_held: pd.Series
    trades: list = field(default_factory=list)
    n_entries: int = 0
    n_sl: int = 0
    n_tp: int = 0
    n_liq: int = 0
    n_signal_exits: int = 0
    one_leg_hours: int = 0
    residual_violations: int = 0
    max_open_orders: int = 0
    open_orders_at_end: int = 0
    tp_qty_fraction: float = 1.0
    funding_pnl: float = 0.0
    cost_pnl: float = 0.0
    spot_pnl: float = 0.0
    fut_pnl: float = 0.0
    liq_loss: float = 0.0
    deferred_signal_exits: int = 0
    skipped_entries_missing_bar: int = 0
    in_pos_at_end: bool = False


def simulate_coin(bars, funding, cap0, p=Params(), c=Costs()):
    # bars: hourly DataFrame (f_open..f_close, s_open..s_close; NaN = no bar). funding: Series of prints by settlement ts.
    idx = bars.index
    fo, fh, fl, fc = (bars["f_" + k].to_numpy(float) for k in ("open", "high", "low", "close"))
    so, sh, sl_, sc = (bars["s_" + k].to_numpy(float) for k in ("open", "high", "low", "close"))
    fr = funding.sort_index()
    fr_ts = fr.index
    fr_v = fr.to_numpy(float)
    pos_of = {t: i for i, t in enumerate(fr_ts)}

    n = len(idx)
    eq_close = np.empty(n)
    eq_worst = np.empty(n)
    fut_h = np.zeros(n, bool)
    spot_h = np.zeros(n, bool)
    R = CoinResult(pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=bool), pd.Series(dtype=bool))

    cash = cap0
    fut_on = spot_on = False
    q_s = q_f = S0 = F0 = X = 0.0
    orders = set()
    pending_signal_exit = False
    trade = None
    last_s = np.nan
    last_f = np.nan

    def end_trade_check():
        # R3: after any exit all orders for the coin are cancelled and both legs are flat
        if orders or fut_on or spot_on:
            R.residual_violations += 1

    for i in range(n):
        ts = idx[i]
        s_ok = not np.isnan(so[i])
        f_ok = not np.isnan(fo[i])
        if f_ok:
            last_f = fc[i]
        is_settle = ts in pos_of
        last9 = None
        if is_settle:
            k = pos_of[ts]
            last9 = fr_v[max(0, k - p.n_mean + 1): k + 1] if k + 1 >= p.n_mean else None

        # 1) funding at settlement for a short held through the settlement instant
        if fut_on and is_settle:
            mark = fo[i] if f_ok else last_f
            amt = fr_v[pos_of[ts]] * q_f * mark
            cash += amt
            R.funding_pnl += amt
            trade["funding"] += amt

        # 2) signal exit at this bar open (both legs together; wait if either leg has no bar)
        if fut_on and spot_on and is_settle and last9 is not None and exit_signal(last9, p):
            pending_signal_exit = True
        if pending_signal_exit and fut_on and spot_on:
            if f_ok and s_ok:
                _close_fut(R, trade, c, ts, fo[i], q_f, F0, "signal")
                cash += q_f * (F0 - fo[i]) - q_f * fo[i] * c.fut_side
                _close_spot(R, trade, c, ts, so[i], q_s, S0)
                cash += q_s * (so[i] - S0) - q_s * so[i] * c.spot_side
                fut_on = spot_on = False
                orders.clear()
                pending_signal_exit = False
                R.n_signal_exits += 1
                R.trades.append(trade)
                end_trade_check()
                trade = None
            else:
                if trade is not None and not trade.get("_deferred"):
                    trade["_deferred"] = True
                    R.deferred_signal_exits += 1

        # 3) a spot leg left alone (spot bar was missing when the short closed): sell at first available open
        if spot_on and not fut_on and s_ok:
            _close_spot(R, trade, c, ts, so[i], q_s, S0)
            cash += q_s * (so[i] - S0) - q_s * so[i] * c.spot_side
            spot_on = False
            R.trades.append(trade)
            end_trade_check()
            trade = None

        # 4) entry at this settlement bar open
        entered_now = False
        if not fut_on and not spot_on and is_settle and last9 is not None and entry_signal(last9, p):
            if f_ok and s_ok:
                C = cash
                X = p.x_frac * C
                S0, F0 = so[i], fo[i]
                q_s, q_f = X / S0, X / F0
                ec = X * c.spot_side + X * c.fut_side
                cash -= ec
                R.cost_pnl -= ec
                fut_on = spot_on = True
                assert F0 * (1 + p.sl) < F0 * (1 + p.liq)  # R1: stop inside liquidation
                orders = {"SL", "TP"}  # R1: both resting on the exchange right after entry, full qty
                R.max_open_orders = max(R.max_open_orders, len(orders))
                R.n_entries += 1
                entered_now = True
                trade = dict(entry_ts=ts, slot_cap=C, X=X, spot_entry_px=S0, fut_entry_px=F0, funding=0.0,
                             cost=-ec, exit_ts=None, exit_reason=None, fut_exit_px=None, spot_exit_px=None,
                             spot_exit_ts=None, spot_pnl=0.0, fut_pnl=0.0)
            else:
                R.skipped_entries_missing_bar += 1

        # 5) intrabar: liquidation / SL / TP on the short (exchange orders), using the futures 1h bar
        worst = None
        if fut_on and f_ok:
            sl_px = F0 * (1 + p.sl)
            tp_px = F0 * (1 - p.tp)
            liq_px = F0 * (1 + p.liq)
            margin = X / p.lev
            s_low = sl_[i] if s_ok else last_s
            fut_worst = max(-margin, q_f * (F0 - fh[i]))
            spot_worst = q_s * (s_low - S0) if spot_on else 0.0
            worst = cash + spot_worst + fut_worst
            reason = None
            if fh[i] >= liq_px * (1 - EPS):
                reason = "liq"
                cash -= margin
                R.liq_loss -= margin
                R.fut_pnl -= margin
                trade["fut_pnl"] -= margin
                trade.update(exit_ts=ts, exit_reason="liq", fut_exit_px=liq_px)
                R.n_liq += 1
            elif fh[i] >= sl_px * (1 - EPS):
                reason = "sl"
                fill = max(sl_px, fo[i]) * (1 + c.sl_extra_slip * c.mult)
                _close_fut(R, trade, c, ts, fill, q_f, F0, "sl")
                cash += q_f * (F0 - fill) - q_f * fill * c.fut_side
                R.n_sl += 1
            elif fl[i] <= tp_px * (1 + EPS):
                reason = "tp"
                _close_fut(R, trade, c, ts, tp_px, q_f, F0, "tp")
                cash += q_f * (F0 - tp_px) - q_f * tp_px * c.fut_side
                R.n_tp += 1
            if reason is not None:
                fut_on = False
                orders.clear()  # R3: the other resting order is cancelled with the fill
                pending_signal_exit = False
                if s_ok:  # R4: spot sold at the same bar close
                    _close_spot(R, trade, c, ts, sc[i], q_s, S0)
                    cash += q_s * (sc[i] - S0) - q_s * sc[i] * c.spot_side
                    spot_on = False
                    R.trades.append(trade)
                    end_trade_check()
                    trade = None
        elif fut_on or spot_on:
            # no futures bar (not expected after the v2 fill): mark at last prices
            s_low = sl_[i] if s_ok else last_s
            worst = cash + (q_s * (s_low - S0) if spot_on else 0.0) + (q_f * (F0 - last_f) if fut_on else 0.0)

        if s_ok:
            last_s = sc[i]
        s_mark = sc[i] if s_ok else last_s
        f_mark = fc[i] if f_ok else last_f
        eq = cash + (q_s * (s_mark - S0) if spot_on else 0.0) + (q_f * (F0 - f_mark) if fut_on else 0.0)
        eq_close[i] = eq
        eq_worst[i] = eq if worst is None else min(worst, eq)
        fut_h[i] = fut_on
        spot_h[i] = spot_on
        if fut_on != spot_on:
            R.one_leg_hours += 1

    R.eq_close = pd.Series(eq_close, index=idx)
    R.eq_worst = pd.Series(eq_worst, index=idx)
    R.fut_held = pd.Series(fut_h, index=idx)
    R.spot_held = pd.Series(spot_h, index=idx)
    R.open_orders_at_end = len(orders) if not (fut_on or spot_on) else 0
    R.in_pos_at_end = fut_on or spot_on
    if trade is not None:
        trade["open_at_end"] = True
        R.trades.append(trade)
    return R


def _close_fut(R, trade, c, ts, px, q_f, F0, reason):
    pnl = q_f * (F0 - px)
    fee = q_f * px * c.fut_side
    R.fut_pnl += pnl
    R.cost_pnl -= fee
    trade["fut_pnl"] += pnl
    trade["cost"] -= fee
    trade.update(exit_ts=ts, exit_reason=reason, fut_exit_px=px)


def _close_spot(R, trade, c, ts, px, q_s, S0):
    pnl = q_s * (px - S0)
    fee = q_s * px * c.spot_side
    R.spot_pnl += pnl
    R.cost_pnl -= fee
    trade["spot_pnl"] += pnl
    trade["cost"] -= fee
    trade.update(spot_exit_px=px, spot_exit_ts=ts)


def block_bootstrap_lb(x, block, n_boot, seed, alpha):
    # moving-block bootstrap of the mean; returns the alpha quantile (one-sided lower bound)
    x = np.asarray(x, float)
    n = len(x)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(n_boot, nb))
    offs = np.arange(block)
    means = np.empty(n_boot)
    for b in range(n_boot):
        ix = (starts[b][:, None] + offs[None, :]).ravel()[:n]
        means[b] = x[ix].mean()
    return float(np.quantile(means, alpha))
