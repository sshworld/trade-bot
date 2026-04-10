#!/bin/bash
set -e

echo "=== Trade Bot Setup ==="
echo ""

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

step() { echo -e "\n${GREEN}[Step $1]${NC} $2"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# ── 1. 모드 선택 ────────────────────────────────────────────
step 1 "거래 모드 선택"

if [ ! -f .env ]; then
  cp .env.example .env
fi

CURRENT_KEY=$(grep "^BINANCE_API_KEY=" .env | cut -d'=' -f2)
if [ -z "$CURRENT_KEY" ]; then
  echo ""
  echo -e "${CYAN}어떤 모드로 실행하시겠습니까?${NC}"
  echo ""
  echo "  1) ${GREEN}Testnet (모의거래)${NC} — 가상 자금으로 테스트"
  echo "     키 발급: https://testnet.binancefuture.com"
  echo ""
  echo "  2) ${RED}Mainnet (실거래)${NC} — 실제 자금으로 거래"
  echo "     키 발급: https://www.binance.com → API Management"
  echo ""
  read -p "  선택 (1 또는 2, 기본: 1): " MODE_CHOICE
  MODE_CHOICE=${MODE_CHOICE:-1}

  if [ "$MODE_CHOICE" = "2" ]; then
    sed -i '' "s|^BINANCE_TESTNET=.*|BINANCE_TESTNET=false|" .env
    echo -e "\n  ${RED}⚠ Mainnet (실거래) 모드${NC}"
    echo -e "  ${YELLOW}실제 자금이 사용됩니다. 신중하게 진행하세요.${NC}"
    KEY_URL="https://www.binance.com → API Management"
  else
    sed -i '' "s|^BINANCE_TESTNET=.*|BINANCE_TESTNET=true|" .env
    echo -e "\n  ${GREEN}Testnet (모의거래) 모드${NC}"
    KEY_URL="https://testnet.binancefuture.com → API Management"
  fi

  # ── 2. API 키 입력 ──────────────────────────────────────────
  echo ""
  echo -e "  ${CYAN}Binance Futures API 키를 입력하세요.${NC}"
  echo "  발급: $KEY_URL"
  echo ""

  read -p "  API Key: " API_KEY
  read -p "  Secret Key: " SECRET_KEY

  if [ -n "$API_KEY" ] && [ -n "$SECRET_KEY" ]; then
    sed -i '' "s|^BINANCE_API_KEY=.*|BINANCE_API_KEY=$API_KEY|" .env
    sed -i '' "s|^BINANCE_API_SECRET=.*|BINANCE_API_SECRET=$SECRET_KEY|" .env
    echo -e "  ${GREEN}API 키 저장 완료${NC}"
  else
    warn "키를 입력하지 않았습니다. .env 파일에서 직접 입력하세요."
  fi
else
  TESTNET=$(grep "^BINANCE_TESTNET=" .env | cut -d'=' -f2)
  if [ "$TESTNET" = "true" ]; then
    echo "  모드: Testnet (모의거래)"
  else
    echo "  모드: Mainnet (실거래)"
  fi
  echo "  API 키 설정됨 (${CURRENT_KEY:0:10}...)"
fi

# ── 3. Python 의존성 ────────────────────────────────────────
step 3 "백엔드 의존성 설치 (uv)"
if ! command -v uv &> /dev/null; then
  echo "  uv 설치 중..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
cd "$ROOT_DIR/backend"
uv sync --quiet
echo "  Python 패키지 설치 완료"

# ── 4. Node 의존성 ──────────────────────────────────────────
step 4 "프론트엔드 의존성 설치 (pnpm)"
if ! command -v pnpm &> /dev/null; then
  echo "  pnpm 설치 중..."
  npm install -g pnpm
fi
cd "$ROOT_DIR/frontend"
pnpm install --silent
echo "  Node 패키지 설치 완료"

# ── 5. 알림 채널 설정 ───────────────────────────────────────
step 5 "알림 채널 설정 (선택)"
CURRENT_TG=$(grep "^ALERT_TELEGRAM_BOT_TOKEN=" "$ROOT_DIR/.env" | cut -d'=' -f2)
if [ -z "$CURRENT_TG" ]; then
  echo ""
  echo -e "  ${CYAN}거래 이벤트 알림을 받으시겠습니까?${NC}"
  echo "  (포지션 진입/청산, 이상 감지 시 Telegram으로 알림)"
  echo ""
  read -p "  Telegram 알림 설정? (y/n, 기본: n): " SETUP_TG
  SETUP_TG=${SETUP_TG:-n}

  if [ "$SETUP_TG" = "y" ] || [ "$SETUP_TG" = "Y" ]; then
    echo ""
    echo "  Telegram Bot 생성: @BotFather에서 /newbot → token 복사"
    echo "  Chat ID 확인: @userinfobot에게 메시지 → chat_id 복사"
    echo ""
    read -p "  Bot Token: " TG_TOKEN
    read -p "  Chat ID: " TG_CHAT_ID

    if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT_ID" ]; then
      sed -i '' "s|^ALERT_TELEGRAM_BOT_TOKEN=.*|ALERT_TELEGRAM_BOT_TOKEN=$TG_TOKEN|" "$ROOT_DIR/.env"
      sed -i '' "s|^ALERT_TELEGRAM_CHAT_ID=.*|ALERT_TELEGRAM_CHAT_ID=$TG_CHAT_ID|" "$ROOT_DIR/.env"
      echo -e "  ${GREEN}Telegram 알림 설정 완료${NC}"
    fi
  else
    echo "  알림 건너뜀 (나중에 .env에서 설정 가능)"
  fi
else
  echo "  Telegram 알림 설정됨"
fi

# ── 6. 데이터 디렉토리 ─────────────────────────────────────
step 6 "데이터 디렉토리 생성"
mkdir -p "$ROOT_DIR/backend/data"
echo "  backend/data/ (SQLite DB)"

# ── 7. API 연결 테스트 ──────────────────────────────────────
step 7 "Binance API 연결 테스트"
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
        err = str(e)
        if '401' in err or '2015' in err:
            print('  ✗ API 키가 유효하지 않습니다.')
            print('    - Testnet 모드인데 Mainnet 키를 입력했거나')
            print('    - Mainnet 모드인데 Testnet 키를 입력한 경우일 수 있습니다.')
            print('    - Futures Testnet 키는 https://testnet.binancefuture.com 에서 발급')
        else:
            print(f'  ✗ 연결 실패: {err}')
    await binance_client.close()

asyncio.run(test())
" 2>&1 || warn "연결 테스트 실패"
else
  warn "API 키 미설정. Paper trading만 동작합니다."
fi

echo ""
echo "=== 설치 완료 ==="
echo ""
echo "실행:"
echo "  make backend    (터미널 1)"
echo "  make frontend   (터미널 2)"
echo ""
echo "브라우저: http://localhost:3000"
echo ""
echo "설정 변경: .env 파일 수정 후 서버 재시작"
echo ""
