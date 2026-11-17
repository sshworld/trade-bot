"""announce.py — the announcement classifier must read titles exactly like the research that measured the edge.

fixtures/ann_cases.json holds public Binance announcements (title, catalog, publishDate, CMS body) with the answer
taken from the research outputs (p74 announcements.json + prepare_events.py for listings, p00d announcements.json +
prepare_events.py for delist/monitoring) and an exchangeInfo subset from the research snapshot — not from announce.py.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import math
import pathlib
import re

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
    """On every real delist / monitoring notice the classifier trades exactly the D sleeve's contracts
    (bundle_v5_signals). Its tokens are the D sleeve's — or [] where a guard hands the notice to a person; then the
    D sleeve has no contract either and the fixture says why."""
    text = SG.flatten_body(json.loads(case["body"]))
    a = SG.parse_announcement(case["code"], case["title"], case["publishDate"], text)
    perpetual = {s: i for s, i in PERPS.items() if i["contractType"] == "PERPETUAL"}
    want_syms = SG.d_event_symbols(a, perpetual)
    anns = AN.classify(case["title"], case["body"], case["catalogId"])
    assert [s for x in anns for s in AN.symbols(x, PERPS, case["publishDate"], require_trading=False)] == want_syms
    skipped = any(w in case["title"].lower() for w in ("rebrand", "swap")) or "to support the Story (IP) rebranding plan" in text
    if skipped or not a["symbols"]:
        assert anns == [] and want_syms == []
        return
    if not anns:
        assert case["research_tokens"] == a["symbols"] and case["note"] and want_syms == []
        return
    assert [(x.kind, list(x.tokens)) for x in anns] == [(a["kind"], a["symbols"])]


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


def close_body(*contracts, extra="", when="2026-12-01 09:00"):
    """A futures-delist body in the CMS wording: the close section with the settlement time (what lifecycle_of reads)."""
    return ("Fellow Binancians,\nBinance Futures will close all positions and conduct an automatic settlement on USDⓈ-M "
            + " and ".join(contracts) + f" perpetual contracts at {when} (UTC). The contracts will be delisted after the "
            "settlement is complete.\nPlease Note:\n" + extra)


def test_d_kinds_need_the_body_and_never_guess_without_it():
    t = "Binance Futures Will Delist USDⓈ-M FOOUSDT Perpetual Contract"
    assert AN.needs_body(t, 161) and not AN.needs_body("Binance Will List Foo (FOO)", 48)
    assert AN.classify(t, None, 161) == [] and AN.classify(t, "   ", 161) == []
    [a] = AN.classify(t, close_body("FOOUSDT"), 161)
    assert (a.kind, a.direction, a.tokens) == ("futures_delist", -1, ("FOO",))
    m = "Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts (2026-12-01)"
    [a] = AN.classify(m, close_body("FOOUSDT", "BARUSDT"), 161)
    assert a.tokens == ("BAR", "FOO")                       # 'Multiple': the body's contracts, sorted, as in the research
    assert AN.classify("Binance Will Delist ABC on 2025-01-01", None, 161) == []


def test_rebrand_swap_and_story_notices_are_skipped_like_the_research():
    assert AN.classify("Binance Will Delist UTK and Support Rebranding and Airdrop Plan", "x", 161) == []
    assert AN.classify("Binance Will Delist ABC and Support the Token Swap", "x", 161) == []
    t = "Binance Futures Will Delist USDⓈ-Margined IPUSDT and IPUSDC Perpetual Contracts"
    assert AN.classify(t, close_body("IPUSDT", extra="... to support the Story (IP) rebranding plan ..."), 161) == []
    assert AN.classify(t, close_body("IPUSDT"), 161)[0].tokens == ("IP",)
    skip = "p00d 제외 공지(rebrand·swap·Story 이전)"             # the research rule itself, not a later guard
    assert AN.explain("Binance Will Delist ABC and Support the Token Swap", "x", 161) == ([], "현물 상폐: " + skip)
    assert AN.explain(t, close_body("IPUSDT", extra="to support the Story (IP) rebranding plan"), 161) == ([], "선물 상폐: " + skip)


def test_body_forms_node_tree_string_dict_and_plain_text():
    tree = {"node": "root", "child": [{"tag": "p", "child": [{"text": "close FOOUSDT"}]}, {"tag": "li", "text": "BARUSDT"}]}
    assert AN.body_text(json.dumps(tree)) == SG.flatten_body(tree) == "close FOOUSDT\nBARUSDT\n"
    assert AN.body_text(tree) == SG.flatten_body(tree)
    assert AN.body_text("plain FOOUSDT text") == "plain FOOUSDT text"
    assert AN.body_text("[Notice] plain text") == "[Notice] plain text"      # not JSON: plain text
    assert AN.body_text('{"child": [{"text": "FOOUSDT"}') is None             # a broken node tree is never searched
    assert AN.body_text(b"bytes FOOUSDT") == "bytes FOOUSDT"
    assert AN.body_text(None) is None and AN.body_text("") is None and AN.body_text(json.dumps({"child": []})) is None
    t = "Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts"
    tree2 = {"node": "root", "child": [{"tag": "p", "text": close_body("FOOUSDT", "BARUSDT")}]}
    assert AN.classify(t, json.dumps(tree2), 161)[0].tokens == ("BAR", "FOO")


def test_an_unreadable_node_tree_is_no_body_not_a_crash():
    t = "Binance Futures Will Delist USDⓈ-M FOOUSDT Perpetual Contract"
    for bad in ({"text": None}, {"child": 5}, {"text": "a", "child": [{"text": 7}]}):
        assert AN.body_text(json.dumps(bad)) is None and AN.body_text(bad) is None
        assert AN.classify(t, json.dumps(bad), 161) == []


def test_a_token_traded_both_ways_by_one_announcement_is_left_to_a_person():
    t = "Binance Will List Foo (FOO) and Add the Monitoring Tag to FOO"   # not a real title: both rules select it
    assert AN.title_kinds(t, None) == ("spot_listing", "monitoring")
    assert AN.classify(t, "body", None) == []
    t2 = "Binance Will List Foo (FOO); Binance Will Extend the Monitoring Tag to Include BAR"
    assert AN.title_kinds(t2, None) == ("spot_listing", "monitoring")
    assert AN.classify(t2, "body", None) == []        # no real monitoring title looks like this: a person decides
    assert AN.explain(t2, "body", None)[1].startswith("모니터링 태그: 제목이 실제 모니터링 공지 꼴")


def test_ann_is_immutable():
    a = AN.Ann("monitoring", -1, ("ABC",), ("why",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.tokens = ("XYZ",)


# ───────────────────────── symbols ─────────────────────────
def _info(sym, onboard=1, status="TRADING", ctype="PERPETUAL", quote="USDT", under="COIN"):
    return dict(symbol=sym, contractType=ctype, status=status, onboardDate=onboard, quoteAsset=quote, underlyingType=under)


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
    assert mods <= {"__future__", "json", "math", "re", "dataclasses", ".strategies"}
    for banned in ("open(", "httpx", "socket", "urllib", "requests", "numpy"):
        assert banned not in src


# ───────────────────────── guards: shapes the research rules read in the wrong direction ─────────────────────────
# None of these titles is real: the real 84 listing / 28 monitoring / 44 spot-delist / 72 futures-delist titles and 40
# futures bodies (2022-02..2026-11) pass the guards unchanged (scratchpad check), and the fixture above pins the real ones.
B = "plain body text without contracts"


@pytest.mark.parametrize("title", [
    "Binance Will List XYZ (XYZ) and Delist ABC (ABC)",
    "Binance Will List XYZ (XYZ) and Remove ABC (ABC)",
    "Binance Will List Sonic (S) and Support the Fantom (FTM) Token Swap",
    "Binance Will List Sonic (S) (Formerly Fantom (FTM))",
    "Binance Will List XYZ (XYZ) (Previously ABC (ABC))",
    "Binance Will List XYZ (XYZ) (Prev. ABC (ABC))",                     # nested parentheses
    "Binance Will List XYZ (XYZ) after the ABC (ABC) Migration",
    "Binance Will List XYZ (XYZ) and Suspend Trading of ABC (ABC)",
])
def test_a_listing_title_that_also_handles_an_outgoing_token_is_left_to_a_person(title):
    assert AN.classify(title, None, 48) == [] and AN.classify(title, None, None) == []
    assert "사람 판단" in AN.explain(title, None, 48)[1]


def test_listing_guard_words_are_word_starts_not_substrings():
    [a] = AN.classify("Binance Will List Giggle Fund (GIGGLE) and SynFutures (F) with Seed Tag Applied", None, 48)
    assert a.tokens == ("GIGGLE", "F")                     # a real p74 title: "SynFutures" is not a guard word


def test_listing_drops_btc_and_duplicates_like_p74():
    [a] = AN.classify("Binance Will List Foo (FOO) (BTC)", None, 48)
    assert a.tokens == ("FOO",) and any("BTC" in r for r in a.reasons)
    [b] = AN.classify("Binance Will List Foo (FOO) and Foo Classic (FOO)", None, 48)
    assert b.tokens == ("FOO",)


@pytest.mark.parametrize("title", [
    "Binance Will Extend the Monitoring Tag to Include ABC & DEF, Removing the Monitoring Tag for GHI",
    "Binance Will Extend the Monitoring Tag to Include ABC; Monitoring Tag Removal for GHI",
    "Binance Will Extend the Monitoring Tag to Include ABC, and the Monitoring Tag for GHI Will Be Removed",
    "Binance Will No Longer Include ABC in the Monitoring Tag",
    "Update on Monitoring Tag: ABC, DEF No Longer Included",
    "Binance Will Exclude ABC from the Monitoring Tag and Add It to the Seed Tag",
    "Binance Will Change the Monitoring Tag of ABC to Seed Tag",
    "Binance Will Change the Tag of ABC from Monitoring Tag to Seed Tag",
    "Binance Will Extend the Monitoring Tag to Include ABC & DEF and the Seed Tag to Include GHI",
    "Binance Will Lift the Monitoring Tag for ABC and Include DEF",
    "Binance Will Extend the Monitoring Tag to Include ABC on 2026-01-02 and the Seed Tag to Include DEF",
    "Binance Will Not Extend the Monitoring Tag to Include ABC on 2026-11-18",
    "Binance Will Extend the Monitoring Tag to Include ABC on 2026-11-18, but ABC Will Not Be Added",
    "Binance Will Add the Monitoring Tag to ABC and Remove It from DEF",              # never seen: 'Add'
    "Binance Will Extend the Monitoring Tag to Include ABC, Remove the Monitoring Tag for DEF Later",
    "BINANCE WILL EXTEND THE MONITORING TAG TO ABC ON 2026-01-02",      # p00d also reads BINANCE, WILL, EXTEND, …
])
def test_a_monitoring_title_outside_the_real_shape_is_left_to_a_person(title):
    assert AN.title_kinds(title, 49) == ("monitoring",)
    assert AN.classify(title, B, 49) == []
    assert "사람 판단" in AN.explain(title, B, 49)[1]


@pytest.mark.parametrize("title, tokens", [
    ("Binance Will Change the Monitoring Tag Inclusion Frequency to Monthly and Extend the Monitoring Tag to Include "
     "AERGO, ALPACA & AST on 2025-03-04", ("AERGO", "ALPACA", "AST")),      # real shape: a bare "change" is fine
    ("Binance Will Extend the Monitoring Tag to GPS on 2025-03-07", ("GPS",)),
    ("Binance Will Extend the Monitoring Tag to Include WAN, Remove the Monitoring Tag for GPS & MBL, and Remove the "
     "Seed Tag for BERA on 2025-10-09", ("WAN",)),
    ("Binance Will Extend the Monitoring Tag to Include BETA, BOND, WTC and XEM on 2023-10-04", ("BETA", "BOND", "WTC", "XEM")),
    ("Binance Will Extend the Monitoring Tag to Include STMX & TROY, Remove the Monitoring Tag for CVX & SUN, and Remove "
     "the Seed Tag for ARKM, BLUR, JTO & TIA on 2025-01-02", ("STMX", "TROY")),
    ("Binance Will Extend the Monitoring Tag to Include BLZ, CLV, KEY, PROS & VITE and Remove the Seed Tag for PENDLE & SEI "
     "on 2024-10-03", ("BLZ", "CLV", "KEY", "PROS", "VITE")),
])
def test_monitoring_titles_of_the_real_shape_still_read_like_the_research(title, tokens):
    [a] = AN.classify(title, B, 49)
    assert (a.kind, a.direction, a.tokens) == ("monitoring", -1, tokens)
    assert list(a.tokens) == SG.parse_announcement("", title, 0, B)["symbols"]


@pytest.mark.parametrize("title", [
    "Binance Will Delist ABC/BTC, DEF/ETH Spot Trading Pairs",
    "Binance Will Delist ETH/BTC Margin Pairs",
    "Binance Will Delist BTC Options Contracts",
    "Binance Will Delist SOL Leveraged Tokens",
    "Binance Will Delist BNB Vault Products",
    "Binance Will Delist XRP Margin Pairs on 2025-01-01",
    "Binance Will Delist ABC from Binance Earn",
    "Binance Will Delist ABC from Binance Convert",
    "Binance Will Delist ABC from Cross Margin and Isolated Margin",
    "Binance Will Delist Non-MiCA Compliant Stablecoin Trading Pairs For EEA Users on 2025-03-31",   # real (0 events)
    "Binance Will Delist SRM and RAY Margin Pairs and Binance Earn Products",                        # real (2022)
    "Binance Will Delist ABC on 2026-01-01 for EEA Users",
])
def test_a_spot_delist_title_that_is_not_a_plain_ticker_list_is_left_to_a_person(title):
    assert AN.title_kinds(title, 161) == ("spot_delist",)
    assert AN.classify(title, B, 161) == []


def test_spot_delist_titles_of_the_real_shape_still_read_like_the_research():
    for title, tokens in (("Binance Will Delist ANT, MULTI, VAI, XMR on 2024-02-20", ("ANT", "MULTI", "VAI", "XMR")),
                          ("Binance Will Delist BCD, CND, MTH, NCASH and YOYO on 2022-03-08", ("BCD", "CND", "MTH", "NCASH")),
                          ("Binance Will Delist COS, D, HIGH, MBOX on 2026-06-19", ("COS", "D", "HIGH", "MBOX"))):
        [a] = AN.classify(title, B, 161)
        assert a.tokens == tokens                         # YOYO: the research's own " and " cut (known miss)


@pytest.mark.parametrize("title, body", [
    ("Binance Futures Will Delist Multiple Perpetual Contracts",
     "Will close ABCUSDT. Note: leverage of BTCUSDT and ETHUSDT will be updated."),
    ("Binance Futures Will Delist Multiple Perpetual Contracts",
     close_body("ABCUSDT", "BTCUSDT")),                                  # a major is never delisted: a misreading
    ("Binance Futures Will Delist Multiple Perpetual Contracts",
     close_body("ABCUSDT", extra="The leverage of DEFUSDT will be updated.")),     # DEF has no settlement time
    ("Binance Futures Will Delist Multiple Perpetual Contracts",
     close_body("ABCUSDC", extra="The ABCUSDT perpetual contract is not affected.")),
    ("Binance Futures Will Delist Multiple Perpetual Contracts",
     close_body("ABCUSDT", "DEFUSDT", extra="Users may trade DEFUSDC instead.")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDC Perpetual Contract",
     close_body("ABCUSDC", extra="The ABCUSDT perpetual contract is not affected.")),
    ("Binance Futures Will Delist COIN-M ABCUSD Perpetual Contract",
     close_body("ABCUSD", extra="Users may trade the ABCUSDT USDⓈ-M perpetual instead.")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT and Launch DEFUSDT Perpetual Contracts", close_body("ABCUSDT", "DEFUSDT")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Quarterly 0627 Delivery Contract", close_body("ABCUSDT_250627")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", "Binance Futures will close ABCUSDT soon."),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", close_body("ABCUSDT", when="2026-13-45 09:00")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", close_body("1000ABCUSDT")),   # another contract's
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", close_body("ABCUSDT_261225")),          # time
    ("Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts",
     close_body("1000ABCUSDT", extra="The ABCUSDT leverage will be updated.")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract",                  # the body contradicts the title
     "Binance Futures will close XYZUSDT at 2026-12-01 09:00 (UTC). ABCUSDT is not affected.\nThe contracts will be delisted."),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract",
     close_body("XYZUSDT", "ABCUSDT", extra="Note: the ABCUSDT perpetual contract will not be affected.")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract",                  # same close-section line
     "Binance Futures will close XYZUSDT at 2026-12-01 09:00 (UTC) and ABCUSDT. Positions are not affected.\n"
     "The contracts will be delisted."),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract",                  # ... ABC with its own time
     "Binance Futures will close ABCUSDT at 2026-12-01 09:00 (UTC). Positions are not affected.\n"
     "The contracts will be delisted."),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract",                  # another line of the section
     close_body("ABCUSDT").replace(" The contracts will", "\nABCUSDT: see below. Positions are not affected.\n"
                                   "The contracts will")),
] + [("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", body)
     for stays in ("ABCUSDT is not going to be affected.", "ABCUSDT is excluded from this delisting.",
                   "ABCUSDT will continue trading.", "ABCUSDT remains\nunaffected.", "ABCUSDT will remain open.",
                   "Trading of ABCUSDT is exempt.", "The ABCUSDT contract will not be delisted.")
     for body in (f"Binance Futures will close XYZUSDT at 2026-12-01 09:00 (UTC). {stays}\nThe contracts will be delisted.",
                  close_body("ABCUSDT", extra=stays))      # ABC with its own time: only the words tell
] + [
    ("Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts",
     "Binance Futures will close ABCUSDT at 2026-12-01 09:00 (UTC). DEFUSDT is not  affected.\nThe contracts will be delisted."),
    ("Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts",                 # any whitespace in the phrase
     close_body("ABCUSDT", "DEFUSDT", extra="Spot trading is not\u00a0affected.")),
    ("Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts",
     close_body("ABCUSDT", "DEFUSDT", extra="Spot trading is not\taffected.")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract",                  # the time of another contract
     "Binance Futures will close XYZUSDT at 2026-12-01 09:00 (UTC). ABCUSDT keeps running.\nThe contracts will be delisted."),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract",
     "Binance Futures will close XYZUSDT at 2026-12-01 09:00 (UTC), and then ABCUSDT.\nThe contracts will be delisted."),
])
def test_a_futures_delist_contract_named_for_another_reason_is_left_to_a_person(title, body):
    assert AN.title_kinds(title, 161) == ("futures_delist",)
    assert AN.classify(title, body, 161) == []
    assert AN.explain(title, body, 161)[1]


def test_a_not_affected_note_about_something_else_does_not_block_a_real_delisting():
    """The real REEF notice (2025-01): after the close section, 'existing positions … will not be affected'."""
    body = close_body("ABCUSDT", extra="In addition, Binance Futures has adjusted the leverage and margin tiers of the "
                      "ABCUSDT USDⓈ-M perpetual contract at 2025-01-15 07:30 (UTC). Please note that existing positions "
                      "opened before the update will not be affected.")
    t = "Binance Futures Will Delist and Update the Leverage & Margin Tiers of USDⓈ-M ABCUSDT Perpetual Contract"
    assert [a.tokens for a in AN.classify(t, body, 161)] == [("ABC",)]


T2_HEAD = ("Binance Futures will close all positions and conduct an automatic settlement the following perpetual "
           "contract(s) as below:\n")                    # the real heading of the time-first lines


@pytest.mark.parametrize("close", [                       # every shape of the real settlement lines, made-up contracts
    "Binance Futures will close all positions and conduct an automatic settlement on USDⓈ-M ABCUSDT perpetual contract "
    "at 2026-12-01 09:00 (UTC).",
    "Binance Futures will close all positions and conduct an automatic settlement on USDⓈ-M ABCUSDT, DEFUSDT and GHIUSDT "
    "Perpetual Contracts at 2026-12-01 09:00 (UTC).",
    "Binance Futures will close all positions and conduct an automatic settlement on the USDⓈ-M DEFUSDT, GHIUSDT USDⓈ-M "
    "perpetual contracts at 2026-12-01 09:00 (UTC), and ABCUSDT USDⓈ-M perpetual contracts at 2026-12-02 09:00 (UTC).",
    "Binance Futures will close all positions and conduct an automatic settlement on the ABCUSDT USDⓈ-M perpetual "
    "contract at 2026-12-01 09:00 (UTC).",
    "Binance Futures will close all positions and conduct an automatic settlement on USDⓈ-Margined ABCUSDT and MEMEFI "
    "perpetual contracts at 2026-12-01 09:00 (UTC).",
    T2_HEAD + "2026-12-01 09:00 (UTC): USDⓈ-M ABCUSDT Perpetual Contract",
    T2_HEAD + "2026-12-01 09:00 (UTC): USDⓈ-M DEFUSDT, GHIUSDT and ABCUSDT Perpetual Contracts",
    T2_HEAD + "2026-12-01 09:00 (UTC): USDⓈ-M DEFUSDT Perpetual Contract\n2026-12-02 09:00 (UTC): USDⓈ-M ABCUSDT "
              "Perpetual Contract",
    T2_HEAD + "\n2026-12-01 09:00 (UTC): USDⓈ-M DEFUSDT Perpetual Contract\n\n2026-12-02 09:00 (UTC): USDⓈ-M ABCUSDT "
              "Perpetual Contract\n\n",                   # blank lines aside
])
def test_settlement_lines_of_the_real_shape_are_read(close):
    t = "Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract"
    body = f"Fellow Binancians,\n{close}\nThe contract will be delisted after the settlement is complete."
    assert [a.tokens for a in AN.classify(t, body, 161)] == [("ABC",)]


@pytest.mark.parametrize("close", [                       # never seen: a person reads it
    "Binance Futures will close ABCUSDT at 2026-12-01 09:00 (UTC).",
    "Binance Futures will close XYZUSDT and keep ABCUSDT open past 2026-12-01 09:00 (UTC).",
    "Binance Futures will close all positions and conduct an automatic settlement on USDⓈ-M ABCUSDT perpetual contract "
    "at 2026-12-01 09:00 (UTC) unless the vote passes.",
    "Binance Futures will close all positions and conduct an automatic settlement on USDⓈ-M XYZUSDT perpetual contract "
    "at 2026-12-01 09:00 (UTC). ABCUSDT keeps running.",
    "Binance Futures will close all positions at 2026-12-01 09:00 (UTC): ABCUSDT",
    T2_HEAD + "2026-12-01 09:00 (UTC): ABCUSDT",
    T2_HEAD + "2026-12-01 09:00 (UTC): USDⓈ-M ABCUSDT Perpetual Contract stays open",
    T2_HEAD + "The list below no longer applies:\n2026-12-01 09:00 (UTC): USDⓈ-M ABCUSDT Perpetual Contract",   # place
    T2_HEAD + "2026-12-01 09:00 (UTC): USDⓈ-M XYZUSDT Perpetual Contract\nFor reference only:\n"
              "2026-12-01 09:00 (UTC): USDⓈ-M ABCUSDT Perpetual Contract",
    "Binance Futures will close all positions and conduct an automatic settlement on USDⓈ-M XYZUSDT perpetual contract "
    "at 2026-12-01 09:00 (UTC).\nBinance Futures will close all positions and conduct an automatic settlement on USDⓈ-M "
    "ABCUSDT perpetual contract at 2026-12-01 09:00 (UTC).",
    "Binance Futures will close the contracts below:\n2026-12-01 09:00 (UTC): USDⓈ-M ABCUSDT Perpetual Contract",
])
def test_a_settlement_line_of_another_shape_is_left_to_a_person(close):
    t = "Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract"
    body = f"Fellow Binancians,\n{close}\nThe contract will be delisted after the settlement is complete."
    anns, why = AN.explain(t, body, 161)
    assert anns == [] and "실제 공지 꼴" in why


@pytest.mark.parametrize("title, cat, body", [
    ("Binance Will List Foo (FOO) (Postponed)", 48, None),
    ("Binance Will List Foo (FOO) - Listing Cancelled", 48, None),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract (Cancelled)", 161, close_body("ABCUSDT")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", 161,          # a schedule called off above it
     "The following previously published settlement schedule has been cancelled:\n" + close_body("ABCUSDT")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", 161,
     close_body("ABCUSDT", extra="Update: the delisting of ABCUSDT is postponed until further notice.")),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", 161,
     "Binance Futures will not close ABCUSDT after all.\n" + close_body("ABCUSDT")),
])
def test_a_cancelled_or_postponed_notice_is_left_to_a_person(title, cat, body):
    anns, why = AN.explain(title, body, cat)
    assert anns == [] and "취소·연기" in why


def test_a_contract_without_a_settlement_time_says_so():
    t = "Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract"
    for body in ("Fellow Binancians,\nABCUSDT will be delisted soon.",
                 close_body("XYZUSDT", extra="ABCUSDT: details to follow.")):
        anns, why = AN.explain(t, body, 161)
        assert anns == [] and "ABCUSDT 의 정산 시각이 본문 'Binance Futures will close' 부분에 없음" in why


def test_the_close_section_is_found_like_the_research_after_a_dotted_capital_i():
    """'İ'.lower() is two characters: lifecycle_of's index then starts inside the phrase — it still reads the line."""
    t = "Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract"
    one = "İ\n" + close_body("ABCUSDT")
    assert SG.lifecycle_of(dict(kind="futures_delist", code="", t=0, symbols=["ABC"], text=one))
    assert [a.tokens for a in AN.classify(t, one, 161)] == [("ABC",)]
    many = "İ" * 120 + "\n" + close_body("ABCUSDT")          # the research's slice starts after the contract
    assert not SG.lifecycle_of(dict(kind="futures_delist", code="", t=0, symbols=["ABC"], text=many))
    assert AN.classify(t, many, 161) == []


