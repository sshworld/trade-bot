"""Bundle v2 + V5 regime risk + E3 full trailing exit — the account book, ported from the research engine.

Source (read-only): lab/p179_exit_decision/engine.py `run(...)` (= p177 v5_fixed.py + p179 exit variants), called by
p179 run.py as run(meta, tape, lo, hi, fee, W, -1, 6., True, REG, 1.25, .75, True, variant=3, None). Only the
variant=3 (E3: full position trailed, no take-profit) path is ported; the other variants' branches are dropped.
The arithmetic below is a line-by-line transcription (same operation order → same IEEE doubles). Do not "improve" it:
`tests/test_bundle_v5_match.py` replays the original candidate tape and requires the original trades.

Components (g): 0 M macro (BTC/ETH, 72 h), 1 D delist short (24 h / settlement − 30 min), 2 R 4h-range retest (48 h),
3 H 52-week-high breakout (7 d). Slots: at most 7 positions; per component M 2 / D 1 / R 2 / H 1; one per symbol.

Per-minute data row `a` of a candidate (12 floats, the research tape layout):
  a[0..3] contract open/high/low/close   a[4..7] mark open/high/low/close   a[8] funding rate stamped in this minute
  a[9] component ATR (M 1h Wilder, D 1m SMA14, R 4h Wilder, H 1d Wilder)
  a[10] D: quote volume of the previous minute   a[11] D entry minute: max mark high of the 20 minutes before

The research loop does, per minute i: funding of held positions (mark open) → owner guards → entries (minute-open
values only) → stop / time exits and trailing on the completed bar → mark-close equity. `open_minute(i)` is the first
half (everything that only needs minute-open data), `close_minute(i)` the second half; calling them back to back
for every minute is exactly the research loop. Live: open_minute(i) at the minute open, close_minute(i) after it.

Minute index i = epoch minute (ms // 60000). The research index is i − T0 with T0 = 2024-01-01 00:00 KST; every
modulo it uses (5-minute trailing cadence) is invariant under that shift (T0 % 5 == 0). KST day starts are i % 1440 == 900.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

KST_DAY_OFFSET = 900            # 00:00 KST = 15:00 UTC = minute 900 of the UTC day
GN = ("M", "D", "R", "H")
SLOTS = 7
RISK_MULT = 6.0                 # p116 L6 risk multiplier
EXIT_REASON = {1: "stop", 3: "time", 4: "period_end"}
HOLD_MIN = {0: 4320, 2: 2880, 3: 10080}   # D: until meta `last` (24 h or settlement − 30 min)


def _floor(x):
    return float(math.floor(x))


def _ceil(x):
    return float(math.ceil(x))


@dataclass
class Cand:
    """One raw signal (research `meta` row). e/sl are the research pre-computed entry/stop (D recomputes both at entry);
    tp holds D's ATR at the signal (meta[c,7]); L = contract leverage; last = last minute it may be held (D)."""
    cid: str
    g: int
    sym: str
    i: int
    sd: float
    e: float
    sl: float
    tp: float
    L: float
    step: float
    minq: float
    minn: float
    tick: float
    last: int
    info: dict = field(default_factory=dict)

    def to_dict(self):
        return dict(cid=self.cid, g=self.g, sym=self.sym, i=self.i, sd=self.sd, e=self.e, sl=self.sl, tp=self.tp, L=self.L,
                    step=self.step, minq=self.minq, minn=self.minn, tick=self.tick, last=self.last, info=self.info)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


def _slot():
    return dict(c=None, q=0.0, ep=0.0, sl=0.0, best=0.0, dist=0.0, pnl=0.0, fees=0.0, fundp=0.0, protected=False, iq=0.0)


