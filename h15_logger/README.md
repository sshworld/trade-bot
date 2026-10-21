# h15_logger — H15 liquidation logger (forward-only data)

Spec: `specs/trade-bot-strategy-spec-h15.md` (rules `quant/hypotheses_h15.md` §6, sha bc85913d…) + TA logger rules
(2026-10-21). Public data only, no API keys, separate process, separate unix user (`h15log`), separate unit
(`h15-logger.service`), lower priority than the live bot. NOT part of `live_v6`; shares no files with it.

## Output (`/var/lib/h15-logger`)
| file | content |
|---|---|
| `liq/YYYY-MM-DD.csv` (UTC; previous days `.csv.gz`) | `minute_ts_ms,symbol,ll_usd,sl_usd,n_ll,n_sl,max_single_usd,late` — 6 rows per **fully connected** minute, zeros included. Missing minute = gap. `ll` = `o.S=SELL` (long liquidated), notional `o.z × o.ap`. |
| `oi/YYYY-MM-DD.csv` | `poll_ts_ms,symbol,open_interest,exch_time_ms`, 6 rows every 5 min (+7 s). |
| `gaps.csv` | `kind,connect_ts_ms,disconnect_ts_ms,reason` — process_start / connect / disconnect (session) / process_stop. |
| `quality.csv` | `hour_start_ms,hour_end_ms,events,<6 coins>,valid_minutes,silence_warning,partial` — one row per UTC hour (TA collection-quality rule 2026-10-22): liquidation events **received** (by receive time, late ones included), per coin, fully-connected minutes written, whether a silence WARNING fired in that hour; first hour of a process and the hour of a clean stop are `partial=1`. An hour with no row = process down (SIGTERM/OOM kill writes nothing) → gap. Used as data-gap intervals for the H15 judgment. |
| `STOPPED` | written on a 429/418 or watchdog stop; while it exists the logger exits 75 at start (systemd does not restart 75). |

## Caps
* Memory: systemd `MemoryHigh=80M`, `MemoryMax=100M` (spec hard cap), `MemorySwapMax=0`, `OOMScoreAdjust=1000`
  (killed first); in-process RSS > 60 MB → exit 1 (a gap; systemd restarts after 60 s, max 6/h).
* CPU / IO: `Nice=19`, `CPUSchedulingPolicy=idle`, `CPUWeight=10`, `CPUQuota=25%`, `IOWeight=10`, `IOSchedulingClass=idle`.
* Disk: data dir ≤ 256 MB (expected ~40 MB/yr gzipped + ~30 MB/yr OI) and ≥ 2 GB free on the filesystem, else stop.
* IP weight: OI = 6 requests (weight 1 each) per 5 min ≈ 1.2/min = 0.05 % of 2400/min. A round is skipped whenever
  the IP's `X-MBX-USED-WEIGHT-1M` (shared with the bot) is ≥ 240 (10 %). 5xx → rest of the round skipped.
* 429 / 418 (REST or websocket handshake) → STOPPED marker + exit 75 (stays stopped; ops decide).

## Collection quality (TA rule 2026-10-22)
0 events received for 60 min (from process start or the last event) → `WARNING quality: 0 liquidation events received for 60 min …`
in the journal only (no Telegram), repeated every 60 min while the silence lasts; flagged in that hour's `quality.csv` row.
It does not stop the logger.

## Watchdog (every 30 s) — the bot comes first
Stops (marker + exit 75) if `live_v6-live` MainPID / NRestarts / ActiveState differ from the baseline taken at
logger start, if the bot is not active at logger start, if its state can't be read 3× in a row, or after 2
consecutive checks with MemAvailable < 150 MB, CPU PSI some avg60 > 40 %, memory PSI some avg60 > 5 %
(load5 > 3 only if PSI is unavailable). Consequence: a live deploy/restart also stops the logger — ops re-arm it:
`sudo rm /var/lib/h15-logger/STOPPED && sudo systemctl start h15-logger`.

## Ambiguities — conservative choice taken
1. **Stream:** TA rule text says `!forceOrder@arr`; the locked spec §6 says the combined 6-symbol `@forceOrder`
   stream, *not* `!forceOrder@arr`, to keep CPU low. Chosen: 6-symbol stream (locked spec wins; less CPU; same
   1 snapshot / symbol / s throttle). One websocket, liquidations only either way.
2. **OI polling:** spec says not required for H15; TA rules define it. Chosen: poll (TA rule) with the strictest
   budget (skip at 10 % IP weight, stop on 429/418); `--no-oi` disables it.
3. **Late messages:** "added to a late counter for that row, not re-written" — rows are never rewritten; a late
   message's notional is dropped and it is counted in `late` of that symbol's NEXT written row.
4. **Partially connected minutes:** not written (a minute is valid only if the socket was up for all of it).
5. **"Bot affected":** any change of the bot's PID/restart count/state counts (even a planned deploy).

## Run / test
```
python -m h15_logger run --data /var/lib/h15-logger [--bot-unit live_v6-live] [--no-oi]
python -m pytest h15_logger/tests -q          # offline, no network
```
