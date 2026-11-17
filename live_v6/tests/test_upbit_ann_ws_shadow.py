"""All offline: fake clocks/transports, real signing, writer, and redirect machinery."""
import ast
import base64
import errno
import hashlib
import hmac
import inspect
import json
import logging
import os
from pathlib import Path
import random
import re
import socket
import stat
import sys
import threading
import time
import uuid

import pytest
from live_v6.tools import upbit_ann_ws_shadow as S

from .test_ann_ws_shadow import check_logger_unit
from .test_ann_ws_shadow import no_process_wide_log_hooks_left_behind  # noqa: F401  (autouse here as well)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden in offline tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_jwt_hs512_signature_and_fresh_nonce():
    tokens = [S.jwt_token("fixture-key", "not-base64+secret") for _ in range(2)]
    nonces = []
    for token in tokens:
        head, payload, sig = token.split(".")
        assert json.loads(unb64(head)) == {"alg": "HS512", "typ": "JWT"}
        p = json.loads(unb64(payload))
        assert set(p) == {"access_key", "nonce"} and p['access_key'] == 'fixture-key'
        assert uuid.UUID(p['nonce']).version == 4
        expected = hmac.new(b"not-base64+secret", (head + "." + payload).encode(), hashlib.sha512).digest()
        assert hmac.compare_digest(unb64(sig), expected)
        assert "=" not in token
        nonces.append(p['nonce'])
    assert nonces[0] != nonces[1]


def test_subscription_defaults_all_and_explicit_filter():
    a, b = json.loads(S.subscription()), json.loads(S.subscription(["trade", "wallet", "trade"]))
    assert a[1] == {"type": "announcement", "include_body": False}
    assert a[2] == b[2] == {"format": "DEFAULT"}
    assert b[1]['categories'] == ['trade', 'wallet']
    assert a[0]['ticket'] != b[0]['ticket']
    uuid.UUID(a[0]['ticket'])
    for bad in ([], ['trading'], ['trade', 'invalid']):
        with pytest.raises(ValueError):
            S.subscription(bad)


DOC = dict(type='announcement', event_type='CREATED', uuid='notice-123',
           title='셀레스티아(TIA)(KRW, BTC, USDT 마켓), 아이오넷(IO)(BTC, USDT 마켓) 신규 거래지원 안내',
           category='trade', url='https://upbit.com/service_center/notice?id=123&view=share',
           first_listed_at='2026-07-14T16:36:34.125+09:00',
           listed_at='2026-07-14T07:36:34.250Z', timestamp=1784014594300, stream_type='REALTIME')


def test_parse_all_raw_timestamps_timezone_offsets_and_lags():
    for raw in (DOC, json.dumps(DOC), json.dumps(DOC).encode()):
        r = S.parse_push(raw, 1784014594500, 40, 5)
        assert r['k'] == 'upbit_ann' and r['recv_ms'] == 1784014594500
        assert r['first_listed_at_ms'] == 1784014594125
        assert r['listed_at_ms'] == 1784014594250
        assert r['timestamp_ms'] == 1784014594300
        for field, lag in [('first_listed_at', 375), ('listed_at', 250), ('timestamp', 200)]:
            assert r[field] == DOC[field]
            assert r['lag_raw_ms_' + field] == lag
            assert r['lag_ms_' + field] == lag + 40
        assert r['offset_ms'] == 40 and r['offset_age_s'] == 5
        assert r['tickers'] == ['TIA', 'IO'] and r['tag'] == 'upbit_list_krw'
        assert r['keys'] == sorted(DOC) and r['url'] == DOC['url']
    assert S.to_ms('2026-07-14T02:36:34.125-05:00') == 1784014594125
    r = S.parse_push(dict(DOC, event_type='UPDATED', title='x'*700), 1784014594100, None)
    assert r['event_type'] == 'UPDATED' and len(r['title']) == 500
    assert r['lag_ms_timestamp'] is None and r['lag_raw_ms_timestamp'] == -200


def test_the_three_lags_of_one_push_are_three_different_measurements():
    """docs.upbit.com/kr/reference/websocket-announcement: first_listed_at = first publication, listed_at = latest
    publication (renewed when the notice is updated) - whole seconds in the doc's example - and timestamp is just
    "타임스탬프 (ms)". Which one is "the" lag is unknown until real pushes are in; the module text has to say so."""
    second = 1784014594000                                       # 2026-07-14T16:36:34+09:00
    push = dict(DOC, first_listed_at='2026-07-14T16:36:34+09:00', listed_at='2026-07-14T16:36:34+09:00',
                timestamp=second + 950)
    r = S.parse_push(push, second + 1000, 0.0, 5.0, 4.0)
    assert (r['lag_ms_listed_at'], r['lag_ms_timestamp']) == (1000, 50)       # one push: "1 s" or "50 ms"
    assert r['offset_rtt_ms'] == 4.0 and S.parse_push(push, second + 1000, None)['offset_rtt_ms'] is None
    days = 3 * 86_400_000                                        # the notice is updated three days later
    update = dict(push, event_type='UPDATED', listed_at='2026-07-17T16:36:34+09:00', timestamp=second + days + 950)
    r = S.parse_push(update, second + days + 1000, 0.0)
    assert r['lag_ms_first_listed_at'] == days + 1000 and r['lag_ms_listed_at'] == 1000   # the AGE of the notice
    for needle in ('first_listed_at', 'whole seconds', 'UPDATED', 'lag_ms_timestamp alone', 'BINANCE'):
        assert needle in S.__doc__, needle


@pytest.mark.parametrize('value', [None, True, False, 'broken', '2026-07-14T07:36:34', float('nan'), float('inf'), {}, []])
def test_bad_timestamp_is_null(value):
    assert S.to_ms(value) is None
    r = S.parse_push(dict(DOC, timestamp=value), 10, 0)
    assert r['timestamp_ms'] is None and r['lag_ms_timestamp'] is None


@pytest.mark.parametrize('raw', ['bad', b'\xff', '[]', 'null', '{"status":"UP"}', '{"type":"ticker"}'])
def test_ignore_non_announcement(raw):
    assert S.parse_push(raw, 1, 0) is None


