"""Synthetic bars + a scripted rule for the offline tests (no network, no parquet)."""
from h34_paper import core
from h34_paper.core import MS15, Rule, SymData, Daily

T0 = (core.LOCK_TS_MS // MS15) * MS15 - 100 * MS15        # a bar grid that contains the lock time


def flat_bars(t0, n, px=100.0, h=100.1, l=99.9):
    return [(t0 + i * MS15, px, h, l, px) for i in range(n)]


def make_data(coins, n=60, t0=T0, over=None, px=None):
    """over: {(sym, index): (o,h,l,c)} replaces bars; px: {sym: price}. 1h series is irrelevant for scripted rules."""
    data = {}
    for s in coins:
        b = flat_bars(t0, n, (px or {}).get(s, 100.0))
        sd = SymData()
        sd.name = s
        for (sym, i), (o, h, l, c) in (over or {}).items():
            if sym == s:
                b[i] = (b[i][0], o, h, l, c)
        sd.s15.set_bars(b)
        sd.s1h.set_bars([])
        sd.rsi, sd.e20, sd.e50 = [None] * n, [], []
        data[s] = sd
    return data


def fire_rule(name, side, fire, target=core.TARGET, stop=core.STOP, max_bars=core.MAX_BARS):
    """fire: {sym: set(bar index)}; the detector signals on those 15m bars."""
    def detect(side_, sd, daily, i):
        return ({"scripted": True}, None) if i in fire.get(sd.name, ()) else (None, None)
    return Rule(name, side, detect, target, stop, max_bars)


def run(engine, data, idx_from, idx_to, emit=None):
    trades, events = [], []

    def e(kind, key, rec):
        (trades if kind == "trade" else events).append(rec)
        if emit:
            emit(kind, key, rec)
    ts = data[next(iter(data))].s15.ts
    for i in range(idx_from, idx_to):
        engine.process(ts[i], data, Daily(), e)
    return trades, events


def skips(events, why=None):
    return [e for e in events if e["event"] == "signal_skipped" and (why is None or e["reason"] == why)]


class FakeFeed:
    """Serves historical bars as the public API would at a simulated clock: bars with t_open <= now, the newest (still forming)
    bar masked to its open only (h=l=c=o) so any use of a not-yet-closed bar's high/low/close would change results.
    Window sizes equal the real feed's (WARM). `drop` removes bars (outage tests)."""

    def __init__(self, bars, now_ms, drop=None):
        from h34_paper.feed import WARM, STEP
        self.src, self.t, self.WARM, self.STEP = bars, now_ms, WARM, STEP
        self.drop = drop or set()
        self.offset_ms = 0
        self.cache = {}
        self.refreshes = 0
        self._ts = {}

    def now_ms(self):
        return self.t

    def sync_time(self):
        return 0

    def refresh(self, full=False):
        import bisect
        self.refreshes += 1
        self.cache = {}
        for key, arr in self.src.items():
            sym, iv = key
            step = self.STEP[iv]
            if key not in self._ts:
                self._ts[key] = [b[0] for b in arr]
            hi = bisect.bisect_right(self._ts[key], self.t)
            out = []
            for b in arr[max(0, hi - self.WARM[iv] - 50):hi]:
                if (sym, iv, b[0]) in self.drop:
                    continue
                out.append(b if b[0] + step <= self.t else (b[0], b[1], b[1], b[1], b[1]))
            self.cache[key] = out[-self.WARM[iv]:]

    def bars(self, sym, iv):
        return self.cache[(sym, iv)]
