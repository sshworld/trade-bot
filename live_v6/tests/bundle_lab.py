"""bundle_v5 match test support: a `Market` that serves the RESEARCH raw data (lab folders, read-only) minute by minute,
so the live driver regenerates every signal itself and its trades can be diffed against p179's result CSVs.

Needs BUNDLE_LAB (the lab folder) — the astra_ws data folder is its sibling — and numpy + pandas (test-only).
Missing p98 archive files may be given in BUNDLE_DL (files named like data.binance.vision paths with '/' → '_').
"""
from __future__ import annotations

import json
import math
import os
import pathlib

import numpy as np
import pandas as pd

from live_v6.strategies import bundle_v5_signals as SG
from live_v6.strategies.bundle_v5 import Market

T0 = 28400580                    # 2024-01-01 00:00 KST, epoch minute
N = 1035 * 1440
CUT = 912 * 1440
PERIODS = {"development": (0, CUT), "confirmation": (CUT, N), "all": (0, N)}


def lab_paths():
    lab = os.getenv("BUNDLE_LAB")
    if not lab or not pathlib.Path(lab, "p179_exit_decision").exists():
        return None
    lab = pathlib.Path(lab)
    return lab, lab.parent / "astra_ws", pathlib.Path(os.getenv("BUNDLE_DL", "/nonexistent"))


def _ms_min(x):
    return int(x) // 60000