TITLE_FIXTURE = json.loads((Path(__file__).parent / 'fixtures/upbit_titles.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('row', TITLE_FIXTURE['rows'], ids=lambda r: f"{r['source']}:{r['id']}")
def test_all_research_event_titles(row):
    assert S.classify_upbit_title(row['title']) == row['expected']


@pytest.mark.parametrize(('title','tag'), [
    ('[거래] 예시(XYZ) 신규 거래 지원 안내 (KRW 마켓)', 'upbit_list_krw'),
    ('테더(USDT) KRW, BTC 마켓 추가 안내 (출금 개시 안내)', 'upbit_list_krw'),
    ('예시(XYZ) 신규 거래지원 안내 (BTC 마켓)', 'upbit_list_other'),
    ('예시(XYZ) 신규 거래지원 안내', None),
    ('예시(XYZ) 유의 종목 지정 연장 안내', None),
    ('예시(XYZ) 유의 종목 지정 취소 안내', None),
    ('BTC, USDT 마켓 이벤트', None),
    ('KRW 입출금 점검', None),
    # how the extension of a running designation REALLY reads (notices 6696, 3127, 1267) - not "지정 연장"
    ('멀티버스엑스(EGLD) 거래 유의 종목 지정 기간 연장 안내', None),
    ('위믹스(WEMIX), 카바(KAVA) 유의 종목 지정 기간 연장 안내', None),
    ('리퍼리움(RFR) 유의 종목 지정 안내 (기간 연장)', None),
    ('멀티버스엑스(EGLD) 거래 유의 종목 지정 안내', 'upbit_warning'),             # ... and the designation itself
    ('예시(XYZ) 거래 유의 종목 지정 안내 (입출금 중단 기간 연장)', 'upbit_warning'),    # (made up) still a designation
])
def test_classifier_boundaries(title, tag):
    assert S.classify_upbit_title(title) == tag


def test_an_extended_warning_period_is_not_tagged_as_a_new_designation():
    extended = [r for r in TITLE_FIXTURE['rows'] if '유의 종목' in r['title'] and '연장' in r['title']]
    assert len(extended) == 19 and len({r['title'] for r in extended}) == 17      # real notices, with their ids
    assert all(r['expected'] is None and S.classify_upbit_title(r['title']) is None for r in extended)
    designations = [r for r in TITLE_FIXTURE['rows'] if r['expected'] == 'upbit_warning']
    assert len(designations) == 81 and not any('연장' in r['title'] or '해제' in r['title'] for r in designations)


@pytest.mark.parametrize(('title', 'tag'), [
    ('예시(XYZ) 거래지원 종료 안내 (가나다(ABC) 거래지원 취소 안내)', 'upbit_delist'),
    ('예시(XYZ) 거래 유의 종목 지정 안내 (가나다(ABC) 거래지원 취소 안내)', 'upbit_warning'),
])
def test_a_title_that_also_cancels_a_listing_keeps_its_delist_or_warning_tag(title, tag):
    # No real title says both (none among 4 813), so nothing but the code decides this: one tag per notice, the first
    # match wins - delist, warning, cancelled listing. Pinned here so that the order is changed on purpose, with this
    # test, and not by moving an `if`.
    assert S.classify_upbit_title(title) == tag


def test_tickers_do_not_capture_markets_dates_or_annotations():
    assert S.extract_tickers('KRW, BTC 마켓 디지털 자산 추가 (ALT, PYTH)') == ['ALT', 'PYTH']
    assert S.extract_tickers('에이피아이쓰리(API3) (API3) (12/14 15:00) (KRW, BTC 마켓)') == ['API3']
    assert S.extract_tickers('테더(USDT) KRW, BTC 마켓 추가 안내') == ['USDT']
    assert S.extract_tickers('원화 마켓 디지털 자산 추가 (도지코인 DOGE) (완료)') == ['DOGE']
    assert S.extract_tickers('(AKT 거래지원 개시 시점 연기 안내)') == []


TICKER_ROWS = [r for r in TITLE_FIXTURE['rows'] if 'tickers' in r]


@pytest.mark.parametrize('row', TICKER_ROWS, ids=lambda r: f"{r['source']}:{r['id']}")
def test_research_titles_with_a_ticker_expectation(row):
    assert S.extract_tickers(row['title']) == row['tickers']


def test_ticker_expectations_cover_the_hard_real_titles():
    titles = {r['title']: r['tickers'] for r in TICKER_ROWS}
    assert len(titles) >= 40                                     # hand-checked titles, not a token sample
    assert {'1INCH', '0G', '2Z'} <= {t for ts in titles.values() for t in ts}     # real tickers that start with a digit
    assert titles['KRW, BTC 마켓 디지털 자산 추가 (1INCH, AAVE, MASK)'] == ['1INCH', 'AAVE', 'MASK']
    assert sum(len(ts) >= 2 for ts in titles.values()) >= 10 and [] in titles.values()
    # the same title never carries two different expectations
    assert all(r['tickers'] == titles[r['title']] for r in TICKER_ROWS)
    assert all(r['tickers'] == titles[r['title']] for r in TITLE_FIXTURE['rows'] if r['title'] in titles)


@pytest.mark.parametrize(('title', 'tickers'), [
    ('1인치네트워크(1INCH) 거래 유의 종목 지정 안내', ['1INCH']),            # the review's two reproductions
    ('KRW 마켓 디지털 자산 추가 (1INCH, AAVE)', ['1INCH', 'AAVE']),
    ('예시(1000SATS) 신규 거래지원 안내 (KRW, BTC, USDT 마켓)', ['1000SATS']),
    ('BTC 마켓 디지털 자산 추가 (일인치 1INCH, 에이브 AAVE)', ['1INCH', 'AAVE']),
    ('예시(2Z), 예시(0G) 신규 거래지원 안내 (KRW 마켓)', ['2Z', '0G']),
    ('예시(XYZ) 거래지원 종료 안내 (12/7 15:00)', ['XYZ']),               # digits alone are never a ticker
    ('서버 점검 안내 (12/7)', []),
    ('업비트 개선 사항 안내 (2026)', []),
    ('이벤트 안내 (1/2, 3)', []),
    ('예시(XYZ) 신규 거래지원 안내 (KRW 마켓) (1/6 추가 예정)', ['XYZ']),
    ('원화(KRW)마켓 장애에 따른 주문 취소 및 긴급 점검 안내', []),
])
def test_tickers_starting_with_a_digit_and_groups_that_hold_one(title, tickers):
    assert S.extract_tickers(title) == tickers


@pytest.mark.parametrize('group', ['A' * 20_000 + '!', '1' * 20_000, '9' * 20_000 + 'A!', 'A, ' * 7_000 + '!',
                                   '가' * 20_000, '가 ' * 10_000 + 'A!', ' ' * 20_000 + '!'],
                         ids=['capitals', 'digits', 'digits-then-letter', 'list', 'hangul', 'names', 'blanks'])
def test_ticker_extraction_takes_linear_time_on_a_hostile_title(group):
    # a frame may be 1 MiB and is parsed on the receive thread: a pattern that backtracks over a long run (20 000
    # capitals took ~8 s with `[A-Z0-9]*[A-Z][A-Z0-9]*`) would stop the measurement for hours
    title = '예시(XYZ) 신규 거래지원 안내 (KRW 마켓) (' + group + ')'
    started = time.perf_counter()
    tickers = S.extract_tickers(title)                           # the pattern itself, on all of it (parse_push cuts)
    rec = S.parse_push(dict(DOC, title=title), 1784014594500, None)
    assert time.perf_counter() - started < 2.0
    assert tickers == ['XYZ'] and rec['tickers'] == ['XYZ'] and rec['tag'] == 'upbit_list_krw'


# What used to take quadratic time somewhere between the socket and the queue, each at a size that took ~10 s:
HOSTILE = {
    'market list without 마켓': ('title', lambda: '신규 거래지원 ' + 'KRW, ' * 16_000),      # classifying the title
    'many different tickers': ('title', lambda: ''.join(f'(A{i})' for i in range(50_000))),  # collecting tickers
    'start of many tokens, title': ('title', lambda: 'eyJ' * 70_000),                        # redacting JWTs
    'start of many tokens, url': ('url', lambda: 'https://upbit.com/x?' + 'eyJ' * 70_000),
    'start of many tokens, extra field': ('note', lambda: ['eyJ' * 70_000]),
}


@pytest.mark.parametrize('shape', sorted(HOSTILE))
def test_a_huge_frame_is_handled_in_a_moment_and_leaves_a_small_row(tmp_path, monkeypatch, shape):
    """Everything between recv() and the queue runs on the receive thread and holds the interpreter lock: while it
    crawls over one frame, no ping is sent, nothing is written, and pushes behind it get their stamp late."""
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    field, make = HOSTILE[shape]
    sh, _, _ = shadow(tmp_path, [json.dumps(dict(DOC, **{field: make()}))])
    started = time.perf_counter()
    sh.run_once()
    assert time.perf_counter() - started < 2.0
    ann = next(r for r in drain(sh) if r['k'] == 'upbit_ann')
    assert len(json.dumps(ann)) < 4000 and ann['lag_raw_ms_timestamp'] is not None


def test_a_row_stays_small_whatever_the_frame_holds():
    big = 1_000_000                                              # the socket accepts frames of up to 1 MiB
    doc = dict(DOC, title=DOC['title'] + '가' * big, url=DOC['url'] + 'a' * big, uuid='u' * big, category=['c'] * big,
               event_type={'e': 'e' * big}, stream_type='s' * big, first_listed_at='9' * big,
               listed_at=DOC['listed_at'] + ' ' * big, **{f'k{i:04d}' + 'x' * 300: 1 for i in range(2000)})
    r = S.parse_push(doc, 1784014594500, 40, 5, 4)
    assert len(json.dumps(r, ensure_ascii=False).encode()) < 12_000
    assert r['lag_ms_timestamp'] == 240 and r['timestamp'] == DOC['timestamp']       # what was measured is all there
    assert r['title'] == doc['title'][:500] and r['title_len'] == len(doc['title'])
    assert r['url'] == doc['url'][:500] and r['uuid'] == 'u' * 500 and r['stream_type'] == 's' * 500
    assert r['category'] == ('[' + '"c", ' * 100)[:500] and r['event_type'] == '{"e": "' + 'e' * 493   # JSON text, cut
    assert r['first_listed_at'] == '9' * 500 and r['first_listed_at_ms'] is None
    assert r['listed_at'] == doc['listed_at'][:500] and r['listed_at_ms'] is None    # not a time any more: no lag
    assert len(r['keys']) == S.base.KEYS_MAX == 30 and max(map(len, r['keys'])) == S.base.KEY_MAX == 100
    plain = S.parse_push(DOC, 1784014594500, 40, 5, 4)           # an ordinary push: every field as it came
    assert all(plain[k] == v for k, v in DOC.items() if k != 'type') and plain['keys'] == sorted(DOC)
    assert plain['title_len'] == len(DOC['title'])


def test_tag_and_tickers_come_from_the_title_as_it_is_logged_and_title_len_tells_when_that_is_not_all_of_it():
    head = '예시(XYZ) 신규 거래지원 안내 (KRW 마켓)'
    title = head + ' ' * 500 + '(가나다(ABC) 거래지원 취소 안내)'      # what makes it a cancelled listing is cut off
    r = S.parse_push(dict(DOC, title=title), 1784014594500, None)
    assert r['title'] == title[:500] and r['title_len'] == len(title) > S.base.TITLE_MAX == 500
    assert (r['tag'], r['tickers']) == (S.classify_upbit_title(r['title']), S.extract_tickers(r['title']))
    assert (r['tag'], r['tickers']) == ('upbit_list_krw', ['XYZ'])
    assert S.classify_upbit_title(title) == 'upbit_list_cancel'      # what the whole title would have been tagged
    # ... which no real title comes near: the longest of 4 813 has 176 characters
    assert max(len(row['title']) for row in TITLE_FIXTURE['rows']) < 200


HEMI = '헤미(HEMI), 유즈리스(USELESS) 신규 거래지원 안내 (BTC, USDT 마켓) (헤미(HEMI) 거래지원 취소 안내)'


@pytest.mark.parametrize(('title', 'tag'), [
    (HEMI, 'upbit_list_cancel'),                                 # the real notice (fixture id 6558)
    (HEMI.split(' (헤미')[0], 'upbit_list_other'),               # ... as first published, before the cancellation
    ('예시(XYZ) 신규 거래지원 안내 (KRW, BTC, USDT 마켓) (거래 지원 취소 안내)', 'upbit_list_cancel'),
    ('예시(XYZ) 신규 거래지원 취소 안내', 'upbit_list_cancel'),
    ('예시(XYZ) 거래지원 취소 안내 (KRW 마켓)', 'upbit_list_cancel'),
    ('KRW 마켓 디지털 자산 추가 (XYZ) (XYZ 거래지원 취소 안내)', 'upbit_list_cancel'),
    # other cancellations say nothing about a listing
    ('니어프로토콜(NEAR) 입출금 일시 중단 안내 (일정 취소 안내)', None),
    ('저스트(JST) 4차 에어드랍 지원 안내 (취소)', None),
    ('예시(XYZ) 유의 종목 지정 취소 안내', None),
    ('예시(XYZ) 신규 거래지원 안내 (KRW 마켓) (이벤트 일정 취소 안내)', 'upbit_list_krw'),
])
def test_a_cancelled_listing_is_tagged_as_such_and_never_as_a_listing(title, tag):
    assert S.classify_upbit_title(title) == tag


def test_no_listing_title_keeps_its_listing_tag_once_it_says_the_listing_is_cancelled():
    listings = {r['title'] for r in TITLE_FIXTURE['rows'] if r['expected'] in ('upbit_list_krw', 'upbit_list_other')}
    assert len(listings) > 190
    for title in listings:
        assert S.classify_upbit_title(title + ' (거래지원 취소 안내)') == 'upbit_list_cancel'
    rec = S.parse_push(dict(DOC, event_type='UPDATED', title=HEMI), 1784014594500, None)
    assert rec['tag'] == 'upbit_list_cancel' and rec['tickers'] == ['HEMI', 'USELESS']


class Clock:
    def __init__(self):
        self.now = 1000.0
    def __call__(self):
        return self.now


class FakeWS:
    def __init__(self, clock, script=(), pongs=True):
        self.clock, self.script, self.pongs = clock, list(script), pongs
        self.sent, self.pings = [], []
        self.closed = False
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.closed = True
    def send(self, message):
        self.sent.append(message)
    def ping(self, data):
        self.pings.append((self.clock.now, data))
        ev = threading.Event()
        if self.pongs:
            ev.set()
        return ev
    def recv(self, timeout):
        self.clock.now += timeout
        if not self.script:
            raise TimeoutError
        value = self.script.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def shadow(tmp_path, script=(), pongs=True):
    clock, calls = Clock(), []
    def connect(url, **kwargs):
        ws = FakeWS(clock, script, pongs)
        calls.append((url, kwargs, ws))
        return ws
    sh = S.UpbitShadow('fixture-key', 'fixture-secret', str(tmp_path/'log.jsonl'),
                       connect=connect, http_get=lambda url: {'serverTime': 1000000}, clock=clock, mono=clock)
    return sh, calls, clock


def drain(sh):
    rows = []
    while not sh.q.empty():
        rows.append(sh.q.get_nowait())
    return rows


def test_connection_headers_only_nonce_ping_subscription_and_first_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'RECONNECT_S', 95)
    sh, calls, clock = shadow(tmp_path, [json.dumps(DOC), 'unknown'])
    original = S.decode
    def decode(raw):
        clock.now += .25  # deliberately slow parsing must not affect receive stamp
        return original(raw)
    monkeypatch.setattr(S, 'decode', decode)
    sh.run_once()
    sh.run_once()
    a, b = calls
    assert a[0] == b[0] == S.WS_URL and '?' not in a[0]
    tokens = [c[1]['additional_headers']['Authorization'].removeprefix('Bearer ') for c in calls]
    assert tokens[0] != tokens[1]
    for _, kw, ws in calls:
        assert set(kw['additional_headers']) == {'Authorization'}
        assert kw['ping_interval'] is None and kw['proxy'] is None
        assert kw['logger'].disabled and not kw['logger'].propagate
        assert len(ws.sent) == 1 and 'categories' not in json.loads(ws.sent[0])[1]
        assert len(ws.pings) == 3 and all(payload == b'' for _, payload in ws.pings)
        assert all(30 <= y[0]-x[0] <= 31 for x,y in zip(ws.pings,ws.pings[1:]))
        assert ws.closed
    rows = drain(sh)
    assert next(r for r in rows if r['k']=='upbit_ann')['recv_ms'] == 1001000
    assert rows[-1]['event'] == 'planned_reconnect'
    data = json.dumps(rows)
    for secret in ['fixture-key', 'fixture-secret', *tokens]:
        assert secret not in data and secret not in a[0] and secret not in ''.join(a[2].sent)


def test_no_pong_reconnects_at_second_ping(tmp_path):
    sh, calls, clock = shadow(tmp_path, pongs=False)
    with pytest.raises(ConnectionError, match='no pong'):
        sh.run_once()
    assert clock.now == 1060
    assert calls[0][2].pings == [(1030, b'')]
    assert calls[0][2].closed


def run_waits(sh, n):
    waits = []
    sh.clock_loop = lambda: None
    sh._writer_worker = lambda: None
    def wait(seconds):
        waits.append(seconds)
        if len(waits) == n:
            sh.stop.set()
        return sh.stop.is_set()
    sh.stop.wait = wait
    sh.run()
    return waits


def test_invalid_auth_frame_long_backoff_and_scrub(tmp_path):
    sh, calls, _ = shadow(tmp_path, [json.dumps({'error': {'name':'INVALID_AUTH', 'message':'fixture-key fixture-secret'}})])
    assert run_waits(sh, 5) == [600,1200,2400,3600,3600]
    rows = drain(sh)
    assert len([r for r in rows if r['k']=='upbit_error']) == 5
    assert 'fixture-key' not in json.dumps(rows) and 'fixture-secret' not in json.dumps(rows)
    assert len({c[1]['additional_headers']['Authorization'] for c in calls}) == 5


@pytest.mark.parametrize('deferred', [False, True])
def test_http_rejection_also_backs_off_when_enter_raises(tmp_path, deferred):
    sh, _, _ = shadow(tmp_path)
    class Rejected(Exception):
        response = type('Response', (), {'status_code': 401})()
    class CM:
        def __enter__(self):
            raise Rejected('fixture-secret')
        def __exit__(self, *args):
            pass
    def connect(*args, **kwargs):
        if deferred:
            return CM()
        raise Rejected('fixture-secret')
    sh._connect = connect
    assert run_waits(sh, 4) == [600,1200,2400,3600]


@pytest.mark.parametrize('kind', ['transport','stream'])
def test_normal_backoff_capped_no_busy_loop(tmp_path, kind):
    sh, _, _ = shadow(tmp_path, [json.dumps({'error': {'name':'INVALID_PARAM'}})])
    if kind == 'transport':
        def fail(url, **kw):
            raise OSError(str(kw['additional_headers']) + ' fixture-secret')
        sh._connect = fail
    assert run_waits(sh, 8) == [2,4,8,16,32,60,60,60]
    rows = json.dumps(drain(sh))
    assert 'fixture-secret' not in rows and 'eyJ' not in rows


@pytest.mark.parametrize(('status','expected'), [(503,[2,4,8]), (429,[600,1200,2400])])
def test_http_error_policy(tmp_path, status, expected):
    sh, _, _ = shadow(tmp_path)
    def once():
        raise S.base.Rejected(status)
    sh.run_once = once
    assert run_waits(sh, 3) == expected


def test_unknown_frames_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'RECONNECT_S', 50)
    sh, _, _ = shadow(tmp_path, ['junk'] * 40)
    sh.run_once()
    rows = drain(sh)
    assert sum(r['k']=='other' for r in rows) == S.base.MAX_OTHER_PER_CONN
    assert rows[-1]['other'] == 40


