# macro_events.csv: v10.1 re-creation (2026-10-21 KST, after box /workspace loss)

Columns (same as before): `ts_utc` (YYYY-MM-DD HH:MM, UTC), `type` (CPI / NFP / FOMC), `local_time` (ET), `source_url`, `note`.
Coverage: releases dated 2021-01-01..2026-09-30. **182 rows: CPI 68, NFP 68, FOMC 46.** That is the same count by type, and the same first row (2021-01-08 13:30 NFP) and last row (2026-09-16 18:00 FOMC), as the lost file.

## How it was built
- **CPI:** release dates taken from the BLS CPI archived news releases page. Each archived PDF is named `cpi_MMDDYYYY.pdf` = release date. https://www.bls.gov/bls/news-release/cpi.htm
- **NFP (Employment Situation):** same method, `empsit_MMDDYYYY.pdf`. https://www.bls.gov/bls/news-release/empsit.htm
- BLS release time: 08:30 ET for all rows. That is the BLS standard time for both releases, confirmed for the moved releases on the revised-dates page.
- **Shutdown-moved releases**, as officially rescheduled. Source: "Revised news release dates following the 2025 and 2026 lapses in appropriations", https://www.bls.gov/bls/2025-lapse-revised-release-dates.htm

  | Release | Previously scheduled | Moved to |
  |---|---|---|
  | Sep 2025 CPI | 2025-10-15 | **2025-10-24** |
  | Sep 2025 NFP | 2025-10-03 | **2025-11-20** |
  | Nov 2025 NFP | 2025-12-05 | **2025-12-16** |
  | Nov 2025 CPI | 2025-12-10 | **2025-12-18** |
  | Jan 2026 NFP | 2026-02-06 | **2026-02-11** |
  | Jan 2026 CPI | 2026-02-11 | **2026-02-13** |

  **Oct 2025 CPI and Oct 2025 Employment Situation were cancelled (not published) → no row.**
- **FOMC:** last day of each scheduled meeting, statement at 14:00 ET. Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm (2021–2027 panels). The 2025-08-22 notation vote is excluded (no meeting or statement). There were no unscheduled meetings in 2021-01..2026-09.
- ET → UTC with the IANA `America/New_York` zone (DST aware): CPI/NFP map to 12:30 or 13:30 UTC, FOMC to 18:00 or 19:00 UTC.
- Pages were fetched 2026-10-21 with curl (the BLS pages return 403 without browser headers).

## Integrity
- sha256 of this re-created CSV: see the report. It is **not** the old `fecbc016…c40ef9`. The old file used the BLS per-year schedule pages as `source_url` and different note text. Those cells cannot be reproduced byte-for-byte, so the hash differs. Event timestamps were rebuilt from official sources, and the counts by type match the old file, but the old file is gone, so a row-by-row comparison is not possible.
- H25 rev2 §1 cites the old sha. TA should record the new sha in the v10.1 lock.
