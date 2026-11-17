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
The D kinds call bundle_v5_signals directly, so this classifier and the D sleeve read the same tokens.

Guards on top of the research rules. A break-it review found shapes the rules read in the WRONG direction (a token
that is leaving, a pair or margin notice, a contract mentioned for another reason). None of them occurs in the real
announcements the research and that review downloaded (2022-02..2026-11: 84 listing, 26 monitoring-tag, 43 spot-delist
and 72 futures-delist titles, 40 futures-delist bodies): no contract of the research samples is lost (only the EEA
notice, which had no contract, now gives []). Each guard gives [] (a person decides) — never another token:
  spot_listing   the title also handles another token (delist, remove, swap, rebrand, formerly, previously, migrate,
                 rename, redenominate, replace, merge, suspend, halt, discontinue, terminate, cease — as word starts,
                 so "SynFutures" is fine) or nests parentheses ("Sonic (S) (Formerly Fantom (FTM))").
  monitoring     the whole title must have the shape of every real one: "Binance Will ( Change the Monitoring Tag
                 Inclusion Frequency to … and) Extend the Monitoring Tag to (Include) <ticker list>(, (and) Remove the
                 Monitoring/Seed Tag for <ticker list>)…( on 20YY-MM-DD)", and every research token must be in the first
                 list. Removals in other words (Removing, Removal, Will Be Removed, No Longer, Exclude, Lift, Change …
                 to Seed Tag), the Seed Tag's own "to Include" list, "Will Not Extend", "Add …" and anything after the
                 date are thus never shorted.
  spot_delist    the whole title must be "Binance Will Delist <ticker list>( on 20YY-MM-DD)": pairs ("ABC/BTC"),
                 margin, Earn, Convert, options, leveraged tokens, vaults and regional (EEA) notices are not delistings
                 of a token.
  futures_delist the contracts are the title's own XXXUSDT unless the title says "Multiple" (then the body's, as in
                 the research). Each must have its settlement time in the body's "Binance Futures will close" section
                 (bundle_v5_signals.lifecycle_of, the contract as a whole word — not inside 1000XUSDT or XUSDT_261225),
                 and the line that time comes from must have the shape and place of every real one: the section's
                 first line "Binance Futures will close all positions and conduct an automatic settlement on (the)
                 USDⓈ-M <contracts> perpetual contract(s) at <time> (UTC)(, and <contracts> … at <time> (UTC))." or,
                 right below the heading "… automatic settlement the following perpetual contract(s) as below:", a
                 line "<time> (UTC): USDⓈ-M <contracts> Perpetual Contract(s)" (81 of the 82 research contracts of
                 the 40 real bodies — 56 first lines, 25 time-first lines; the 82nd is the Story (IP) notice the
                 research skips). None may be said to stay ("not … affected/delisted/
                 included", "unaffected", "excluded", "exempt", "continues trading", "remains open/listed" — on a line
                 of that section or in one sentence anywhere; a sentence naming the contract and such words about
                 something else, e.g. existing positions, is thus also left to a person). A title — or a Multiple
                 body — saying "not affected", "unaffected", "instead", "launch", "relist", "migrate", "replace",
                 "quarterly", "delivery", "option(s)", "convert" or "swap" (a contract named for another reason),
                 more than 50 contracts, a token over 20 characters or a body over 50,000 characters (real notices:
                 at most 6 contracts of at most 10, bodies under 9,000) is left to a person. A new wording of the
                 settlement line is thus left to a person until the shape is added.
  all D kinds    a token among BTC, ETH, BNB, SOL, XRP is a misreading (pairs, leverage notes), never a delisting.
  every kind     a title saying cancelled, postponed, delayed, revoked, withdrawn, called off, "will not be (de)listed"
                 (CALLED_OFF) is left to a person (none of the 225 real titles the rules select does); so is a futures
                 body saying so (none of the 40 real ones; spot-delist bodies say "orders will be canceled", and the
                 other kinds are read from the title alone, as in the research).
  one notice     a contract that would be traded both ways (also through the 1000-prefix: FOO long → 1000FOOUSDT,
                 1000FOO short) gives [].
So the classifier may give [] — or, for a futures title, fewer contracts — where the bot's D sleeve (bundle_v5_signals,
read-only here) trades, never a token the D sleeve would not trade and never the other direction.

