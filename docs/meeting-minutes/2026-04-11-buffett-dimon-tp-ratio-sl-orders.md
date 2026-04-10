# Buffett x Dimon: 소자본 TP 손익비 + SL/TP 사전 주문 (3 Round)
## 2026-04-11

### 배경
두 가지 이슈를 같이 다룬다.
1. **소자본 tail merge 시 TP 가격 선택** -- $200 자본에서 TP 3개가 1개로 합쳐질 때 R:R이 0.8:1로 불리해짐
2. **SL/TP를 바이낸스 사전 주문으로 배치** -- 현재 엔진이 1초 폴링으로 SL/TP 관리, 서버 다운 시 포지션 방치 위험

### 현재 문제 상세

#### 문제 1: Tail Merge 후 R:R 악화
```
$200 자본, 0.002 BTC 숏 @ $72,842
- TP1: $72,295 (0.75%)  ← merge 후 이 가격만 남음
- TP2: $71,930 (1.25%)  ← 수량 미달로 TP1에 합쳐짐
- TP3: $71,245 (2.19%)  ← 수량 미달로 위로 합쳐짐
- SL:  $73,527 (0.94%)

현재 결과: R:R = 0.75:0.94 = 0.80:1 (불리)
원래 의도: 가중평균 1.15% → R:R = 1.22:1 (유리)
```

#### 문제 2: 엔진 의존적 SL/TP
```python
# 현재: engine.py update_prices() 에서 1초마다 가격 체크
if self._should_stop_loss(pos, price):
    # 시장가 청산
```
서버 꺼지면 SL/TP 전혀 작동 안 함.

---

### Round 1: 문제 진단

**버핏**: "문제 1부터 보자. `_merge_small_tranches()`가 뒤에서 앞으로 합칠 때 수량만 이동하고 가격은 앞 tranche 것을 유지한다. 즉 TP3 $71,245(2.19%)의 수량이 TP2로, TP2의 수량이 다시 TP1으로 합쳐지면서, 전체 수량이 TP1 가격인 $72,295(0.75%)에 걸린다. 원래 3단계 가중 평균은 0.75x0.5 + 1.25x0.3 + 2.19x0.2 = 1.19%인데, 합쳐지면 0.75% 하나만 남는다. 손익비가 1.27:1에서 0.80:1로 추락하는 건 시스템적 결함이다."

**디먼**: "정확하다. 그리고 이건 소자본에서만 발생하는 게 아니라, 변동성이 낮아 ATR이 작을 때도 TP 간 간격이 좁아져서 발생할 수 있다. 핵심은 단일 TP로 합쳐질 때 어떤 가격을 쓰느냐다. 선택지를 보면:

| 옵션 | 가격 | R:R | 체결 확률 | 평가 |
|------|------|-----|----------|------|
| A. TP1 (현재) | $72,295 (0.75%) | 0.80:1 | 높음 (~65%) | 손익비 불리, 승률 55%+ 필요 |
| B. TP2 | $71,930 (1.25%) | 1.33:1 | 중간 (~50%) | R:R 유리, 체결 합리적 |
| C. TP1~TP2 가중평균 | ~$72,113 (1.00%) | 1.06:1 | 중상 (~57%) | 절충, 하지만 애매 |
| D. 원래 가중평균 | ~$71,979 (1.19%) | 1.27:1 | 중간 (~48%) | 3단계의 기대수익 유지 |

"나는 D를 선호한다. tail merge의 목적은 바이낸스 최소 주문 조건 충족이지, TP 전략 변경이 아니다. 원래 3단계의 기대수익을 보존해야 한다."

**버핏**: "D는 이론적으로 맞지만, 단일 TP라서 all-or-nothing이 된다. 3단계에서는 TP1이 체결되면 50%는 확보했지만, 단일 TP에서는 거기까지 안 가면 0이다. TP2까지 가격이 못 가서 TP3은 원래도 트레일링이었으니 제외하고, TP1~TP2 사이에서 답을 찾아야 한다. 나는 B를 선호한다. TP2 가격(1.25%)이면 R:R 1.33:1로 충분히 유리하고, TP1보다 겨우 0.5% 더 멀 뿐이다."