def test_credentials_redacted_before_truncation_in_every_field(tmp_path, monkeypatch, caplog):
    sh, _, _ = shadow(tmp_path)
    token = S.jwt_token(sh.key, sh.secret)
    sh._token = token
    assert 'eyJ' not in sh.scrub('Authorization: Bearer ' + token + ' ' + sh.key + ' ' + sh.secret)
    assert '?' not in sh.scrub('wss://somewhere/path?secret=value')
    sh.write({'k':'test', 'nested': {sh.key: [token, sh.secret]}, 'url': DOC['url']})
    r = drain(sh)[0]
    assert r['url'] == DOC['url']
    assert not any(v in json.dumps(r) for v in (sh.key,sh.secret,token))
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    def connect(url, **kw):
        jwt = kw['additional_headers']['Authorization'][7:]
        kw['logger'].debug('Authorization: %s', jwt)
        return FakeWS(sh.clock, [json.dumps(dict(DOC, title='x'*490 + jwt + sh.secret))])
    sh._connect = connect
    with caplog.at_level(logging.DEBUG):
        sh.run_once()
    title = next(r['title'] for r in drain(sh) if r['k']=='upbit_ann')
    assert 'eyJ' not in title and sh.secret not in title
    assert 'Authorization' not in caplog.text


# what redact_jwts replaces, as the pattern it used to be (quadratic on a long run that holds "eyJ" again and again)
JWT_PATTERN = re.compile(r'eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')