Known misses, kept because the research measured exactly these rules (changing them needs the research re-run first):
spot-delist titles are cut at " and " ("… NCASH and YOYO on …" misses YOYO); the monitoring and spot-delist title
rules never read a token starting with a digit (1INCH, 1000SATS — futures contracts like 1000SATSUSDT are read); a
listing in full-width parentheses ("（FOO）") or with a lower-case ticker (XAUt) gives []; a futures contract written
without USDT ("DEFIUSDT and MEMEFI perpetual contracts": MEMEFI, hand-added by p00d) is missed — the evaluator marks
such notices.

Doubt means an empty list (a person decides), never a guessed token: no ticker found, a D kind without its body, a
catalog the research did not read (or an unreadable one), a title over 400 characters, a guard above. explain() says
why.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from .strategies import bundle_v5_signals as SG

SPOT_LISTING, MONITORING, SPOT_DELIST, FUTURES_DELIST = "spot_listing", "monitoring", "spot_delist", "futures_delist"
KINDS = (SPOT_LISTING, MONITORING, SPOT_DELIST, FUTURES_DELIST)
D_KINDS = (MONITORING, SPOT_DELIST, FUTURES_DELIST)
DIRECTION = {SPOT_LISTING: 1, MONITORING: -1, SPOT_DELIST: -1, FUTURES_DELIST: -1}
KIND_KO = {SPOT_LISTING: "현물 상장", MONITORING: "모니터링 태그", SPOT_DELIST: "현물 상폐", FUTURES_DELIST: "선물 상폐"}

LIST_CATALOGS = (48,)                      # p74 collect.py: catalog 48 "New Cryptocurrency Listing"
D_CATALOGS = tuple(SG.D_CATALOGS)          # p00d collect.py: 161 "Delisting", 49 "Latest Binance News"
LIST_PREFIX = "binance will list "         # p74 collect.py
LIST_TICKER = re.compile(r"\(([A-Z0-9]{1,20})\)")
LIST_DROP = ("UTC", "USDT", "USDC", "USD", "BNB", "BTC")
D_SKIP_TITLE = ("rebrand", "swap")         # p00d prepare_events.py = bundle_v5_signals.d_event_symbols
D_SKIP_BODY = "to support the Story (IP) rebranding plan"

# guards (module docstring) — word starts, case-insensitive
LIST_OTHER = re.compile(r"\b(?:delist|remov|swap|rebrand|formerly|previously|migrat|renam|redenominat|replac|merg"
                        r"|suspend|halt|discontinu|terminat|cease)\w*", re.I)
TICKER_LIST = r"[A-Z0-9]{1,20}(?:(?:\s*,\s*(?:and\s+)?|\s*&\s*|\s+and\s+)[A-Z0-9]{1,20})*"
MON_TITLE = re.compile((r"\s*(?i:binance will (?:change the monitoring tag inclusion frequency to [a-z]+ and )?"
                        r"extend the monitoring tag to (?:include )?)(" + TICKER_LIST + r")"
                        r"(?:(?i:,? (?:and )?remove the (?:monitoring|seed) tag for )" + TICKER_LIST + r")*"
                        r"(?: (?i:on) 20\d\d-\d\d-\d\d)?\s*").replace(" ", r"\s+"))   # any run of spaces
DELIST_SHAPE = re.compile(r"\s*(?i:binance will delist)\s+" + TICKER_LIST + r"(?:\s+(?i:on)\s+20\d\d-\d\d-\d\d)?\s*")
FUT_CONTRACT = re.compile(r"\b([A-Z0-9]+)USDT\b")              # = bundle_v5_signals.parse_announcement
FUT_OTHER = re.compile(r"\b(?:not\s+affected|unaffected|instead|launch\w*|relist\w*|migrat\w*|replac\w*|quarterly"
                       r"|delivery|options?|convert\w*|swap\w*)\b", re.I)
FUT_NEGATION = (r"(?:not\s+(?:\w+\s+){0,3}(?:affected|impacted|delisted|included|removed)|un(?:affected|impacted)"
                r"|exclud\w*|exempt\w*|continu\w*\s+(?:to\s+)?(?:be\s+)?trad\w*"
                r"|remain\w*\s+(?:open|available|listed|tradable|trading))")   # "this contract stays"
