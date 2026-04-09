# Architecture

## Overview

Binance Bitcoin 선물 거래 분석 대시보드. 실시간 시세, 기술적 지표, 수학적 분석 근거를 제공.

## Stack

- **Frontend**: Next.js 15 + React + TypeScript, TailwindCSS, lightweight-charts
- **Backend**: Python FastAPI, pandas, ta, binance-connector
- **Database**: PostgreSQL 16
- **Infra**: Docker Compose, uv, pnpm

## Data Flow

```
Binance WS → ws_consumer.py → ConnectionManager → Frontend WS
                            → analysis/engine.py → REST API
                            → db/repository.py   → PostgreSQL
```

## Key Modules

### Backend (`backend/app/`)
- `binance/` - Binance API 연동 (REST + WebSocket)
- `analysis/` - 기술적 분석 엔진 (RSI, MACD, BB, Fibonacci, Elliott Wave)
- `ws/` - WebSocket 서버 (클라이언트 브로드캐스트)
- `api/routes/` - REST API 엔드포인트
- `tasks/` - 주기적 분석 스케줄러

### Frontend (`frontend/src/`)
- `components/charts/` - lightweight-charts 기반 캔들스틱 차트
- `components/indicators/` - 지표 패널 (RSI, MACD, 시그널)
- `hooks/` - WebSocket, 마켓 데이터, 지표 커스텀 훅
- `lib/` - API 클라이언트, 유틸리티
