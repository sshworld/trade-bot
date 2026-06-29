# Slice S1 — 시장가 청산 PnL=0 회계 버그 수정 (type: fix)

## 배경 (실거래 봇, 실제 돈 — 정확성 최우선)
시장가 청산(SL/시간/교체/emergency)의 청산 손익이 `realized_pnl=0`으로 기록되는 버그.
DB ground truth: 손절 9건이 `close_reason=stop_loss`인데 `realized_pnl=0` (실제론 각 약 −1.5 손실).

### 버그 메커니즘 (검증 완료)
- `backend/app/trading/live_engine.py` `_live_close_position`(566~) STEP1 직후 (라인 576-578):
  로컬 `pos.entry_tranches + pos.exit_tranches` 중 PENDING/WAITING → **CANCELLED** 로 미리 변경.
- 부모 `backend/app/trading/engine.py` `_close_position`(439~) 라인 445-456:
  청산 PnL을 **WAITING/PENDING exit tranche 수량 합(`remaining_qty`)** 으로만 계산.
  → 이미 CANCELLED라 `remaining_qty=0` → PnL 계산 블록 skip → `pos.realized_pnl=0`.
- 실제 청산 MARKET 주문(`_live_close_position` STEP2)의 손익은 어디에도 귀속 안 됨.
- TP 청산은 reconcile에서 `pos.realized_pnl += _calc_tranche_pnl`(live_engine.py:743-744)로 적립돼 정상 → **건드리지 말 것**.

## 수정 대상
`backend/app/trading/engine.py` 의 `_close_position` (라인 439~515).

## 수정 내용
청산 PnL을 **tranche 상태가 아니라 실제 열려있던 수량** 기준으로 계산한다.

핵심 공식:
```
filled_exit_qty  = sum(t.quantity for t in pos.exit_tranches if t.status == FILLED)
closed_open_qty  = pos.total_quantity - filled_exit_qty   # 이번 청산이 닫는 실제 오픈 수량
```
- `closed_open_qty > 0 and pos.avg_entry_price` 이면:
  - `pnl = self._calc_pnl(pos.side, pos.avg_entry_price, price, closed_open_qty, pos.leverage)`
  - `pos.realized_pnl += pnl`
  - `fee = self._calc_fee(price, closed_open_qty, is_market=True)`; `pos.total_fees += fee`; `self.account.balance -= fee`
- 기존 PENDING/WAITING tranche 의 status=CANCELLED 정리 루프(라인 445-453)는 **그대로 유지**(주문 정리 목적). 단, **PnL 계산을 그 `remaining_qty`에 의존하지 않게** 바꾼다.
- 이미 체결된 exit tranche의 PnL은 reconcile에서 이미 `pos.realized_pnl`에 적립됐으므로 **여기서 중복 가산 금지** (그래서 `total_quantity - filled_exit_qty`만 계산).
- 하단 `avg_exit` 계산(라인 470-480)은 표시용이므로 의미 유지(필요시 `closed_open_qty` 기준으로 일관화). `pnl_pct`(라인 482-483)는 갱신된 `pos.realized_pnl` 기준 그대로.

### 중요 — Paper 경로 회귀 불변
Paper 엔진은 `_close_position` 호출 시 exit tranche가 WAITING(취소 안 됨)이고 `remaining_qty == 열린수량`이라 기존과 동일 결과가 나와야 한다. 새 공식 `total_quantity - filled_exit_qty`도 같은 값을 줘야 하므로 결과 불변. 반드시 회귀 테스트로 확인.

### Live override 보존
`live_engine.py:1226 _close_position` 의 `price <= 0` → `trade.realized_pnl=0` 무효화 분기는 **절대 건드리지 말 것**(emergency 가격불명 시 오염 방지).

## TDD (Red→Green→Refactor)
새 파일 `backend/tests/trading/test_close_pnl_accounting.py`:
1. **Red 핵심**: PaperTradingEngine(또는 적절한 fixture)로 숏 포지션 구성 — `avg_entry_price=Decimal("59500")`, `total_quantity=Decimal("0.005")`, `allocated_margin>0`, exit_tranches를 **CANCELLED 상태**(실제 live close 직전 상태 모사)로 둠. `_close_position(pos_id, Decimal("59750"), "stop_loss")` 호출 → `trade.realized_pnl == (59500-59750)*0.005 == Decimal("-1.25")` (기존 코드면 0). 
2. 부분 TP 후 청산: exit 1개 FILLED(이미 PnL 적립), 나머지 오픈 → 중복 가산 없이 잔여 오픈수량만 계산되는지.
3. **회귀**: 정상 Paper 경로(exit tranche WAITING 유지)에서 청산 PnL이 수정 전과 동일한지.
4. conftest 실DB 격리 사용(기존 `backend/tests/conftest.py` autouse). 실거래 DB 오염 금지.

테스트 실행: `cd backend && uv run pytest -q tests/trading/test_close_pnl_accounting.py`
전체 회귀: `cd backend && uv run pytest -q tests/trading/`

## 완료 기준
- 신규 테스트 PASS, 기존 `tests/trading/` 전체 PASS.
- `grep -qE "filled_exit_qty|closed_open_qty" backend/app/trading/engine.py` 매치.
- 다른 파일(live_engine.py, schemas.py) 수정 금지 — 이 슬라이스는 engine.py + 신규 테스트만.
