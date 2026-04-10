# Architecture

## Overview

Binance BTC/USDT 선물 자동 매매 시스템. 실시간 시세, 기술적 분석, 자동 매매 실행.

## Stack

- **Backend**: Python 3.12+, FastAPI, pandas, ta, httpx, websockets
- **Frontend**: Next.js 16, React 19, TypeScript, TailwindCSS 4, lightweight-charts 5
- **Database**: SQLite (거래 영속화)
- **Data**: In-memory KlineStore (8 TF × 500 캔들)
- **Exchange**: Binance Futures API (REST + WebSocket, HMAC-SHA256)
- **Infra**: uv (Python), pnpm (Node.js)

## Data Flow

```
Binance WS → ws_consumer.py → KlineStore → 1초 signal_scan
                            → ConnectionManager → Frontend WS
                                                    │
                              analysis/signals.py ──┘
                                     │
                              Confluence (3+ 독립 패밀리)
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
              PaperEngine      LiveEngine        Anomaly
              (시뮬레이션)    (Binance 실주문)    Detector
                    │                │                │
                    └────────────────┼────────────────┘
                                     │
                              SQLite 영속화
                              Telegram 알림
```

## Key Modules

### Backend (`backend/app/`)
- `analysis/` - 시그널 생성 (7지표 × 6TF, 패밀리 중복 제거 confluence)
- `trading/engine.py` - PaperTradingEngine (시뮬레이션)
- `trading/live_engine.py` - LiveTradingEngine (Binance 실주문, reconciliation)
- `trading/schemas.py` - 데이터 모델, TradingSettings, LiveTradingSettings
- `trading/persistence.py` - SQLite 영속화
- `trading/anomaly_detector.py` - 10가지 행동 이상 감지
- `trading/alert_sender.py` - Telegram + Webhook 알림
- `binance/client.py` - Binance REST API (인증 + 공개)
- `binance/kline_store.py` - 8TF 캔들 스토어
- `binance/ws_consumer.py` - WebSocket 실시간 수신
- `api/routes/` - REST API 엔드포인트
- `tasks/scheduler.py` - 1초 스캔 + 5초 reconciliation + 30초 heartbeat

### Frontend (`frontend/src/`)
- `app/dashboard/` - 차트 + 시그널 파이프라인 + 지표 오버레이
- `app/trading/` - 포지션 + 거래내역 + 성과 요약
- `components/indicators/TFSignalPanel.tsx` - TF별 시그널 진행도 (패밀리 기준)
- `components/charts/` - lightweight-charts 캔들스틱
- `hooks/` - WebSocket, 마켓 데이터 훅

## Engine Selection

```python
# engine.py 하단
if not settings.binance_testnet and settings.binance_api_key:
    trading_engine = LiveTradingEngine()   # Mainnet → 실주문
else:
    trading_engine = PaperTradingEngine()  # Testnet → 시뮬레이션
```