@pytest.mark.parametrize("extra", [" " * 49_000, "\t" * 49_000, "\n" + " " * 48_000 + "A", "\n" * 49_000 + "A",
                                   ("not " + " " * 40) * 1_000])
def test_long_runs_of_blanks_are_read_at_once(extra):
    import time
    t = "Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract"
    body = close_body("ABCUSDT", extra=extra)
    assert len(body) <= AN.MAX_FUT_BODY
    t0 = time.monotonic()
    anns, _ = AN.explain(t, body, 161)
    assert time.monotonic() - t0 < 1
    assert [a.tokens for a in anns] == [("ABC",)]


def test_a_flood_of_contracts_is_left_to_a_person_at_once():
    import time
    m = "Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts"
    many = [f"T{i}" for i in range(3000)]
    flood = close_body(*(x + "USDT" for x in many))
    assert len(flood) < AN.MAX_FUT_BODY
    t0 = time.monotonic()
    anns, why = AN.explain(m, flood, 161)
    assert anns == [] and "3000개(50개 초과)" in why and time.monotonic() - t0 < 1
    anns, why = AN.explain(m, close_body(*(x + "USDT" for x in many[:51])), 161)
    assert anns == [] and "51개(50개 초과)" in why
    [a] = AN.classify(m, close_body(*(x + "USDT" for x in many[:50])), 161)
    assert len(a.tokens) == 50
    anns, why = AN.explain(m, close_body("A" * 21 + "USDT"), 161)
    assert anns == [] and "20자" in why
    assert AN.classify(m, close_body("A" * 20 + "USDT"), 161)[0].tokens == ("A" * 20,)
    full = close_body(*(x + "USDT" for x in many[:50]))
    full += "x" * (AN.MAX_FUT_BODY - len(full))
    assert len(AN.body_text(full)) == AN.MAX_FUT_BODY
    t0 = time.monotonic()
    [a] = AN.classify(m, full, 161)                      # the longest body still read, with the most contracts
    assert len(a.tokens) == 50 and time.monotonic() - t0 < 1
    for body in (full + "x", close_body("A" * 1_000_000 + "USDT")):
        t0 = time.monotonic()
        anns, why = AN.explain(m, body, 161)
        assert anns == [] and "50,000자" in why and time.monotonic() - t0 < 1


