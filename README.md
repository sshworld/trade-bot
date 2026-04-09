# Trade Bot - Binance Bitcoin Futures Analysis

Binance Bitcoin 선물 거래 분석 대시보드

## Quick Start

```bash
# 환경 설정
cp .env.example .env
# .env 파일에 Binance API 키 입력

# 의존성 설치
make setup

# DB 시작
make db

# 백엔드 실행 (터미널 1)
make backend

# 프론트엔드 실행 (터미널 2)
make frontend
```

## Features

- 실시간 BTC/USDT 선물 가격 스트리밍
- 캔들스틱 차트 (lightweight-charts)
- 기술적 지표: RSI, MACD, Bollinger Bands, Moving Averages
- 고급 분석: Fibonacci Retracement, Elliott Wave, Volume Profile
- 매매 시그널 생성

## Tech Stack

- **Frontend**: Next.js 15, React, TypeScript, TailwindCSS
- **Backend**: Python, FastAPI, pandas, ta
- **Database**: PostgreSQL 16
- **API**: Binance Futures (binance-connector)
