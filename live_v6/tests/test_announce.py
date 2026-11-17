"""announce.py — the announcement classifier must read titles exactly like the research that measured the edge.

fixtures/ann_cases.json holds public Binance announcements (title, catalog, publishDate, CMS body) with the answer
taken from the research outputs (p74 announcements.json + prepare_events.py for listings, p00d announcements.json +
prepare_events.py for delist/monitoring) and an exchangeInfo subset from the research snapshot — not from announce.py.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import pathlib

import pytest

from live_v6 import announce as AN
from live_v6.strategies import bundle_v5_signals as SG

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "ann_cases.json").read_text(encoding="utf-8"))
CASES = FIX["cases"]
PERPS = FIX["perps"]


def _ids(c):
    return c["name"][:60]


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_research_announcements_classify_like_the_research(case):
    anns = AN.classify(case["title"], case["body"], case["catalogId"])
    assert [dict(kind=a.kind, direction=a.direction, tokens=list(a.tokens)) for a in anns] == case["expect"]
    syms = [s for a in anns for s in AN.symbols(a, PERPS, case["publishDate"], require_trading=False)]
    assert syms == case["symbols"]
    assert all(a.reasons for a in anns)


def test_fixture_covers_every_kind_with_positives_and_negatives():
    kinds = {e["kind"] for c in CASES for e in c["expect"]}
    assert kinds == set(AN.KINDS)
    assert sum(1 for c in CASES if not c["expect"]) >= 10
    assert sum(1 for c in CASES if c["expect"] and not c["symbols"]) >= 3     # a trade kind but no perpetual


def _d_cases():
    return [c for c in CASES if c["catalogId"] in AN.D_CATALOGS and SG.title_selected(c["title"])]


@pytest.mark.parametrize("case", _d_cases(), ids=_ids)
def test_delist_and_monitoring_equal_the_bots_d_sleeve(case):
    """The D sleeve (bundle_v5_signals) and the classifier must never disagree on a delist / monitoring notice."""
    text = SG.flatten_body(json.loads(case["body"]))
    a = SG.parse_announcement(case["code"], case["title"], case["publishDate"], text)
    perpetual = {s: i for s, i in PERPS.items() if i["contractType"] == "PERPETUAL"}
    want_syms = SG.d_event_symbols(a, perpetual)
    anns = AN.classify(case["title"], case["body"], case["catalogId"])
    skipped = any(w in case["title"].lower() for w in ("rebrand", "swap")) or "to support the Story (IP) rebranding plan" in text
    if skipped or not a["symbols"]:
        assert anns == [] and want_syms == []
        return
    assert [(x.kind, list(x.tokens)) for x in anns] == [(a["kind"], a["symbols"])]
    assert AN.symbols(anns[0], PERPS, case["publishDate"], require_trading=False) == want_syms


def test_memefi_hand_fix_of_the_research_is_not_guessed():
    """p00d prepare_events.py hand-adds MEMEFI (never written as MEMEFIUSDT); the rule — and the D sleeve — do not."""
    c = next(c for c in CASES if "MEMEFI" in c["title"])
    assert c["research_symbols"] == ["DEFIUSDT", "MEMEFIUSDT"]
    anns = AN.classify(c["title"], c["body"], c["catalogId"])
    assert AN.symbols(anns[0], PERPS, c["publishDate"], require_trading=False) == ["DEFIUSDT"]


# ───────────────────────── titles ─────────────────────────
def test_monitoring_add_and_remove_in_one_title_keeps_only_the_inclusion():
    t = "Binance Will Extend the Monitoring Tag to Include ANT, FIRO & ZEN, and Remove the Seed Tag for GMX on 2024-01-04"
    [a] = AN.classify(t, "plain body", 49)
    assert (a.kind, a.direction, a.tokens) == ("monitoring", -1, ("ANT", "FIRO", "ZEN"))
    assert any("remove" in r for r in a.reasons)
    assert AN.classify("Binance Will Remove the Monitoring Tag for ZEC and the Seed Tag for ENA on 2025-07-09", "x", 49) == []


def test_listing_tokens_come_from_title_parentheses_minus_quote_words():
    [a] = AN.classify("Binance Will List Cheems (1000CHEEMS) and Test (TST) with Seed Tag Applied", None, 48)
    assert (a.kind, a.direction, a.tokens) == ("spot_listing", 1, ("1000CHEEMS", "TST"))
    [b] = AN.classify("Binance Will List Foo (FOO) (USDT) (BNB)", None, None)
    assert b.tokens == ("FOO",) and any("USDT" in r for r in b.reasons)
    assert AN.classify("Binance Will List World Liberty Financial USD (USD1)", None, 48)[0].tokens == ("USD1",)


@pytest.mark.parametrize("title", [
    "Binance Will List Tether Gold (XAUt) with Seed Tag Applied",           # lower-case ticker: research found none
    "Binance Will List BFUSD and Introduce BFUSD Zero Trading Fee Promotion",
    "Binance Will List (USDT)",
    "Binance Futures Will Launch USDⓈ-M ILV Perpetual Contract With Up to 50x Leverage",
    "Binance Will Add Polygon (POL) on Earn, Buy Crypto, Convert, Margin & Futures",
    "Introducing Fusionist (ACE) on Binance Launchpool! Farm ACE by Staking BNB and FDUSD",
    "Binance Announced the First Batch of Vote to List Results and Will List CHEEMS (1000CHEEMS)",
    "Notice on the Rebranding of ABC (ABC) to XYZ (XYZ)",
    "",
])
def test_not_a_listing_or_unsure_is_empty(title):
    assert AN.classify(title, None, 48) == []
    assert AN.classify(title, None, None) == []


def test_catalog_must_be_the_one_the_research_read():
    assert AN.classify("Binance Will List Foo (FOO)", None, 161) == []
    assert AN.classify("Binance Will Delist ABC on 2025-01-01", "body", 48) == []
    assert AN.title_kinds("Binance Will Delist ABC on 2025-01-01", None) == ("spot_delist",)
    assert AN.title_kinds("Binance Will List Foo (FOO)", 48) == ("spot_listing",)


def test_d_kinds_need_the_body_and_never_guess_without_it():
    t = "Binance Futures Will Delist USDⓈ-M FOOUSDT Perpetual Contract"
    assert AN.needs_body(t, 161) and not AN.needs_body("Binance Will List Foo (FOO)", 48)
    assert AN.classify(t, None, 161) == [] and AN.classify(t, "   ", 161) == []
    [a] = AN.classify(t, "Binance Futures will close all positions on FOOUSDT and BARUSDT.", 161)
    assert (a.kind, a.tokens) == ("futures_delist", ("BAR", "FOO"))          # sorted, title + body, as in the research
    assert AN.classify("Binance Will Delist ABC on 2025-01-01", None, 161) == []


def test_rebrand_swap_and_story_notices_are_skipped_like_the_research():
    assert AN.classify("Binance Will Delist UTK and Support Rebranding and Airdrop Plan", "x", 161) == []
    assert AN.classify("Binance Will Delist ABC and Support the Token Swap", "x", 161) == []
    t = "Binance Futures Will Delist USDⓈ-Margined IPUSDT and IPUSDC Perpetual Contracts"
    assert AN.classify(t, "IPUSDT ... to support the Story (IP) rebranding plan ...", 161) == []
    assert AN.classify(t, "IPUSDT will be delisted.", 161)[0].tokens == ("IP",)


def test_body_forms_node_tree_string_dict_and_plain_text():
    tree = {"node": "root", "child": [{"tag": "p", "child": [{"text": "close FOOUSDT"}]}, {"tag": "li", "text": "BARUSDT"}]}
    assert AN.body_text(json.dumps(tree)) == SG.flatten_body(tree) == "close FOOUSDT\nBARUSDT\n"
    assert AN.body_text(tree) == SG.flatten_body(tree)
    assert AN.body_text("plain FOOUSDT text") == "plain FOOUSDT text"
    assert AN.body_text("{not json") == "{not json"
    assert AN.body_text(b"bytes FOOUSDT") == "bytes FOOUSDT"
    assert AN.body_text(None) is None and AN.body_text("") is None and AN.body_text(json.dumps({"child": []})) is None
    t = "Binance Futures Will Delist USDⓈ-M FOOUSDT Perpetual Contract"
    assert AN.classify(t, json.dumps(tree), 161)[0].tokens == ("BAR", "FOO")


def test_an_unreadable_node_tree_is_no_body_not_a_crash():
    t = "Binance Futures Will Delist USDⓈ-M FOOUSDT Perpetual Contract"
    for bad in ({"text": None}, {"child": 5}, {"text": "a", "child": [{"text": 7}]}):
        assert AN.body_text(json.dumps(bad)) is None and AN.body_text(bad) is None
        assert AN.classify(t, json.dumps(bad), 161) == []


def test_a_token_traded_both_ways_by_one_announcement_is_left_to_a_person():
    t = "Binance Will List Foo (FOO) and Add the Monitoring Tag to FOO"   # not a real title: both rules select it
    assert AN.title_kinds(t, None) == ("spot_listing", "monitoring")
    assert AN.classify(t, "body", None) == []
    t2 = "Binance Will List Foo (FOO); Binance Will Extend the Monitoring Tag to Include BAR"   # each rule its own tokens
    assert [(a.kind, a.tokens) for a in AN.classify(t2, "body", None)] == [("spot_listing", ("FOO",)), ("monitoring", ("BAR",))]


def test_ann_is_immutable():
    a = AN.Ann("monitoring", -1, ("ABC",), ("why",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.tokens = ("XYZ",)


# ───────────────────────── symbols ─────────────────────────
def _info(sym, onboard=1, status="TRADING", ctype="PERPETUAL", quote="USDT"):
    return dict(symbol=sym, contractType=ctype, status=status, onboardDate=onboard, quoteAsset=quote)


def test_symbols_follow_the_research_contract_rules():
    perps = {s: _info(s) for s in ("FOOUSDT", "1000BARUSDT", "1000FOOUSDT", "BAZUSDT", "QUXUSDT", "OLDUSDT")}
    perps["BAZUSDT"] = _info("BAZUSDT", onboard=2_000)                    # listed after the announcement
    perps["QUXUSDT"] = _info("QUXUSDT", ctype="TRADIFI_PERPETUAL")
    perps["OLDUSDT"] = _info("OLDUSDT", status="SETTLING")
    lst = AN.Ann("spot_listing", 1, ("FOO", "BAR", "BAZ", "QUX", "OLD"))
    assert AN.symbols(lst, perps, 1_000) == ["FOOUSDT", "1000FOOUSDT", "1000BARUSDT"]
    assert AN.symbols(lst, perps, 1_000, require_trading=False) == ["FOOUSDT", "1000FOOUSDT", "1000BARUSDT", "OLDUSDT"]
    assert AN.symbols(lst, perps, 2_000) == ["FOOUSDT", "1000FOOUSDT", "1000BARUSDT", "BAZUSDT"]
    mon = AN.Ann("monitoring", -1, ("FOO", "BAR"))
    assert AN.symbols(mon, perps, 1_000) == ["FOOUSDT"]                  # no 1000-prefix lookup for D kinds
    fut = AN.Ann("futures_delist", -1, ("1000BAR",))
    assert AN.symbols(fut, perps, 1_000) == ["1000BARUSDT"]
    assert AN.symbols(mon, {"FOOUSDT": _info("FOOUSDT", quote="USDC")}, 1_000) == []
    assert AN.symbols(mon, {}, 1_000) == []
    assert AN.symbols(mon, {"FOOUSDT": _info("FOOUSDT", onboard="soon")}, 1_000) == []      # unreadable: not listed
    assert AN.symbols(mon, {"FOOUSDT": ["not", "a", "dict"]}, 1_000) == []


def test_module_is_pure_stdlib_no_network_no_disk():
    src = pathlib.Path(AN.__file__).read_text(encoding="utf-8")
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add("." * node.level + (node.module or ""))
    assert mods <= {"__future__", "json", "re", "dataclasses", ".strategies"}
    for banned in ("open(", "httpx", "socket", "urllib", "requests", "numpy"):
        assert banned not in src