@pytest.mark.parametrize('text', [
    '', 'eyJ', 'eyJ.a', 'eyJ.a.b', 'xeyJ.a.b', 'eyJa.b.c.d.e', 'eyJ..a.b', 'eyJ.a..b', 'a.eyJ.b.c', '.eyJ.a.b.',
    'eyJ.a.', 'eyJ.eyJ.eyJ.eyJ.eyJ', 'eyJ.eyJ.eyJ.eyJ.eyJ.eyJ.eyJ', 'x.eyJ.a.eyJ.b.c', 'eyJ.a.b.eyJ.c.d',
    'eyJ.a.b eyJ.c.d', 'eyj.a.b', 'eyJ-_.a-_.b-_', '가eyJ.a.b나', '"eyJ.a.b"', 'eyJeyJ.a.b', 'aeyJbeyJ.c.d', 'a.b.c',
    '...', 'eyJ.a.b...eyJ.c.d', 'Authorization: Bearer eyJhbGciOiJIUzUxMiJ9.eyJhY2Nlc3Nfa2V5IjoiayJ9.c2lnbmF0dXJl, next',
])
def test_jwt_redaction_replaces_exactly_what_the_pattern_did(text):
    assert S.redact_jwts(text) == JWT_PATTERN.sub('[REDACTED]', text)


def test_jwt_redaction_replaces_exactly_what_the_pattern_did_on_random_text():
    rng = random.Random(20261117)
    pieces = ['eyJ', 'eyJ', 'e', 'y', 'J', '.', '.', '.', 'a', 'B', '7', '-', '_', ' ', '"', '가', '\n']
    for _ in range(5000):
        text = ''.join(rng.choice(pieces) for _ in range(rng.randrange(40)))
        assert S.redact_jwts(text) == JWT_PATTERN.sub('[REDACTED]', text), repr(text)
    token = S.jwt_token('fixture-key', 'fixture-secret')
    assert S.redact_jwts('x' * 490 + token + '.tail') == 'x' * 490 + '[REDACTED].tail'


def test_redaction_takes_linear_time_on_a_long_run_that_starts_a_token_again_and_again(tmp_path):
    sh, _, _ = shadow(tmp_path)
    text = 'eyJ' * 100_000                                       # 300 000 characters: ~20 s as a regular expression
    started = time.perf_counter()
    assert S.redact_jwts(text) == text                           # no dots: not a whole token ...
    # ... but a run that starts with "eyJ" may be what is left of one (a header, a payload): masked, as a whole
    assert sh.redact(text) == '[REDACTED]' and sh.clean({text: [text]}) == {'[REDACTED]': ['[REDACTED]']}
    assert sh.scrub(text) == '[REDACTED]' and sh.redact('x' + text) == 'x' + text     # (inside a word: not a token)
    assert time.perf_counter() - started < 2.0