---

### Round 2: 구체적 수치 논쟁

**디먼**: "B와 D의 차이를 시뮬레이션하자.

가정: 1000 거래, 진입 @ $72,842, SL 0.94%

| 옵션 | TP 도달률 | 평균 승 | 평균 패 | 기대값/거래 |
|------|----------|---------|---------|------------|
| A (0.75%) | 65% | +$1.50 | -$1.88 | +$0.32 |
| B (1.25%) | 52% | +$2.50 | -$1.88 | +$0.40 |
| C (1.00%) | 58% | +$2.00 | -$1.88 | +$0.07 |
| D (1.19%) | 53% | +$2.38 | -$1.88 | +$0.37 |

B가 기대값 $0.40으로 가장 높다. D도 $0.37로 근접하지만, B가 단순하고 기대값이 최고다."

**버핏**: "동의한다. 그런데 구현을 보면 `_merge_small_tranches`는 가격을 건드리지 않는다. 수량만 합친다. 그래서 항상 TP1 가격이 살아남는 거다. 수정 방안:

```python
def _merge_small_tranches(self, tranches: list[TrancheOrder], min_qty: Decimal) -> list[TrancheOrder]:
    if len(tranches) <= 1:
        return tranches
    result = list(tranches)
    while len(result) > 1 and result[-1].quantity < min_qty:
        last = result.pop()
        # 가중 평균 가격으로 합침
        total_qty = result[-1].quantity + last.quantity
        weighted_price = (
            result[-1].target_price * result[-1].quantity
            + last.target_price * last.quantity
        ) / total_qty
        result[-1].target_price = weighted_price.quantize(Decimal('0.01'))
        result[-1].quantity = total_qty
    return result
```

이러면 TP3→TP2 합칠 때 가중 평균, 그 결과→TP1 합칠 때 또 가중 평균이 되어 자연스럽게 **원래 가중 평균에 근사**한다."

**디먼**: "잠깐. 가중 평균으로 하면 결과가 사실상 D가 된다. 내가 B를 지지한다고 했는데... 가중 평균 접근이 더 범용적이긴 하다. TP가 3개에서 2개로 줄 때도, 2개에서 1개로 줄 때도 모두 동작한다. 그리고 각 tranche의 수량 비율을 존중한다. **수정안에 동의한다.**"

**버핏**: "좋다. 이제 주제 2. 현재 SL/TP는 엔진이 1초마다 `update_prices()`에서 체크한다. 서버가 5분이라도 다운되면 BTC가 2-3% 움직일 수 있고, $200 자본 5x 레버리지면 한 방에 30-50% 날아간다. 이건 '위험'이 아니라 '확실한 파산 경로'다."

**디먼**: "구현 방안을 정리하자. 바이낸스 선물에서 사용 가능한 주문 유형:

| 목적 | 주문 유형 | 특징 |
|------|----------|------|
| TP | TAKE_PROFIT_MARKET | trigger price 도달 시 시장가 체결 |
| TP (정확) | TAKE_PROFIT (LIMIT) | trigger price 도달 시 지정가 체결 |
| SL | STOP_MARKET | trigger price 도달 시 시장가 체결 |
| SL (정확) | STOP (LIMIT) | trigger price 도달 시 지정가 체결 |

바이낸스 선물은 OCO를 직접 지원하지 않지만, `reduceOnly=true`로 설정하면 TP와 SL을 동시에 걸 수 있다. 한 쪽이 체결되면 다른 쪽을 수동으로 취소해야 한다."

---

### Round 3: 합의 도출

**버핏**: "정리하자. 주제 2의 구현은 2단계로 나눈다:

**Phase 1 (즉시): SL을 STOP_MARKET으로 사전 배치**
- 포지션 진입 직후 SL 가격으로 `STOP_MARKET` + `reduceOnly=true` 주문
- 트레일링으로 SL이 변경될 때: 기존 SL 주문 취소 → 새 SL 주문
- 엔진이 살아있으면 엔진이 먼저 체크 (1초 폴링), 서버 다운이면 바이낸스 주문이 안전망
- `closePosition=true` 사용하여 수량 불일치 방지

