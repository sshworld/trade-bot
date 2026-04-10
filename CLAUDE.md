# Trade Bot — Claude 작업 가이드

> 새 세션에서 이 파일을 먼저 읽고 작업 컨텍스트를 파악할 것.

## 프로젝트 개요
Binance BTC/USDT 선물 자동 매매 시스템. 단타(scalping) 전략.
현재: **실거래 운영 중** (LiveTradingEngine, Mainnet).

## 기술 스택
- **Backend**: Python FastAPI, pandas, ta, httpx, websockets
- **Frontend**: Next.js 16, React, TypeScript, TailwindCSS, lightweight-charts
- **Data**: 인메모리 KlineStore (8 TF × 500 캔들, WebSocket 실시간 갱신)
- **DB**: SQLite (`backend/data/trading.db`)
- **Infra**: uv (Python), pnpm (Node.js)

## 핵심 원칙

### 1. 의사결정 프로세스
**트레이딩 파라미터 변경 시 반드시:**
1. `/trade-review` 실행 (Buffett + Dimon 토론)
2. `docs/meeting-minutes/`에 회의록 저장
3. 사용자 승인 후 구현

### 2. 수동 개입 없음
100% 자동 매매. 이상 감지 → 자동 중단 + Telegram 알림.

### 3. 능동적 업무
이슈 발견 → 전문가 토론 → 결론 → 회의록 → 구현 한 흐름으로.

### 4. 데이터 보존
거래 기록 reset 금지. SQLite 영속화.

## Slash Commands
| 명령 | 용도 |
|------|------|
| `/trade-review` | 파라미터 변경 전 전문가 토론 |
| `/check` | 시스템 전체 상태 점검 |
| `/audit` | 코드 감사 |
| `/deploy` | 빌드 검증 + push |
| `/implement` | 구현 자동 루프 |
| `/analyze` | 거래 성과 분석 |

## 현재 확정 파라미터 (2026-04-11)

### 계좌/리스크
| 파라미터 | 값 |
|---------|-----|
| 레버리지 | **5x 고정** (2026-04-10 회의록) |
| 동시 포지션 | 1개 |
| 거래당 리스크 | **순수 balance × 2%** (클램프 없음, 2026-04-11 회의록) |
| 최소 거래 조건 | 노셔널 ≥ $100 (Binance 최소) |
| 일일 거래/교체 횟수 | **무제한** |
| 일일 손실 -3% | 사이즈 절반 |
| 일일 손실 -5% | **당일 중단** (00시 복귀) |
| 속도 제한 | 60분 3연속 SL → 30분 중단 |
| Drawdown -7% | 당일 중단 (Live 강화) |
| 슬리피지 버퍼 | 95% (계산 사이즈의 95%만 사용) |

### TP/SL — ATR 기반 (단타 최적화)
| TF | SL | TP1 | TP2 | TP3 | Split |
|---|---|---|---|---|---|
| 30m | 1.2×ATR | 1.0×ATR | 1.8×ATR | 3.0×ATR | 50/30/20 |
| 1h | 1.5×ATR | 1.2×ATR | 2.0×ATR | 3.5×ATR | 50/30/20 |
| 4h | 2.0×ATR | 1.5×ATR | 2.5×ATR | 4.0×ATR | 50/30/20 |

### 트레일링
- TP1 → SL을 본전(수수료 포함)
- TP2 → SL을 TP1 가격
- TP2 이후: 동적 트레일 (최고가 - 2.0×ATR, 5×ATR 넘으면 1.0×ATR)

### 진입
- WITH_TREND: 확인 추가 50%/30%/20% (0%, +0.3%, +0.6%)
- COUNTER: 2 tranche 60/40 (0%, -0.3%)

### 교체
- 무제한, 20분 쿨다운
- PnL < 0% AND 새 시그널 > 기존 + 0.5
- 같은 시그널 8시간 차단

### 시그널
- 7 지표, 패밀리 중복 제거 (3+ 독립 패밀리 필수)
- Strength = net_score / 4.0
- MACD 히스토그램 weight 0.3

### 시간 청산
- 2× 평균 승리 시간 → SL 조임
- 4× → 시장가 청산

## TODO
- [x] LiveTradingEngine (2026-04-11 구현)
- [x] Telegram 알림 (2026-04-11 연동)
- [x] 순수 % 리스크 체계 (2026-04-11 회의록)
- [ ] PnL에 수수료 포함 표시
- [ ] UI: 패밀리 count 기준 표시 개선 (부분 완료)
- [ ] 자본 $10,000 도달 시 리스크 재검토 토론

## 디렉토리
```
backend/app/
├── analysis/signals.py       # Registry + 패밀리 + Confluence
├── trading/engine.py         # PaperTradingEngine (ATR TP/SL)
├── trading/live_engine.py    # LiveTradingEngine (실거래, Binance 주문)
├── trading/schemas.py        # TF_ATR_PARAMS + 설정 + LiveTradingSettings
├── trading/persistence.py    # SQLite
├── binance/client.py         # REST (인증+공개)
├── binance/kline_store.py    # 8TF 캔들 스토어
├── tasks/scheduler.py        # 1초 스캔

frontend/src/
├── app/dashboard/page.tsx    # 차트 + 시그널 + 오버레이
├── app/trading/page.tsx      # 포지션 + 거래내역
├── components/indicators/TFSignalPanel.tsx

docs/meeting-minutes/         # 전문가 회의록
.claude/commands/             # slash commands
```

## 실행
```bash
make setup && make backend && make frontend
```

## 주의
- `backend/` 에서 uvicorn, `frontend/` 에서 pnpm dev
- 본전 = 진입가 ± 왕복 수수료
- `/recalculate` API로 열린 포지션 TP/SL 재계산