def test_an_error_frame_is_redacted_first_and_then_cut_to_a_small_row(tmp_path):
    sh, _, _ = shadow(tmp_path)
    jwt = S.jwt_token('another-key', 'another-secret')           # not this connection's token: only its shape tells
    message = 'm' * 440 + jwt + ' ' + sh.secret + 'm' * 1_000_000     # both lie across the place where the cut falls
    frame = json.dumps({'error': {'name': 'INVALID_PARAM', 'message': message}})
    sh._connect = lambda url, **kw: FakeWS(sh.clock, [frame])
    with pytest.raises(S.StreamError):
        sh.run_once()
    row = next(r for r in drain(sh) if r['k'] == 'upbit_error')
    assert isinstance(row['error'], str) and len(row['error']) == S.base.FIELD_MAX == 500
    assert row['error'].startswith('{"name": "INVALID_PARAM", "message": "mmm') and '[REDACTED]' in row['error']
    assert 'eyJ' not in row['error'] and sh.secret[:6] not in row['error']         # no half of a secret either
    small = {'name': 'INVALID_AUTH', 'message': 'no'}
    sh._connect = lambda url, **kw: FakeWS(sh.clock, [json.dumps({'error': small})])
    with pytest.raises(S.StreamError):
        sh.run_once()
    assert next(r for r in drain(sh) if r['k'] == 'upbit_error')['error'] == small    # an ordinary one: as it came


def test_actual_websockets_redirect_loop_makes_one_attempt_only(monkeypatch):
    import websockets.sync.client as client
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus, SecurityError
    from websockets.http11 import Response
    before = client.MAX_REDIRECTS
    connect = S.base._connect_no_redirect()
    attempts = []
    def fake_open(self, deadline):
        attempts.append((self.uri, self.additional_headers))
        raise InvalidStatus(Response(302, 'Found', Headers({'Location': 'wss://untrusted.invalid/path'})))
    monkeypatch.setattr(client.reconnect, 'open_connection', fake_open)
    try:
        with pytest.raises(SecurityError, match='redirects'):
            connect(S.WS_URL, additional_headers={'Authorization':'Bearer offline-token'}, proxy=None)
        assert len(attempts) == 1 and attempts[0][0] == S.WS_URL
    finally:
        client.MAX_REDIRECTS = before


def test_clock_reuses_public_binance_only_midpoint_and_expiry(tmp_path):
    sh, _, clock = shadow(tmp_path)
    def get(url):
        assert url == 'https://fapi.binance.com/fapi/v1/time'
        clock.now += .2
        return {'serverTime': 1000155}
    sh._http_get = get
    sh.measure_clock()
    assert sh.offset_ms == pytest.approx(55)
    assert sh._offset()[0] == pytest.approx(55)
    clock.now += S.base.CLOCK_MAX_AGE_S + 1
    assert sh._offset()[0] is None
    def slow(url):
        clock.now += 2
        return {'serverTime':0}
    sh._http_get = slow
    sh.measure_clock()
    assert drain(sh)[-1]['skipped'] == 'slow'
    assert S.UpbitShadow.measure_clock is S.base.Shadow.measure_clock
    assert S.UpbitShadow.clock_loop is S.base.Shadow.clock_loop
    assert S.UpbitShadow.writer_loop is S.base.Shadow.writer_loop


def test_wall_clock_step_nulls_every_corrected_lag_and_keeps_the_raw_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, clock = shadow(tmp_path, [json.dumps(DOC)])
    shift = [1784014590.0 - clock.now]
    sh.clock = lambda: clock.now + shift[0]                      # wall clock: steps on its own, mono does not
    def get(url):
        clock.now += .004
        return {'serverTime': sh.clock() * 1000 - 2 + 40}
    sh._http_get = get
    sh.measure_clock()
    assert sh._offset()[0] == pytest.approx(40, abs=.01)
    shift[0] += 5
    sh.run_once()
    rows = drain(sh)
    ann = next(r for r in rows if r['k'] == 'upbit_ann')
    for field in ('first_listed_at', 'listed_at', 'timestamp'):
        assert ann['lag_ms_' + field] is None and ann['lag_raw_ms_' + field] is not None
    assert ann['offset_ms'] is None and ann['offset_age_s'] is None and ann['offset_rtt_ms'] is None
    assert [r['delta_ms'] for r in rows if r.get('event') == 'step'] == [pytest.approx(5000, abs=.2)]
    assert sh.clock_wake.is_set()


def test_a_pause_of_both_clocks_is_no_step_and_the_measurement_after_the_push_gives_it_away(tmp_path, monkeypatch):
    """Inherited, and the same for all three lags: a VM paused from outside (or a slewed clock) leaves wall and
    monotonic clock together. Nothing is voided, every lag_ms_* is a number that is 300 ms wrong - so the push asks
    for a clock measurement, and that row says how far the offset has moved."""
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, clock = shadow(tmp_path, [json.dumps(dict(DOC, timestamp=1784014594400))])
    lost = [0.0]                                                 # seconds the exchange went on while this box stood
    sh.clock = lambda: clock.now + 1784014593.48 - 1000.0        # the box clock: the push arrives at ...594.500
    def get(url):
        clock.now += .004
        return {'serverTime': (sh.clock() + lost[0]) * 1000 - 2}
    sh._http_get = get
    sh.measure_clock()
    assert drain(sh)[-1]['drift_ms'] is None and sh._offset()[0] == pytest.approx(0, abs=.01)
    lost[0] = .3
    sh.run_once()
    rows = drain(sh)
    ann = next(r for r in rows if r['k'] == 'upbit_ann')
    assert ann['lag_ms_timestamp'] == pytest.approx(100, abs=.2)     # on a clock that is 300 ms behind: really 400
    assert ann['offset_rtt_ms'] == pytest.approx(4) and not [r for r in rows if r.get('event') == 'step']
    assert sh.clock_wake.is_set()
    sh.measure_clock()
    after = drain(sh)[-1]
    assert after['drift_ms'] == pytest.approx(300, abs=.01)
    assert ann['lag_raw_ms_timestamp'] + after['offset_ms'] == pytest.approx(400, abs=.3)


def test_only_an_announcement_asks_for_a_clock_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, _ = shadow(tmp_path, ['junk', '{"status":"UP"}'])
    sh.run_once()
    assert not sh.clock_wake.is_set()
    sh._connect = lambda url, **kw: FakeWS(sh.clock, [json.dumps(DOC)])
    sh.run_once()
    assert sh.clock_wake.is_set()


def test_offset_is_checked_against_the_clocks_of_the_receive_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, clock = shadow(tmp_path, [json.dumps(DOC)])
    sh.measure_clock()
    seen, real = [], sh._correction
    def spy(*args):
        seen.append(args)
        return real(*args)
    sh._correction = spy
    original = S.decode
    def decode(raw):
        clock.now += .25                                         # slow parsing after the stamp must not matter
        return original(raw)
    monkeypatch.setattr(S, 'decode', decode)
    sh.run_once()
    ann = next(r for r in drain(sh) if r['k'] == 'upbit_ann')
    assert seen == [(ann['recv_ms'] / 1000, ann['recv_ms'] / 1000)]     # (wall, mono): one fake clock is both here


def file_lines(sh):
    return [x for x in Path(sh.out_path).read_bytes().split(b'\n') if x]


def test_lone_surrogate_title_is_written_and_the_writer_goes_on(tmp_path):
    sh, _, _ = shadow(tmp_path)
    bad = '예시(XYZ) \ud800 신규 거래지원 안내 (KRW 마켓)'
    rec = S.parse_push(json.dumps(dict(DOC, title=bad)), 1784014594500, None)
    assert rec['title'] == bad and rec['tag'] == 'upbit_list_krw'
    sh.write(rec)
    sh.write({'k': 'after'})
    sh.stop.set()
    sh.writer_loop()                                             # the review's reproduction ended the thread here
    rows = [json.loads(x) for x in file_lines(sh)]
    assert [r['k'] for r in rows] == ['upbit_ann', 'after'] and rows[0]['title'] == bad
    assert sh.write_failed == 0 and '신규 거래지원' in Path(sh.out_path).read_text(encoding='utf-8')


