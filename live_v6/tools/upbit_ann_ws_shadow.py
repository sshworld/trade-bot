"""Read-only Upbit announcement receive-time logger; no trading operations.

Run as a module with --out PATH; UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY required.
Only network destinations: private announcement WebSocket and the inherited
public Binance futures clock. All categories by default; --categories trade,wallet
filters explicitly. Records retain CREATED and UPDATED separately, without dedup.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import hmac
import json
import logging
import math
import os
import re
import signal
import stat
import threading
import uuid

from . import ann_ws_shadow as base

WS_URL = "wss://api.upbit.com/websocket/v1/private"
CATEGORIES = ("notice", "trade", "wallet", "maintenance", "digital_asset", "nft", "service", "event")
PING_S = 30.0
RECONNECT_S = 23 * 3600.0
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_MARKETS = re.compile(r"(?<![A-Z0-9])(?:KRW|BTC|USDT|원화)(?:\s*[,/·]\s*(?:KRW|BTC|USDT|원화))*\s*마켓")


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
    # p109 designation only: release and mere caution aren't designations.
    t = re.sub(r"\s+", "", title)
    if "거래지원종료" in t:
        return "upbit_delist"
    if "유의종목지정" in t and not re.search(r"유의종목지정(?:해제|연장|취소)", t):
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


def parse_push(raw, recv_ms: float, offset_ms: float | None, offset_age_s=None):
    msg = raw if isinstance(raw, dict) else decode(raw)
    if msg is None or msg.get("type") != "announcement":
        return None
    title = str(msg.get("title") or "")
    rec = dict(k="upbit_ann", recv_ms=round(recv_ms, 1),
               offset_ms=offset_ms, offset_age_s=offset_age_s, title=title[:500],
               tag=classify_upbit_title(title), tickers=extract_tickers(title), keys=sorted(msg))
    for field in ("event_type", "uuid", "category", "url", "stream_type"):
        rec[field] = msg.get(field)
    for field in ("first_listed_at", "listed_at", "timestamp"):
        value = msg.get(field)
        ms = to_ms(value)
        rec[field] = value
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
        self._producers_done = threading.Event()
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
        return _JWT.sub("[REDACTED]", text)

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
        except OSError:
            # Inherited writer logs OSError; don't expose path/credential text.
            raise OSError("secure log append failed") from None

    def _writer_worker(self):
        # Reuse writer_loop; drain again after producers finish to close its
        # stop/empty race when SIGTERM arrives just before a final enqueue.
        super().writer_loop()
        self._producers_done.wait()
        super().writer_loop()

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
                    off, age = self._offset(recv_ms / 1000, self.mono())  # valid for THIS stamp's clocks?
                    msg = decode(raw)
                    if msg is not None and "error" in msg:
                        error = msg["error"]
                        self.write(dict(k="upbit_error", recv_ms=recv_ms, error=error))
                        raise StreamError(isinstance(error, dict) and error.get("name") == "INVALID_AUTH")
                    rec = parse_push(self.clean(msg), recv_ms, off, age) if msg is not None else None
                    if rec is None:
                        other += 1
                        if other <= base.MAX_OTHER_PER_CONN:
                            self.write(dict(k="other", recv_ms=recv_ms, raw=self.scrub(raw)))
                    else:
                        n += 1
                        self.write(rec)
        except StreamError:
            raise
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None:
                raise base.Rejected(status) from None
            # No raw library exception (possibly with headers) escapes the boundary.
            raise ConnectionError(self.scrub(repr(exc))) from None

    def run(self):
        writer = threading.Thread(target=self._writer_worker, name="upbit-ann-writer", daemon=True)
        clock = threading.Thread(target=self.clock_loop, name="upbit-ann-clock", daemon=True)
        writer.start()
        clock.start()
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
            self.stop.set()
            clock.join(timeout=6.0)
            self.write(dict(k="conn", event="stopped", dropped=self.dropped, write_failed=self.write_failed))
            self._producers_done.set()
            writer.join(timeout=2.0)


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
