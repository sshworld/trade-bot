# Trade Bot — Claude 작업 가이드

> 새 세션에서 이 파일을 먼저 읽고 작업 컨텍스트를 파악할 것.

## 프로젝트 개요
Binance BTC/USDT 선물 자동 매매 시스템.
현재: Paper trading (testnet) → 목표: 실거래 전환.

## 기술 스택
- **Backend**: Python FastAPI, pandas, ta, httpx, websockets
- **Frontend**: Next.js 16 (App Router), React, TypeScript, TailwindCSS, lightweight-charts
- **Data**: 인메모리 KlineStore (8 TF × 500 캔들, WebSocket 실시간 갱신, REST 호출 0)
- **DB**: SQLite (`backend/data/trading.db` — 거래기록, 포지션, 계좌, 일자별 스냅샷)
- **Infra**: uv (Python), pnpm (Node.js), Docker Compose (PostgreSQL 옵션)

## 핵심 원칙 (반드시 준수)

### 1. 의사결정 프로세스
**트레이딩 파라미터(TP/SL/레버리지/포지션사이즈/진입조건/리스크 등) 변경 시:**
1. Warren Buffett + Jamie Dimon 페르소나로 토론 에이전트 실행
2. 토론 결과를 `docs/meeting-minutes/` 에 회의록 저장
3. 사용자에게 결과 보고 후 승인 받고 구현

**절대 임의로 파라미터를 변경하지 않는다.**

### 2. 수동 개입 없음
모든 매매는 100% 프로그램 자동. 수동 확인/승인 UI 없음.
사용자는 24/7 모니터링하지 않음 → 이상 감지는 자동 + Telegram 알림.

### 3. 능동적 업무
- 이슈 발견 → 전문가 토론 → 결론 → 회의록 저장 → 구현까지 한 흐름
- "어떻게 할까요?" 물어보지 말고 전문가 토론 먼저 돌리고 결과 보고
- UX 디자인은 사용자에게 직접 확인 (Donald Norman 리뷰는 사용 안 함)

### 4. 데이터 보존
- 거래 기록 reset 절대 금지 (사용자가 명시적으로 요청한 경우만)
- 모든 데이터는 SQLite DB에 영속화 (서버 재시작 시 복원)

## 현재 상태 (2026-04-09 기준)

### 동작 중
- Binance testnet API 키 설정됨 (`.env`)
- 1초마다 6개 TF 시그널 스캔 (15m, 30m, 1h, 4h, 1d, 1w)
- Confluence 발생 시 자동 포지션 진입 (Paper Trading)
- 포지션/거래기록/계좌 SQLite 영속화

### 미완성 (TODO)
- [ ] Binance Futures testnet API 키 재발급 필요 (현재 Spot testnet 키라 401)
- [ ] LiveTradingEngine: 시뮬레이션 → 실제 Binance 주문 전환
- [ ] Telegram 알림 연동 (alert_sender.py 코드 있음, .env에 token 필요)

### 2026-04-10 변경사항 (적용 완료)
- ATR 기반 동적 TP/SL (고정% 제거)
- 지표 패밀리 중복 제거 (3+ 독립 패밀리 필수)
- 진입: 물타기→확인 추가 (0%, +0.3%, +0.6%)
- TP3: 무제한 트레일링 (TP2 이후 동적 trail)
- 시간 기반 청산 (2×평균→SL 조임, 4×평균→청산)
- 교체: 무제한, PnL < 0 + 시그널 강도 차이 0.5, 20분 쿨다운
- 일일 거래/교체 횟수 제한 제거
- 일일 손실 -3% 사이즈 절반, -5% 당일 중단 (48시간 제거)
- 속도 제한: 60분 3연속 SL → 30분 일시 중단
- MACD 히스토그램 weight 0.5→0.3

## 확정 파라미터 (Buffett×Dimon 회의록)

### 계좌/리스크
| 파라미터 | Paper | Real (전환 시) |
|---------|-------|---------------|
| 레버리지 | 3-5x | 3-5x |
| 동시 포지션 | 1개 | 1개 |
| 거래당 리스크 | balance × 2% | clamp(balance × 2%, $10, $100) |
| 일일 손실 | -3/-5/-8% | -2/-3/-5% |
| Circuit breaker | -50% | -20% |
| Peak drawdown | -10% | -7% |
| 일일 최대 거래 | 5회 | 5회 |

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
- TP1 체결 → SL을 본전(수수료 포함)으로
- TP2 체결 → SL을 TP1 가격으로
- SL보다 불리한 pending entry 자동 취소

### 포지션 교체 (반대 시그널)
- 미실현 PnL < TP1 → 교체 (청산 + 반대 진입)
- 미실현 PnL ≥ TP1 → 무시 (트레일링에 맡김)
- 쿨다운 30분, 일일 3회

### 같은 방향 시그널
- PnL < 1.5%: 무시
- PnL 1.5-3%: SL을 본전(수수료 포함)으로
- PnL ≥ 3%: 미실현 수익 50% 잠금