_FUT_TIME = SG.DATE_PAT.replace(" ", r"\s+") + r"\s+\(UTC\)"
_FUT_LIST = r"[A-Z0-9]{1,30}(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+)[A-Z0-9]{1,30})*"
_FUT_USDM = r"(?:USDⓈ-M(?:argined)?\s+)?"
_FUT_SEG = _FUT_USDM + _FUT_LIST + r"\s+" + _FUT_USDM + r"(?i:perpetual\s+contracts?\s+at)\s+" + _FUT_TIME
CLOSE_LINE = re.compile(                   # the two shapes of every settlement line of the real bodies (module docstring)
    r"\s*(?:(?i:binance\s+futures\s+will\s+close\s+all\s+positions\s+and\s+conduct\s+an\s+automatic\s+settlement\s+on"
    r"\s+(?:the\s+)?)" + _FUT_SEG + r"(?:\s*,\s*(?i:and\s+(?:the\s+)?)" + _FUT_SEG + r")*\.?"
    r"|" + _FUT_TIME + r":\s*" + _FUT_USDM + _FUT_LIST + r"\s+" + _FUT_USDM + r"(?i:perpetual\s+contracts?))\s*")
CLOSE_HEAD = re.compile(r"\s*(?i:binance\s+futures\s+will\s+close\s+all\s+positions\s+and\s+conduct\s+an\s+automatic"
                        r"\s+settlement\s+(?:on\s+)?the\s+following\s+perpetual\s+contract\(s\)\s+as\s+below:)\s*")
MAX_FUT_CONTRACTS = 50                     # real futures-delist notices name at most 6 (2022-02..2026-11)
MAX_FUT_TOKEN = 20                         # ... with tokens of at most 10 characters
MAX_FUT_BODY = 50_000                      # ... in bodies of at most 8,707 characters (every body: at most 12,710)
CALLED_OFF = re.compile(r"\b(?:cancel(?:l)?ed|cancel(?:l)?ation\w*|postpon\w*|delay\w*|revok\w*|revocation|rescind\w*"
                        r"|withdrawn|retract\w*|voided|called\s+off|no\s+longer\s+(?:be\s+)?(?:delisted|closed|settled|listed)"
                        r"|will\s+not\s+(?:be\s+)?(?:delist\w*|clos\w*|settl\w*|list\w*))\b", re.I)
MAJORS = ("BTC", "ETH", "BNB", "SOL", "XRP")
MON_BODY_ADDED = re.compile(r"to be added to the Monitoring Tag", re.I)   # p107 build_events.py's body section
BAD_CATALOG = -1                           # an unreadable catalog id: no catalog the research read
MAX_TITLE = 400                            # longest real title 288 chars; ann_ws_shadow logs 500 at most (cut)
LIVE_UNDERLYING = ("COIN", "PREMARKET")    # exchangeInfo underlyingType of the research's listing / D contracts


@dataclass(frozen=True)
class Ann:
    kind: str                      # spot_listing | monitoring | spot_delist | futures_delist
    direction: int                 # +1 long, -1 short
    tokens: tuple[str, ...]        # research order, no duplicates
    reasons: tuple[str, ...] = ()  # why (rule, where the tokens came from, what was dropped)


def body_text(body) -> str | None:
    """A pushed / CMS body as plain text, or None when there is none or it cannot be read.

    A CMS node tree (dict, or a JSON string holding one — what the detail API returns) is flattened exactly like
    bundle_v5_signals.flatten_body (= p00d collect.py). A string starting with "{" must be such a tree (a broken or
    too deeply nested one is unreadable: None, never searched as text); any other JSON value (null, [], 123, "…") is
    not a body (None); a string that is not JSON at all is plain text, taken as it is."""
    if body is None:
        return None
    if isinstance(body, (bytes, bytearray)):
        body = bytes(body).decode("utf-8", "replace")
    node = body
    if isinstance(body, str):
        if not body.strip():
            return None
        try:
            node = json.loads(body)
        except RecursionError:                              # nested beyond the parser: unreadable
            return None
        except ValueError:
            return None if body.lstrip()[:1] == "{" else body
        if not isinstance(node, dict):
            return None
    if not isinstance(node, dict):
        return None
    try:
        text = SG.flatten_body(node)
    except (TypeError, RecursionError):                    # e.g. {"text": null}: unreadable, never guessed
        return None
    return text if text.strip() else None


