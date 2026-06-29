# Slice S2 — 손절 직후 같은 방향 즉시 재진입 차단 (churn 재발방지) (type: fix)

## 배경 (실거래 봇, 실제 돈)
2026-06-29 churn: 동일 `bearish 1h strength=1.00` 시그널로 숏을 9연속 진입→즉시 손절(8~68초).
손절 직후 같은 방향 재진입을 막는 가드가 없어(5초 시그널 throttle만 존재) 수수료/슬리피지 누수.
이 슬라이스는 **같은 방향 손절 직후 그 방향 신규 진입을 쿨다운 동안 차단**한다.

## 수정 대상
1. `backend/app/trading/schemas.py` — `TradingSettings` 에 설정 추가.
2. `backend/app/trading/live_engine.py` — `on_signal`(158~)에 가드 추가.

## 수정 내용

### schemas.py
`TradingSettings`(라인 ~229 replacement 설정 근처)에 추가:
```python
# 손절 직후 같은 방향 재진입 차단 (churn 방지, 2026-06-29 incident)
reentry_cooldown_after_sl_ms: int = 300_000   # 5분
```
`LiveTradingSettings`는 `TradingSettings` 상속이므로 자동 반영. 별도 override 불필요.

### live_engine.py — on_signal
- 위치: `side` 확정 직후. 현재 라인 247 `side = PositionSide.LONG if signal["direction"]=="bullish" else PositionSide.SHORT` **다음**, 기존 포지션 처리 블록(라인 252 `if self.open_positions:`) **이전**에 삽입.
- 로직: 최근 거래 이력에서 **같은 방향**의 직전 `stop_loss` 청산이 쿨다운 이내면 진입 차단.
```python
# 손절 직후 같은 방향 재진입 쿨다운 (churn 방지)
cooldown_ms = self.settings.reentry_cooldown_after_sl_ms
if cooldown_ms > 0 and self.trade_history:
    last = self.trade_history[-1]
    last_dir_side = PositionSide.LONG if last.side == PositionSide.LONG else PositionSide.SHORT
    if (last.close_reason == "stop_loss"
            and last_dir_side == side
            and now - last.closed_at < cooldown_ms):
        logger.info(f"[LIVE] REJECT: reentry cooldown after SL ({(now-last.closed_at)/1000:.0f}s < {cooldown_ms/1000:.0f}s)")
        return None
```
- `now`는 on_signal 상단에서 이미 정의됨(`now = int(time.time()*1000)`).
- `last.side`는 `PositionSide` enum. `last.close_reason`은 문자열 `"stop_loss"`.
- velocity-brake가 `self.trade_history[-10:]`의 `close_reason == "stop_loss"`를 보는 기존 패턴(on_signal 라인 221-224)과 동일 컨벤션 사용.

### 주의 (정확히 지킬 것)
- **같은 방향만** 차단. 반대방향 반전 진입은 허용(가드 통과). 
- `stop_loss` 청산에만 적용. take_profit/breakeven/time_exit/replaced_by_signal 후에는 차단 안 함.
- 기존 포지션이 열려 있을 때의 동작(같은방향 SL 조임 후 return None, 반대방향 교체)은 **변경 금지** — 가드는 그보다 위에서 신규/교체 양쪽에 적용되지만 같은 방향에 한함.
- 다른 파일(engine.py 등) 수정 금지.

## TDD (Red→Green→Refactor)
새 파일 `backend/tests/trading/test_reentry_cooldown.py`:
1. **Red 핵심**: LiveTradingEngine fixture, `_initialized=True`, `open_positions` 비움. `trade_history`에 방금(`closed_at = now-1000`) `close_reason="stop_loss"`, `side=SHORT` TradeRecord 추가. `await engine.on_signal({bearish short, strength 1.0, ...}, price)` → 반환 `None` 이고 신규 포지션 생성 안 됨(`open_positions` 여전히 빔). 
2. 쿨다운 경과(`closed_at = now - 400_000`) → 진입 허용(가드 통과; 이후 단계는 mock/필터로 적절히).
3. 반대방향(직전 SL이 SHORT인데 새 시그널 bullish/LONG) → 가드 통과(차단 안 함).
4. 직전 청산이 `take_profit` → 차단 안 함.
- Binance 실주문은 mock/patch (기존 test_telegram_commands / test_sl_* 패턴 참고). 가드의 **차단 여부(return None / 포지션 미생성)** 만 검증하면 됨 — 실제 주문까지 안 가도 됨.
- conftest 실DB 격리(autouse) 사용. 실거래 DB 오염 금지.

테스트: `cd backend && uv run pytest -q tests/trading/test_reentry_cooldown.py`
전체 회귀: `cd backend && uv run pytest -q tests/trading/`

## 완료 기준
- 신규 테스트 PASS, 기존 `tests/trading/` 전체 PASS.
- `grep -q "reentry_cooldown_after_sl_ms" backend/app/trading/schemas.py` 및 `.../live_engine.py` 매치.
- engine.py 등 범위 외 파일 수정 없음.
