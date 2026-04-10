# 🤖 Trade Bot

> Binance BTC/USDT 선물 자동 매매 시스템

실시간 기술적 분석 기반의 단타 자동 매매 봇. 7개 지표 × 6개 타임프레임 교차 분석, ATR 기반 동적 TP/SL, 패밀리 중복 제거 confluence 시그널로 최적의 진입/청산 타이밍을 포착합니다.

---

## 📊 주요 기능

### 시그널 분석
- **7개 기술적 지표**: RSI, MACD, Bollinger Bands, SMA/EMA, Fibonacci, Elliott Wave, Volume Profile
- **6개 타임프레임 동시 분석**: 15m, 30m, 1h, 4h, 1d, 1w (1초마다 스캔)
- **패밀리 중복 제거 Confluence**: 3개 이상 **독립 패밀리**가 합류 + 강한 트리거 필수
- **Multi-TF Trend Filter**: 상위 TF 기반 WITH_TREND / COUNTER_TREND / BLOCKED

### 포지션 관리
- **확인 추가 진입**: 50% 즉시 → 방향 확인 후 30%/20% 추가 (물타기 아님)
- **ATR 기반 동적 TP/SL**: 변동성에 따라 자동 조정
- **3단계 익절**: TP1(50%) → TP2(30%) → TP3(20%), 단타에 맞는 타이트한 ATR 배수
- **트레일링 SL**: TP1→본전(수수료 포함), TP2→TP1, 이후 동적 트레일
- **시간 기반 청산**: 오래 끄는 거래 자동 정리

### 리스크 관리
- **거래당 2% 리스크**: SL 역산 기반 사이즈 (레버리지와 무관하게 손실 고정)
- **레버리지 3-5x**: 시그널 강도에 따라 자동 조절 (net_score/4.0)
- **일일 손실 제한**: -3% 사이즈 절반, -5% 당일 중단
- **속도 제한**: 60분 내 3연속 SL → 30분 중단
- **10가지 이상 감지**: Rapid-Fire, Flip-Flop, Fee Bleeding 등

### 실시간 대시보드
- **캔들스틱 차트**: TradingView lightweight-charts, rAF 60fps
- **시그널 파이프라인**: TF별 진행도, confluence, 부족 요소 (접기/펼치기)
- **지표 오버레이**: 시그널 클릭 → 차트에 RSI/MACD/BB/SMA/Fibonacci/Elliott 표시
- **토스트 알림**: 거래 이벤트 실시간 팝업

---

## 🛠 기술 스택

| 영역 | 기술 |
|------|------|
| **Backend** | Python 3.12+, FastAPI, pandas, ta, scipy |
| **Frontend** | Next.js 16, React 19, TypeScript, TailwindCSS 4 |
| **Chart** | TradingView lightweight-charts 5 |
| **Data** | In-memory KlineStore, SQLite (거래 영속화) |
| **Exchange** | Binance Futures API (REST + WebSocket, HMAC-SHA256) |

---

## 🏗 아키텍처

```
Binance WebSocket ──→ KlineStore ──→ 1초 전 TF 분석
                           │              │
                           │       Signal Registry (7지표 × 6TF)
                           │              │
                           │       패밀리 중복 제거 Confluence
                           │              │
                           │       Trend Filter (WITH/COUNTER/BLOCKED)
                           │              │
                           ▼              ▼
                     Trading Engine ◄─── ATR 기반 TP/SL 계산
                           │
                           ├─ 확인 추가 진입 (50/30/20)
                           ├─ 동적 트레일링 SL
                           ├─ 시간 기반 청산
                           └─ SQLite 영속화
```

---

## 🚀 Quick Start

```bash
git clone https://github.com/sshworld/trade-bot.git
cd trade-bot
make setup      # 아래 대화형 설정 진행
make backend    # 터미널 1
make frontend   # 터미널 2
# http://localhost:3000
```

### Setup 과정

```
[Step 1] 거래 모드 선택

  1) Testnet (모의거래) — 가상 자금으로 테스트
     키 발급: https://testnet.binancefuture.com

  2) Mainnet (실거래) — 실제 자금으로 거래
     키 발급: https://www.binance.com → API Management

  선택 (1 또는 2): _

[Step 2] API Key / Secret Key 입력
[Step 3~4] 의존성 설치 (자동)
[Step 5] 알림 채널 설정 (Telegram, 선택)
[Step 6] 데이터 디렉토리 생성
[Step 7] Binance 연결 테스트
```

---

## 📈 매매 전략

### ATR 기반 TP/SL (단타 최적화)

| TF | SL | TP1(50%) | TP2(30%) | TP3(20%) |
|---|---|---|---|---|
| 30m | 1.2×ATR | 1.0×ATR | 1.8×ATR | 3.0×ATR |
| 1h | 1.5×ATR | 1.2×ATR | 2.0×ATR | 3.5×ATR |
| 4h | 2.0×ATR | 1.5×ATR | 2.5×ATR | 4.0×ATR |

> 1h ATR ≈ $400일 때: TP1=$480, TP2=$800, SL=$600

### 지표 패밀리

| 패밀리 | 지표 | 트리거(w≥1.5) |
|--------|------|-------------|
| **MACD** | 크로스(1.5) + 히스토그램(0.3) | 크로스 |
| **RSI** | 과매수/과매도(1.5) | RSI |
| **BB** | 밴드 돌파(1.5) | BB |
| **MA** | 정배열(0.7) + 크로스(1.5) + EMA(0.5) | 크로스 |
| **Fibonacci** | 레벨 근접(1.0) | - |
| **Elliott** | 파동(0.8-1.0) | - |
| **VP** | Value Area 이탈(0.8) | - |

> 같은 패밀리는 가장 높은 weight만 confluence 카운트. 3+ 독립 패밀리 필수.

### 진입 조건

```
✓ 3개 이상 독립 패밀리 합류
✓ 합산 점수 ≥ TF별 임계값
✓ 순점수 ≥ 임계값 (지연 지표 할인 적용)
✓ 강한 트리거 1개 이상 (RSI극단, MACD크로스, BB돌파, MA크로스)
```

---

## 📁 프로젝트 구조

```
trade-bot/
├── backend/app/
│   ├── analysis/           # 시그널 + 지표 + 추세 필터
│   ├── trading/            # 매매 엔진 + 스키마 + DB + 이상 감지
│   ├── binance/            # API 클라이언트 + KlineStore + WebSocket
│   ├── api/routes/         # REST API
│   └── tasks/              # 1초 스케줄러
├── frontend/src/
│   ├── app/                # Dashboard + Trading 페이지
│   ├── components/         # 차트, 시그널, 거래 UI
│   └── hooks/              # WebSocket, 데이터 훅
├── docs/meeting-minutes/   # 전문가 토론 회의록
├── .claude/commands/       # AI slash commands
├── CLAUDE.md               # AI 작업 가이드
└── AGENTS.md               # 에이전트 지침
```

---

## 🔧 주요 설계 결정

| 결정 | 근거 | 회의록 |
|------|------|--------|
| ATR 기반 TP/SL | 고정%는 변동성 무시 | 04-10 scalping |
| 패밀리 중복 제거 | MACD 2개=실질 1개 | 04-10 performance |
| 확인 추가 진입 | 레버리지 선물 물타기 위험 | 04-10 aggressive |
| 거래 횟수 무제한 | 일일 손실%가 실질 안전망 | 04-10 unlimited |
| 5x 고정 아닌 3-5x | 시그널 강도 반영 | 04-10 leverage |

---

## 📜 License

[MIT License](LICENSE)
