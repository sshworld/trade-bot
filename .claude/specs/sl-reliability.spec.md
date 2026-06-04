# Spec S1 — SL 배치 신뢰성 (fix)

## 배경 (중요)
실거래 Binance 선물 봇. 서버 끊김 추정 + SL(손절) 미발화로 ~$40 손실 발생. 근본원인: `_place_sl_order`의 Binance algo 배치 실패가 `try/except: log`로 조용히 삼켜져, SL 없이 포지션만 열리는 무방비 상태가 됨. 텔레그램엔 "SL 배치됨"으로 표시되어 인지 못함. 또 cancel→place 순서라 SL 갱신마다 SL이 잠시 사라지는 윈도우 존재.

회의록: `docs/meeting-minutes/2026-06-04-buffett-dimon-sl-reliability-orphan-fee-overhaul.md` (안건 1).

## 대상 파일
- `backend/app/trading/live_engine.py` — `_place_sl_order`(line ~934-965), `_cancel_sl_order`(~967-976), reconcile_orders/initialize 의 SL 검증
- `backend/app/binance/client.py` — `place_algo_order`(line 216-244)
- 신규 테스트: `backend/tests/trading/test_sl_reliability.py`

## 현재 코드 (live_engine.py `_place_sl_order`)
```python
async def _place_sl_order(self, pos: Position):
    close_side = "SELL" if pos.side == PositionSide.LONG else "BUY"
    await self._cancel_sl_order(pos)                 # ← 먼저 취소 (위험: 이후 실패 시 무방비)
    filled_qty = sum(t.quantity for t in pos.entry_tranches if t.status == OrderStatus.FILLED)
    exited_qty = sum(t.quantity for t in pos.exit_tranches if t.status == OrderStatus.FILLED)
    remaining = filled_qty - exited_qty
    if remaining <= 0:
        return                                       # ← 취소만 하고 재배치 없음
    try:
        result = await binance_client.place_algo_order(
            symbol="BTCUSDT", side=close_side, order_type="STOP_MARKET",
            trigger_price=pos.stop_loss_price.quantize(Decimal("0.1")),
            close_position=True,
        )
        pos.signal_details = pos.signal_details or {}
        algo_id = str(result.get("algoId", ""))
        if algo_id:
            pos.signal_details["sl_algo_id"] = algo_id
        logger.info(...)
    except Exception as e:
        logger.error(f"[LIVE] SL algo order failed: {e}")   # ← 조용히 삼킴
```

## 요구 변경 (정확히)

### 1. `_place_sl_order` — place-before-cancel + 재시도 + 실패시 비상청산
- 순서 변경: **새 SL을 먼저 place → algoId 확인 → 그 다음 기존 SL cancel**. (기존 sl_algo_id를 지역변수에 보관 후, 새 배치 성공 시에만 취소)
- `remaining <= 0`: 기존 SL 취소도 **보류**(아무것도 하지 않고 return — 기존 SL 유지). early-return 시 절대 취소만 하지 않을 것.
- 배치는 **최대 3회 재시도, 각 사이 0.5s 백오프**. 매 시도 후 `result.get("algoId")`가 truthy인지 확인 — 확인돼야 성공.
- 3회 모두 실패(algoId 미확보) → **`_emergency_close(pos, reason="sl_place_failed")` 호출** (즉시 시장가 청산) + `self._manual_halt`류 HALT 설정(`self.anomaly_detector.set_manual_halt("SL place failed")` 사용 — 이 메서드 존재함) + 텔레그램 CRITICAL 알림(`self.alert_sender._send_telegram_text` 또는 send_text).
- 성공 시 새 algoId를 `pos.signal_details["sl_algo_id"]`에 저장하고, 보관해둔 **이전 algoId가 있으면 그것만 cancel**.

### 2. 신규 메서드 `_emergency_close(self, pos, reason)`
- Binance `get_position_risk("BTCUSDT")`로 실제 수량 조회 → 반대 방향 시장가 청산(`place_order` MARKET).
- `_nuke_all_binance_orders()` 호출(잔존 주문 제거 — 이미 존재하는 메서드).
- 로컬 `_close_position(pos.id, 현재가, reason)` 호출.
- 텔레그램 CRITICAL 알림.
- (S2에서 nuke가 강화되지만 지금은 기존 메서드 그대로 사용.)

### 3. client.py `place_algo_order` — Binance -2021 명시 처리
- `_retry_request`가 4xx에서 `raise_for_status()` → httpx.HTTPStatusError 발생. `place_algo_order`에서 이를 잡아 응답 본문의 `"code": -2021`(또는 "would immediately trigger") 감지 시 **커스텀 예외 `AlgoWouldImmediatelyTrigger`(신규, client.py에 정의)** 를 raise. 그 외 에러는 그대로 전파.
- 호출부(`_place_sl_order`): `AlgoWouldImmediatelyTrigger` 잡으면 = SL이 이미 돌파됨 → 재시도 말고 **즉시 `_emergency_close(pos, reason="stop_loss")`**.

### 4. SL 존재 검증 `_assert_sl_armed(self, pos)`
- `get_position_risk`로 positionAmt≠0 확인 → 그렇다면 `pos.signal_details.get("sl_algo_id")`로 `get_algo_order` 조회해 algoStatus가 NEW/WORKING인지 확인.
- 없거나 비활성 → `_place_sl_order(pos)` 1회 재무장. 그래도 실패 → `_emergency_close`.
- 이 메서드를 reconcile_orders 시작부와 initialize의 SL 재배치 루프에서 호출.

## 제약
- **네트워크 호출 금지 테스트**: 모든 Binance 호출은 monkeypatch로 mock.
- 기존 테스트(14개) 깨지 말 것: `cd backend && uv run pytest -q`.
- `anomaly_detector.set_manual_halt(reason)` / `release_manual_halt()` 메서드 이미 존재(활용).
- 서버 재시작·실거래 주문 실제 호출 금지(코드만).
- `PositionSide`, `OrderStatus` 는 `app.trading.schemas`에서 import.

## 테스트 (`backend/tests/trading/test_sl_reliability.py`)
1. `test_place_sl_before_cancel`: place 성공 mock → 새 algoId 저장 + 기존 algoId cancel 호출됨(place 이후 순서).
2. `test_sl_place_retry_then_emergency`: place_algo_order가 3회 모두 algoId 없는 응답/예외 → `_emergency_close` 호출 + halt 설정 확인.
3. `test_sl_would_immediately_trigger`: place_algo_order가 `AlgoWouldImmediatelyTrigger` raise → 재시도 없이 즉시 emergency_close(reason=stop_loss).
4. `test_remaining_zero_keeps_existing_sl`: remaining<=0 → cancel/place 둘 다 호출 안 됨(기존 SL 유지).
5. `test_assert_sl_armed_rearm`: positionAmt≠0 + algo 부재 → _place_sl_order 재호출.

mock 패턴: `monkeypatch.setattr(live_engine.binance_client, "place_algo_order", AsyncMock(...))` 식. 엔진 인스턴스는 기존 테스트(`tests/trading/`)의 픽스처 패턴 참고. LiveTradingEngine 직접 생성이 어려우면 메서드 단위로 self mock.

## 완료 기준
- `grep -qE "_emergency_close|_assert_sl_armed" backend/app/trading/live_engine.py`
- `grep -q "AlgoWouldImmediatelyTrigger" backend/app/binance/client.py`
- 신규 테스트 전부 pass + 기존 테스트 green
- 완료 시 마지막 줄에 `✅ S1 done` 출력. 실패 시 `❌ <이유>`.