def test_futures_title_contracts_win_over_body_mentions_and_tokens_like_pumpbtc_are_not_majors():
    t = "Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract"
    [a] = AN.classify(t, close_body("ABCUSDT", "XYZUSDT", extra="Leverage of BTCUSDT will be updated."), 161)
    assert a.tokens == ("ABC",)                          # not the body's XYZ / BTC (the D sleeve would short both)
    m = "Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts (2026-10-05)"
    [b] = AN.classify(m, close_body("PROMPTUSDT", "PUMPBTCUSDT", "1000000BOBUSDT"), 161)    # real 2026-10-05 contracts
    assert b.tokens == ("1000000BOB", "PROMPT", "PUMPBTC")
    [c] = AN.classify("Binance Futures Will Delist USDⓈ-M NEIROETHUSDT Perpetual Contract", close_body("NEIROETHUSDT"), 161)
    assert c.tokens == ("NEIROETH",)


def test_a_major_read_as_a_delist_or_monitoring_token_is_left_to_a_person():
    assert AN.classify("Binance Will Delist ABC, BTC on 2026-01-01", B, 161) == []
    assert AN.classify("Binance Will Extend the Monitoring Tag to Include ABC & ETH", B, 49) == []


ADVERSARIAL = [(t, B, 49) for t in test_a_monitoring_title_outside_the_real_shape_is_left_to_a_person.pytestmark[0].args[1]] + \
    [(t, B, 161) for t in test_a_spot_delist_title_that_is_not_a_plain_ticker_list_is_left_to_a_person.pytestmark[0].args[1]] + \
    [(t, b, 161) for t, b in test_a_futures_delist_contract_named_for_another_reason_is_left_to_a_person.pytestmark[0].args[1]] + \
    [("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", close_body("ABCUSDT", "XYZUSDT"), 161)]


