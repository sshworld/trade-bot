# 회의록 — SL 신뢰성 / 고아주문 / 분할TP SL / 수수료·회계 정비

- **일자**: 2026-06-04
- **참석**: Warren Buffett (리스크/자본보존), Jamie Dimon (실행/수익)
- **배경**: 실거래 봇 약 $40 손실 (서버 끊김 추정 + SL 미발화). 손실 사후 + `live_engine.py`/`engine.py` 전반 적대 audit 결과 5개 안건 토론.
- **트리거**: 사용자 `/plan-dev` → `/trade-review` 우선 진행 결정.

## 적대 audit 핵심 발견 (근거)

| ID | 심각도 | 위치 | 증상 |
|----|--------|------|------|
| A | CRITICAL | live_engine.py:964 | SL 배치 실패가 `except: log`로 삼켜짐 → 무방비 포지션 |
| A | CRITICAL | live_engine.py:942-949 | cancel→place 순서 + `remaining<=0` early-return으로 SL 없는 윈도우 |
| A | HIGH | live_engine.py:116-123 | initialize: open_positions 비면 SL 재배치 전체 skip |
| B | CRITICAL | live_engine.py:799-826 | 닫힘 경로 (b)(c) pos-scoped cancel만 → TP algo 고아 |
| C | HIGH | live_engine.py:452 | `account.total_fees += position.total_fees` 이중 누적 버그 |
| C | HIGH | engine.py:473-480 | Live가 Paper balance/daily_pnl 로컬 가감 상속 → 이중 회계 |
| D | HIGH | engine.py:641-642 | TP1 체결(+0.6%)→SL=breakeven(+0.016%), 체결가보다 0.58% 아래 |
| D | HIGH | engine.py:688-690 | 동적 트레일 가드 바닥이 min(체결)=TP1까지만 |
| E | CRITICAL | live_engine.py:799-846 | position-gone 감지가 reconcile 루프 끝 → 앞 예외 시 phantom |
| E | HIGH | live_engine.py:666 | get_order/get_algo_order None → tranche 영원히 WAITING |

## 안건별 결론

### 안건 1 — SL 배치 신뢰성 (CRITICAL)
- **place → confirm algoId → cancel old** 순서로 변경 (place-before-cancel)
- SL 배치 후 algoId 확인 **의무화**, 실패 시 **3회 재시도 (0.5s 백오프)**
- 전부 실패 → **즉시 시장가 청산 + HALT + 텔레그램 CRITICAL 경고**
- reconcile(5s) + initialize: Binance positionAmt≠0 인데 live STOP algo 부재 시 → 1회 재무장, 실패 시 청산+halt
- Binance `-2021 (would immediately trigger)` → SL 이미 돌파로 간주 → 즉시 청산(stop_loss)
- SL 취소 후 재배치 없는 early-return 금지 (remaining<=0이면 취소도 보류)

### 안건 2 — 고아 주문 제거 (CRITICAL)
- 모든 닫힘 경로 (a)(b)(c)(d-후속) → `_nuke_all_binance_orders` 단일 경로 통일
- `_nuke_all_binance_orders` 강화:
  - raw httpx → `binance_client._retry_request` 경유 (재시도/레이트리밋 적용)
  - 취소 후 openAlgoOrders + allOpenOrders **read-back 검증**, 비워질 때까지 3회 재시도
  - 잔존 포지션(positionAmt≠0) 시장가 청산 (기존 STEP3 로직 흡수)
  - 3회 후에도 더러우면 HALT + 텔레그램 alert
- on_signal: 첫 tranche 발행 전 clean book(포지션 0, 주문 0) 검증 → 더러우면 nuke 선행

### 안건 3 — 분할 TP 후 SL 위치 (전략 변경)
- **확정 파라미터: `tp_sl_buffer_ratio = 0.30`**
- 공식 (LONG): `SL = best_filled_TP - (best_filled_TP - avg_entry) × 0.30`
- 공식 (SHORT): `SL = best_filled_TP + (avg_entry - best_filled_TP) × 0.30` (부호 대칭)
- 효과: TP1 체결 → SL ≈ entry **+0.42%** (본전 위 확실), TP2 체결 → SL ≈ entry **+0.84%** (TP1 위)
- 동적 트레일 가드 바닥: `max(체결 TP) × (1-buffer)` 로 상향 (engine.py:690 LONG, :706 SHORT)
- breakeven은 하한 유지: `SL = max(breakeven, tp_floor)` (LONG) / `min(...)` (SHORT)
- **근거**: Buffett "이긴 거래를 지는 거래로 만들지 마라" + Dimon 휩쏘 방지 절충 (0.25 타이트 ↔ 0.40 여유 → 0.30)

### 안건 4 — 수수료 개념 제거 (전략/표시)
- `AccountState.total_fees` 누적 **제거** (engine.py:300,302,336,338,370,372,472,474 + live_engine.py:413,414,452,677,751 의 += 사이트)
- `TradeRecord.total_fees` (거래별 실제 체결 fee) **보존** — audit trail
- `/status` 텔레그램 수수료 집계 줄 **제거** (telegram_bot.py:152,222)
- `_breakeven_price`는 `settings.fee_taker_pct`만 사용 → 영향 없음, 그대로 유지
- `save_daily_snapshot`/`get_status`의 total_fees 인자 → 0 또는 trade_history 합산으로 대체
- anomaly check_post_trade(daily_fees=) 인자 정리 (fee_bleeding은 이미 비활성)

### 안건 5 — 회계 일원화 (전략)
- **Live 전용 `_close_position` 오버라이드** 신설: 로컬 balance/fee 가감 금지, 실잔고만 반영
- 실현 PnL = (실제 청산가 - 평단) 기반 (balance-delta-vs-mutated-field 금지)
- `daily_start_balance` = 실잔고 스냅샷 (live는 `+ margin_used` 제거; engine.py:553,542)
- daily_pnl = 실잔고 기반 도출

### 보너스 (audit E — 안정성, 안건 외 합의)
- reconcile: position-gone/balance-sync 블록을 **독립 try**로 분리해 per-tranche 예외와 무관하게 항상 실행
- `on_price_update`/`reconcile_orders`에 `_initialized` 가드 추가, initialize 변이 구간 lock 보호
- `get_order`/`get_algo_order`: transient(5xx/-1021) vs terminal(4xx unknown) 구분, 연속 miss N회 시 alert
- heartbeat no-op(anomaly_detector.py:260) → 경량 stale-price **경고**(중단 아님) 재활성

## 확정 파라미터 요약

| 항목 | 값 |
|------|-----|
| SL 배치 재시도 | 3회 / 0.5s 백오프 |
| SL 배치 실패 시 | 즉시 시장가 청산 + HALT + 알림 |
| SL 순서 | place → confirm → cancel old |
| 닫힘 경로 정리 | 전부 `_nuke_all_binance_orders` + read-back 3회 |
| `tp_sl_buffer_ratio` | 0.30 |
| TP1 후 SL | entry +0.42% (체결 TP 위) |
| TP2 후 SL | entry +0.84% (TP1 위) |
| `account.total_fees` | 제거 (per-trade는 보존) |
| daily_pnl / balance | 실잔고 기반 일원화 |

## 다음 단계
사용자 승인 → `/plan-dev` 구현 (vertical slice). 서버 재시작은 구현·검증 완료 후 사용자 명시 승인 1회.
