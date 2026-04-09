# Buffett × Dimon: 개발자 반론 최종 정리
## 2026-04-09

### 1. Manual Halt → 제거. 자동 이상 감지 + 알림으로 대체.
- 수동 버튼은 무인 운영에서 무의미
- 대체:
  - **Auto-halt**: 이상 패턴 감지 시 자동 중단 (10분 내 5주문, daily loss 초과 등)
  - **알림**: Telegram/webhook으로 중단 사실 통보
  - **Watchdog**: 외부 프로세스로 봇 생존 확인 (cron/systemd)

### 2. Crash Window → "waiting" status 저장으로 해결.
- 복잡한 분산 시스템 문제가 아님. 단순한 상태 추적.
- 플로우:
  1. `status="waiting"` + `client_order_id` DB 저장
  2. Binance API 호출
  3. `status="filled"` 또는 `"failed"` 업데이트
  4. 시작 시: `"waiting"` 레코드 → `client_order_id`로 Binance 조회 → 동기화
- 핵심: `client_order_id`를 미리 생성하여 저장해야 Binance 쪽과 매칭 가능
