# Trade Bot — Claude 작업 가이드

## 프로젝트 개요
Binance BTC/USDT 선물 자동 매매 시스템. 모의투자(paper trading) → 실거래 전환 예정.

## 기술 스택
- Backend: Python FastAPI, pandas, ta, binance-connector
- Frontend: Next.js 16, React, TypeScript, TailwindCSS, lightweight-charts
- Data: 인메모리 KlineStore (시작 시 로드 + WebSocket 실시간 갱신, REST API 호출 0)
- Infra: uv (Python), pnpm (Node.js)

## 핵심 원칙

### 1. 의사결정 프로세스
**트레이딩 파라미터(TP/SL/레버리지/포지션사이즈/진입조건 등) 변경 시 반드시:**
1. Warren Buffett + Jamie Dimon 페르소나로 토론 에이전트 실행
2. 토론 결과를 `docs/meeting-minutes/` 에 회의록 저장
3. 사용자에게 결과 보고
4. 승인 후 구현

**절대 임의로 파라미터를 변경하지 않는다.**

### 2. 수동 개입 없음
모든 매매는 100% 프로그램 자동. 수동 확인/승인 UI 없음.

### 3. 능동적 업무
- 이슈 발견 → 전문가 토론 → 결론 → 구현까지 한 흐름으로
- 회의록 작성, 메모리 업데이트 등 부수 작업도 알아서

## 현재 확정 파라미터 (2026-04-08 회의록 기준)

### 계좌/리스크
| 파라미터 | 값 |
|---------|-----|
| 시작 자본 | $1,000 |
| 레버리지 | 3-5x |
| 동시 포지션 | 1개 |
| 거래당 리스크 | 자본의 2% |
| 일일 손실 Tier1 | -3% → 사이즈 절반 |
| 일일 손실 Tier2 | -5% → 당일 거래 중단 |
| 일일 손실 Tier3 | -8% → 48시간 중단 |
| 연속 SL 쿨다운 | 같은 방향 2연속 SL → 30분 차단 |
| 일일 최대 거래 | 5회 |

### TP/SL — WITH_TREND (마진 기준 %)
| TF | TP1 | TP2 | TP3 | SL | Split |
|---|---|---|---|---|---|
| 30m | +5% | +10% | +18% | -3.5% | 50/30/20 |
| 1h | +7% | +14% | +25% | -5% | 50/30/20 |
| 4h | +10% | +20% | +35% | -7% | 50/30/20 |

### TP/SL — COUNTER_TREND & CONSENSUS
| TF | TP1 | TP2 | TP3 | SL | Split |
|---|---|---|---|---|---|
| 30m | +3.5% | +7% | +12% | -3% | 50/30/20 |
| 1h | +5% | +10% | +18% | -4% | 50/30/20 |
| 4h | +7% | +14% | +25% | -5.5% | 50/30/20 |

### 트레일링 SL
- TP1 체결 → SL을 진입가(본전)로
- TP2 체결 → SL을 TP1 가격으로

### ATR 가드레일 (SL만)
- ATR(14) 기준
- SL < 1.5×ATR → 1.5×ATR로 확대
- SL > 4.0×ATR → 4.0×ATR로 축소

### 포지션 교체 (반대 시그널)
- 미실현 PnL < 현재 TP1 → 교체 (청산 + 반대 진입)
- 미실현 PnL ≥ TP1 → 무시
- 쿨다운 30분, 일일 3회 상한

### 같은 방향 시그널
- PnL < 0%: 무시
- PnL 0~3%: SL을 본전으로
- PnL ≥ 3%: SL을 미실현 수익 50% 잠금

### 진입 TF
- 30m, 1h, 4h: 진입 가능
- 15m: 분석/UI 표시만 (진입 불가)
- 1d, 1w: 추세 필터만

### 시그널 시스템
- 7개 지표 (RSI, MACD, BB, MA, Fibonacci, Elliott, VP)
- Registry 패턴 (확장 가능)
- Confluence 합류 (TF별 임계값)
- Strong trigger 필수 (weight ≥ 1.5)
- Lagging state 할인 (MA_align, EMA_pos → 반대 방향 시 30%로 할인)
- 3-tier 분류: WITH_TREND / COUNTER_TREND / BLOCKED + CONSENSUS

### 데이터 아키텍처
- 시작 시 8개 TF × 500 캔들 REST 로드 → KlineStore
- 이후 WebSocket kline 스트림으로 실시간 갱신 (REST 0회)
- 1초마다 전체 TF 시그널 스캔 (로컬 데이터)
- 캔들 종가 확정 시 즉시 재분석

## 디렉토리 구조 (핵심)
```
backend/app/
  analysis/signals.py      — 시그널 생성 (Registry + Confluence)
  analysis/trend_filter.py — WITH/COUNTER/BLOCKED 분류
  trading/engine.py        — 매매 엔진 (포지션/체결/PnL)
  trading/schemas.py       — 데이터 모델 + 설정값
  binance/kline_store.py   — 인메모리 캔들 스토어
  binance/ws_consumer.py   — WebSocket 수신 + tick 처리
  tasks/scheduler.py       — 1초 스캔 + 캔들 종가 트리거

frontend/src/
  app/dashboard/page.tsx   — 차트 + 시그널 트리
  app/trading/page.tsx     — 포지션 + 거래내역
  components/indicators/TFSignalPanel.tsx — 시그널 파이프라인 UI

docs/meeting-minutes/      — 전문가 토론 회의록
```

## 주의사항
- 데이터 reset 하지 말 것 (거래 기록 보존)
- mainnet 사용 중 (testnet 아님)
- 수수료 추적 중 (maker 0.02%, taker 0.04%)
- front에서 internal server error 발생 시 backend 재시작 확인
- pnpm dev는 frontend/ 디렉토리에서, uvicorn은 backend/ 디렉토리에서 실행