class Book:
    """The shared research account (wallet 106 USDT in research) with the owner guards:
    KST-00 equity −10 % → no new entries until the next KST 00; realised-wallet peak −20 % → no new entries for 1440 min,
    then the peak is reset to the wallet."""

    def __init__(self, fee=1.0, capital=106.0, weights=None, regime=None, state=None, end=None):
        self.fee = float(fee)
        self.weights = weights            # i → (wM, wD, wR, wH)
        self.regime = regime              # i → V5 score (−5 … +5)
        self.end = end                    # research `hi` (exclusive); None = open-ended (live)
        if state:
            self.__dict__.update(_load(state))
            return
        self.capital = float(capital)
        self.wallet = float(capital)
        self.peak = float(capital)
        self.until = -1
        self.base = float(capital)
        self.halt = False
        self.lo = None                    # first minute processed
        self.prev_eq = float(capital)     # curve[i-1]
        self.slots = [_slot() for _ in range(SLOTS)]
        self.lastclose: dict = {}         # "g:sym" → minute of the last close
        self.realized = [0.0, 0.0, 0.0, 0.0]
        self.audit = {"entries": 0, "exits": 0, "peak_halts": 0, "peak_resets": 0, "daily_halts": 0}
        self.skips = {}
        self.open_i = None                # minute whose open half ran last
        self.closed_i = None              # minute whose close half ran last
        self.eventeq = float(capital)

    # ── persistence ──
    def state(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("weights", "regime", "fee", "end")}
        d["slots"] = [dict(s, c=s["c"].to_dict() if s["c"] is not None else None) for s in self.slots]
        return d

    # ── helpers ──
    def _guard(self, i):
        if self.until < 0 and self.wallet <= self.peak * .8:
            self.until = i + 1440
            self.audit["peak_halts"] += 1
            return True
        return False

    def _skip(self, g, why):
        k = f"{GN[g]}:{why}"
        self.skips[k] = self.skips.get(k, 0) + 1

    def positions(self):
        return [(k, s) for k, s in enumerate(self.slots) if s["c"] is not None]

    # ── first half of minute i: funding, owner guards, entries (minute-open data only) ──
    def open_minute(self, i, rows, cands):
        """rows(cand, i) → 12-float row (only a[0], a[4], a[8], a[10], a[11] are read here).
        cands: this minute's raw signals, already in research order (component, then symbol order). Returns actions."""
        assert self.closed_i is None or i == self.closed_i + 1, (i, self.closed_i)
        acts = []
        if self.lo is None:
            self.lo = i
        w = self.weights(i)
        if i == self.lo or i % 1440 == KST_DAY_OFFSET:
            self.base = self.capital if i == self.lo else self.prev_eq
            self.halt = False
        if self.until >= 0 and i >= self.until:
            self.until = -1
            self.peak = self.wallet
            self.audit["peak_resets"] += 1
            acts.append(dict(type="peak_release", i=i, wallet=self.wallet))
        for k in range(SLOTS):
            s = self.slots[k]
            c = s["c"]
            if c is None:
                continue
            a = rows(c, i)
            sd = c.sd
            if i > c.i:
                cash = -sd * s["q"] * a[4] * a[8]
                self.wallet += cash
                s["pnl"] += cash
                s["fundp"] += cash
                if cash != 0:
                    acts.append(dict(type="funding", i=i, cand=c, cash=cash, rate=a[8]))
                self.peak = max(self.peak, self.wallet)
                if self._guard(i):
                    acts.append(dict(type="peak_halt", i=i, wallet=self.wallet, peak=self.peak))
        self.peak = max(self.peak, self.wallet)
        if self._guard(i):
            acts.append(dict(type="peak_halt", i=i, wallet=self.wallet, peak=self.peak))
        eventeq = self.wallet
        for k in range(SLOTS):
            s = self.slots[k]
            c = s["c"]
            if c is not None:
                a = rows(c, i)
                eventeq += c.sd * s["q"] * (a[4] - s["ep"])
        if eventeq <= self.base * .9:
            if not self.halt:
                self.audit["daily_halts"] += 1
                acts.append(dict(type="daily_halt", i=i, equity=eventeq, base=self.base))
            self.halt = True
        fee = self.fee
        for c in cands:
            assert c.i == i, (c.cid, c.i, i)
            g = c.g
            sym = c.sym
            sd = c.sd
            L = c.L
            step = c.step
            tick = c.tick
            if self.halt or self.until >= 0:
                self._skip(g, "halt")
                acts.append(dict(type="skip", i=i, cand=c, reason="owner_halt"))
                continue
            count = 0
            used = 0.
            sused = 0.
            gross = 0.
            slot = -1
            conflict = False
            for k in range(SLOTS):
                s = self.slots[k]
                old = s["c"]
                if old is None:
                    slot = k
                    continue
                used += s["q"] * s["ep"] / old.L
                if old.sym == sym:
                    conflict = True
                if old.g == g:
                    count += 1
                    sused += s["q"] * s["ep"] / L
                    gross += s["q"] * rows(old, i)[4]
            cap = 1 if g in (1, 3) else 2
            if conflict or count >= cap or slot < 0 or (g == 2 and i - self.lastclose.get(f"{g}:{sym}", -10000000) < 60):
                self._skip(g, "slot")
                acts.append(dict(type="skip", i=i, cand=c, reason="conflict" if conflict else "cooldown" if (
                    g == 2 and count < cap and slot >= 0) else "slots"))
                continue
            a = rows(c, i)
            sleeve_capital = self.wallet * w[g]
            capital = sleeve_capital * RISK_MULT
            eqcap = eventeq * w[g] * RISK_MULT
            avail = max(0., min(self.wallet, eventeq) - used)
            sav = max(0., min(self.wallet, eventeq) * w[g] - sused)
            reg = self.regime(i)
            side_factor = 1. + .25 * sd * reg / 5.
            totalcap = RISK_MULT * max(0., min(self.wallet, eventeq)) * (.06 * w[0] + .02 * w[1] + .02 * w[2] + .05 * w[3])
            heldrisk = 0.
            for k in range(SLOTS):
                s = self.slots[k]
                if s["c"] is not None:
                    heldrisk += s["q"] * s["dist"]
            remaining = max(0., totalcap - heldrisk)
            e = c.e
            st = c.sl
            if g == 1:
                e = a[0] * (1 - .0023)
                st = _ceil(max(a[11], e + 3 * c.tp) / tick - 1e-9) * tick
                d = st - e
                quantity = _floor(min(capital * .02 * side_factor / d, capital * .8 * L / e, a[10] * .01 / e) / step + 1e-9) * step
                e = a[0] * (1 - .0022 - min(.01, .01 * quantity * a[0] / a[10]))
                st = _ceil(max(a[11], e + 3 * c.tp) / tick - 1e-9) * tick
                d = st - e
                quantity = min(quantity, _floor(capital * .02 * side_factor / d / step + 1e-9) * step)
                e = a[0] * (1 - .0022 - min(.01, .01 * quantity * a[0] / a[10]))
                st = _ceil(max(a[11], e + 3 * c.tp) / tick - 1e-9) * tick
                d = st - e
                lp = e * (1 + 1 / L) / (1 + .02 + .0005 * fee)
                buffer = (lp - e) / (2 * d)
            else:
                d = abs(e - st)
                if g == 0:
                    ld = (1 / L - .005) / (1 - sd * .005)
                    lp = e * (1 - sd * ld)
                    buffer = ld / (2 * (d / e + .0002 + .0005 * fee))
                    target = eqcap * .06 / 2 * side_factor / (d / e + .001 * fee + .0004)
                    notional = min(target, .4 * L * eqcap, max(0., .8 * L * eqcap - gross), min(avail, sav) * .9 / (1 / L + .001))
                else:
                    mm = .01 if g == 2 else .006
                    lp = e * (1 - sd / L) / (1 - sd * mm)
                    buffer = sd * (e - lp) / (2 * d + (e * .001 * fee if g == 2 else 0.))
                    if g == 3:
                        lp = e * (1 - sd * (1 / L - .006))
                        buffer = sd * (e - lp) / (2 * d)
                    notional = (min(capital * .01 * side_factor / (d / e), capital * L * .4) if g == 2
                                else min(capital * .05 * side_factor / (d / e), capital * 5))
                quantity = _floor(notional / (a[0] if g == 3 else e) / step + 1e-9) * step
            if quantity * d > remaining:
                quantity = min(quantity, _floor(remaining / max(d, 1e-30) / step + 1e-9) * step)
                if g == 1:
                    e = a[0] * (1 - .0022 - min(.01, .01 * quantity * a[0] / a[10]))
                    st = _ceil(max(a[11], e + 3 * c.tp) / tick - 1e-9) * tick
                    d = st - e
                    lp = e * (1 + 1 / L) / (1 + .02 + .0005 * fee)
                    buffer = (lp - e) / (2 * d)
            if quantity * d > remaining + 1e-8:
                self._skip(g, "risk_cap")
                acts.append(dict(type="skip", i=i, cand=c, reason="risk_cap"))
                continue
            if buffer < 1 or d <= 0:
                self._skip(g, "liq_buffer")
                acts.append(dict(type="skip", i=i, cand=c, reason="liq_buffer"))
                continue
            if quantity < c.minq or quantity * a[0] * .98 < c.minn:
                self._skip(g, "min_order")
                acts.append(dict(type="skip", i=i, cand=c, reason="min_order", qty=quantity))
                continue
            margin_need = (quantity * e / L + quantity * e * .0005 * fee if g == 1
                           else quantity * (a[0] if g in (0, 2) else e) * (1 / L + (.0005 * fee if g == 3 else .001)))
            if margin_need > min(avail, sav) * .9:
                self._skip(g, "margin")
                acts.append(dict(type="skip", i=i, cand=c, reason="margin"))
                continue
            s = self.slots[slot]
            s.update(c=c, q=quantity, iq=quantity, ep=e, sl=st, dist=d, best=a[4] if g in (0, 1) else e)
            cost = quantity * e * .0005 * fee
            self.wallet -= cost
            s.update(pnl=-cost, fees=cost, fundp=0., protected=True)
            self.audit["entries"] += 1
            acts.append(dict(type="enter", i=i, cand=c, qty=quantity, entry=e, stop=st, dist=d, lev=L, liq=lp, fee=cost,
                             slot=slot, wallet=self.wallet, side_factor=side_factor, regime=reg))
            self.peak = max(self.peak, self.wallet)
            if self._guard(i):
                acts.append(dict(type="peak_halt", i=i, wallet=self.wallet, peak=self.peak))
            eq = self.wallet
            for z in range(SLOTS):
                cc = self.slots[z]["c"]
                if cc is not None:
                    eq += cc.sd * self.slots[z]["q"] * (rows(cc, i)[4] - self.slots[z]["ep"])
            eventeq = eq
            if eq <= self.base * .9:
                if not self.halt:
                    self.audit["daily_halts"] += 1
                    acts.append(dict(type="daily_halt", i=i, equity=eq, base=self.base))
                self.halt = True
        self.eventeq = eventeq
        self.open_i = i
        return acts

    # ── second half of minute i: stop / time exits, trailing on the completed bar, mark-close equity ──
    def close_minute(self, i, rows):
        assert self.open_i == i, (self.open_i, i)
        acts = []
        fee = self.fee
        hi = self.end
        for k in range(SLOTS):
            s = self.slots[k]
            c = s["c"]
            if c is None:
                continue
            opened = c.i
            g = c.g
            sd = c.sd
            L = c.L
            tick = c.tick
            a = rows(c, i)
            reason = 0
            raw = 0.
            mm = .005 if g == 0 else .02 + .0005 * fee if g == 1 else .01 if g == 2 else .006
            collateral = s["ep"] / L
            lp = (s["ep"] - sd * collateral) / (1 - sd * mm)
            if g == 3:
                lp = s["ep"] * (1 - sd * (1 / L - .006))
            last_minute = hi is not None and i == hi - 1
            if (a[6] <= s["sl"] if sd > 0 else a[5] >= s["sl"]):
                raw = min(s["sl"], a[0]) if sd > 0 else max(s["sl"], a[0])
                reason = 1
            elif ((g == 0 and i - opened >= 4320) or (g == 2 and i - opened >= 2880) or (g == 1 and i >= c.last)
                  or (g == 3 and i - opened >= 10080)):
                raw = a[3] if last_minute else a[0]
                reason = 3
            elif last_minute:
                raw = a[3]
                reason = 4
            if reason == 0:
                old = s["sl"]
                am = 3. if g != 2 else 2.5
                if g == 0:
                    s["best"] = max(s["best"], a[5]) if sd > 0 else min(s["best"], a[6])
                    new = s["best"] - sd * am * a[9]
                    new = (_floor(new / tick + 1e-9) if sd > 0 else _ceil(new / tick - 1e-9)) * tick
                    s["sl"] = max(s["sl"], new) if sd > 0 else min(s["sl"], new)
                elif g == 1:
                    s["best"] = min(s["best"], a[6])
                    new = _ceil((s["best"] + am * a[9]) / tick - 1e-9) * tick
                    s["sl"] = min(s["sl"], new)
                elif g == 2:
                    s["best"] = max(s["best"], a[1]) if sd > 0 else min(s["best"], a[2])
                    if (i + 1) % 5 == 0 and sd * (s["best"] - s["ep"]) >= s["dist"]:
                        new = s["best"] - sd * am * a[9]
                        new = (_floor(new / tick + 1e-9) if sd > 0 else _ceil(new / tick - 1e-9)) * tick
                        s["sl"] = max(s["sl"], new) if sd > 0 else min(s["sl"], new)
                else:
                    s["best"] = max(s["best"], a[1]) if sd > 0 else min(s["best"], a[2])
                    new = s["best"] - sd * am * a[9]
                    new = (_floor(new / tick + 1e-9) if sd > 0 else _ceil(new / tick - 1e-9)) * tick
                    s["sl"] = max(s["sl"], new) if sd > 0 else min(s["sl"], new)
                # New stop takes effect only next minute; never fill from this completed bar.
                if s["sl"] != old:
                    acts.append(dict(type="stop", i=i, cand=c, stop=s["sl"], old=old, best=s["best"], atr=a[9]))
            if reason:
                xp = raw * (1 - sd * .0002)
                if g == 1:
                    xp = raw * (1 + .0022 + (.01 if a[10] <= 0 else min(.01, .01 * s["q"] * raw / a[10])))
                if s["q"] > 0:
                    cost = s["q"] * xp * .0005 * fee
                    cash = sd * s["q"] * (xp - s["ep"]) - cost
                    self.wallet += cash
                    s["pnl"] += cash
                    s["fees"] += cost
                trade = dict(cand=c, g=g, entry_i=opened, exit_i=i, side=sd, entry=s["ep"], qty=s["iq"], risk_distance=s["dist"],
                             net_pnl=s["pnl"], net_R=s["pnl"] / (s["iq"] * s["dist"]), fees=s["fees"], funding=s["fundp"],
                             exit_reason=reason, exit_price=xp, final_stop=s["sl"], liquidation_price=lp,
                             initial_margin=s["iq"] * s["ep"] / L, raw_exit=raw)
                self.realized[g] += s["pnl"]
                self.lastclose[f"{g}:{c.sym}"] = i
                self.slots[k] = _slot()
                self.audit["exits"] += 1
                acts.append(dict(type="exit", i=i, cand=c, reason=EXIT_REASON[reason], price=xp, trade=trade, wallet=self.wallet))
                self.peak = max(self.peak, self.wallet)
                if self._guard(i):
                    acts.append(dict(type="peak_halt", i=i, wallet=self.wallet, peak=self.peak))
        self.peak = max(self.peak, self.wallet)
        if self._guard(i):
            acts.append(dict(type="peak_halt", i=i, wallet=self.wallet, peak=self.peak))
        eq = self.wallet
        for k in range(SLOTS):
            s = self.slots[k]
            c = s["c"]
            if c is None:
                continue
            a = rows(c, i)
            eq += c.sd * s["q"] * (a[7] - s["ep"])
        if eq <= self.base * .9:
            if not self.halt:
                self.audit["daily_halts"] += 1
                acts.append(dict(type="daily_halt", i=i, equity=eq, base=self.base))
            self.halt = True
        self.prev_eq = eq
        self.closed_i = i
        return acts

    def equity(self):
        return self.prev_eq

    def live_closed(self, sym, i, price, reason="exchange"):
        """LIVE mode only: the exchange closed `sym` (stop fired / safety close) → drop the slot at `price` (no fee
        model: the engine journal holds the real fill). Returns the trade dict or None."""
        for k, s in enumerate(self.slots):
            c = s["c"]
            if c is not None and c.sym == sym:
                cash = c.sd * s["q"] * (price - s["ep"])
                self.wallet += cash
                s["pnl"] += cash
                self.realized[c.g] += s["pnl"]
                self.lastclose[f"{c.g}:{sym}"] = i
                self.slots[k] = _slot()
                return dict(cand=c, exit_i=i, exit_price=price, reason=reason)
        return None

    def drop(self, cid):
        """LIVE mode only: the engine did not open this entry (refused / post-only unfilled) → free the slot, give the
        modelled entry fee back. Returns the candidate or None."""
        for k, s in enumerate(self.slots):
            c = s["c"]
            if c is not None and c.cid == cid:
                self.wallet += s["fees"]
                self.slots[k] = _slot()
                return c
        return None

    def sync_wallet(self, wallet):
        """LIVE mode only: realised wallet from the exchange replaces the book's (sizing uses the real account)."""
        self.wallet = float(wallet)


def _load(st: dict) -> dict:
    d = dict(st)
    d["slots"] = [dict(s, c=Cand.from_dict(s["c"]) if s.get("c") else None) for s in st["slots"]]
    return d
