from datetime import date, datetime, timezone
import json
import sqlite3

import pytest

from live_v6.tools import calendar_watch as watch


def bls(month, *rows):
    return (f"<h1>{month}</h1><table>" + "".join(
        "<tr>" + "".join(f"<td><p>{s}</p></td>" for s in row) + "</tr>" for row in rows) + "</table>").encode()


def fed(month, *events):
    html = f"<h4>{month}</h4><h4>Statistical Releases</h4>"
    for event in events:
        html += "<div>" + "".join(f'<div class="col-xs-{n}"><p>{v}</p></div>'
                                   for n, v in zip((2, 7, 3), event)) + "</div>"
    return html.encode()


def test_calendar_distinguishes_the_release_and_zone():
    dec = date(2026, 12, 1)
    raw = bls("December 2026",
              ("Friday, December 04, 2026", "08:30 AM", "Employment Situation for November 2026"),
              ("Thursday, December 10, 2026", "08:30 AM", "Consumer Price Index for November 2026"),
              ("Friday, December 18, 2026", "10:00 AM", "State Employment and Unemployment for November 2026"))
    assert [(k, t.isoformat()) for k, t in watch.parse_page("BLS", dec, raw)] == [
        ("CPI", "2026-12-10T13:30:00+00:00"), ("NFP", "2026-12-04T13:30:00+00:00")]
    assert watch.release_time(date(2027, 6, 1), "8:30 a.m.").hour == 12
    with pytest.raises(ValueError, match="heading"):
        watch.parse_page("BLS", date(2026, 11, 1), raw)
    with pytest.raises(ValueError, match="lacks"):
        watch.parse_page("BLS", dec, bls("December 2026"))


def test_fed_rejects_minutes_press_conference_and_strategy_only():
    raw = fed("December 2026", ("2:30 p.m.", "FOMC Press Conference", "9"),
              ("2:00 p.m.", "FOMC Minutes", "30"), ("2:00 p.m.", "FOMC Meeting Two-day meeting", "9"))
    assert watch.parse_page("Fed", date(2026, 12, 1), raw) == [
        ("FOMC", datetime(2026, 12, 9, 19, tzinfo=timezone.utc))]
    assert watch.parse_page("Fed", date(2026, 12, 1), raw.replace(b"col-xs-7", b"col-sm-7")) == [
        ("FOMC", datetime(2026, 12, 9, 19, tzinfo=timezone.utc))]
    with pytest.raises(ValueError, match="unrecognized"):
        watch.parse_page("Fed", date(2026, 12, 1), raw.replace(b"col-xs-7", b"new-calendar-title"))
    assert watch.parse_page("Fed", date(2027, 10, 1),
                            fed("October 2027", ("2:00 p.m.", "FOMC Meeting", "27"))) == []


def test_cli_preserves_input_and_withholds_candidate_on_fetch_failure(tmp_path, monkeypatch, capsys):
    # Use frozen receipt dates so the same future changes apply whenever the test runs.
    real_observe = watch.observe
    received = datetime(2026, 11, 24, tzinfo=timezone.utc)
    raw = {"BLS": bls("December 2026",
                      ("Friday, December 04, 2026", "08:30 AM", "Employment Situation for November 2026"),
                      ("Thursday, December 10, 2026", "08:30 AM", "Consumer Price Index for November 2026")),
           "Fed": fed("December 2026", ("2:00 p.m.", "FOMC Meeting", "9"))}
    def observe(db, month, source, schedule):
        def fetch(_):
            if raw[source] is None:
                raise OSError("unavailable")
            return raw[source]
        return real_observe(db, month, source, schedule, fetch, lambda: received)
    monkeypatch.setattr(watch, "observe", observe)
    path, db, candidate = (tmp_path / n for n in ("schedule.csv", "calendar.sqlite3", "candidate.csv"))
    original = "kind,event_utc,event_id\nCPI,2026-12-11T13:30:00Z,old\nNFP,2026-11-06T13:30:00Z,stable\n"
    path.write_text(original)
    args = ["--month", "2026-12", "--db", str(db), "--schedule", str(path), "--candidate", str(candidate)]
    assert watch.main(args) == 1
    assert [r["status"] for r in json.loads(capsys.readouterr().out)] == ["changed", "changed"]
    reviewed = candidate.read_text()
    assert "CPI,2026-12-10" in reviewed and "2026-12-11" not in reviewed and ",stable" in reviewed
    raw["BLS"] = None
    assert watch.main(args) == 2
    report = json.loads(capsys.readouterr().out)
    assert report[0]["status"] == "unavailable" and report[0]["remove"] is None
    assert candidate.read_text() == reviewed and path.read_text() == original
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 4
