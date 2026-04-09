#!/bin/bash
set -e

echo "=== Trade Bot Setup ==="
echo ""

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step() { echo -e "\n${GREEN}[Step $1]${NC} $2"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# ── 1. Binance API 키 설정 ──────────────────────────────────
step 1 "Binance API 설정"

if [ ! -f .env ]; then
  cp .env.example .env
fi

# 키가 비어있으면 입력 받기
CURRENT_KEY=$(grep "^BINANCE_API_KEY=" .env | cut -d'=' -f2)
if [ -z "$CURRENT_KEY" ]; then
  echo ""
  echo -e "${CYAN}Binance Futures Testnet API 키를 설정합니다.${NC}"
  echo "  키가 없으면 https://testnet.binancefuture.com 에서 생성하세요."
  echo "  (실제 Binance 계정으로 로그인 → API Management → Generate HMAC-SHA-256 Key)"
  echo ""

  read -p "  API Key: " API_KEY
  read -p "  Secret Key: " SECRET_KEY

  if [ -n "$API_KEY" ] && [ -n "$SECRET_KEY" ]; then
    # .env에 키 저장
    sed -i '' "s|^BINANCE_API_KEY=.*|BINANCE_API_KEY=$API_KEY|" .env
    sed -i '' "s|^BINANCE_API_SECRET=.*|BINANCE_API_SECRET=$SECRET_KEY|" .env
    echo -e "  ${GREEN}API 키 저장 완료${NC}"
  else
    warn "키를 입력하지 않았습니다. 나중에 .env 파일에서 직접 입력하세요."
  fi

  echo ""
  read -p "  Testnet 사용? (y/n, 기본: y): " USE_TESTNET
  USE_TESTNET=${USE_TESTNET:-y}
  if [ "$USE_TESTNET" = "n" ] || [ "$USE_TESTNET" = "N" ]; then
    sed -i '' "s|^BINANCE_TESTNET=.*|BINANCE_TESTNET=false|" .env
    echo -e "  ${YELLOW}Mainnet (실거래) 모드${NC}"
  else
    sed -i '' "s|^BINANCE_TESTNET=.*|BINANCE_TESTNET=true|" .env
    echo -e "  ${GREEN}Testnet (모의거래) 모드${NC}"
  fi
else
  echo "  API 키 이미 설정됨 (${CURRENT_KEY:0:10}...)"
fi

# ── 2. Python 의존성 ────────────────────────────────────────
step 2 "백엔드 의존성 설치 (uv)"
if ! command -v uv &> /dev/null; then
  echo "  uv 설치 중..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
cd "$ROOT_DIR/backend"
uv sync --quiet
echo "  Python 패키지 설치 완료"

# ── 3. Node 의존성 ──────────────────────────────────────────
step 3 "프론트엔드 의존성 설치 (pnpm)"
if ! command -v pnpm &> /dev/null; then
  echo "  pnpm 설치 중..."
  npm install -g pnpm
fi
cd "$ROOT_DIR/frontend"
pnpm install --silent
echo "  Node 패키지 설치 완료"

# ── 4. 데이터 디렉토리 ─────────────────────────────────────
step 4 "데이터 디렉토리 생성"
mkdir -p "$ROOT_DIR/backend/data"
echo "  backend/data/ 생성 완료 (SQLite DB 저장 위치)"

# ── 5. API 키 검증 ──────────────────────────────────────────
step 5 "Binance API 연결 테스트"
cd "$ROOT_DIR/backend"
API_KEY=$(grep "^BINANCE_API_KEY=" "$ROOT_DIR/.env" | cut -d'=' -f2)
if [ -n "$API_KEY" ]; then
  uv run python3 -c "
import asyncio
from app.binance.client import binance_client

async def test():
    try:
        balance = await binance_client.get_balance('USDT')
        print(f'  ✓ Binance 연결 성공! 잔고: \${balance}')
    except Exception as e:
        print(f'  ✗ Binance 연결 실패: {e}')
        print('    .env의 API 키를 확인하세요.')
    await binance_client.close()

asyncio.run(test())
" 2>&1 || warn "API 연결 테스트 실패 — 나중에 키를 확인하세요."
else
  warn "API 키 미설정. 시그널 분석만 동작합니다."
fi

echo ""
echo "=== 설치 완료 ==="
echo ""
echo "실행 방법:"
echo "  make start              (백엔드 + 프론트엔드 동시 실행)"
echo ""
echo "또는 개별:"
echo "  make backend            (백엔드 서버)"
echo "  make frontend           (프론트엔드 서버)"
echo ""
echo "브라우저: http://localhost:3000"
echo ""
echo "설정 변경:"
echo "  .env 파일에서 API 키/모드 수정 가능"
echo ""
