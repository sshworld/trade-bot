"""Compare the bundle's upcoming macro triggers with the publishers' monthly calendars.

python -m live_v6.tools.calendar_watch --db /path/calendar.sqlite3 [--month 2026-12]
The original schedule is only read. --candidate writes a reviewable CSV on complete coverage.
Each observation retains the original page (deduplicated), its URL, local receipt time and errors.
"""
import argparse
import calendar
import csv
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from live_v6.strategies.bundle_v5_signals import load_macro_schedule

EAST = ZoneInfo("America/New_York")
UTC = timezone.utc
DEFAULT_SCHEDULE = Path(__file__).resolve().parents[1] / "deploy/bundle_macro_schedule.csv"
# Policy strategy discussion; the Fed explicitly excludes the usual decision at this meeting.
STRATEGY_ONLY = {date(2027, 10, 27): "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261112a.htm"}


class CalendarPage(HTMLParser):
    """Read BLS table rows and Fed's three-column calendar, ignoring navigation."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.headings = []
        self.heading = None
        self.table_row = None
        self.cell = None
        self.depth = 0
        self.column = None
        self.fed_row = []
        self.meeting_titles = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "title"):
            self.heading = []
        if tag == "tr":
            self.table_row = []
        if tag in ("td", "th") and self.table_row is not None:
            self.cell = []
        if tag == "div":
            self.depth += 1
            css = dict(attrs).get("class", "").split()
            for size in ("xs", "sm", "md", "lg"):
                width = next((n for n in ("2", "7", "3") if f"col-{size}-{n}" in css), None)
                if width:
                    self.column = (self.depth, width, [])
                    break

    def handle_data(self, data):
        if re.fullmatch(r"FOMC Meeting(?:\s+Two-day meeting.*)?", data.strip(), re.I):
            self.meeting_titles += 1
        for target in (self.cell, self.heading, self.column[2] if self.column else None):
            if target is not None:
                target.append(data)

    def handle_endtag(self, tag):
        def joined(parts):
            return " ".join(" ".join(parts).split())
        if tag in ("h1", "h2", "h3", "h4", "title") and self.heading is not None:
            self.headings.append(joined(self.heading))
            self.heading = None
        if tag in ("td", "th") and self.table_row is not None and self.cell is not None:
            self.table_row.append(joined(self.cell))
            self.cell = None
        if tag == "tr" and self.table_row is not None:
            self.rows.append(self.table_row)
            self.table_row = None
        if tag == "div":
            if self.column and self.column[0] == self.depth:
                _, role, values = self.column
                if role == "2":
                    self.fed_row = [joined(values)]
                elif role == "7" and len(self.fed_row) == 1:
                    self.fed_row.append(joined(values))
                elif role == "3" and len(self.fed_row) == 2:
                    self.rows.append([*self.fed_row, joined(values)])
                    self.fed_row = []
                self.column = None
            self.depth = max(0, self.depth - 1)


def source_url(source, month):
    if source == "BLS":
        return f"https://www.bls.gov/schedule/{month:%Y/%m}_sched_list.htm"
    return f"https://www.federalreserve.gov/newsevents/{month.year}-{calendar.month_name[month.month].lower()}.htm"


def read_page(url):
    req = Request(url, headers={"User-Agent": "tradebot-calendar-research/1.0", "Accept": "text/html"})
    with urlopen(req, timeout=12) as response:
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("calendar page exceeds 2 MB")
        return data


def release_time(day, time_text):
    clock = datetime.strptime(time_text.upper().replace(".", "").strip(), "%I:%M %p").time()
    return datetime.combine(day, clock, EAST).astimezone(UTC)


def parse_page(source, month, raw):
    page = CalendarPage()
    page.feed(raw.decode("utf-8-sig"))
    page.close()
    label = f"{calendar.month_name[month.month]} {month.year}"
    if not any(label.lower() in h.lower() for h in page.headings):
        raise ValueError(f"wrong or missing calendar heading for {label}")
    rows = []
    meeting_rows = 0
    for cells in page.rows:
        if len(cells) != 3:
            continue
        if source == "BLS":
            day_text, time_text, title = cells
            if title.startswith("Employment Situation for "):
                kind = "NFP"
            elif title.startswith("Consumer Price Index for "):
                kind = "CPI"
            else:
                continue
            day = datetime.strptime(day_text.strip(), "%A, %B %d, %Y").date()
        else:
            time_text, title, day_text = cells
            if not re.match(r"^FOMC Meeting(?:$|\s)", title):
                continue
            meeting_rows += 1
            kind = "FOMC"
            day = month.replace(day=int(day_text))
            if "strateg" in title.lower() or day in STRATEGY_ONLY:
                continue
        if (day.year, day.month) != (month.year, month.month):
            raise ValueError(f"release date outside {month:%Y-%m}: {day}")
        rows.append((kind, release_time(day, time_text)))
    if source == "BLS" and {kind for kind, _ in rows} != {"CPI", "NFP"}:
        raise ValueError("monthly BLS calendar lacks a scheduled CPI or national employment release")
    if source == "Fed" and ("Statistical Releases" not in page.headings or not page.rows
                             or meeting_rows < page.meeting_titles):
        raise ValueError("unrecognized Fed monthly calendar")
    if len(rows) != len(set(rows)):
        raise ValueError("duplicate release in source")
    return sorted(rows)


def observe(db, month, source, schedule, fetch=read_page, clock=lambda: datetime.now(UTC)):
    url = source_url(source, month)
    raw = None
    digest = None
    try:
        raw = fetch(url)
        digest = sha256(raw).hexdigest()
        official = parse_page(source, month, raw)
        error = None
    except (OSError, UnicodeError, ValueError) as exc:
        error = str(exc)
        official = []
    seen = clock().astimezone(UTC)
    def included(row):
        return row[1] >= seen and row[1].astimezone(EAST).strftime("%Y-%m") == month.strftime("%Y-%m")
    old = {r for r in schedule if included(r) and r[0] in (("CPI", "NFP") if source == "BLS" else ("FOMC",))}
    new = {r for r in official if included(r)}
    if not error and source == "Fed" and not new and any(t.astimezone(EAST).date() not in STRATEGY_ONLY for _, t in old):
        error = "previously scheduled Fed decision missing; verify the publisher's cancellation or revised date"
    def public(rows):
        return [[k, t.isoformat()] for k, t in sorted(rows, key=lambda item: (item[1], item[0]))]
    state = "unavailable" if error else "changed" if old != new else "matched"
    record = dict(source=source, url=url, month=month.strftime("%Y-%m"), received_at=seen.isoformat(),
                  status=state, sha256=digest, releases=public(new) if not error else None,
                  add=public(new-old) if not error else None, remove=public(old-new) if not error else None,
                  error=error)
    with db:
        if raw is not None:
            db.execute("INSERT OR IGNORE INTO pages VALUES (?,?)", (digest, raw))
        db.execute("INSERT INTO observations (result) VALUES (?)", (json.dumps(record, ensure_ascii=False),))
    return record


def write_candidate(path, records, schedule):
    """Merge reviewed months' future differences; preserve unrelated, historical and custom ids."""
    revised = dict(schedule)
    for rec in records:
        if rec["status"] == "unavailable":
            raise ValueError("candidate withheld due to unavailable source")
        for kind, stamp in rec["remove"]:
            revised.pop((kind, datetime.fromisoformat(stamp)), None)
        for kind, stamp in rec["add"]:
            dt = datetime.fromisoformat(stamp)
            revised.setdefault((kind, dt), f"{kind}_{dt.astimezone(EAST).date()}")
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, newline="", encoding="utf-8") as f:
        tmp = f.name
        try:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(("kind", "event_utc", "event_id"))
            for (kind, dt), eid in sorted(revised.items(), key=lambda item: (item[0][1], item[0][0])):
                writer.writerow((kind, dt.strftime("%Y-%m-%dT%H:%M:%SZ"), eid))
            f.flush()
            os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            Path(tmp).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE)
    parser.add_argument("--month", action="append", help="YYYY-MM, repeatable; default this and next month")
    parser.add_argument("--candidate", type=Path, help="new CSV for review; withheld if any source fails")
    args = parser.parse_args(argv)
    try:
        start = datetime.now(EAST).date().replace(day=1)
        months = [datetime.strptime(m, "%Y-%m").date() for m in args.month] if args.month else [
            start, (start + timedelta(days=32)).replace(day=1)]
        paths = [p.resolve() for p in (args.db, args.schedule, args.candidate) if p]
        if len(set(paths)) != len(paths):
            raise ValueError("database, input schedule and candidate must be different paths")
        schedule = {(kind, datetime.fromtimestamp(minute * 60, UTC)): eid
                    for minute, kind, eid in load_macro_schedule(args.schedule)}
        db = sqlite3.connect(args.db)
        try:
            db.executescript("CREATE TABLE IF NOT EXISTS pages (sha256 TEXT PRIMARY KEY, raw BLOB NOT NULL);"
                             "CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, result TEXT NOT NULL);")
            records = [observe(db, month, source, schedule) for month in dict.fromkeys(months) for source in ("BLS", "Fed")]
            print(json.dumps(records, ensure_ascii=False, indent=2))
            if any(r["status"] == "unavailable" for r in records):
                return 2
            if args.candidate:
                write_candidate(args.candidate, records, schedule)
            return int(any(r["status"] == "changed" for r in records))
        finally:
            db.close()
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"calendar check failed: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