@pytest.mark.parametrize("title, body, cat", ADVERSARIAL)
def test_a_guard_only_ever_drops_what_the_d_sleeve_reads_never_adds_or_flips(title, body, cat):
    a = SG.parse_announcement("", title, 0, AN.body_text(body) or "")
    for x in AN.classify(title, body, cat):
        assert x.kind == a["kind"] and x.direction == -1 and set(x.tokens) <= set(a["symbols"])


def test_one_unreadable_part_makes_the_whole_announcement_empty():
    """A listing title that is also a D title: the listing part alone is readable, the D part is not → [] (never
    the listing alone)."""
    t1 = "Binance Will List ABC (ABC) and Extend the Monitoring Tag to Include 1INCH"          # D part: no token
    t2 = "Binance Will List ABC (ABC) and Extend the Monitoring Tag to Include DEF"             # D part: no body / shape
    t3 = "Binance Will List ABC (ABC) and Extend the Monitoring Tag to Include DEF and the Seed Tag to Include GHI"
    for title, body in ((t1, "body"), (t2, None), (t2, "body"), (t3, "body")):
        assert AN.title_kinds(title, None) == ("spot_listing", "monitoring")
        assert AN._listing(title, None)[0] is not None                  # the listing part alone would be read
        anns, why = AN.explain(title, body, None)
        assert anns == [] and why.startswith("모니터링 태그:")


