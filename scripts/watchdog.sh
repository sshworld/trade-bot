#!/bin/bash
# WebSocket Watchdog
# 30초마다 backend status를 체크해서 stale_price halt이거나 응답 없으면 서버 재시작

LOG_FILE="/tmp/trade-bot-watchdog.log"
BACKEND_DIR="/Users/sshworld/project/trade/trade-bot/backend"
CHECK_INTERVAL=30
STALE_THRESHOLD=120  # 초

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

restart_server() {
    log "🔄 RESTARTING server..."
    pkill -f "uvicorn app.main:app" 2>/dev/null
    sleep 2
    cd "$BACKEND_DIR"
    export PATH="$HOME/.local/bin:$PATH"
    nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/trade-bot-server.log 2>&1 &
    sleep 5
    log "✅ Server restarted (PID: $!)"
}

log "🟢 Watchdog started (interval=${CHECK_INTERVAL}s, stale=${STALE_THRESHOLD}s)"

while true; do
    # 1. Backend 응답 체크
    response=$(curl -s --max-time 5 'http://localhost:8000/api/trading/status' 2>&1)

    if [ -z "$response" ] || ! echo "$response" | grep -q "balance"; then
        log "❌ Backend NOT responding"
        restart_server
        sleep "$CHECK_INTERVAL"
        continue
    fi

    # 2. stale_price halt 체크
    halt_reason=$(echo "$response" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('anomaly',{}).get('halt_reason',''))" 2>/dev/null)

    if echo "$halt_reason" | grep -q "stale_price"; then
        log "⚠️ Stale price halt detected: $halt_reason"
        restart_server
        sleep "$CHECK_INTERVAL"
        continue
    fi

    # 3. Ticker API 체크 (실시간 데이터 확인)
    ticker=$(curl -s --max-time 5 'http://localhost:8000/api/market/ticker?symbol=BTCUSDT' 2>&1)

    if [ -z "$ticker" ] || ! echo "$ticker" | grep -q "price"; then
        log "❌ Ticker API failed"
        restart_server
        sleep "$CHECK_INTERVAL"
        continue
    fi

    log "✅ OK - $(echo $ticker | python3 -c "import sys,json;d=json.load(sys.stdin);print(f\"price=\${d['price']}\")" 2>/dev/null)"

    sleep "$CHECK_INTERVAL"
done