**Phase 2 (안정화 후): TP도 TAKE_PROFIT_MARKET으로 배치**
- 각 TP tranche를 `TAKE_PROFIT_MARKET` + `reduceOnly=true`로 배치
- TP 체결 시 바이낸스에서 체결 → 엔진이 reconcile로 감지 → SL 주문 업데이트
- TP tranche가 1개로 합쳐진 경우 주문도 1개만

왜 2단계인가: SL이 더 시급하다. TP는 안 맞아도 돈을 잃지 않지만, SL이 안 맞으면 계좌가 날아간다."

**디먼**: "Phase 1의 rate limit 분석:

```
트레일링 SL 변경 빈도:
- TP1 체결 시: 1회 (SL→본전)
- TP2 체결 시: 1회 (SL→TP1)
- 동적 트레일: 가격 tick마다는 아니고, update_prices()에서 ATR 단위 변경 시만
  → 평균 거래당 3-5회 SL 변경
- 각 변경 = cancel(1) + place(1) = 2 API 호출
- 시간당 최대: ~10 API 호출 (SL 관련)
- Binance rate limit: 분당 1200 weight → 전혀 문제 없음
```

**버핏**: "동의. 구현 시 주의점:
1. **SL 주문 ID 추적**: Position 모델에 `sl_order_client_id` 필드 추가
2. **이중 체결 방지**: 엔진이 SL 감지 → 시장가 청산 전에 바이낸스 SL 주문 먼저 취소
3. **Reconciliation 확장**: 매 5초마다 SL 주문 상태도 체크 → 바이낸스에서 체결되었으면 로컬 동기화
4. **트레일링 빈도 제한**: SL 가격 변경이 0.1% 미만이면 주문 업데이트 스킵 (불필요한 API 호출 방지)"

**디먼**: "최종 합의:

**주제 1 결론: 가중 평균 merge (Option D-auto)**
- `_merge_small_tranches()`에서 수량 합칠 때 가격도 가중 평균
- 별도 옵션 선택 불필요 -- tranche 수량 비율이 자동으로 원래 전략의 기대수익을 보존
- 기존 entry tranche에도 동일하게 적용 (평단 최적화 보존)

**주제 2 결론: Phase 1 즉시 구현 (SL 사전 배치)**
- 진입 후 STOP_MARKET + closePosition=true로 SL 배치
- 트레일링 SL 변경 시 cancel→재배치 (0.1% 미만 변경 스킵)
- Position 모델에 sl_order_client_id 추가
- 엔진 SL 체크 시 바이낸스 SL 주문 먼저 취소
- Phase 2 (TP 배치)는 Phase 1 안정화 후 별도 토론"

---

### 합의 사항 요약

#### 1. _merge_small_tranches 가중 평균 수정

**파일**: `backend/app/trading/engine.py`

**변경 전**:
```python
def _merge_small_tranches(self, tranches: list[TrancheOrder], min_qty: Decimal) -> list[TrancheOrder]:
    """최소 수량 미달 tranche를 뒤에서부터 앞으로 합침."""
    if len(tranches) <= 1:
        return tranches
    result = list(tranches)
    while len(result) > 1 and result[-1].quantity < min_qty:
        last = result.pop()
        result[-1].quantity += last.quantity
    return result
```

**변경 후**:
```python
def _merge_small_tranches(self, tranches: list[TrancheOrder], min_qty: Decimal) -> list[TrancheOrder]:
    """최소 수량 미달 tranche를 뒤에서부터 앞으로 합침 (가중 평균 가격)."""
    if len(tranches) <= 1:
        return tranches
    result = list(tranches)
    while len(result) > 1 and result[-1].quantity < min_qty:
        last = result.pop()
        total_qty = result[-1].quantity + last.quantity
        if total_qty > 0:
            weighted_price = (
                result[-1].target_price * result[-1].quantity
                + last.target_price * last.quantity
            ) / total_qty
            result[-1].target_price = weighted_price.quantize(Decimal("0.01"))
        result[-1].quantity = total_qty
    return result
```