def test_a_contract_traded_both_ways_through_the_1000_prefix_is_left_to_a_person(monkeypatch):
    t = "Binance Will List Foo (FOO); Binance Futures Will Delist USDⓈ-M 1000FOOUSDT Perpetual Contract"
    assert AN.title_kinds(t, None) == ("spot_listing", "futures_delist")
    assert AN.classify(t, close_body("1000FOOUSDT"), None) == []            # the listing guard ('Delist') already
    monkeypatch.setattr(AN, "LIST_OTHER", re.compile(r"(?!)"))             # without it the contract check still holds:
    assert AN.classify(t, close_body("1000FOOUSDT"), None) == []            # FOO long → 1000FOOUSDT, 1000FOO short
    assert "1000FOOUSDT" in AN.explain(t, close_body("1000FOOUSDT"), None)[1]
    t2 = "Binance Will List Foo (FOO); Binance Futures Will Delist USDⓈ-M 1000BARUSDT Perpetual Contract"
    assert [(a.kind, a.tokens) for a in AN.classify(t2, close_body("1000BARUSDT"), None)] == \
        [("spot_listing", ("FOO",)), ("futures_delist", ("1000BAR",))]


def test_deeply_nested_bodies_are_unreadable_not_a_crash():
    t = "Binance Futures Will Delist USDⓈ-M FOOUSDT Perpetual Contract"
    d = {"text": close_body("FOOUSDT")}
    for _ in range(1500):
        d = {"child": [d]}
    assert AN.body_text(d) is None and AN.classify(t, d, 161) == []
    deep = '{"text": "FOOUSDT", "child": ' + "[" * 20000 + "]" * 20000 + "}"
    with pytest.raises(RecursionError):
        json.loads(deep)                                 # what the parser itself does
    assert AN.body_text(deep) is None and AN.classify(t, deep, 161) == []


