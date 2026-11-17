"""Read-only Upbit announcement receive-time logger; no trading operations.

Run as a module with --out PATH; UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY required.
Only network destinations: private announcement WebSocket and the inherited
public Binance futures clock. All categories by default; --categories trade,wallet
filters explicitly. Records retain CREATED and UPDATED separately, without dedup.

One {"k":"upbit_ann"} row per push. It carries THREE lags, and they are not three
readings of one thing (docs.upbit.com/kr/reference/websocket-announcement, read
2026-11-17):
  first_listed_at  "최초 게시 시각 (KST)", ISO 8601; whole seconds in the doc example.
                   In an UPDATED push it is still the FIRST publication: its lag is
                   then the age of the notice (days), not a delivery time.
  listed_at        "최종 게시 시각 (KST)", "공지사항이 갱신되는 경우 함께 갱신됩니다", ISO 8601;
                   whole seconds in the doc example. If the real value is cut to
                   the second as well, its lag reads up to 999 ms too long.
  timestamp        "타임스탬프 (ms)" - the doc does not say of what, and in its example
                   it is another day than the two ISO times. If it is the moment
                   the push was made, its lag leaves out publication -> push.
Which of them is "the" lag is not known before real pushes are in: look at
timestamp_ms - listed_at_ms first (spread evenly over 0..999 ms means listed_at is
cut to the second), and never read lag_ms_timestamp alone as "the notice came
after N ms".
lag_raw_ms_<field> = receive stamp - that time; lag_ms_<field> adds the clock
offset (null while there is no valid one). The offset is the inherited one, taken
against the BINANCE futures server: it puts this box on Binance time, and whatever
Upbit's own clock differs from that stays inside every lag_ms_*.
tag and tickers are made from the title as it is logged (its first 500 characters;
title_len is the whole length). offset_rtt_ms, the clock / writer / conn rows, what
a clock step or slewing does to lag_ms_* and how to read the file: see the module
text of ann_ws_shadow.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import errno
import hashlib
import hmac
import json
import logging
import math
import os
import re
import signal
import stat
import uuid

from . import ann_ws_shadow as base

WS_URL = "wss://api.upbit.com/websocket/v1/private"
CATEGORIES = ("notice", "trade", "wallet", "maintenance", "digital_asset", "nft", "service", "event")
PING_S = 30.0
RECONNECT_S = 23 * 3600.0
_MARKETS = re.compile(r"(?<![A-Z0-9])(?:KRW|BTC|USDT|원화)(?:\s*[,/·]\s*(?:KRW|BTC|USDT|원화))*\s*마켓")
# "유의 종목 지정" in a title that does NOT designate anything: release, cancellation, and the extension of a
# running designation - which really reads "지정 기간 연장 안내" or "지정 안내 (기간 연장)" (19 of 813 real notices).
_NOT_A_DESIGNATION = re.compile(r"유의종목지정(?:기간)?(?:해제|연장|취소)|\(기간연장\)")
_JWT_RUN = re.compile(r"[A-Za-z0-9_.-]+")
_OWN_ERRORS = ("not a private regular file", "short log write")    # OSErrors raised by the writer code itself


def redact_jwts(text: str) -> str:
    """Every JWT-shaped piece of `text` replaced by [REDACTED]: exactly what the pattern
    eyJ[A-Za-z0-9_-]*\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+ matches, found in ONE pass. As a regular expression that
    pattern scans a long run of such characters again from every "eyJ" in it: 48 KiB of "eyJeyJ..." kept the
    receive thread (and, through the interpreter lock, the other threads) busy for 0.6 s, and four times as long
    for every doubling - a frame may be 1 MiB.
    Here a run is split at its dots; a part that holds "eyJ" and is followed by two non-empty parts is a token."""
    def run(m):
        parts, out, i = m.group().split("."), [], 0
        while i < len(parts):
            at = parts[i].find("eyJ")
            if at >= 0 and i + 2 < len(parts) and parts[i + 1] and parts[i + 2]:
                out.append(parts[i][:at] + "[REDACTED]")
                i += 3
            else:
                out.append(parts[i])
                i += 1
        return ".".join(out)
    return _JWT_RUN.sub(run, text)


def jwt_token(key: str, secret: str) -> str:
    def b64(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
    header = b64(b'{"alg":"HS512","typ":"JWT"}')
    payload = b64(json.dumps({"access_key": key, "nonce": str(uuid.uuid4())},
                             separators=(",", ":")).encode())
    unsigned = header + "." + payload
    return unsigned + "." + b64(hmac.new(secret.encode(), unsigned.encode("ascii"), hashlib.sha512).digest())


def subscription(categories=None) -> str:
    data = {"type": "announcement", "include_body": False}
    if categories is not None:
        if not categories or any(c not in CATEGORIES for c in categories):
            raise ValueError("unsupported announcement categories")
        data["categories"] = list(dict.fromkeys(categories))
    return json.dumps([{"ticket": str(uuid.uuid4())}, data, {"format": "DEFAULT"}])


def classify_upbit_title(title: str) -> str | None:
    # p76 events: both legacy '마켓 디지털 자산 추가' and '신규 거래지원'.
    # p109 designation only: release, an extended period and mere caution aren't designations.
    t = re.sub(r"\s+", "", title)
    if "거래지원종료" in t:
        return "upbit_delist"
    if "유의종목지정" in t and not _NOT_A_DESIGNATION.search(t):
        return "upbit_warning"
    if "거래지원취소" in t:
        # A listing that was called off - for one of the coins in the title or for all of them (real case: notice
        # 6558, HEMI cancelled, USELESS kept). The tag is per notice, so such a title never gets a listing tag.
        return "upbit_list_cancel"
    if not any(p in t for p in ("신규거래지원", "디지털자산추가", "마켓추가안내")):
        return None
    markets = " ".join(_MARKETS.findall(title))
    if re.search(r"\bKRW\b|원화", markets):
        return "upbit_list_krw"
    if re.search(r"\b(?:BTC|USDT)\b", markets):
        return "upbit_list_other"
    return None


# A ticker is upper-case letters and digits with at least one letter: it may start with a digit (1INCH, 0G, 2Z) but
# is never digits only (dates). Older notices put the Korean name before it. The "has a letter" test is a lookahead
# on purpose: `[A-Z0-9]*[A-Z][A-Z0-9]*` backtracks quadratically over a long run of capitals, and a title is
# untrusted input parsed on the receive thread.
_TICKER_ITEM = r"(?:[가-힣]+\s+)?(?=[0-9]*[A-Z])[A-Z0-9]+"
_TICKER_GROUP = re.compile(r"\s*" + _TICKER_ITEM + r"(?:\s*[,/·]\s*" + _TICKER_ITEM + r")*\s*")


def extract_tickers(title: str) -> list[str]:
    # Entire ticker groups, optionally with Korean names in older notices.
    # Market/annotation prose doesn't match this grammar.
    found = []
    for group in re.findall(r"\(([^()]*)\)", title):
        if _TICKER_GROUP.fullmatch(group):
            for part in re.split(r"\s*[,/·]\s*", group.strip()):
                token = part.split()[-1]
                if token != "KRW" and token not in found:
                    found.append(token)
    return found


def to_ms(value) -> float | None:
    """Numeric values are epoch milliseconds; ISO strings must carry a timezone.

    Never guess UTC or host timezone for malformed/naive timestamps.
    """
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result = float(value)
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None or dt.utcoffset() is None:
                return None
            result = dt.timestamp() * 1000
        else:
            return None
        return result if math.isfinite(result) else None
    except (ValueError, OverflowError, OSError):
        return None


def decode(raw):
    try:
        msg = json.loads(raw)
        return msg if isinstance(msg, dict) else None
    except (TypeError, ValueError):
        return None


def parse_push(raw, recv_ms: float, offset_ms: float | None, offset_age_s=None, offset_rtt_ms=None):
    """One row from a pushed frame, or None when it is not an announcement. Whatever the frame holds, the row is
    small and quick to make: the title is cut to TITLE_MAX characters BEFORE it is classified and searched for
    tickers (both take quadratic time on some long titles - 2 s for 40 000 characters of "KRW, KRW, ...", with
    every other thread waiting), every other echoed field is cut too, and title_len tells when the title was."""
    msg = raw if isinstance(raw, dict) else decode(raw)
    if msg is None or msg.get("type") != "announcement":
        return None
    whole = str(msg.get("title") or "")
    title = whole[:base.TITLE_MAX]
    rec = dict(k="upbit_ann", recv_ms=round(recv_ms, 1), offset_ms=offset_ms, offset_age_s=offset_age_s,
               offset_rtt_ms=None if offset_rtt_ms is None else round(offset_rtt_ms, 1),
               title=title, title_len=len(whole), tag=classify_upbit_title(title), tickers=extract_tickers(title),
               keys=[k[:base.KEY_MAX] for k in sorted(str(k) for k in msg)[:base.KEYS_MAX]])
    for field in ("event_type", "uuid", "category", "url", "stream_type"):
        rec[field] = base.short(msg.get(field))
    for field in ("first_listed_at", "listed_at", "timestamp"):
        value = msg.get(field)
        ms = to_ms(value)
        rec[field] = base.short(value)
        rec[field + "_ms"] = ms
        rec["lag_raw_ms_" + field] = None if ms is None else round(recv_ms - ms, 1)
        rec["lag_ms_" + field] = None if ms is None or offset_ms is None else round(recv_ms + offset_ms - ms, 1)
    return rec


class StreamError(Exception):
    def __init__(self, auth=False):
        self.auth = auth
        super().__init__("announcement authentication rejected" if auth else "announcement stream error")


class UpbitShadow(base.Shadow):
    def __init__(self, key, secret, out_path, *, categories=None, **kwargs):
        if not key or not secret:
            raise ValueError("UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY are required")
        subscription(categories)  # validate before starting any workers
        super().__init__(key, secret, out_path, **kwargs)
        self.categories = categories
        self._token = ""
        # An isolated disabled logger prevents library DEBUG handshake dumps.
        self._ws_log = logging.Logger("upbit-shadow-transport")
        self._ws_log.disabled = True
        self._ws_log.propagate = False

    def redact(self, text):
        text = str(text)
        for value in (self._token, self.key, self.secret):
            if value:
                text = text.replace(value, "[REDACTED]")
                text = text.replace(json.dumps(value)[1:-1], "[REDACTED]")
        return redact_jwts(text)

    def scrub(self, text):
        return base.scrub(self.redact(text))

    def clean(self, rec):
        # Sanitize every string, including echoed titles, field names and errors.
        # Preserve legitimate notice URL queries (id is needed for later joins).
        def clean(value):
            if isinstance(value, str):
                return self.redact(value)
            if isinstance(value, dict):
                return {self.redact(k): clean(v) for k, v in value.items()}
            if isinstance(value, list):
                return [clean(v) for v in value]
            return value
        return clean(rec)

    def write(self, rec):
        super().write(self.clean(rec))

    def _append(self, line):
        """Harden the inherited writer's append: regular private files, no links.

        Single writer, private parent directory (systemd StateDirectory=0700).
        Rotation uses the inherited 20 MiB cap and one .1 backup.
        Encoding (never fails) and the write itself (whole row, on a line of
        its own even after a torn one) are the inherited _encode / _write_all;
        the latter reads the last byte of the file, hence O_RDWR.
        """
        try:
            data = self._encode(line)
            flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
            fd = os.open(self.out_path, flags, 0o600)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise OSError("not a private regular file")
                os.fchmod(fd, 0o600)
                if info.st_size and info.st_size + len(data) > base.MAX_FILE_BYTES:
                    os.replace(self.out_path, self.out_path + ".1")
                    os.close(fd)
                    fd = -1
                    fd = os.open(self.out_path, flags | os.O_EXCL, 0o600)
                self._write_all(fd, data)
            finally:
                if fd >= 0:
                    os.close(fd)
        except OSError as exc:
            # The inherited writer logs this error. Its text must not carry the path (or anything else of the
            # original text) - but WHICH error it was is what tells a full disk from a permission problem, so the
            # errno stays: "PermissionError: [Errno 13] secure log append failed (EACCES)".
            if isinstance(exc.errno, int):
                name = errno.errorcode.get(exc.errno, "errno %d" % exc.errno)
                raise OSError(exc.errno, "secure log append failed (%s)" % name) from None
            own = exc.args[0] if exc.args and exc.args[0] in _OWN_ERRORS else "no errno"
            raise OSError("secure log append failed (%s)" % own) from None

    def run_once(self):
        self._token = jwt_token(self.key, self.secret)  # fresh nonce per attempt
        try:
            with self._connect(WS_URL, additional_headers={"Authorization": "Bearer " + self._token},
                               ping_interval=None, open_timeout=10, close_timeout=3,
                               proxy=None, logger=self._ws_log) as ws:
                ws.send(subscription(self.categories))
                self.write(dict(k="conn", event="open", categories=self.categories))
                opened = last_ping = self.mono()
                pong = None
                n = other = 0
                while not self.stop.is_set():
                    now = self.mono()
                    if now - opened >= RECONNECT_S:
                        self.write(dict(k="conn", event="planned_reconnect", pushes=n, other=other))
                        return
                    if now - last_ping >= PING_S:
                        if pong is not None and not pong.is_set():
                            raise ConnectionError("no pong for the previous ping")
                        pong = ws.ping(b"")
                        last_ping = now
                    try:
                        raw = ws.recv(timeout=1.0)
                    except TimeoutError:
                        continue
                    recv_ms = self.clock() * 1000  # stamp before decoding/offset/scrub
                    off, age, rtt = self._correction(recv_ms / 1000, self.mono())  # valid for THIS stamp's clocks?
                    msg = decode(raw)
                    if msg is not None and "error" in msg:
                        error = msg["error"]
                        # redact, THEN cut (a secret cut in half would no longer be recognised)
                        self.write(dict(k="upbit_error", recv_ms=recv_ms, error=base.short(self.clean(error))))
                        raise StreamError(isinstance(error, dict) and error.get("name") == "INVALID_AUTH")
                    rec = parse_push(self.clean(msg), recv_ms, off, age, rtt) if msg is not None else None
                    if rec is None:
                        other += 1
                        if other <= base.MAX_OTHER_PER_CONN:
                            self.write(dict(k="other", recv_ms=recv_ms, raw=self.scrub(raw)))
                    else:
                        n += 1
                        self.write(rec)
                        self.clock_wake.set()  # measure the clock again now: was this row's offset still true?
        except StreamError:
            raise
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None:
                raise base.Rejected(status) from None
            # No raw library exception (possibly with headers) escapes the boundary.
            raise ConnectionError(self.scrub(repr(exc))) from None

    def run(self):
        writer, clock = self._start_workers("upbit-ann")
        backoff, reject_wait = 2.0, 600.0
        try:
            while not self.stop.is_set():
                started = self.mono()
                rejected = False
                try:
                    self.run_once()
                except (StreamError, base.Rejected) as exc:
                    rejected = (exc.status in (401, 403, 418, 429)
                                if isinstance(exc, base.Rejected) else exc.auth)
                    self.write(dict(k="conn", event="rejected" if rejected else "error",
                                    status=getattr(exc, "status", None), detail=self.scrub(exc)))
                except Exception as exc:
                    self.write(dict(k="conn", event="error", detail=self.scrub(repr(exc))))
                if rejected:
                    wait = reject_wait
                    reject_wait = min(reject_wait * 2, 3600.0)
                else:
                    # Only a sustained healthy session resets authentication rejection history.
                    if self.mono() - started > 60:
                        backoff, reject_wait = 2.0, 600.0
                    wait = backoff
                    backoff = min(backoff * 2, 60.0)
                # All paths wait >=2s: <=1 attempt/2s, comfortably under 5/s.
                if not self.stop.is_set():
                    self.write(dict(k="conn", event="backoff", seconds=wait))
                    self.stop.wait(wait)
        finally:
            self._shutdown(writer, clock)  # inherited: "stopped" row last, and the writer empties the queue again


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--categories", help="comma-separated categories; omitted means all")
    a = ap.parse_args(argv)
    categories = None if a.categories is None else [c.strip() for c in a.categories.split(",")]
    try:
        subscription(categories)
    except ValueError:
        ap.error("unsupported categories; use: " + ",".join(CATEGORIES))
    key, secret = os.environ.get("UPBIT_ACCESS_KEY"), os.environ.get("UPBIT_SECRET_KEY")
    if not key or not secret:
        ap.error("UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY are required")
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sh = UpbitShadow(key, secret, a.out, categories=categories,
                     connect=base._connect_no_redirect(), http_get=base._http_get)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sh.stop.set())
    try:
        sh.run()
    except Exception as exc:
        logging.getLogger(__name__).error("shadow stopped: %s", sh.scrub(repr(exc)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