def catalog(v) -> int | None:
    """None = unknown; an int, a digit string or an integral float = that catalog; anything else (bool, "abc", 48.5)
    = BAD_CATALOG, which selects nothing (an unreadable id is not "unknown")."""
    if v is None:
        return None
    if isinstance(v, bool):
        return BAD_CATALOG
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if math.isfinite(v) and v.is_integer() else BAD_CATALOG
    if isinstance(v, str) and v.strip().isascii() and v.strip().isdigit():
        try:
            return int(v.strip())
        except ValueError:                                  # more digits than int() converts
            return BAD_CATALOG
    return BAD_CATALOG


def _d_kind(title: str) -> str:
    return SG.parse_announcement("", title, 0, "")["kind"]


def title_kinds(title: str, catalog_id=None) -> tuple[str, ...]:
    """The research rules the TITLE alone selects, before tokens and body (0, 1 or 2 kinds).

    catalog_id None = unknown: the title rules alone decide. A known catalog the research did not read for that kind
    selects nothing; so does an unreadable one (see catalog())."""
    title = str(title or "")
    cat = catalog(catalog_id)
    out = []
    if len(title) > MAX_TITLE:              # not a real title (or a cut one); the research's title splits are quadratic
        return ()
    if title.lower().startswith(LIST_PREFIX) and (cat is None or cat in LIST_CATALOGS):
        out.append(SPOT_LISTING)
    if SG.title_selected(title) and (cat is None or cat in D_CATALOGS):
        out.append(_d_kind(title))
    return tuple(out)


def needs_body(title: str, catalog_id=None) -> bool:
    """True when classify() can only answer with the body (every D kind: futures contracts and the p00d body skip)."""
    return any(k in D_KINDS for k in title_kinds(title, catalog_id))


def _nested_parens(title: str) -> bool:
    depth = 0
    for ch in title:
        if ch == "(":
            depth += 1
            if depth > 1:
                return True
        elif ch == ")":
            depth = max(0, depth - 1)
    return False


def _listing(title: str, cat) -> tuple[Ann | None, str]:
    found = LIST_TICKER.findall(title)
    toks = tuple(dict.fromkeys(s for s in found if s not in LIST_DROP))
    if not toks:                                            # p74 prepare_events.py: 'no_title_ticker'
        return None, "제목 괄호에 티커 없음(p74 no_title_ticker)"
    other = LIST_OTHER.search(title)
    if other:
        return None, f"제목이 다른 토큰 처리('{other.group(0)}')도 다룸 — 괄호 티커가 모두 신규 상장인지 모름, 사람 판단"
    if _nested_parens(title):
        return None, "제목 괄호가 겹침(옛 이름 표기 등) — 괄호 티커가 모두 신규 상장인지 모름, 사람 판단"
    why = ["p74 현물 상장: 제목이 'Binance Will List ' 로 시작" + ("" if cat is not None else " (카탈로그 미상)"),
           "티커: 제목 괄호 " + ", ".join(toks)]
    dropped = [s for s in dict.fromkeys(found) if s in LIST_DROP]
    if dropped:
        why.append("괄호 안 제외어: " + ", ".join(dropped))
    return Ann(SPOT_LISTING, DIRECTION[SPOT_LISTING], toks, tuple(why)), ""


def _listed(segment: str) -> set:
    return set(re.findall(r"[A-Z0-9]+", segment))


def _monitoring_guard(title: str, toks: tuple) -> tuple[tuple | None, str]:
    m = MON_TITLE.fullmatch(title)
    if m is None:
        return None, ("제목이 실제 모니터링 공지 꼴('Binance Will Extend the Monitoring Tag to (Include) <티커 목록>"
                      "(, Remove the … Tag for <티커 목록>) on <날짜>')이 아님(제거·Seed 태그·부정 표현일 수 있음) — 사람 판단")
    extra = [t for t in toks if t not in _listed(m.group(1))]
    if extra:
        return None, f"p00d 규칙이 포함 목록 밖의 {', '.join(extra)} 도 읽음 — 사람 판단"
    return toks, ""


def _spot_delist_guard(title: str, toks: tuple) -> tuple[tuple | None, str]:
    # the p00d tokens (title[20:] up to " on " / " and ") then always come from that ticker list
    if DELIST_SHAPE.fullmatch(title) is None:
        return None, "제목이 'Binance Will Delist <티커 목록> on <날짜>' 꼴이 아님(페어·마진·Earn·Convert·옵션·지역 공지 등) — 사람 판단"
    return toks, ""


