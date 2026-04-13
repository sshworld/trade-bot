# 🤖 Trade Bot

> Binance BTC/USDT 선물 자동 매매 시스템

실시간 기술적 분석 기반의 단타 자동 매매 봇. 7개 지표 × 6개 타임프레임 교차 분석, 마진 % 기반 TP/SL, 패밀리 중복 제거 confluence 시그널로 최적의 진입/청산 타이밍을 포착합니다.

---

## 📊 주요 기능

### 시그널 분석
- **7개 기술적 지표**: RSI, MACD, Bollinger Bands, SMA/EMA, Fibonacci, Elliott Wave, Volume Profile
- **6개 타임프레임 동시 분석**: 15m, 30m, 1h, 4h, 1d, 1w (1초마다 스캔)
- **패밀리 중복 제거 Confluence**: 3개 이상 **독립 패밀리**가 합류 + 강한 트리거 필수
- **Multi-TF Trend Filter**: 상위 TF 기반 WITH_TREND / COUNTER_TREND / BLOCKED

### 포지션 관리
- **물타기 분할 진입**: 50% 즉시 → ATR 기반 역행 시 30%/20% 추가 (평단 유리하게)
- **마진 % 기반 TP**: TP1(3%) → TP2(6%) → TP3(10%) — BTC 0.6%만 움직여도 수익
- **잔고 2% 고정 SL**: 전량 1건 청산, 최소 거리 0.3% 보장
- **트레일링 SL**: TP1→본전(수수료 포함), TP2→TP1, 이후 마진 % 동적 트레일
- **시간 기반 안전장치**: 48시간 SL 조임, 72시간 강제 청산

### 리스크 관리
- **SL = 잔고 × 2% 고정 손실**: 포지션 크기에 관계없이 일관된 리스크
- **마진 캡 55%**: 잔고의 55%까지만 마진 사용
- **레버리지 5x 고정**: 마진 효율 최적화
- **최저 운영 잔고 $100**: 미달 시 자동 거래 중단
- **일일 손실 제한**: -3% 사이즈 절반, -5% 당일 중단, Peak Drawdown -7% 정지
- **속도 제한**: 60분 내 3연속 SL → 30분 중단
- **10가지 이상 감지**: Rapid-Fire, Flip-Flop, Fee Bleeding 등
- **실거래 지원**: LiveTradingEngine — Binance 실주문, 5초 주문 조회, ghost position 감지
- **SL/TP 사전 배치**: Binance Algo API (STOP_MARKET, TAKE_PROFIT_MARKET) — 서버 꺼져도 작동
- **동적 분할 진입**: 소자본 자동 조정 (3분할→2분할→1분할, tail merge)
- **텔레그램 봇**: /status, /position, /help 명령어로 실시간 상태 확인

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
                     Trading Engine ◄─── 마진 % 기반 TP/SL
                           │
                           ├─ Paper: 시뮬레이션 체결
                           ├─ Live: Binance 실주문 + 5초 Reconciliation
                           ├─ 물타기 분할 진입 (ATR offset)
                           ├─ 마진 % 트레일링 SL
                           ├─ 48h/72h 시간 안전장치
                           ├─ Telegram 알림 (진입/청산/이상감지)
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

### TP/SL — 마진 % 기반 (단타 최적화)

| 단계 | 마진 수익% | BTC 이동% (@5x) | 물량 | 후속 액션 |
|------|:---:|:---:|:---:|:---:|
| **TP1** | 3% | 0.6% | 50% | SL → 본전(수수료 포함) |
| **TP2** | 6% | 1.2% | 30% | SL → TP1 가격 |
| **TP3** | 10% | 2.0% | 20% | 트레일링 조임 |
| **SL** | 잔고 2% | — | 전량 | 1건 청산 |

> $200 잔고, BTC $84K 기준: TP1=$84,471(+$471), SL=$83,429(-$571) → R:R 1.46:1

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
│   ├── trading/            # Paper/Live 매매 엔진 + 스키마 + DB + 이상 감지
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
| 마진 % 기반 TP/SL | ATR은 단타 목표 비현실적, % 기반이 달성 가능 | 04-13 percent-based-tpsl |
| 잔고 2% 고정 SL | 포지션 크기 무관 일관된 리스크 | 04-13 percent-based-tpsl |
| 마진 캡 55% | cross margin 청산 리스크 관리 | 04-13 dynamic-tranche |
| 물타기 분할 진입 | 역행 시 유리한 평단 + ATR offset | 04-13 entry-offset |
| 패밀리 중복 제거 | MACD 2개=실질 1개 | 04-10 performance |
| 거래 횟수 무제한 | 일일 손실%가 실질 안전망 | 04-10 unlimited |
| 5x 고정 레버리지 | SL 사이징으로 실손실 동일 | 04-10 leverage-5x |
| 48h/72h 시간 청산 | 기존 2h/4h는 수익 기회 차단 | 04-13 percent-based-tpsl |
| Live Trading | Paper→Live 전환, 실주문 | 04-11 구현 |

---

## 🔗 Binance 계정 개설

이 프로젝트를 사용하려면 Binance Futures 계정이 필요합니다.

[![Binance](https://img.shields.io/badge/Binance-가입하기-F0B90B?style=for-the-badge&logo=binance)](https://www.binance.com/register?ref=130350784)

> 레퍼럴 링크입니다. 이 링크로 가입해주시면 프로젝트 개발에 도움이 됩니다.

---

## 📜 License

[MIT License](LICENSE)
