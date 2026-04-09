# Buffett × Dimon: 실계좌 실행 아키텍처
## 2026-04-09

### 개발자 반론 검토

#### 반론 1: Kill Switch 불필요 (쿨다운/일일제한 이미 있음)
**판정: 대부분 맞지만, 수동 중단 플래그는 유지**
- 자동 보호장치는 모두 "코드가 정상일 때"만 작동
- PnL 계산 버그, lock 실패 등 "코드 자체가 문제"인 경우 모든 자동 보호가 무력화
- Kill switch = `manual_halt: bool` 플래그 + API 엔드포인트 (15줄)
- 복잡한 서비스가 아니라 단순한 수동 오버라이드

#### 반론 2: Startup Safety Check 불필요 (확인 후 저장하면 됨)
**판정: 개발자가 틀림. Crash Window 문제.**
```
T1: 봇 → Binance 주문 전송
T2: Binance 체결 (포지션 생성됨)
T3: Binance → 봇 응답 전송 중
T4: *** 봇 크래시 (응답 수신 전) ***
T5: DB에 기록 없음, Binance에 포지션 있음 → 유령 포지션
```
"확인 후 저장"으로도 T2~T4 사이 크래시는 방지 불가 (분산 시스템 근본 한계)

### 해결: Intent → Submit → Confirm 3단계 저장

```
1. DB에 INTENT 저장 (status="submitting")
2. Binance API 호출
3. 응답 받으면 DB 업데이트 (status="filled" or "failed")

크래시 시: 시작할 때 status="submitting" 레코드 발견 → Binance API로 실제 상태 확인 → 동기화
```

### 실행 아키텍처 State Machine

```
SIGNAL → PRE_VALIDATION → INTENT_SAVED(DB) → ORDER_SUBMITTED(Binance) 
  → [크래시 시 RECONCILE] → ORDER_CONFIRMED → DB_UPDATED → MONITORING
  → EXIT_SUBMITTED → EXIT_CONFIRMED → POSITION_CLOSED(DB)
```

### Binance API 사용

| 엔드포인트 | 시점 | 용도 |
|-----------|------|------|
| POST /fapi/v1/order | 진입/청산 | 실제 주문 |
| GET /fapi/v1/order | Reconciliation | 주문 상태 확인 |
| GET /fapi/v2/positionRisk | 시작 + 주기 | 유령 포지션 감지 |
| GET /fapi/v2/balance | 시작 + 주기 | 잔고 불일치 감지 |

### 코드 변경 계획

1. `PaperTradingEngine` — 그대로 유지 (paper/backtest용)
2. `LiveTradingEngine` — 신규, 실제 Binance API 호출
3. `BinanceClient` — 인증(HMAC-SHA256) 추가 (현재 공개 API만)
4. `persistence.py` — Position에 "submitting" 상태 추가
5. `AccountState` — `manual_halt` 플래그 추가
6. `main.py` — 시작 시 `startup_reconciliation()` 실행
7. 설정으로 `TRADING_MODE = "paper" | "real"` 분기
