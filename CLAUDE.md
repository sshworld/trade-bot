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

## 현재 확정 파라미터 (2026-04-13)

### 계좌/리스크
| 파라미터 | 값 |
|---------|-----|
| 레버리지 | **5x 고정** (2026-04-10 회의록) |
| 동시 포지션 | 1개 |
| SL 리스크 | **잔고 × 2%** 고정 손실 (2026-04-13 회의록) |
| 마진 캡 | **잔고의 55%** (2026-04-13 회의록) |
| 최소 거래 조건 | 노셔널 ≥ $100 (Binance 최소) |
| 최저 운영 잔고 | **$100** (미달 시 거래 중단) |
| 일일 거래/교체 횟수 | **무제한** |
| 일일 손실 -3% | 사이즈 절반 |
| 일일 손실 -5% | **당일 중단** (00시 복귀) |
| 속도 제한 | 60분 3연속 SL → 30분 중단 |
| Drawdown -7% | 당일 중단 (Live 강화) |
| 슬리피지 버퍼 | 95% (계산 사이즈의 95%만 사용) |
| 시그널 스로틀 | **5초** |
| 잔고 관리 | **Binance 실잔고 기준** (cross margin, 로컬 margin 차감 없음) |

### TP — 마진 대비 % (2026-04-13 회의록, ATR 폐기)
| 단계 | 마진 수익% | BTC 이동% (@5x) | 물량 | 후속 |
|------|:---:|:---:|:---:|:---:|
| TP1 | **3%** | 0.6% | **50%** | SL → 본전(수수료 포함) |
| TP2 | **6%** | 1.2% | **30%** | SL → TP1 가격 |
| TP3 | **10%** | 2.0% | **20%** | 트레일링 조임 |

### SL — 잔고 2% 고정 손실
- 전량 1건 청산 (분할 SL 없음)
- 최소 SL 거리: **0.3%** (스프레드/슬리피지 보호)
- 물타기 시 평단 기준 재계산
- **SL 사전 배치**: STOP_MARKET + reduceOnly (서버 꺼져도 작동)

### 트레일링
- TP1 → SL을 본전(수수료 포함)
- TP2 → SL을 TP1 가격
- TP2 이후: 최고가 - **마진 3%** / TP3 넘으면 **마진 1.5%**

### 진입 (물타기, ATR 기반 offset)
- 50%/30%/20% @ [0, ATR×0.5, ATR×1.0] 역행 (캡 0%/1.0%/1.5%)
- 동적 최소 tranche: ceil($110 / price, 0.001) — tail merge
- 소자본 자동 조정: 3분할→2분할→1분할

### 교체
- 무제한, 20분 쿨다운
- PnL < 0% AND 새 시그널 > 기존 + 0.5
- 같은 시그널 8시간 차단

### 시그널
- 7 지표, 패밀리 중복 제거 (3+ 독립 패밀리 필수)
- Strength = net_score / 4.0
- MACD 히스토그램 weight 0.3

### 시간 청산 (2026-04-13 회의록)
- **48시간** → SL 50% 조임
- **72시간** → 시장가 청산

## TODO
- [x] LiveTradingEngine (2026-04-11 구현)
- [x] Telegram 알림 (2026-04-11 연동)
- [x] 순수 % 리스크 체계 (2026-04-11 회의록)
- [x] 시그널 쿨다운 5분→5초 (2026-04-11 회의록)
- [x] 분할 진입 평단 최적화 (2026-04-11 회의록)
- [x] Binance 실잔고 동기화 (2026-04-11)
- [x] UI: 패밀리 count + bearish 빨간색 + reject 사유 표시
- [x] SL/TP 바이낸스 Algo API 사전 배치 (서버 꺼져도 작동)
- [x] 동적 최소 tranche (tail merge, 소자본 자동 분할 조정)
- [x] TP 가중 평균 merge (R:R 비율 보존)
- [x] SHORT tighten_sl 방향 버그 수정
- [x] 텔레그램 봇 명령어 (/status, /position, /help)
- [x] ATR → 마진 % 기반 TP/SL 전환 (2026-04-13 회의록)
- [x] 시간 청산 48h/72h 전환 (기존 2h/4h 폐기)
- [x] 마진 캡 55% + 최저 운영 잔고 $100
- [x] 텔레그램 /status 상세 개선
- [ ] PnL에 수수료 포함 표시
- [ ] 자본 $10,000 도달 시 리스크 재검토 토론
- [ ] TP 사전 배치 Phase 2 (트레일링 TP)

## 디렉토리
```
backend/app/
├── analysis/signals.py       # Registry + 패밀리 + Confluence
├── trading/engine.py         # PaperTradingEngine (ATR TP/SL)
├── trading/live_engine.py    # LiveTradingEngine (실거래, Binance 주문)
├── trading/schemas.py        # TF_ATR_PARAMS + 설정 + LiveTradingSettings
├── trading/persistence.py    # SQLite
├── trading/telegram_bot.py   # 텔레그램 봇 명령어 (/status, /position)
├── trading/alert_sender.py   # Telegram + Webhook 알림
├── binance/client.py         # REST + Algo Order API (인증+공개)
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
- `backend/` 에서 uvicorn (**--reload 사용 금지**, 실거래 안정성), `frontend/` 에서 pnpm dev
- 본전 = 진입가 ± 왕복 수수료
- `/recalculate` API로 열린 포지션 TP/SL 재계산
- 코드 수정 후 서버 재시작 시 **반드시 사용자 승인** 필요