class LabMarket(Market):
    def __init__(self, lab, asset, dl):
        self.lab, self.asset, self.dl = lab, asset, dl
        self.rm = np.load(lab / "p14_retest/data/market.npy", mmap_mode="r")
        self.rf = np.load(lab / "p14_retest/data/fund.npy", mmap_mode="r")
        self.mmiss = np.load(lab / "p14_retest/data/mark_missing.npy", mmap_mode="r")
        self.cvalid = {}
        for k, s in enumerate(SG.S):
            with np.load(asset / "data" / f"{s}.npz") as z:
                self.cvalid[s] = np.r_[np.ones(540, bool), z["valid"][:N - 540]]
        info = json.load(open(asset / "exchangeInfo.json"))
        self.info = {s["symbol"]: s for s in info["symbols"]}
        self._filters = {}
        self.H = lab / "p98_52w_high"
        d = pd.read_pickle(self.H / "daily.pkl")
        d["t"] = d.open_time.to_numpy(np.int64) // 60000
        self.daily = {s: g.sort_values("t")[["t", "high", "low", "close", "quote_volume"]].to_numpy() for s, g in d.groupby("symbol")}
        self.btc = {int(t): float(c) for t, c in self.daily["BTCUSDT"][:, [0, 3]]}
        P = lab / "p00d_delist_short"
        self.ann = []
        for a in json.load(open(P / "announcements.json")):
            assert SG.title_selected(a["title"]), a["title"]
            x = SG.parse_announcement(a["code"], a["title"], a["t"], a["text"])
            x["_research_symbols"] = a["symbols"]
            self.ann.append(x)
        self.ann.sort(key=lambda a: a["t"])
        self.ann_k = 0
        self.dfiles = {}
        for ev in json.load(open(P / "event_index.json")):
            with np.load(P / ev["file"]) as z:
                t = z["time"] // 60000
                self.dfiles.setdefault(ev["symbol"], []).append((int(t[0]), int(t[-1]), t, z["k"], z["m"], z["f"]))
        self._day = {}
        self._fund = {}

    # ── data sources ──
    def _S(self, sym):
        return SG.S.index(sym) if sym in SG.S else -1

    def _dwin(self, sym, i):
        for a, b, t, k, m, f in self.dfiles.get(sym, ()):
            if a <= i <= b:
                return t, k, m, f
        return None

    def _arch(self, sym, day, mark):
        key = (sym, day, mark)
        if key not in self._day:
            if len(self._day) > 64:
                self._day.clear()
            ds = pd.Timestamp(day * 60, unit="s", tz="UTC").strftime("%Y-%m-%d")
            typ = "markPriceKlines" if mark else "klines"
            pre = "mark-" if mark else ""
            cands = [self.asset / "data" / f"{pre}{sym}-1m-{ds[:7]}.zip", self.H / "data" / f"daily_{typ}_{sym}_1m_{sym}-1m-{ds}.zip",
                     self.dl / f"daily_{typ}_{sym}_1m_{sym}-1m-{ds}.zip"]
            p = next((c for c in cands if c.exists()), None)
            out = {}
            if p is not None:
                f = pd.read_csv(p, compression="zip")
                tt = f.open_time.to_numpy(np.int64) // 60000
                ok = (tt >= day) & (tt < day + 1440)
                for row in zip(tt[ok], *(f[c].to_numpy(float)[ok] for c in ("open", "high", "low", "close"))):
                    out[int(row[0])] = row[1:]
                rep = self.H / "data" / f"repair-{sym}-{ds}.zip"
                if mark and rep.exists():
                    f = pd.read_csv(rep, compression="zip")
                    tt = f.open_time.to_numpy(np.int64) // 60000
                    for row in zip(tt, *(f[c].to_numpy(float) for c in ("open", "high", "low", "close"))):
                        if day <= row[0] < day + 1440:
                            out[int(row[0])] = row[1:]
            self._day[key] = out
        return self._day[key]

    def _bar(self, sym, i, mark):
        k = self._S(sym)
        if k >= 0:
            r = i - T0
            if not 0 <= r < N:
                return None
            v = self.rm[r, k, 4 * mark:4 * mark + 4]
            ok = bool(~self.mmiss[r, k]) if mark else bool(self.cvalid[sym][r])
            return dict(t=i, o=float(v[0]), h=float(v[1]), l=float(v[2]), c=float(v[3]), qv=0.0, ok=ok)
        w = self._dwin(sym, i)
        if w is not None:
            t, kk, mm, _ = w
            j = int(np.searchsorted(t, i))
            x = (mm if mark else kk)[j]
            return dict(t=i, o=float(x[1]), h=float(x[2]), l=float(x[3]), c=float(x[4]), qv=float(kk[j, 7]), ok=True)
        x = self._arch(sym, (i // 1440) * 1440, mark).get(i)
        if x is None:
            return None
        return dict(t=i, o=float(x[0]), h=float(x[1]), l=float(x[2]), c=float(x[3]), qv=0.0, ok=True)

    # ── Market API ──
    def bar(self, sym, i, forming=False):
        return self._bar(sym, i, False)

    def mark(self, sym, i, forming=False):
        return self._bar(sym, i, True)

    def funding(self, sym, i):
        k = self._S(sym)
        if k >= 0:
            return float(self.rf[i - T0, k])
        w = self._dwin(sym, i)
        if w is not None:
            fr = {int(v[0] // 60000): float(v[2]) for v in w[3]}
            return fr.get(i, 0.0)
        mo = pd.Timestamp(i * 60, unit="s", tz="UTC").strftime("%Y-%m")
        key = (sym, mo)
        if key not in self._fund:
            cands = [self.asset / "data" / f"{sym}-fundingRate-{mo}.zip", self.H / "data" / f"monthly_fundingRate_{sym}_{sym}-fundingRate-{mo}.zip",
                     self.dl / f"monthly_fundingRate_{sym}_{sym}-fundingRate-{mo}.zip"]
            p = next((c for c in cands if c.exists()), None)
            acc = {}
            if p is not None:
                f = pd.read_csv(p, compression="zip")
                for t, r in zip(f.calc_time.to_numpy(np.int64) // 60000, f.last_funding_rate.to_numpy(float)):
                    acc[int(t)] = acc.get(int(t), 0.0) + float(r)
            self._fund[key] = acc
        return self._fund[key].get(i, 0.0)

    def prev_funding(self, sym, before_ms):
        w = self._dwin(sym, before_ms // 60000)
        if w is None:
            return None
        f = w[3]
        prev = f[f[:, 0] < before_ms]
        return (float(prev[-1, 2]), float(prev[-1, 1])) if len(prev) else None

    def klines(self, sym, interval, end_i, n):
        k = self._S(sym)
        assert k >= 0, sym
        end = end_i - end_i % interval
        start = max(end - n * interval, T0 - (T0 % interval) + interval)
        r0, r1 = start - T0, end - T0
        if r1 <= r0:
            return []
        a = np.asarray(self.rm[r0:r1, k, :4]).reshape(-1, interval, 4)
        ts = range(start, end, interval)
        return [dict(t=t, o=float(x[0, 0]), h=float(x[:, 1].max()), l=float(x[:, 2].min()), c=float(x[-1, 3]))
                for t, x in zip(ts, a)]

    def filters(self, sym):
        if sym not in self._filters:
            s = self.info.get(sym)
            if s is None:
                self._filters[sym] = None
            else:
                f = {x["filterType"]: x for x in s["filters"]}
                self._filters[sym] = (float(f["LOT_SIZE"]["stepSize"]), float(f["LOT_SIZE"]["minQty"]),
                                      float(f["MIN_NOTIONAL"]["notional"]), float(f["PRICE_FILTER"]["tickSize"]))
        return self._filters[sym]

    def perpetuals(self):
        return {s: v for s, v in self.info.items() if v.get("contractType") == "PERPETUAL"}

    def daily_history(self, until_day):
        out = {}
        for s, a in self.daily.items():
            a = a[a[:, 0] <= until_day]
            if len(a):
                out[s] = [dict(t=int(r[0]), h=r[1], l=r[2], c=r[3], qv=r[4]) for r in a]
        return out

    def daily_day(self, day):
        out = {}
        for s, a in self.daily.items():
            j = np.searchsorted(a[:, 0], day)
            if j < len(a) and a[j, 0] == day:
                r = a[j]
                out[s] = dict(t=int(r[0]), h=r[1], l=r[2], c=r[3], qv=r[4])
        return out

    def btc_closes(self, until_day):
        return [c for t, c in sorted(self.btc.items()) if t <= until_day]

    def announcements(self, now_ms):
        out = []
        while self.ann_k < len(self.ann) and self.ann[self.ann_k]["t"] <= now_ms:
            out.append(self.ann[self.ann_k])
            self.ann_k += 1
        return out

    def skip_announcements(self, before_ms):
        while self.ann_k < len(self.ann) and self.ann[self.ann_k]["t"] < before_ms:
            self.ann_k += 1


class Collect:
    """Port that keeps every action (the replay compares them)."""

    def __init__(self):
        self.acts = []
        self.notes = []

    def handle(self, acts, i, drv):
        self.notes += drv.notes
        drv.notes.clear()
        self.acts += acts


def replay(period="confirmation", fee=1.0, lab=None):
    """Run the live driver minute by minute over a research period. Returns (driver, port)."""
    from live_v6.strategies.bundle_v5 import BundleConfig, BundleDriver
    lab, asset, dl = lab or lab_paths()
    lo, hi = PERIODS[period]
    m = LabMarket(lab, asset, dl)
    ev = pd.read_csv(lab / "p49_macro_proxy/events.csv")
    macro = sorted((int(pd.Timestamp(x).timestamp()) // 60, k, str(e)) for x, k, e in zip(ev.event_utc, ev.kind, ev.event_id))
    port = Collect()
    drv = BundleDriver(m, port, BundleConfig(fee_mult=fee, atomic=False, end=T0 + hi), macro=macro)
    # D: announcements published before the period still define lifecycle limits / pending entries
    for a in m.announcements((T0 + lo) * 60000 - 1):
        drv.d["seen"].append(a["code"])
        drv.d["lifecycle"] += SG.lifecycle_of(a)
        for sym in SG.d_event_symbols(a, m.perpetuals()):
            tm = SG.d_entry_minute(a["t"])
            if tm >= T0 + lo:
                drv.d["pending"].append([tm, sym, a["code"]])
    for i in range(T0 + lo, T0 + hi):
        assert drv.process(i), i
    port.handle(drv.book.close_minute(T0 + hi - 1, lambda c, k: drv.row(c, k, False)), T0 + hi - 1, drv)
    return drv, port
