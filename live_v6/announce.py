"""Binance announcement classifier for the fast-entry sleeve — pure functions, no network, no disk.

A pushed announcement (title, body, catalog id) becomes a list of `Ann(kind, direction, tokens, reasons)` and each
`Ann` a list of USDⓈ-M perpetual symbols. Nothing calls this yet; the later live sleeve and the post-hoc evaluator
(tools/ann_eval.py) use it, so both read announcements exactly like the research that measured the edge.

The definitions are the research ones (read-only lab code in the scratchpad; the window map evaluated these samples):
  spot_listing   LONG.  p74 collect.py + prepare_events.py: catalog 48, title starts with "binance will list "
                 (case-insensitive); tokens = upper-case tickers in parentheses of the title, minus UTC/USDT/USDC/USD/
                 BNB/BTC. Everything else in catalog 48 (Futures/Options launches, "Binance Will Add … on Earn/Convert/
                 Margin", HODLer/Launchpool introductions, vote-to-list results, renames, token swaps) does not start
                 with that prefix and is therefore not a listing — the research selected by the prefix only.
  monitoring     SHORT. p00d collect.py = bundle_v5_signals.title_selected / parse_announcement (the bot's D sleeve):
                 catalogs 161/49, "monitoring tag" + extend/include/add/change; tokens of the INCLUSION clause only
                 (text after "include", cut at the first "remove": removals and seed-tag changes are never traded).
                 p107 (window-map monitoring sample) parses the body's added-token section instead; both give the same
                 86 events (checked against both event indexes).
  spot_delist    SHORT. p00d: title starts with "binance will delist "; tokens = title from char 20 to " on " /
                 " and " / " & Support".
  futures_delist SHORT. p00d: "binance futures will delist" + ("usd" or "multiple"); contracts XXXUSDT in title + body
                 (sorted, as in the research). Needs the body.
  all D kinds    p00d prepare_events.py = bundle_v5_signals.d_event_symbols: no event when the title says "rebrand" or
                 "swap" or the body says "to support the Story (IP) rebranding plan".
The D kinds call bundle_v5_signals directly, so this classifier and the D sleeve cannot drift apart.

Doubt means an empty list (a person decides), never a guessed token: no ticker found, a D kind without its body, a
catalog the research did not read, or one announcement that would trade the same token both ways.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .strategies import bundle_v5_signals as SG

SPOT_LISTING, MONITORING, SPOT_DELIST, FUTURES_DELIST = "spot_listing", "monitoring", "spot_delist", "futures_delist"
KINDS = (SPOT_LISTING, MONITORING, SPOT_DELIST, FUTURES_DELIST)
D_KINDS = (MONITORING, SPOT_DELIST, FUTURES_DELIST)
DIRECTION = {SPOT_LISTING: 1, MONITORING: -1, SPOT_DELIST: -1, FUTURES_DELIST: -1}

LIST_CATALOGS = (48,)                      # p74 collect.py: catalog 48 "New Cryptocurrency Listing"
D_CATALOGS = tuple(SG.D_CATALOGS)          # p00d collect.py: 161 "Delisting", 49 "Latest Binance News"
LIST_PREFIX = "binance will list "         # p74 collect.py
LIST_TICKER = re.compile(r"\(([A-Z0-9]{1,20})\)")
LIST_DROP = ("UTC", "USDT", "USDC", "USD", "BNB", "BTC")
D_SKIP_TITLE = ("rebrand", "swap")         # p00d prepare_events.py = bundle_v5_signals.d_event_symbols
D_SKIP_BODY = "to support the Story (IP) rebranding plan"


@dataclass(frozen=True)
class Ann:
    kind: str                      # spot_listing | monitoring | spot_delist | futures_delist
    direction: int                 # +1 long, -1 short
    tokens: tuple[str, ...]        # research order, no duplicates
    reasons: tuple[str, ...] = ()  # why (rule, where the tokens came from, what was dropped)


def body_text(body) -> str | None:
    """A pushed / CMS body as plain text, or None when there is none.

    A CMS node tree (dict, or a JSON string holding one — what the detail API returns) is flattened exactly like
    bundle_v5_signals.flatten_body (= p00d collect.py); any other string is taken as plain text as it is."""
    if body is None:
        return None
    if isinstance(body, (bytes, bytearray)):
        body = bytes(body).decode("utf-8", "replace")
    node = body
    if isinstance(body, str):
        if not body.strip():
            return None
        if body.lstrip()[:1] != "{":
            return body
        try:
            node = json.loads(body)
        except ValueError:
            return body
        if not isinstance(node, dict):
            return body
    if not isinstance(node, dict):
        return None
    try:
        text = SG.flatten_body(node)
    except (TypeError, RecursionError):                    # e.g. {"text": null}: unreadable, never guessed
        return None
    return text if text.strip() else None


def _d_kind(title: str) -> str:
    return SG.parse_announcement("", title, 0, "")["kind"]


def title_kinds(title: str, catalog_id: int | None = None) -> tuple[str, ...]:
    """The research rules the TITLE alone selects, before tokens and body (0, 1 or 2 kinds).

    catalog_id None = unknown: the title rules alone decide. A known catalog the research did not read for that kind
    selects nothing."""
    title = str(title or "")
    out = []
    if title.lower().startswith(LIST_PREFIX) and (catalog_id is None or catalog_id in LIST_CATALOGS):
        out.append(SPOT_LISTING)
    if SG.title_selected(title) and (catalog_id is None or catalog_id in D_CATALOGS):
        out.append(_d_kind(title))
    return tuple(out)


def needs_body(title: str, catalog_id: int | None = None) -> bool:
    """True when classify() can only answer with the body (every D kind: futures contracts and the p00d body skip)."""
    return any(k in D_KINDS for k in title_kinds(title, catalog_id))


def _listing(title: str, catalog_id) -> Ann | None:
    found = LIST_TICKER.findall(title)
    toks = tuple(dict.fromkeys(s for s in found if s not in LIST_DROP))
    if not toks:                                            # p74 prepare_events.py: 'no_title_ticker'
        return None
    why = ["p74 현물 상장: 제목이 'Binance Will List ' 로 시작" + ("" if catalog_id is not None else " (카탈로그 미상)"),
           "티커: 제목 괄호 " + ", ".join(toks)]
    dropped = [s for s in dict.fromkeys(found) if s in LIST_DROP]
    if dropped:
        why.append("괄호 안 제외어: " + ", ".join(dropped))
    return Ann(SPOT_LISTING, DIRECTION[SPOT_LISTING], toks, tuple(why))


def _d_ann(title: str, text: str | None, catalog_id) -> Ann | None:
    if text is None:                                        # futures contracts and the body skip need it
        return None
    a = SG.parse_announcement("", title, 0, text)
    if any(w in title.lower() for w in D_SKIP_TITLE) or D_SKIP_BODY in text:
        return None                                         # p00d prepare_events.py: rebrand / swap notices
    toks = tuple(a["symbols"])
    if not toks:
        return None
    kind = a["kind"]
    why = {MONITORING: ["p00d 모니터링 태그: 제목에 'monitoring tag' + extend/include/add/change",
                        "토큰: 제목의 포함(include) 구절"
                        + (" — 제거(remove) 구절은 버림" if re.search(r"\s+(?:and )?remove", title, re.I) else "")],
           SPOT_DELIST: ["p00d 현물 상폐: 제목이 'Binance Will Delist ' 로 시작",
                         "토큰: 제목(21번째 글자부터 ' on '·' and '·' & Support' 앞까지)"],
           FUTURES_DELIST: ["p00d 선물 상폐: 'Binance Futures Will Delist' + USD/Multiple",
                            "계약: 제목+본문의 XXXUSDT (정렬)"]}[kind]
    if catalog_id is None:
        why[0] += " (카탈로그 미상)"
    return Ann(kind, DIRECTION[kind], toks, tuple(why))


def classify(title: str, body=None, catalog_id: int | None = None) -> list[Ann]:
    """(kind, direction, tokens) of one announcement under the research definitions; [] = not a trade (or unsure).

    body: the push's `body` as it came (CMS node-tree JSON string, dict or plain text) or None. One announcement can
    hold two kinds (a listing title that is also a D title): each is read by its own research rule; if any part
    cannot be read, or a token would be traded both ways, the whole announcement is [] (a person decides)."""
    title = str(title or "")
    kinds = title_kinds(title, catalog_id)
    if not kinds:
        return []
    text = body_text(body)
    out = []
    for kind in kinds:
        a = _listing(title, catalog_id) if kind == SPOT_LISTING else _d_ann(title, text, catalog_id)
        if a is None:
            return []
        out.append(a)
    sides = {}
    for a in out:
        for tok in a.tokens:
            sides.setdefault(tok, set()).add(a.direction)
    if any(len(v) > 1 for v in sides.values()):
        return []
    return out


def symbols(ann: Ann, perps: dict, t_ms: int, *, require_trading: bool = True) -> list[str]:
    """USDⓈ-M perpetual symbols for an Ann. perps = {symbol: info} from GET /fapi/v1/exchangeInfo `symbols`.

    Research conditions (p74 / p00d prepare_events.py, p107): contractType PERPETUAL (TRADIFI_PERPETUAL and delivery
    contracts are out), quote USDT, onboardDate <= the announcement time t_ms (a contract listed with or after the
    announcement is not in the sample).
    Contract names per kind, as the research built them:
      spot_listing    TOKENUSDT and 1000TOKENUSDT (p74 tried both, e.g. PEPE -> 1000PEPEUSDT).
      futures_delist  the contract named in the announcement (its token keeps a 1000 prefix: 1000XUSDT).
      monitoring, spot_delist  TOKENUSDT only: p00d and p107 never looked for a 1000-prefixed contract, so such
                      contracts were never in the measured sample — they are left out rather than traded untested.
    require_trading: also demand status == "TRADING". The research could not read the status at the event (it used a
    later exchangeInfo snapshot) and instead kept only contracts with trade data around the event; for a live
    decision the current status is that condition. Pass False for past announcements (a contract delisted since then
    is SETTLING today but was trading at the event)."""
    out = []
    for tok in ann.tokens:
        names = (tok + "USDT", "1000" + tok + "USDT") if ann.kind == SPOT_LISTING else (tok + "USDT",)
        for sym in dict.fromkeys(names):
            info = perps.get(sym)
            if not isinstance(info, dict) or info.get("contractType") != "PERPETUAL" or info.get("quoteAsset", "USDT") != "USDT":
                continue
            try:
                onboard = int(info.get("onboardDate") or 0)
            except (TypeError, ValueError, OverflowError):     # listing time unreadable: not shown to be listed
                continue
            if onboard > int(t_ms):
                continue
            if require_trading and info.get("status") != "TRADING":
                continue
            if sym not in out:
                out.append(sym)
    return out