def test_disk_full_in_the_middle_of_a_row_cannot_corrupt_the_next_row(tmp_path, monkeypatch):
    sh, _, _ = shadow(tmp_path)
    sh.write({'k': 'upbit_ann', 'title': 'first'})
    sh.write({'k': 'upbit_ann', 'title': 'second'})
    real, calls = os.write, []
    def write(fd, data):
        calls.append(len(data))
        if len(calls) == 1:
            return real(fd, data[:12])
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, 'No space left on device')
        return real(fd, data)
    monkeypatch.setattr(os, 'write', write)
    sh.stop.set()
    sh.writer_loop()
    lines = file_lines(sh)
    assert lines[0] == b'{"k": "upbit'
    rows = [json.loads(x) for x in lines[1:]]
    assert [(r['k'], r.get('title'), r.get('n')) for r in rows] == [('writer', None, 1), ('upbit_ann', 'second', None)]
    assert sh.write_failed == 1 and stat.S_IMODE(Path(sh.out_path).stat().st_mode) == 0o600


def test_restart_after_a_torn_last_row_starts_on_a_new_line(tmp_path):
    sh, _, _ = shadow(tmp_path)
    Path(sh.out_path).write_bytes(b'{"k": "conn"}\n{"k": "upbit_ann", "ti')
    sh._append('{"k": "clock"}\n')
    sh._append('{"k": "x"}\n')
    assert Path(sh.out_path).read_bytes() == b'{"k": "conn"}\n{"k": "upbit_ann", "ti\n{"k": "clock"}\n{"k": "x"}\n'


def test_dying_writer_worker_takes_the_exit_path(tmp_path, monkeypatch):
    sh, _, _ = shadow(tmp_path)
    codes = []
    monkeypatch.setattr(S.base.os, '_exit', codes.append)
    class Fatal(BaseException):
        pass
    def append(line):
        raise Fatal()
    sh._append = append
    sh.write({'k': 'x'})
    sh.stop.set()
    sh._producers_done.set()
    sh._writer_worker()
    assert codes == [S.base.EXIT_WRITER_DEAD] and S.base.EXIT_WRITER_DEAD != 0


def test_stopped_row_reports_unwritten_rows(tmp_path):
    sh, _, _ = shadow(tmp_path)
    sh.write_failed = 2
    def once():
        sh.stop.set()
    sh.run_once = once
    run_waits(sh, 1)
    last = drain(sh)[-1]
    assert last['event'] == 'stopped' and last['write_failed'] == 2 and last['dropped'] == 0


def test_private_file_rotation_existing_mode_symlink_hardlink_and_partial_write(tmp_path, monkeypatch):
    sh, _, _ = shadow(tmp_path)
    path = Path(sh.out_path)
    path.write_text('old\n')
    path.chmod(0o666)
    sh._append('first\n')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    monkeypatch.setattr(S.base, 'MAX_FILE_BYTES', 12)
    sh._append('second\n')
    backup = Path(str(path)+'.1')
    assert backup.read_text() == 'old\nfirst\n' and path.read_text() == 'second\n'
    assert stat.S_IMODE(backup.stat().st_mode) == stat.S_IMODE(path.stat().st_mode) == 0o600
    path.unlink()
    victim = tmp_path/'victim'
    victim.write_text('v'*100)
    path.symlink_to(victim)
    with pytest.raises(OSError):
        sh._append('no\n')
    assert victim.read_text() == 'v'*100 and path.is_symlink()
    path.unlink()
    os.link(victim, path)
    with pytest.raises(OSError):
        sh._append('no\n')
    path.unlink()
    # A short os.write must be completed, not silently truncate a JSONL row.
    real_write = os.write
    monkeypatch.setattr(os, 'write', lambda fd, b: real_write(fd, b[:2]))
    sh._append('complete\n')
    assert path.read_text() == 'complete\n'


def test_receive_enqueue_has_no_file_io_and_worker_drains_shutdown(tmp_path):
    sh, _, _ = shadow(tmp_path)
    sh.write({'k':'queued'})
    assert not Path(sh.out_path).exists()
    sh.clock_loop = lambda: None
    def once():
        sh.write({'k':'last_push'})
        sh.stop.set()
    sh.run_once = once
    sh.run()
    rows = [json.loads(line) for line in Path(sh.out_path).read_text().splitlines()]
    assert [r['k'] for r in rows] == ['queued','last_push','conn']
    assert rows[-1]['event'] == 'stopped'


def test_rows_enqueued_after_the_writer_saw_stop_and_an_empty_queue_still_reach_the_file(tmp_path):
    """The race itself, made on purpose with the real writer thread and the real run(): SIGTERM while recv() waits,
    the writer leaves its loop, and only then the push of that recv() and the "stopped" row are enqueued."""
    sh, _, clock = shadow(tmp_path)
    sh.clock_loop = lambda: None
    left, real_loop = threading.Event(), sh.writer_loop
    def writer_loop():
        real_loop()
        left.set()
    sh.writer_loop = writer_loop
    class WS(FakeWS):
        def recv(self, timeout):
            sh.stop.set()
            assert left.wait(10)
            return json.dumps(DOC)
    sh._connect = lambda url, **kw: WS(clock)
    sh.run()
    rows = [json.loads(line) for line in Path(sh.out_path).read_text(encoding='utf-8').splitlines()]
    assert [(r['k'], r.get('event')) for r in rows] == [('conn', 'open'), ('upbit_ann', None), ('conn', 'stopped')]
    assert S.UpbitShadow._writer_worker is S.base.Shadow._writer_worker and sh.q.empty()


def test_disk_error_does_not_kill_writer_or_reveal_path(tmp_path, caplog):
    sh, _, _ = shadow(tmp_path)
    sh.out_path = str(tmp_path/'fixture-secret'/'missing')
    sh.write({'k':'one'})
    sh.stop.set()
    sh.writer_loop()
    assert 'secure log append failed' in caplog.text and sh.secret not in caplog.text


@pytest.mark.parametrize(('code', 'kind'), [
    (errno.ENOSPC, 'OSError'), (errno.EACCES, 'PermissionError'), (errno.EROFS, 'OSError'), (errno.EDQUOT, 'OSError'),
    (errno.ELOOP, 'OSError'), (errno.EISDIR, 'IsADirectoryError'), (errno.ENOENT, 'FileNotFoundError'),
])
def test_the_journal_tells_which_error_stopped_a_write_but_never_the_path(tmp_path, monkeypatch, caplog, code, kind):
    sh, _, _ = shadow(tmp_path)
    sh.out_path = str(tmp_path / 'fixture-secret-dir' / 'log.jsonl')
    def refuse(path, flags, mode=0o777):
        raise OSError(code, os.strerror(code), path)                 # as the system raises it: with the path
    monkeypatch.setattr(os, 'open', refuse)
    with pytest.raises(OSError) as raised:
        sh._append('x\n')
    assert raised.value.errno == code and raised.value.filename is None      # still an OSError: the writer pauses
    sh.write({'k': 'one'})
    sh.stop.set()
    sh.writer_loop()
    name = errno.errorcode[code]
    assert f'write failed: {kind}: [Errno {code}] secure log append failed ({name})' in caplog.text
    assert 'fixture-secret-dir' not in caplog.text and str(tmp_path) not in caplog.text


