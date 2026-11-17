"""bundle_v5 PAPER mode: the live strategy on live public market data, with NO order path at all.

    LIVE_V6_STRATEGY=bundle_v5 LIVE_V6_PAPER=1 python -m live_v6 run

Structure (why zero order calls is structural, not a promise): this process never builds V6Engine nor BinanceREST and
needs no API key. Its only exchange client is `PublicREST`, which has GET methods for public market data and nothing
else (no signing, no POST/DELETE). The strategy's book actions go to `PaperPort` (JSONL + Telegram).

Env:
  LIVE_V6_PAPER_DIR          state / ledger folder (default /var/lib/live_v6/paper)
  LIVE_V6_BUNDLE_SCHEDULE    macro release schedule CSV (kind,event_utc[,event_id]) — maintained by hand
  LIVE_V6_BUNDLE_D           0 = component D off (default on)
  LIVE_V6_BUNDLE_RISK_PCT    "M:2,D:0,R:0,H:9" = % of the wallet risked per trade by component (0 = off); replaces
                             the IV weights x LIVE_V6_BUNDLE_RISK_MULT sizing (RISK_MULT is then not applied)
  LIVE_V6_BUNDLE_MARGIN      pooled = no per-component margin budget (default sleeve)
  LIVE_V6_PAPER_CAPITAL      virtual starting wallet (default 106, the research capital)
  LIVE_V6_PAPER_FEE          fee multiplier (1 = taker 0.05 %, default)
  LIVE_V6_ENTRY_MODE         market (default) | postonly_timeout ; LIVE_V6_POSTONLY_TIMEOUT_S (default 300)
  LIVE_V6_PAPER_TELEGRAM     1 = send the [모의] messages to Telegram (TELEGRAM_* env); otherwise log only
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time

import httpx

from .store import JsonStore
from .strategies import bundle_v5_signals as SG
from .strategies.base import DataNotReady
from .strategies.bundle_v5 import BundleConfig, BundleDriver, Market, PaperPort, sizing_from_env

log = logging.getLogger("live_v6.bundle_paper")
FAPI = "https://fapi.binance.com"
WWW = "https://www.binance.com"
IV = {5: "5m", 60: "1h", 240: "4h", 1440: "1d"}
H_START_MS = 1672531200000          # 2023-01-01 UTC: p98's daily history starts here (ATR / 52w-high seeds)
WARM_WEIGHT_MAX = 1000              # used request weight (1 min, per IP; limit 2400) above which the warm-up waits
WARM_TIMEOUT_S = 3.0                # per request of the warm-up (the client default is 10 s)


class PublicREST:
    """GET-only public Binance client. No key, no signature, no write method (tests assert this)."""

    def __init__(self, base=FAPI, www=WWW, timeout=10.0, transport=None, clock=time.time):
        self._c = httpx.Client(base_url=base, timeout=timeout, transport=transport)
        self._w = httpx.Client(base_url=www, timeout=timeout, transport=transport, headers={"User-Agent": "Mozilla/5.0"})
        self.clock = clock
        self.weight = 0
        self._sleep_until = 0.0

    def _get(self, client, path, params=None, timeout=None):
        if self.clock() < self._sleep_until:
            raise DataNotReady(f"rate backoff {path}")
        r = client.request("GET", path, params=params or {}, **({} if timeout is None else {"timeout": timeout}))
        try:
            self.weight = int(r.headers.get("X-MBX-USED-WEIGHT-1M") or self.weight)
        except ValueError:
            pass
        if r.status_code in (418, 429):
            self._sleep_until = self.clock() + float(r.headers.get("Retry-After") or 60)
            raise DataNotReady(f"HTTP {r.status_code} {path}")
        if r.status_code >= 400:
            raise DataNotReady(f"HTTP {r.status_code} {path}: {r.text[:120]}")
        return r.json()

    def get(self, path, params=None, timeout=None):
        return self._get(self._c, path, params, timeout)

    def www(self, path, params=None):
        return self._get(self._w, path, params)


def _bar(row, mark=False):
    return dict(t=int(row[0]) // 60000, o=float(row[1]), h=float(row[2]), l=float(row[3]), c=float(row[4]),
                qv=0.0 if mark else float(row[7]), close_ms=int(row[6]))


class RestMarket(Market):
    """Market for the driver from public REST. Minute bars are cached; a minute missing inside a returned range is
    filled like the research data (astra: OHLC = previous close, not valid)."""

    def __init__(self, rest: PublicREST, clock=time.time, notify=None):
        self.r = rest
        self.clock = clock
        self.notify = notify or (lambda text: None)
        self._k: dict = {}           # (sym, mark) → {minute: bar}
        self._fund: dict = {}        # sym → {minute: Σrate}
        self._fund_at: dict = {}
        self._prem: dict = {}        # sym → (nextFundingTime minute, lastFundingRate) seen before settlement
        self._ivh: dict = {}         # sym → funding interval hours
        self._info = None
        self._info_at = 0.0
        self._kl: dict = {}
        self.ann_seen: set = set()   # codes whose detail was fetched (no re-fetch)
        self.ann_buf: dict = {}
        self.ann_at = 0.0
        self.ann_fail = 0
        self.d_down = False
        self._daily_syms = None

    # ── minute bars ──
    def _load(self, sym, mark, i):
        path = "/fapi/v1/markPriceKlines" if mark else "/fapi/v1/klines"
        rows = self.r.get(path, {"symbol": sym, "interval": "1m", "startTime": (i - 30) * 60000, "limit": 120})
        now = self.clock() * 1000
        d = self._k.setdefault((sym, mark), {})
        prev = None
        for row in rows:
            b = _bar(row, mark)
            if prev is not None and b["t"] > prev["t"] + 1:
                for m in range(prev["t"] + 1, b["t"]):
                    d.setdefault(m, dict(t=m, o=prev["c"], h=prev["c"], l=prev["c"], c=prev["c"], qv=0.0, ok=False,
                                         close_ms=(m + 1) * 60000 - 1))
            b["ok"] = True
            b["forming"] = b["close_ms"] >= now
            d[b["t"]] = b
            prev = b
        if len(d) > 6000:
            for m in sorted(d)[:-3000]:
                del d[m]

    def _get_bar(self, sym, i, mark, forming):
        d = self._k.get((sym, mark), {})
        b = d.get(i)
        if b is None or (b.get("forming") and not forming):
            self._load(sym, mark, i)
            b = self._k.get((sym, mark), {}).get(i)
        if b is None:
            return None
        if b.get("forming") and not forming:
            return None                               # not closed yet
        return b

    def bar(self, sym, i, forming=False):
        return self._get_bar(sym, i, False, forming)

    def mark(self, sym, i, forming=False):
        return self._get_bar(sym, i, True, forming)

    # ── funding ──
    def refresh(self, now_ms):
        """Every loop: keep the pre-settlement funding rate of every symbol (premiumIndex), for a settlement whose
        fundingRate record is not published yet when the minute is processed."""
        try:
            for p in self.r.get("/fapi/v1/premiumIndex"):
                nft = int(p.get("nextFundingTime") or 0) // 60000
                if nft and p.get("lastFundingRate") not in (None, ""):
                    self._prem.setdefault(p["symbol"], {})[nft] = float(p["lastFundingRate"])
        except DataNotReady as e:
            log.warning("premiumIndex: %s", e)

    def funding(self, sym, i):
        f = self._fund.get(sym)
        if f is None or i not in f and self._fund_at.get(sym, 0) < (i + 1) * 60000:
            rows = self.r.get("/fapi/v1/fundingRate", {"symbol": sym, "startTime": (i - 3 * 1440) * 60000, "limit": 1000})
            f = {}
            for x in rows:
                m = int(x["fundingTime"]) // 60000
                f[m] = f.get(m, 0.0) + float(x["fundingRate"])
            self._fund[sym] = f
            self._fund_at[sym] = self.clock() * 1000
        if i in f:
            return f[i]
        pre = self._prem.get(sym, {}).get(i)
        return pre if pre is not None else 0.0

    def prev_funding(self, sym, before_ms):
        rows = self.r.get("/fapi/v1/fundingRate", {"symbol": sym, "endTime": before_ms - 1, "limit": 1})
        if not rows:
            return None
        if sym not in self._ivh:
            try:
                info = {x["symbol"]: x for x in self.r.get("/fapi/v1/fundingInfo")}
                for s, x in info.items():
                    self._ivh[s] = float(x.get("fundingIntervalHours") or 8)
            except DataNotReady:
                pass
        return float(rows[-1]["fundingRate"]), self._ivh.get(sym, 8.0)

    # ── higher timeframes ──
    def klines(self, sym, interval, end_i, n):
        key = (sym, interval, end_i, n)
        if key not in self._kl:
            end = end_i - end_i % interval
            out = []
            start = end - n * interval
            while start < end:
                rows = self.r.get("/fapi/v1/klines", {"symbol": sym, "interval": IV[interval], "startTime": start * 60000,
                                                      "endTime": end * 60000 - 1, "limit": 1500})
                if not rows:
                    break
                out += [dict(t=int(x[0]) // 60000, o=float(x[1]), h=float(x[2]), l=float(x[3]), c=float(x[4])) for x in rows]
                start = out[-1]["t"] + interval
                if len(rows) < 1500:
                    break
            if len(self._kl) > 200:
                self._kl.clear()
            self._kl[key] = [b for b in out if b["t"] + interval <= end]
        return self._kl[key]

    def exchange_info(self):
        if self._info is None or self.clock() - self._info_at > 3600:
            self._info = self.r.get("/fapi/v1/exchangeInfo")
            self._info_at = self.clock()
        return self._info

    def filters(self, sym):
        for s in self.exchange_info()["symbols"]:
            if s["symbol"] == sym:
                f = {x["filterType"]: x for x in s["filters"]}
                return (float(f["LOT_SIZE"]["stepSize"]), float(f["LOT_SIZE"]["minQty"]),
                        float(f["MIN_NOTIONAL"]["notional"]), float(f["PRICE_FILTER"]["tickSize"]))
        return None

    def perpetuals(self):
        return {s["symbol"]: s for s in self.exchange_info()["symbols"] if s.get("contractType") == "PERPETUAL"}

    def book(self, sym):
        x = self.r.get("/fapi/v1/ticker/bookTicker", {"symbol": sym})
        return {"bid": float(x["bidPrice"]), "ask": float(x["askPrice"])}

    # ── daily (H universe, V5 regime) ──
    def _usdt_perps(self):
        return sorted(s["symbol"] for s in self.exchange_info()["symbols"]
                      if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING")

    def _daily(self, sym, start_ms, end_day, timeout=None):
        out = []
        start = start_ms
        while True:
            q = {"symbol": sym, "interval": "1d", "startTime": start, "limit": 1500}
            rows = self.r.get("/fapi/v1/klines", q) if timeout is None else self.r.get("/fapi/v1/klines", q, timeout=timeout)
            out += [dict(t=int(x[0]) // 60000, h=float(x[2]), l=float(x[3]), c=float(x[4]), qv=float(x[7])) for x in rows]
            if len(rows) < 1500:
                break
            start = int(rows[-1][0]) + 86400000
            self._pace()
        return [b for b in out if b["t"] <= end_day]

    def _pace(self):
        if self.r.weight > 1500:                       # stay well under 2400 / min
            time.sleep(max(1.0, 61 - time.time() % 60))

    def daily_history(self, until_day):
        out = {}
        for k, sym in enumerate(self._usdt_perps()):
            self._pace()
            bars = self._daily(sym, H_START_MS, until_day)
            if bars:
                out[sym] = bars
            if k % 50 == 0:
                log.info("daily history %d symbols", k)
        return out

    def daily_symbols(self):
        """The symbols daily_history() walks (for BundleDriver.warm_daily: the same store, built a slice at a time)."""
        return self._usdt_perps()

    def daily_bars(self, sym, until_day):
        """One symbol of daily_history(), for the warm-up. The request weight is per IP and shared with the order
        path, so unlike daily_history() this never sleeps and never runs the minute's weight up: above
        WARM_WEIGHT_MAX it refuses and the warm-up tries again in a later minute. Short timeout: a hanging request
        must not hold the engine's loop."""
        if self.r.weight > WARM_WEIGHT_MAX:
            raise DataNotReady(f"request weight {self.r.weight} > {WARM_WEIGHT_MAX}: warm-up waits")
        return self._daily(sym, H_START_MS, until_day, timeout=WARM_TIMEOUT_S)

    def daily_day(self, day):
        out = {}
        for sym in self._usdt_perps():
            self._pace()
            rows = self.r.get("/fapi/v1/klines", {"symbol": sym, "interval": "1d", "startTime": day * 60000, "limit": 2})
            for x in rows:
                if int(x[0]) // 60000 == day and int(x[6]) < self.clock() * 1000:
                    out[sym] = dict(t=day, h=float(x[2]), l=float(x[3]), c=float(x[4]), qv=float(x[7]))
        return out

    def btc_closes(self, until_day):
        return [b["c"] for b in self._daily("BTCUSDT", H_START_MS, until_day)]

    # ── D: delisting / monitoring announcements (p00d CMS API) ──
    def announcements(self, now_ms):
        """Every parsed announcement of the last 3 days (the DRIVER dedups by code in its rolled-back state, so a
        minute retried after a failure sees the same announcements again). Polled every 15 s."""
        if self.clock() - self.ann_at >= 15:
            self.ann_at = self.clock()
            for a in self._poll_ann():
                self.ann_buf[a["code"]] = a
        cut = now_ms - 3 * 86400000
        self.ann_buf = {k: a for k, a in self.ann_buf.items() if a["t"] >= cut}
        return sorted((a for a in self.ann_buf.values() if a["t"] <= now_ms), key=lambda a: a["t"])

    def _poll_ann(self):
        out = []
        try:
            for cat in SG.D_CATALOGS:
                body = self.r.www("/bapi/composite/v1/public/cms/article/list/query",
                                  {"type": 1, "pageNo": 1, "pageSize": 20, "catalogId": cat})
                for c in ((body.get("data") or {}).get("catalogs") or []):
                    for art in c.get("articles") or []:
                        code, title = art.get("code"), art.get("title") or ""
                        if not code or code in self.ann_seen:
                            continue
                        if not SG.title_selected(title):            # collect.py: list title filter
                            self.ann_seen.add(code)
                            continue
                        det = self.r.www("/bapi/composite/v1/public/cms/article/detail/query", {"articleCode": code})
                        d = det.get("data") or {}
                        t = d.get("publishDate")
                        if not t or not d.get("body"):
                            continue                                 # not complete yet → fetched again next poll
                        text = SG.flatten_body(json.loads(d["body"]))   # collect.py: flatten(json.loads(body))
                        out.append(SG.parse_announcement(code, d.get("title") or title, int(t), text))
                        self.ann_seen.add(code)
            if self.d_down:
                self.notify("✅ [모의] 상장폐지 공지 조회 복구 — D 재개 (놓친 공지는 늦게 감지되어 진입 안 함)")
            self.ann_fail, self.d_down = 0, False
        except Exception as e:  # noqa: BLE001  D only: never stops M / R / H
            self.ann_fail += 1
            if self.ann_fail >= 3 and not self.d_down:
                self.d_down = True
                self.notify(f"⚠️ [모의] 상장폐지 공지 조회 실패 {self.ann_fail}회 — D(상장폐지 숏)만 비활성 ({type(e).__name__})")
            log.warning("announcement poll failed: %r", e)
        return out