### 진입 TF
- 30m, 1h, 4h: 진입 가능
- 15m: 분석/UI만 (진입 불가)
- 1d, 1w: 추세 필터만

### 시그널 시스템
- 7개 지표 Registry 패턴 (INDICATOR_REGISTRY에 추가만 하면 확장)
- Confluence: TF별 임계값 + strong trigger(w≥1.5) 필수
- Lagging state 할인: MA_align, EMA_pos는 반대 방향 시 30%로 할인
- 3-tier: WITH_TREND / COUNTER_TREND / BLOCKED + CONSENSUS override

### Auto-Halt 규칙 (anomaly_detector.py)
| 규칙 | 조건 | 중단 |
|------|------|------|
| Rapid-Fire | 60초 내 6건+ | 1시간 |
| Flip-Flop | 2시간 내 방향전환 3회+ | 2시간 |
| Fee Bleeding | 5건 중 4건 PnL < 0.3% | 1시간 |
| 5연패 | 5연속 손실 | 50% 사이즈 3거래, 재평가 |
| Stale Price | 120초 미수신 | 5분 |
| Abnormal Size | margin > balance 50% | 무기한 (수동) |
| Price Sanity | 진입가 ≠ 시장가 ±3% | 무기한 (수동) |

## 디렉토리 구조
```
backend/app/
├── analysis/
│   ├── signals.py          # 시그널 생성 (Registry + Confluence)
│   ├── trend_filter.py     # WITH/COUNTER/BLOCKED 분류
│   ├── engine.py           # 지표 오케스트레이션
│   └── indicators/         # RSI, MACD, BB, MA, Fib, Elliott, VP
├── trading/
│   ├── engine.py           # PaperTradingEngine (핵심)
│   ├── schemas.py          # 데이터 모델 + TF별 설정 + 회의록 파라미터
│   ├── persistence.py      # SQLite (거래/포지션/계좌/스냅샷)
│   ├── anomaly_detector.py # 10가지 이상 감지
│   └── alert_sender.py     # Telegram/webhook 알림
├── binance/
│   ├── client.py           # REST (인증+공개) + retry + rate limit
│   ├── kline_store.py      # 인메모리 8TF 캔들 스토어
│   ├── ws_consumer.py      # WebSocket 수신 + tick queue + candle close trigger
│   └── schemas.py          # KlineData, TickerData, TickData
├── api/routes/             # REST API (market, analysis, trading, health)
├── ws/                     # WebSocket 서버 (manager + server)
├── tasks/scheduler.py      # 1초 스캔 + 캔들 종가 트리거 + anomaly heartbeat
├── config.py               # 환경설정 (pydantic-settings)
└── main.py                 # FastAPI entry + lifespan

frontend/src/
├── app/
│   ├── dashboard/page.tsx  # 차트 + 시그널 트리 + 지표 오버레이
│   ├── trading/page.tsx    # 포지션 + 거래내역 + 일자별 성과
│   ├── layout.tsx          # 루트 레이아웃 + ToastWrapper
│   └── ToastWrapper.tsx    # 거래 이벤트 토스트 알림
├── components/
│   ├── charts/CandlestickChart.tsx  # lightweight-charts + 지표 오버레이
│   ├── indicators/TFSignalPanel.tsx # 시그널 파이프라인 (접기/펼치기, 클릭→오버레이)
│   ├── trading/                     # AccountSummary, OpenPositions, TradeHistory 등
│   └── layout/Header.tsx            # 봇 상태 뱃지 + 네비게이션
├── hooks/                  # useMarketData, useWebSocket, useTrading, useIndicators
├── lib/api.ts              # REST API 클라이언트
└── types/                  # market.ts, analysis.ts, trading.ts, ws.ts

docs/meeting-minutes/       # 전문가 토론 회의록 (의사결정 근거)
scripts/setup.sh            # 대화형 설정 (API 키 입력 + 의존성 + 연결 테스트)
```

## 실행 방법
```bash
make setup      # 최초 설정 (API 키 입력 포함)
make backend    # 백엔드 (터미널 1)
make frontend   # 프론트엔드 (터미널 2)
```

## 주의사항
- `.env`에 API 키 저장됨 (gitignore 대상, push 안 됨)
- `backend/data/` 에 SQLite DB (gitignore 대상)
- `BINANCE_TESTNET=true`면 주문은 testnet, `false`면 mainnet
- pnpm dev는 `frontend/`, uvicorn은 `backend/` 에서 실행
- 본전 계산에 왕복 수수료(taker×2/leverage) 포함

## 회의록 참조
의사결정 근거가 필요하면 `docs/meeting-minutes/` 확인:
- `2026-04-08-buffett-dimon-final.md` — 전체 파라미터 확정
- `2026-04-09-buffett-dimon-real-account.md` — 실계좌 전환
- `2026-04-09-buffett-dimon-execution-architecture.md` — 주문 실행 아키텍처
- `2026-04-09-buffett-dimon-auto-halt-rules.md` — 이상 감지 규칙
- `2026-04-09-buffett-dimon-streak-rules.md` — 연승/연패 규칙 (Equity Curve)