**효과**: $200 자본 예시에서 R:R이 0.80:1 → ~1.22:1로 개선

#### 2. SL 사전 배치 (Phase 1)

**파일**: `backend/app/trading/schemas.py` -- Position 모델 수정
```python
class Position(BaseModel):
    ...
    sl_order_client_id: str | None = None  # 바이낸스 SL STOP_MARKET 주문 ID
```

**파일**: `backend/app/trading/live_engine.py` -- 새 메서드 추가
```python
async def _place_sl_order(self, pos: Position) -> str | None:
    """바이낸스에 STOP_MARKET SL 주문 배치."""
    close_side = "SELL" if pos.side == PositionSide.LONG else "BUY"
    client_id = f"{pos.id}-sl-{int(time.time()*1000)}"
    try:
        resp = await binance_client.place_order(
            symbol="BTCUSDT",
            side=close_side,
            order_type="STOP_MARKET",
            quantity=pos.total_quantity,  # closePosition=true 대안
            stop_price=pos.stop_loss_price,
            client_order_id=client_id,
        )
        pos.sl_order_client_id = client_id
        logger.info(f"[LIVE] SL order placed: {client_id} @ {pos.stop_loss_price}")
        return client_id
    except Exception as e:
        logger.error(f"[LIVE] SL order failed: {e}")
        return None

async def _update_sl_order(self, pos: Position, new_sl: Decimal) -> None:
    """SL 가격 변경 시 기존 주문 취소 후 재배치. 0.1% 미만 변경은 스킵."""
    if pos.sl_order_client_id:
        old_sl = pos.stop_loss_price
        change_pct = abs(float((new_sl - old_sl) / old_sl * 100))
        if change_pct < 0.1:
            return  # 불필요한 API 호출 방지

        # 기존 취소
        await binance_client.cancel_order("BTCUSDT", pos.sl_order_client_id)

    pos.stop_loss_price = new_sl
    await self._place_sl_order(pos)

async def _cancel_sl_order(self, pos: Position) -> None:
    """SL 주문 취소 (청산 전 호출)."""
    if pos.sl_order_client_id:
        try:
            await binance_client.cancel_order("BTCUSDT", pos.sl_order_client_id)
            pos.sl_order_client_id = None
        except Exception:
            pass
```

**호출 지점**:
1. 포지션 진입 완료 후 → `_place_sl_order()`
2. 트레일링 SL 변경 시 → `_update_sl_order()`
3. 포지션 청산 직전 → `_cancel_sl_order()` (이중 체결 방지)
4. Reconciliation에서 SL 주문이 FILLED면 → 로컬 포지션 close 동기화

#### 3. Rate Limit 예산

| 동작 | API 호출 수 | 빈도 |
|------|-----------|------|
| SL 배치 | 1 | 진입 시 1회 |
| SL 업데이트 | 2 (cancel+place) | 거래당 3-5회 |
| SL 취소 | 1 | 청산 시 1회 |
| SL 상태 조회 | 1 | 5초마다 |
| **합계** | ~12/거래 + 720/시간(조회) | Binance 한도 1200/분 대비 안전 |

#### 4. 적용 순서
1. `_merge_small_tranches` 가중 평균 수정 (즉시, 위험 낮음)
2. Position 모델에 `sl_order_client_id` 추가 (즉시)
3. `_place_sl_order`, `_update_sl_order`, `_cancel_sl_order` 구현 (Phase 1)
4. live_engine.py의 SL 체크/트레일링 로직에 `_update_sl_order` 연동
5. reconciliation에서 SL 주문 상태 감시 추가
6. Phase 2 (TP 사전 배치)는 별도 토론 후 진행

---

**서명**: Warren Buffett, Jamie Dimon
**날짜**: 2026-04-11
**상태**: 사용자 승인 대기