@pytest.mark.parametrize("body", ["null", "[]", " [] ", "123", "true", '"x"', '[{"text": "BARUSDT"}]'])
def test_a_json_value_that_is_not_a_node_tree_is_no_body(body):
    t = "Binance Futures Will Delist USDⓈ-M IPUSDT Perpetual Contract"
    assert AN.body_text(body) is None
    assert AN.classify(t, body, 161) == []               # not a way around "D kinds need the body" or the Story skip


def test_explain_says_why_a_notice_is_not_traded():
    assert AN.explain("Binance Will Add Foo (FOO) on Earn", None, 48) == ([], "매매 대상 아님(제목 규칙)")
    assert "본문 없음" in AN.explain("Binance Will Delist ABC on 2025-01-01", None, 161)[1]
    t = "Binance Will Extend the Monitoring Tag to Include More Tokens on 2026-11-17"
    anns, why = AN.explain(t, "The tokens to be added to the Monitoring Tag list are: Foo (FOO)", 49)
    assert anns == [] and why.startswith("모니터링 태그: 판정 보류(사람 확인)")       # p107 would read FOO from the body
    anns, why = AN.explain("Binance Will List Foo (FOO)", None, 48)
    assert [a.tokens for a in anns] == [("FOO",)] and why == ""


def test_catalog_ids_are_normalised_and_an_unreadable_one_selects_nothing():
    t = "Binance Will List Foo (FOO)"
    for cat in (48, "48", " 48 ", 48.0):
        assert [a.tokens for a in AN.classify(t, None, cat)] == [("FOO",)]
    for cat in ("abc", True, 48.5, math.nan, "４８", [48], "4" * 5000):
        assert AN.classify(t, None, cat) == [] and AN.title_kinds(t, cat) == ()
    assert "카탈로그" in AN.explain(t, None, "abc")[1]
    assert AN.classify(t, None, None)[0].reasons[0].endswith("(카탈로그 미상)")


