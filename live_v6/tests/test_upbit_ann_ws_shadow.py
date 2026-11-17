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
import socket
import stat
import sys
import threading
import time
import uuid

import pytest
from live_v6.tools import upbit_ann_ws_shadow as S

from .test_ann_ws_shadow import check_logger_unit


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
])
def test_classifier_boundaries(title, tag):
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
    rec = S.parse_push(dict(DOC, title=title), 1784014594500, None)
    assert time.perf_counter() - started < 2.0
    assert rec['tickers'] == ['XYZ'] and rec['tag'] == 'upbit_list_krw'


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
    assert ann['offset_ms'] is None and ann['offset_age_s'] is None
    assert [r['delta_ms'] for r in rows if r.get('event') == 'step'] == [pytest.approx(5000, abs=.2)]
    assert sh.clock_wake.is_set()


def test_offset_is_checked_against_the_clocks_of_the_receive_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'RECONNECT_S', 2)
    sh, _, clock = shadow(tmp_path, [json.dumps(DOC)])
    sh.measure_clock()
    seen, real = [], sh._offset
    def spy(*args):
        seen.append(args)
        return real(*args)
    sh._offset = spy
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


def test_disk_error_does_not_kill_writer_or_reveal_path(tmp_path, caplog):
    sh, _, _ = shadow(tmp_path)
    sh.out_path = str(tmp_path/'fixture-secret'/'missing')
    sh.write({'k':'one'})
    sh.stop.set()
    sh.writer_loop()
    assert 'secure log append failed' in caplog.text and sh.secret not in caplog.text


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
            assert node.attr in {'Shadow','scrub','MAX_FILE_BYTES','MAX_OTHER_PER_CONN','Rejected','_connect_no_redirect','_http_get'}
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
    assert svc['TimeoutStopSec'] == '15'