def test_the_journal_tells_a_link_a_directory_and_a_short_write_apart_on_a_real_disk(tmp_path, monkeypatch, caplog):
    def journal(name, prepare=lambda sh, folder: None):
        sh, _, _ = shadow(tmp_path / name)
        (tmp_path / name).mkdir()
        prepare(sh, tmp_path / name)
        caplog.clear()
        sh.write({'k': 'one'})
        sh.stop.set()
        sh.writer_loop()
        assert sh.write_failed == 1 and str(tmp_path) not in caplog.text
        return caplog.text
    def symlink(sh, folder):
        (folder / 'victim').write_text('v')
        os.symlink(folder / 'victim', sh.out_path)
    def hardlink(sh, folder):
        (folder / 'victim').write_text('v')
        os.link(folder / 'victim', sh.out_path)
    assert 'secure log append failed (ELOOP)' in journal('symlink', symlink)
    text = journal('directory', lambda sh, folder: os.mkdir(sh.out_path))
    assert 'IsADirectoryError' in text and 'secure log append failed (EISDIR)' in text
    assert 'OSError: secure log append failed (not a private regular file)' in journal('hardlink', hardlink)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'write', lambda fd, data: 0)
        assert 'OSError: secure log append failed (short log write)' in journal('short')
    with monkeypatch.context() as patch:                         # an OSError without errno that is not the writer's own
        def odd(path, flags, mode=0o777):
            raise OSError('text that names ' + path)
        patch.setattr(os, 'open', odd)
        assert 'OSError: secure log append failed (no errno)' in journal('odd')


def test_cli_refuses_missing_keys_and_bad_categories_before_connect(monkeypatch, tmp_path):
    monkeypatch.delenv('UPBIT_ACCESS_KEY', raising=False)
    monkeypatch.delenv('UPBIT_SECRET_KEY', raising=False)
    for argv in ([], ['--out',str(tmp_path/'log')], ['--out','x','--categories','trading']):
        with pytest.raises(SystemExit) as ex:
            S.main(argv)
        assert ex.value.code == 2


def test_cli_umask_categories_and_transport_wiring(monkeypatch, tmp_path):
    monkeypatch.setenv('UPBIT_ACCESS_KEY','fixture-key')
    monkeypatch.setenv('UPBIT_SECRET_KEY','fixture-secret')
    seen = {}
    def run(self):
        seen['sh'] = self
        seen['umask'] = os.umask(0o077)
    monkeypatch.setattr(S.UpbitShadow, 'run', run)
    monkeypatch.setattr(S.signal, 'signal', lambda *a: None)
    old_mask = os.umask(0o022)
    import websockets.sync.client as client
    old_redirects = client.MAX_REDIRECTS
    try:
        assert S.main(['--out',str(tmp_path/'log'),'--categories','trade,wallet']) == 0
        assert seen['umask'] == 0o077 and seen['sh'].categories == ['trade','wallet']
        assert seen['sh']._http_get is S.base._http_get
        assert client.MAX_REDIRECTS == 1
    finally:
        os.umask(old_mask)
        client.MAX_REDIRECTS = old_redirects


def test_ast_import_and_endpoint_allowlist():
    source = inspect.getsource(S)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split('.')[0] in sys.stdlib_module_names | {'httpx','websockets'} for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                assert node.level == 1 and node.module is None and [a.name for a in node.names] == ['ann_ws_shadow']
            else:
                assert node.module.split('.')[0] in sys.stdlib_module_names | {'httpx','websockets','__future__'}
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {'exec','eval','__import__'}
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'base':
            assert node.attr in {'Shadow','scrub','MAX_FILE_BYTES','MAX_OTHER_PER_CONN','Rejected','_connect_no_redirect',
                                 '_http_get', 'short','TITLE_MAX','KEYS_MAX','KEY_MAX'}    # (the size limits of a row)
    urls = [n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith(('https://','wss://'))]
    assert urls == [S.WS_URL]
    for forbidden in ('/v1/orders','/v1/accounts','/v1/withdraws','/fapi/v1/order','/fapi/v1/balance','/sapi/v1/'):
        assert forbidden not in source
    assert 'signed_url(' not in source


def test_service_isolated_state_and_environment():
    # shared rules (own UID, the bot's group only for the code, hidden paths, kept hardening): check_logger_unit
    header, svc = check_logger_unit('tradebot-upbit-ann-shadow.service', module='upbit_ann_ws_shadow',
                                    env_file='/etc/tradebot/upbit.env',
                                    hidden=('-/var/lib/tradebot-ann-shadow',))     # the Binance logger's data too
    text = (Path(__file__).parents[1]/'deploy/tradebot-upbit-ann-shadow.service').read_text(encoding='utf-8')
    assert '--categories' not in text and 'live.env' not in text    # never the bot's trading keys
    assert 'UPBIT_ACCESS_KEY' in header and 'UPBIT_SECRET_KEY' in header
    assert svc['TimeoutStopSec'] == '20'


def test_f1_upbit_main_filters_third_party_keys_tokens_and_tracebacks(tmp_path, monkeypatch):
    from .test_ann_ws_shadow import _assert_main_log_filter
    _assert_main_log_filter(S, S.UpbitShadow, monkeypatch, tmp_path, ('UPBIT_ACCESS_KEY', 'UPBIT_SECRET_KEY'))


def test_f4_upbit_recv_wait_and_stamp_have_no_file_io(tmp_path, monkeypatch):
    from .test_ann_ws_shadow import _assert_recv_wait
    sh, _, clock = shadow(tmp_path)
    _assert_recv_wait(S, sh, clock, json.dumps(DOC), monkeypatch)