def _close_section(text: str) -> str:
    """The part of a futures-delist body bundle_v5_signals.lifecycle_of reads settlement times from, "Binance Futures
    will close" up to "The contract(s) will …" — its slicing, but found without the shift lifecycle_of's index takes
    after an "İ" (whose lower case is two characters: the section would start inside the phrase)."""
    m = re.search("binance futures will close", text, re.I)
    part = text[m.start():] if m else ""
    return part.split("The contracts will")[0].split("The contract(s)")[0].split("The contract will")[0]


def _settlement_rows(lines: list) -> set:
    """Indexes of the settlement lines of a close section laid out like every real one: its first line in shape 1, or
    the time-first lines (shape 2) right below the real heading ("… automatic settlement the following perpetual
    contract(s) as below:"), blank lines aside. A section laid out otherwise has none."""
    if not lines:
        return set()
    if not CLOSE_HEAD.fullmatch(lines[0]):
        return {0} if CLOSE_LINE.fullmatch(lines[0]) else set()
    rows = set()
    for k, line in enumerate(lines[1:], 1):
        if not line.strip():
            continue
        if not (re.match(r"\s*" + SG.DATE_PAT, line) and CLOSE_LINE.fullmatch(line)):
            break
        rows.add(k)
    return rows


def _close_line(text: str, tok: str) -> tuple:
    """(the line of the close section bundle_v5_signals.lifecycle_of takes TOKUSDT's settlement time from — None when it
    finds no time —, whether that line is a settlement line of the real layout), reading only whole-word mentions
    (lifecycle_of matches substrings: a line about 1000TOKUSDT or TOKUSDT_261225 would count). lifecycle_of may raise
    ValueError / OverflowError (a time that is not a date)."""
    c = tok + "USDT"
    masked = re.sub(rf"(?<=\w){re.escape(c)}|{re.escape(c)}(?=\w)", "#", text)   # hide mentions inside longer words
    if not SG.lifecycle_of(dict(kind=FUTURES_DELIST, code="", t=0, symbols=[tok], text=masked)):
        return None, False
    lines = _close_section(masked).splitlines()
    k = next((k for k, line in enumerate(lines) if c in line and re.search(SG.DATE_PAT, line)), None)
    return (None, False) if k is None else (lines[k], k in _settlement_rows(lines))


def _negated(joined: str, section: str, tok: str) -> bool:
    """The body says TOKUSDT stays (not affected, excluded, continues trading, …): on a line of the close section, or
    in one sentence anywhere — `joined` is the body with lines that go on in lower case joined to the line before.
    In the 40 real futures-delist bodies no research contract is said to stay."""
    c = rf"(?<!\w){re.escape(tok + 'USDT')}(?!\w)"
    if any(re.search(c, ln) and re.search(FUT_NEGATION, ln, re.I) for ln in section.splitlines()):
        return True
    return re.search(rf"{c}[^.\n]{{0,160}}?\b{FUT_NEGATION}|\b{FUT_NEGATION}[^.\n]{{0,160}}?{c}", joined, re.I) is not None


def _futures_guard(title: str, text: str, toks: tuple) -> tuple[tuple | None, str]:
    if len(text) > MAX_FUT_BODY:                            # the checks below read the body once per contract
        return None, f"본문이 {MAX_FUT_BODY:,}자를 넘음(실제 선물 상폐 본문은 9천 자 미만) — 사람 판단"
    off = CALLED_OFF.search(text)
    if off:
        return None, f"본문에 '{off.group(0)}' — 취소·연기된 일정일 수 있음, 사람 판단"
    multiple = "multiple" in title.lower()
    if not multiple:                                        # the contracts the title names (the research's are a superset)
        in_title = set(FUT_CONTRACT.findall(title))
        toks = tuple(t for t in toks if t in in_title)
        if not toks:
            return None, "제목에 USDT 무기한 계약이 없음('Multiple' 제목만 본문의 계약을 씀) — 사람 판단"
    if len(toks) > MAX_FUT_CONTRACTS:
        return None, f"계약이 {len(toks)}개({MAX_FUT_CONTRACTS}개 초과) — 실제 공지는 6개 이하, 사람 판단"
    if any(len(t) > MAX_FUT_TOKEN for t in toks):
        return None, f"계약 이름이 {MAX_FUT_TOKEN}자를 넘음 — 실제 공지는 10자 이하, 사람 판단"
    other = FUT_OTHER.search(title + " " + text if multiple else title)
    if other:
        return None, f"{'제목·본문' if multiple else '제목'}에 '{other.group(0)}' — 다른 이유로 적힌 계약일 수 있음, 사람 판단"
    section, joined = _close_section(text), re.sub(r"\n[ \t]*(?=[a-z])", " ", text)
    negated = [t + "USDT" for t in toks if _negated(joined, section, t)]
    if negated:
        return None, f"본문이 {', '.join(negated)} 는 남는다고 적음('영향 없음'·제외·거래 계속 등) — 상폐와 모순, 사람 판단"
    try:
        found = {t: _close_line(text, t) for t in toks}
    except (ValueError, OverflowError):                     # a settlement time that is not a date
        return None, "본문의 정산 시각을 읽을 수 없음 — 사람 판단"
    undated = [t + "USDT" for t in toks if found[t][0] is None]
    if undated:
        return None, f"{', '.join(undated)} 의 정산 시각이 본문 'Binance Futures will close' 부분에 없음 — 사람 판단"
    odd = [t + "USDT" for t in toks if not found[t][1]]
    if odd:
        return None, (f"{', '.join(odd)} 의 정산 줄이 실제 공지 꼴이 아님('Binance Futures will close all positions … at "
                      f"<시각> (UTC).' 첫 줄, 또는 '… as below:' 바로 아래 '<시각> (UTC): USDⓈ-M … Perpetual Contracts' "
                      f"줄) — 사람 판단")
    return toks, ""