def paper_notifier():
    from .notify import NullNotifier, Notifier
    if os.getenv("LIVE_V6_PAPER_TELEGRAM") == "1":
        return Notifier(prefix="📝[모의] ", mode="live", log_path=None)
    return NullNotifier()


def build_paper(rest=None, clock=time.time, notifier=None):
    folder = os.getenv("LIVE_V6_PAPER_DIR", "/var/lib/live_v6/paper")
    os.makedirs(folder, exist_ok=True)
    store = JsonStore(os.path.join(folder, "bundle_paper_state.json"))
    st = store.load()
    tg = notifier if notifier is not None else paper_notifier()
    m = RestMarket(rest or PublicREST(clock=clock), clock=clock, notify=lambda t: tg.send(t, kind="review"))
    port = PaperPort(os.path.join(folder, "bundle_paper.jsonl"), tg, clock=clock,
                     entry_mode=os.getenv("LIVE_V6_ENTRY_MODE", "market"),
                     timeout_s=float(os.getenv("LIVE_V6_POSTONLY_TIMEOUT_S", "300")))
    port.load(st.get("port"))
    cfg = BundleConfig(fee_mult=float(os.getenv("LIVE_V6_PAPER_FEE", "1")), capital=float(os.getenv("LIVE_V6_PAPER_CAPITAL", "106")),
                       schedule_path=os.getenv("LIVE_V6_BUNDLE_SCHEDULE"), d_enabled=os.getenv("LIVE_V6_BUNDLE_D", "1") != "0",
                       **sizing_from_env())
    drv = BundleDriver(m, port, cfg, state=st.get("drv"))
    if not drv.macro or max(t for t, _, _ in drv.macro) < clock() // 60:
        tg.send("⚠️ [모의] 거시지표 일정 CSV에 앞으로의 일정 없음 — M 신호 없음 (LIVE_V6_BUNDLE_SCHEDULE 갱신 필요)", kind="review")
    return drv, m, port, store


def run_paper(should_stop=None, clock=time.time, rest=None, notifier=None, max_loops=None):
    drv, m, port, store = build_paper(rest, clock, notifier)
    stop = {"flag": False}
    if should_stop is None:
        signal.signal(signal.SIGTERM, lambda *a: stop.update(flag=True))
        signal.signal(signal.SIGINT, lambda *a: stop.update(flag=True))
        should_stop = lambda: stop["flag"]   # noqa: E731
    port.send("▶️ [모의] bundle_v5 모의 실행 시작 (실주문 없음)", "review")
    loops = 0
    while not should_stop() and (max_loops is None or loops < max_loops):
        loops += 1
        now = clock() * 1000
        try:
            m.refresh(now)
            if drv.tick(now, limit=60):
                store.save({"drv": drv.state_dict(), "port": port.state()})
        except Exception:  # noqa: BLE001  data hiccup → retried next loop (the minute is rolled back)
            log.exception("paper loop")
        if max_loops is None:
            time.sleep(1.0)
    store.save({"drv": drv.state_dict(), "port": port.state()})
    return drv, port
