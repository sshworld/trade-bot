# Buffett × Dimon: 실계좌 전환 시 변경사항
## 2026-04-09

### 1. 잔고 소스
- 포지션 사이즈 계산 전 **반드시 Binance API에서 실제 잔고 fetch**
- 캐시 5초 이상이면 재요청
- 로컬 추적 잔고와 API 잔고 차이 1% 이상 → 경고 + 거래 중단

### 2. 초기 자본 개념
- `adjusted_capital_base = initial_capital + 입금 - 출금` (DB 저장)
- 입출금 이벤트 별도 추적
- Circuit breaker: **-20%** (paper -50%에서 강화)

### 3. 거래당 리스크
- `risk = clamp(balance × 2%, MIN_RISK, MAX_RISK)`
- `MAX_RISK_DOLLARS = $100` (계좌 크기 무관 상한)
- `MIN_RISK_DOLLARS = $10` (이 이하면 거래 중단)

### 4. 일일 손실 (강화)
| | Paper | Real |
|--|-------|------|
| Tier 1 | -3% | **-2%** |
| Tier 2 | -5% | **-3%** |
| Tier 3 | -8% | **-5%** |
| 절대값 상한 | 없음 | **MAX_DAILY_LOSS_DOLLARS** |
| Peak drawdown | -10% | **-7%** |

### 5. 코드 변경 필요 사항

#### 실행 레이어
- 시뮬레이션 체결 → **Binance Order API** (LIMIT 우선, MARKET은 가격보호 체크)
- 주문 상태 폴링 (PARTIALLY_FILLED, EXPIRED, REJECTED 처리)
- 슬리피지 버퍼: 계산값의 95%로 사이즈

#### 방어 인프라
- 에러 핸들링: timeout, insufficient margin, rate limit, 네트워크 실패
- Rate limiter (1200 weight/min)
- Kill switch (`TRADING_ENABLED = false` 설정으로 즉시 중단)
- 주문 감사 로그 (모든 주문/체결/거부 → DB)
- 시작 시 Binance 미지 포지션 체크 (있으면 중단)

### 6. 새 설정값
```
TRADING_MODE = "real"
ADJUSTED_CAPITAL_BASE = persisted
MAX_RISK_DOLLARS = 100
MIN_RISK_DOLLARS = 10
MAX_DAILY_LOSS_DOLLARS = 500
DAILY_LOSS_TIERS = [-2%, -3%, -5%]
CIRCUIT_BREAKER_PCT = -20%
PEAK_DRAWDOWN_HALT = -7%
SLIPPAGE_BUFFER = 0.05
TRADING_ENABLED = true (kill switch)
BALANCE_STALE_SECONDS = 5
RECONCILIATION_THRESHOLD = 1%
```

### 핵심 인사이트
> **디먼**: "페이퍼 트레이딩은 실패 모드가 0개. 실거래는 수십 개. 코드 변경의 대부분은 전략이 아니라 방어 인프라."
> **버핏**: "20% 잃었으면 구조적 문제. 50%까지 기다리는 건 리스크 관리가 아니라 재앙 허용."
