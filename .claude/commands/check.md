# /check — 시스템 전체 상태 점검

현재 시스템 상태를 전부 확인하고 보고합니다.

## 점검 항목 (순서대로 실행)

1. **백엔드 상태**: `curl http://localhost:8000/api/health` — kline_store 로드 여부
2. **프론트엔드**: `curl http://localhost:3000/dashboard` — 200 OK 확인
3. **Trading 상태**: `curl http://localhost:8000/api/trading/status` — 잔고, 포지션 수, 수수료
4. **열린 포지션**: `curl http://localhost:8000/api/trading/positions` — 상세 (side, entry, PnL, SL, TP)
5. **시그널 스캔**: `curl http://localhost:8000/api/analysis/scan` — 각 TF별 bull/bear/confluence
6. **Trend Context**: `curl http://localhost:8000/api/analysis/trend-context` — 방향/강도
7. **거래 기록**: `curl http://localhost:8000/api/trading/history` — 총 건수, 최근 거래
8. **WebSocket**: 연결 상태 확인

결과를 한 테이블로 정리해서 보여주세요.
문제가 있으면 원인과 해결 방법도 함께 알려주세요.