GUARDS = {MONITORING: lambda title, text, toks: _monitoring_guard(title, toks),
          SPOT_DELIST: lambda title, text, toks: _spot_delist_guard(title, toks),
          FUTURES_DELIST: _futures_guard}


def _d_ann(title: str, text: str | None, cat) -> tuple[Ann | None, str]:
    if text is None:                                        # futures contracts and the body skip need it
        return None, "본문 없음(상폐·모니터링은 본문까지 보고 판정)"
    a = SG.parse_announcement("", title, 0, text)
    if any(w in title.lower() for w in D_SKIP_TITLE) or D_SKIP_BODY in text:
        return None, "p00d 제외 공지(rebrand·swap·Story 이전)"
    kind, toks = a["kind"], tuple(a["symbols"])
    if not toks:
        if kind == MONITORING and MON_BODY_ADDED.search(text):
            return None, "판정 보류(사람 확인): 제목에 티커가 없고 본문에 추가 대상 구절이 있음(봇 규칙은 제목만 읽음)"
        return None, "p00d 규칙으로 읽은 토큰 없음"
    toks, why_not = GUARDS[kind](title, text, toks)
    if toks is None:
        return None, why_not
    major = [t for t in toks if t in MAJORS]
    if major:
        return None, f"주요 자산 {', '.join(major)} 이(가) 대상으로 읽힘 — 페어·레버리지 언급의 오독으로 보고 사람 판단"
    why = {MONITORING: ["p00d 모니터링 태그: 제목에 'monitoring tag' + extend/include/add/change",
                        "토큰: 제목의 포함(include) 구절"
                        + (" — 제거(remove) 구절은 버림" if re.search(r"\s+(?:and )?remove", title, re.I) else "")],
           SPOT_DELIST: ["p00d 현물 상폐: 제목이 'Binance Will Delist ' 로 시작",
                         "토큰: 제목(21번째 글자부터 ' on '·' and '·' & Support' 앞까지)"],
           FUTURES_DELIST: ["p00d 선물 상폐: 'Binance Futures Will Delist' + USD/Multiple",
                            ("계약: 본문의 XXXUSDT (정렬, 'Multiple' 제목)" if "multiple" in title.lower()
                             else "계약: 제목의 XXXUSDT (정렬)") + " — 모두 본문 정산 일정에 있음"]}[kind]
    if cat is None:
        why[0] += " (카탈로그 미상)"
    return Ann(kind, DIRECTION[kind], toks, tuple(why)), ""


def _names(kind: str, tok: str) -> tuple[str, ...]:
    """Contract names a token can trade as (see symbols())."""
    return (tok + "USDT", "1000" + tok + "USDT") if kind == SPOT_LISTING else (tok + "USDT",)