def test_an_overlong_title_is_left_to_a_person_and_answered_at_once():
    import time
    t = "Binance Will List Foo (FOO)"
    assert AN.classify(t + " " * (AN.MAX_TITLE - len(t)), None, 48)[0].tokens == ("FOO",)
    long_t = t + " " * (AN.MAX_TITLE + 1 - len(t))
    assert AN.title_kinds(long_t, 48) == () and AN.classify(long_t, None, 48) == []
    assert "400자" in AN.explain(long_t, None, 48)[1]
    t0 = time.monotonic()                     # p00d's split on "\s+(and )?remove" takes seconds on 20 000 spaces
    assert AN.classify("Binance Will Extend the Monitoring Tag to ABC" + " " * 20_000 + "x", "x", 49) == []
    assert time.monotonic() - t0 < 1


def test_an_unknown_listing_time_is_not_listed():
    mon = AN.Ann("monitoring", -1, ("NEW",))
    for onboard in (None, "", 0, "0", -5, True, math.nan, math.inf, "bad"):
        assert AN.symbols(mon, {"NEWUSDT": _info("NEWUSDT", onboard=onboard)}, 1_000) == []
    info = _info("NEWUSDT")
    del info["onboardDate"]
    assert AN.symbols(mon, {"NEWUSDT": info}, 1_000) == []
    assert AN.symbols(mon, {"NEWUSDT": _info("NEWUSDT", onboard="999")}, 1_000) == ["NEWUSDT"]


def test_an_index_perpetual_is_not_a_token_for_a_live_decision():
    perps = {"ALLUSDT": _info("ALLUSDT", under="INDEX"), "DEFIUSDT": _info("DEFIUSDT", under="INDEX"),
             "FOOUSDT": _info("FOOUSDT", under=None), "BARUSDT": _info("BARUSDT", under="EQUITY"),
             "PREDICTUSDT": _info("PREDICTUSDT", under="PREMARKET")}
    lst = AN.Ann("spot_listing", 1, ("ALL", "FOO", "BAR", "PREDICT"))
    assert AN.symbols(lst, perps, 1_000) == ["PREDICTUSDT"]          # p74 measured the pre-market PREDICTUSDT
    assert AN.symbols(lst, perps, 1_000, require_trading=False) == ["ALLUSDT", "FOOUSDT", "BARUSDT", "PREDICTUSDT"]
    assert AN.symbols(AN.Ann("monitoring", -1, ("ALL", "PREDICT")), perps, 1_000) == ["PREDICTUSDT"]
    fut = AN.Ann("futures_delist", -1, ("DEFI",))            # the notice names this very contract (p00d DEFIUSDT)
    assert AN.symbols(fut, perps, 1_000) == ["DEFIUSDT"]
