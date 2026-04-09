# 🤖 Trade Bot

> Binance BTC/USDT 선물 자동 매매 시스템

실시간 기술적 분석 기반의 자동 매매 봇. 7개 지표 × 6개 타임프레임 교차 분석으로 최적의 진입/청산 타이밍을 포착합니다.

---

## 📊 주요 기능

### 시그널 분석
- **7개 기술적 지표**: RSI, MACD, Bollinger Bands, SMA/EMA, Fibonacci Retracement, Elliott Wave, Volume Profile
- **6개 타임프레임 동시 분석**: 15m, 30m, 1h, 4h, 1d, 1w
- **Confluence 기반 진입**: 3개 이상 지표가 같은 방향 + 강한 이벤트 트리거(RSI 극단, MACD 크로스, BB 돌파) 발생 시에만 진입
- **Multi-TF Trend Filter**: 상위 TF 추세 방향으로 WITH_TREND / COUNTER_TREND / BLOCKED 분류

### 포지션 관리
- **분할 진입/청산**: 3단계 분할 매수, 3단계 분할 익절 (50/30/20)
- **트레일링 SL**: TP1 체결 → 본전(수수료 포함), TP2 체결 → TP1 가격으로 이동
- **포지션 교체**: 더 강한 반대 시그널 감지 시 자동 교체
- **Equity Curve 사이징**: 최근 거래 성과 기반 포지션 크기 조절

### 리스크 관리
- **거래당 리스크**: 자본의 2% 고정 (SL 역산 기반 사이징)
- **일일 손실 3단계**: -3% 사이즈 축소 → -5% 당일 중단 → -8% 48시간 중단
- **10가지 이상 감지**: Rapid-Fire, Flip-Flop, Fee Bleeding, 연속 손실 등
- **ATR 가드레일**: SL이 변동성 대비 1.5~4.0× ATR 범위 내 유지

### 실시간 대시보드
- **캔들스틱 차트**: TradingView lightweight-charts, 실시간 tick 반영 (rAF 60fps)
- **시그널 파이프라인**: TF별 진행도, confluence 상태, 부족 요소 표시
- **지표 오버레이**: 시그널 트리에서 지표 클릭 → 차트에 RSI/MACD/BB/SMA/Fibonacci/Elliott 오버레이
- **토스트 알림**: 거래 이벤트 실시간 팝업

---

## 🛠 기술 스택

| 영역 | 기술 |
|------|------|
| **Backend** | Python 3.12+, FastAPI, pandas, ta, scipy, httpx, websockets |
| **Frontend** | Next.js 16, React 19, TypeScript, TailwindCSS 4, lightweight-charts 5 |
| **Data** | In-memory KlineStore (8 TF × 500 candles, WebSocket 실시간 갱신) |
| **DB** | SQLite (거래 기록, 포지션, 계좌 상태, 일자별 스냅샷) |
| **Exchange** | Binance Futures API (REST + WebSocket, HMAC-SHA256 인증) |
| **Package** | uv (Python), pnpm (Node.js) |

---

## 🏗 아키텍처

```
Binance WebSocket ──→ KlineStore (메모리) ──→ 1초마다 전 TF 분석
      │                     │                      │
      │                     │               Signal Registry
      │                     │              (7 indicators × 6 TFs)
      │                     │                      │
      ▼                     │               Confluence Check
   Tick Queue              │              (TF별 임계값 + 트리거)
      │                     │                      │
      ▼                     │               Trend Filter
 Trading Engine ◄───────────┘              (WITH/COUNTER/BLOCKED)
      │                                           │
      ├─ 포지션 진입 (분할 3단계)                    │
      ├─ 트레일링 SL                               │
      ├─ 포지션 교체                                │
      └─ SQLite 영속화                              │
                                                   ▼
                                            Frontend (Next.js)
                                            ├─ 캔들스틱 차트
                                            ├─ 시그널 파이프라인
                                            └─ 거래 대시보드
```

---

## 🚀 Quick Start

```bash
# 1. 클론
git clone https://github.com/sshworld/trade-bot.git
cd trade-bot

# 2. 설정 (API 키 입력 + 의존성 설치 + 연결 테스트)
make setup

# 3. 실행
make backend    # 터미널 1
make frontend   # 터미널 2

# 브라우저: http://localhost:3000
```

### 환경 설정

`.env` 파일에서 설정:

```env
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_secret_key
BINANCE_TESTNET=true    # true: testnet, false: mainnet
```

