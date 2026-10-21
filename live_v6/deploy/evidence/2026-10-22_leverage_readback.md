# 2026-10-22 01:39:18 KST — BNBUSDT "레버리지 10x 설정 실패 — 진입 건너뜀 | read-back 20x" (live, 2eb429b)

- Journal (live_v6-live, PID 51227, NRestarts 0): 16:39:18.793 UTC `skip BNBUSDT leverage: set 10x failed: read-back 20x` + 🚨.
- Path (engine.enter): positions() [/fapi/v2/positionRisk] showed 20x → POST /fapi/v1/leverage 10 returned 2xx (no
  exception; body discarded by 2eb429b) → positions() again [/fapi/v2/positionRisk] still 20x → skip + 🚨.
- Read-only check 01:52 KST (GET only): /fapi/v1/symbolConfig BNBUSDT leverage 10, /fapi/v2/positionRisk BNBUSDT 10.
  The set DID apply; the immediate positionRisk read lagged it. BNB was at the 20x account default (never set before).
- No ACCOUNT_CONFIG_UPDATE evidence exists: the mainnet user stream subscribes only to USER_EVENTS (stream.py), which
  does not include ACCOUNT_CONFIG_UPDATE, and parse_user drops unknown events.
- Fix (this branch): set_leverage returns the leverage echoed in the response; if positionRisk still disagrees AND the
  response echoed the requested value, confirm on GET /fapi/v1/symbolConfig. Real mismatch → same skip + 🚨 (detail
  now includes symbolConfig and the set response). No other behaviour change.