def explain(title: str, body=None, catalog_id=None) -> tuple[list[Ann], str]:
    """classify() and, when it gives [], why in one Korean line (for reports; '' when there are Anns)."""
    title = str(title or "")
    cat = catalog(catalog_id)
    if len(title) > MAX_TITLE:
        return [], f"제목이 {MAX_TITLE}자를 넘음(실제 공지 제목은 300자 미만, 잘린 제목일 수 있음) — 사람 판단"
    kinds = title_kinds(title, cat)
    if not kinds:
        return [], "매매 대상 아님(제목 규칙)" + (" — 카탈로그 값을 읽을 수 없음" if cat == BAD_CATALOG else "")
    off = CALLED_OFF.search(title)
    if off:
        return [], f"제목에 '{off.group(0)}' — 취소·연기 공지일 수 있음, 사람 판단"
    text = body_text(body)
    out = []
    for kind in kinds:
        a, why = _listing(title, cat) if kind == SPOT_LISTING else _d_ann(title, text, cat)
        if a is None:
            return [], f"{KIND_KO[kind]}: {why}"
        out.append(a)
    sides = {}
    for a in out:
        for tok in a.tokens:
            for name in _names(a.kind, tok):
                sides.setdefault(name, set()).add(a.direction)
    both = sorted(n for n, v in sides.items() if len(v) > 1)
    if both:
        return [], f"한 공지가 {', '.join(both)} 를 양방향으로 매매하게 됨 — 사람 판단"
    return out, ""


def classify(title: str, body=None, catalog_id=None) -> list[Ann]:
    """(kind, direction, tokens) of one announcement under the research definitions; [] = not a trade (or unsure).

    body: the push's `body` as it came (CMS node-tree JSON string, dict or plain text) or None. One announcement can
    hold two kinds (a listing title that is also a D title): each is read by its own research rule; if any part
    cannot be read, or a contract would be traded both ways, the whole announcement is [] (a person decides)."""
    return explain(title, body, catalog_id)[0]


def symbols(ann: Ann, perps: dict, t_ms: int, *, require_trading: bool = True) -> list[str]:
    """USDⓈ-M perpetual symbols for an Ann. perps = {symbol: info} from GET /fapi/v1/exchangeInfo `symbols`.

    Research conditions (p74 / p00d prepare_events.py, p107): contractType PERPETUAL (TRADIFI_PERPETUAL and delivery
    contracts are out), quote USDT, onboardDate <= the announcement time t_ms (a contract listed with or after the
    announcement is not in the sample). A missing / empty / zero / unreadable onboardDate means "not shown to be
    listed" (the research's snapshot always had one; its default 0 would have meant "listed long ago").
    Contract names per kind, as the research built them:
      spot_listing    TOKENUSDT and 1000TOKENUSDT (p74 tried both, e.g. PEPE -> 1000PEPEUSDT).
      futures_delist  the contract named in the announcement (its token keeps a 1000 prefix: 1000XUSDT).
      monitoring, spot_delist  TOKENUSDT only: p00d and p107 never looked for a 1000-prefixed contract, so such
                      contracts were never in the measured sample — they are left out rather than traded untested.
    require_trading: also demand status == "TRADING" and — except for futures_delist, whose contract is named outright —
    underlyingType COIN or PREMARKET, the types in the research samples (p74 had the pre-market PREDICTUSDT): a token
    name that is also an index perpetual's (ALLUSDT, BTCDOMUSDT) is not that token, and a type the research never
    saw is left to a person. The research could not read the status at the event (it used a later exchangeInfo
    snapshot) and instead kept only contracts with trade data around the event; for a live decision the current
    status is that condition. Pass False for past announcements (a contract delisted since then is SETTLING today but
    was trading at the event; the research did not look at underlyingType — its one index perpetual, DEFIUSDT, is a
    futures delist)."""
    out = []
    for tok in ann.tokens:
        for sym in dict.fromkeys(_names(ann.kind, tok)):
            info = perps.get(sym)
            if not isinstance(info, dict) or info.get("contractType") != "PERPETUAL" or info.get("quoteAsset", "USDT") != "USDT":
                continue
            onboard = info.get("onboardDate")
            if isinstance(onboard, bool) or onboard in (None, "", 0):
                continue                                    # listing time unknown: not shown to be listed
            try:
                onboard = int(onboard)
            except (TypeError, ValueError, OverflowError):  # listing time unreadable: not shown to be listed
                continue
            if onboard <= 0 or onboard > int(t_ms):
                continue
            if require_trading and (info.get("status") != "TRADING"
                                    or (ann.kind != FUTURES_DELIST and info.get("underlyingType") not in LIVE_UNDERLYING)):
                continue
            if sym not in out:
                out.append(sym)
    return out