Futures Testnet 키는 [testnet.binancefuture.com](https://testnet.binancefuture.com) 에서 생성.

---

## 📈 매매 전략

### 진입 조건 (Confluence)

단일 지표가 아닌 **복수 지표 합류** 시에만 진입:

```
필수 조건:
  ✓ 3개 이상 지표가 같은 방향
  ✓ 합산 점수 ≥ TF별 임계값
  ✓ 순점수(bull - bear) ≥ 임계값
  ✓ 강한 트리거 1개 이상 (RSI 극단, MACD 크로스, BB 돌파, MA 크로스)
```

### 지표 가중치

| 지표 | 가중치 | 유형 |
|------|--------|------|
| RSI < 30 / > 70 | 1.5 | 이벤트 트리거 |
| MACD 크로스 | 1.5 | 이벤트 트리거 |
| Bollinger Band 돌파 | 1.5 | 이벤트 트리거 |
| SMA 20/50 크로스 | 1.5 | 이벤트 트리거 |
| MA 정배열/역배열 | 0.7 | 상태 (지연) |
| EMA 구조 | 0.5 | 상태 (지연) |
| Fibonacci 레벨 | 1.0 | 컨텍스트 |
| Elliott Wave | 0.8-1.0 | 패턴 |
| Volume Profile | 0.8 | 컨텍스트 |

> 추세 전환 시 지연 상태 지표(MA, EMA)는 반대 방향 점수에서 70% 할인 적용

### TF별 TP/SL (마진 기준 %)

**With-Trend:**

| TF | TP1 | TP2 | TP3 | SL | Split |
|---|---|---|---|---|---|
| 30m | +5% | +10% | +18% | -3.5% | 50/30/20 |
| 1h | +7% | +14% | +25% | -5% | 50/30/20 |
| 4h | +10% | +20% | +35% | -7% | 50/30/20 |

### 진입 가능 TF

| TF | 역할 |
|-----|------|
| 15m | 분석/UI만 (진입 불가) |
| **30m, 1h, 4h** | **진입 가능** |
| 1d, 1w | 추세 필터만 |

---

## 📁 프로젝트 구조

```
trade-bot/
├── backend/
│   ├── app/
│   │   ├── analysis/           # 시그널 분석 엔진
│   │   │   ├── signals.py      # Registry 패턴 시그널 생성
│   │   │   ├── trend_filter.py # Multi-TF 추세 필터
│   │   │   └── indicators/     # 7개 지표 구현
│   │   ├── trading/            # 매매 엔진
│   │   │   ├── engine.py       # PaperTradingEngine
│   │   │   ├── schemas.py      # 데이터 모델 + 파라미터
│   │   │   ├── persistence.py  # SQLite 영속화
│   │   │   └── anomaly_detector.py
│   │   ├── binance/            # Binance API
│   │   │   ├── client.py       # REST (인증+공개)
│   │   │   ├── kline_store.py  # 인메모리 캔들 스토어
│   │   │   └── ws_consumer.py  # WebSocket 수신
│   │   ├── api/routes/         # REST API 엔드포인트
│   │   ├── ws/                 # WebSocket 서버
│   │   └── tasks/scheduler.py  # 1초 스캔 스케줄러
│   └── pyproject.toml
│
├── frontend/
│   └── src/
│       ├── app/                # Next.js 페이지
│       ├── components/         # React 컴포넌트
│       ├── hooks/              # 커스텀 훅
│       └── types/              # TypeScript 타입
│
├── docs/
│   └── meeting-minutes/        # 매매 전략 의사결정 회의록
│
├── CLAUDE.md                   # AI 작업 가이드
├── AGENTS.md                   # AI 에이전트 지침
└── scripts/setup.sh            # 대화형 설정 스크립트
```

---

## 🔧 주요 설계 결정

자세한 근거는 `docs/meeting-minutes/` 참조.

| 결정 | 근거 |
|------|------|
| 레버리지 3-5x | 자본 보존 우선, 검증 후 상향 |
| 동시 포지션 1개 | $1,000 규모에서 복수 포지션은 리스크 분산이 아닌 집중 |
| 거래당 2% 리스크 | SL 도달 시 정확히 자본의 2% 손실로 역산 |
| TF별 TP/SL | 30m은 좁게, 4h는 넓게 — 변동폭에 맞춤 |
| 15m 진입 불가 | 노이즈 과다, 추세 중 반복 역추세 진입 문제 |
| 지연 지표 할인 | 추세 전환 초기에 MA/EMA가 반대로 걸려 진입 불가 방지 |
| 수수료 포함 본전 | 진입가 = 본전이 아님, 왕복 수수료 반영 |

---

## 📜 License

Private repository. All rights reserved.