def test_f5_upbit_infinite_original_timestamp_is_null_in_strict_file(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    raw = json.dumps(dict(DOC, timestamp=0)).replace('"timestamp": 0', '"timestamp": 1e999')
    sh, _, _ = shadow(tmp_path, [raw])
    sh.run_once()
    sh.stop.set()
    sh.writer_loop()
    rows = [json.loads(line, parse_constant=lambda x: pytest.fail(x)) for line in file_lines(sh)]
    ann = next(r for r in rows if r['k'] == 'upbit_ann')
    assert ann['timestamp'] is None and ann['timestamp_ms'] is None
    assert ann['lag_raw_ms_timestamp'] is None and ann['lag_ms_timestamp'] is None
    assert ann['title'] == DOC['title'] and sh.write_failed == 0


# ───────────────────────── review 2 of 0ec0d61 ─────────────────────────

def test_a_row_names_the_clock_line_its_lags_were_made_with(tmp_path, monkeypatch):
    """The module text of ann_ws_shadow says how to check lag_ms_* - against the measurement named by
    offset_sample_ms, not only against the ones before and after the stamp."""
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, clock = shadow(tmp_path, [json.dumps(DOC)])
    sh._http_get = lambda url: (setattr(clock, 'now', clock.now + .004), {'serverTime': clock.now * 1000 + 40})[1]
    sh.measure_clock()
    sample = drain(sh)[0]['sample_ms']
    sh.run_once()
    ann = next(r for r in drain(sh) if r['k'] == 'upbit_ann')
    assert ann['offset_sample_ms'] == sample and ann['offset_ms'] is not None
    sh2, _, _ = shadow(tmp_path, [json.dumps(DOC)])
    sh2.run_once()
    ann = next(r for r in drain(sh2) if r['k'] == 'upbit_ann')
    assert ann['offset_ms'] is None and ann['offset_sample_ms'] is None
    for phrase in ('offset_sample_ms', 'never by file order or t', "not how long the frame did"):
        assert phrase in S.__doc__


@pytest.mark.parametrize('spelling', ['escaped', 'utf-16', 'utf-32', 'utf-16 cut short',
                                      'escaped, in a string JSON cannot read'])
def test_an_unknown_frame_is_logged_masked_whatever_its_spelling(tmp_path, monkeypatch, spelling):
    """0ec0d61 logged an `other` row as scrub(raw): a key spelled with \\u escapes, or a UTF-16 / UTF-32 frame (a
    bytes repr with a NUL between every two characters), went to the file as it was - and, after the fix, still
    when the string also held an escape JSON does not know (\\q): redact_json cannot decode that one."""
    from .test_ann_ws_shadow import _has_piece_of, _unescape
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    key = 'fixture-key-' + 'k' * 28
    text = json.dumps({'type': 'pong', 'echo': 'x' * 10 + key})              # not an announcement
    if spelling.startswith('escaped'):
        raw = text.replace(key, ''.join('\\u%04x' % ord(c) for c in key))
        if spelling != 'escaped':
            raw = raw.replace('"}', ' \\q"}')
    elif spelling == 'utf-16 cut short':
        raw = text.encode('utf-16') + b'\x00'
    else:
        raw = text.encode(spelling)
    sh, _, _ = shadow(tmp_path, [raw])
    sh.key = key
    sh.run_once()
    other = next(r['raw'] for r in drain(sh) if r['k'] == 'other')
    assert 'pong' in other and '[REDACTED]' in other
    assert not _has_piece_of(_unescape(other), key), other


def test_what_is_left_of_a_token_is_masked_too(tmp_path):
    """Review 2, finding 3: only the token of this connection and a whole three-part JWT were masked. Its header and
    payload together, the payload alone (base64url of {"access_key":"<key>",...}: it decodes to the key) or the start
    of a token cut short stayed in the text."""
    sh, _, _ = shadow(tmp_path)
    token = S.jwt_token(sh.key, sh.secret)                       # another connection's: only its shape tells
    header, payload, _ = token.split('.')
    for text in (header + '.' + payload, payload, token[:60], 'Bearer ' + payload[:30], json.dumps({'a': payload}),
                 'x ' + header + '.' + payload + '. y'):
        out = sh.redact(text)
        assert 'eyJ' not in out and sh.key not in out, (text, out)
        for run in re.findall(r'[A-Za-z0-9_-]{8,}', out):              # nothing left in it decodes to the key
            for skip in range(4):
                try:
                    decoded = unb64(run[skip:])
                except ValueError:
                    continue
                assert b'fixture' not in decoded, (text, out)
    for public in ('heyJude-and-friends-2026', 'eyJ', 'see eyJx', 'a.b.c'):           # no token: left as it is
        assert sh.redact(public) == public


def test_the_shortcut_of_redact_json_changes_nothing_with_tokens_either(tmp_path, monkeypatch):
    from .test_ann_ws_shadow import _assert_shortcut_changes_nothing
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, _ = shadow(tmp_path)
    sh.run_once()                                                 # sets this connection's token
    token = sh._token
    header, payload, signature = token.split('.')
    needles = [sh.key, sh.secret, token, header, payload, payload[:15], signature[:12], 'eyJ', 'eyJhbG', 'e', 'yJ',
               header + '.' + payload, 'signature=ab12', 'SIGNATURE', '.', '-_']
    _assert_shortcut_changes_nothing(sh, needles)


def test_a_piece_of_a_token_glued_to_other_text_is_masked_too(tmp_path, monkeypatch):
    """Cross-review of finding 3's fix: a payload right after another character ("x" + payload) is no run that
    starts with "eyJ", and the signature part has no "eyJ" at all - both stayed, and the payload decodes to the
    key. This connection's payload and signature are masked as exact values now, and the key as every payload
    spells it (an older token's payload loses it too). Public words keep theirs."""
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, _ = shadow(tmp_path)
    sh.run_once()                                                 # sets this connection's token
    header, payload, signature = sh._token.split('.')
    older = S.jwt_token(sh.key, sh.secret).split('.')[1]          # the same key, another nonce
    cut = older[:20 + len(sh.key) // 3 * 4]                       # ... cut right after the key's whole groups
    for text in ('x' + payload, 'sig ' + signature, 'x' + older, 'x' + header + '.' + payload,
                 json.dumps({'echo': 'x' + payload}), 'x' + cut):
        out = sh.redact(text)
        assert payload not in out and signature not in out and '[REDACTED]' in out, (text, out)
        for run in re.findall(r'[A-Za-z0-9_-]{8,}', out):         # nothing left in it decodes to a piece of the key
            for skip in range(4):
                try:
                    decoded = unb64(run[skip:])
                except ValueError:
                    continue
                assert not any(sh.key[i:i + 6].encode() in decoded for i in range(len(sh.key) - 5)), (text, out)
    assert sh.redact('heyJude-and-friends-2026') == 'heyJude-and-friends-2026'


def test_a_key_spelled_with_escapes_in_a_log_message_is_masked_here_too(tmp_path):
    from .test_ann_ws_shadow import _has_piece_of, _unescape
    import io
    sh, _, _ = shadow(tmp_path)
    sh.key = 'fixture-key-' + 'k' * 28
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(S.base.RedactingFilter(sh.redact))
    lg = logging.Logger('crossreview.upbit.escapes')
    lg.addHandler(handler)
    lg.warning('server said %s', ''.join('\\u%04x' % ord(c) for c in sh.key))
    assert '[REDACTED]' in stream.getvalue() and not _has_piece_of(_unescape(stream.getvalue()), sh.key)


def test_the_token_pieces_are_worked_out_from_one_reading_of_the_token(tmp_path):
    """Cross-review, second round: the receive thread may replace the token while another thread works out what to
    mask. Read more than once, the cache could hold the old token's payload and signature under the new token's
    name - for good: the new signature would never be masked."""
    sh, _, _ = shadow(tmp_path)
    tokens = iter([S.jwt_token(sh.key, sh.secret) for _ in range(100)])   # another token at every reading

    class Changing(S.UpbitShadow):
        @property
        def _token(self):
            return next(tokens)

        @_token.setter
        def _token(self, value):
            pass

    sh.__class__ = Changing
    values = sh._secret_values()
    (_, token), held = sh._token_values
    assert held[:3] == (token, *token.split('.')[1:]) and token in values


def test_a_short_access_key_is_masked_inside_any_payload_too(tmp_path, monkeypatch):
    """Cross-review, second and third rounds: no piece of a payload - glued to other text, cut anywhere - may keep
    the letters that spell the whole access key. A key of two letters has no whole group of its own, and the last
    letters of any key share a group with what follows them: the key with that group completed covers both, and a
    piece that holds the payload's start is masked whole. (Two letters cut right after them, with neither, are left:
    an Upbit access key has 40 letters.) The nonce is fixed, of digits: a random one spells the three letters that
    hold "ab" by chance now and then (about 2 runs in 100), and the test would fail for nothing."""
    monkeypatch.setattr(S.uuid, 'uuid4', lambda: uuid.UUID('12345678-1234-4123-8123-123456789012'))
    start_of_payload = base64.urlsafe_b64encode(b'{"access_key":"').decode()
    for key in ('ab', 'abc', 'fixture-key', 'fixture-key-' + 'k' * 28):
        sh = S.UpbitShadow(key, 'fixture-secret', str(tmp_path / 'log.jsonl'), connect=None,
                           http_get=lambda url: {'serverTime': 0})
        payload = S.jwt_token(key, 'fixture-secret').split('.')[1]     # not this connection's token (it has none)
        assert payload.startswith(start_of_payload) and S._PAYLOAD_PIECE.fullmatch(payload)
        spelling = payload[20:(120 + 8 * len(key) - 1) // 6 + 1]        # the letters that hold the key's bits
        assert unb64(spelling[:len(spelling) // 4 * 4] + payload[20 + len(spelling) // 4 * 4:][:4]).startswith(
            key.encode()) and len(spelling) == (8 * len(key) + 5) // 6
        for begin in range(21):
            for cut in range(21, len(payload) + 1):
                if len(key) < 3 and begin and cut < 24:
                    continue
                out = sh.redact('x' + payload[begin:cut])
                assert spelling not in out, (key, begin, cut, out)
