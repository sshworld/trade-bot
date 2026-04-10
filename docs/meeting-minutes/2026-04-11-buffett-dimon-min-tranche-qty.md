# Buffett x Dimon: 분할 진입 Tranche 최소 수량 — Binance 최소 노셔널 문제 해결
## 2026-04-11

---

## 배경

현재 시스템은 WITH_TREND 진입 시 50/30/20 비율로 3분할 진입한다.

**문제 시나리오:**
- 자본: $200, 레버리지: 5x, 리스크: 2%
- 계산된 총 노셔널: ~$460, 총 수량: ~0.005 BTC (@$92,000)
- 3분할 결과: 0.003 / 0.001 / 0.001 BTC
- 0.001 BTC x $92,000 = $92 < **Binance 최소 노셔널 $100**
- 2번째, 3번째 tranche 주문이 Binance에서 거부됨

현재 코드 (`engine.py:732-743`)에서 `_create_entry_tranches()`는 단순히 split 비율로 수량을 나눌 뿐, 개별 tranche의 노셔널 검증이 없다.

---

## Round 1: 고정 최소 수량 vs 동적 계산

### Warren Buffett (자본 보존)

문제의 핵심을 짚자. 우리는 **수학적으로 유효한 주문이 거래소에서 거부되는** 상황을 겪고 있다. 이건 전략 문제가 아니라 **인프라 호환성** 문제다.

0.002 BTC 고정이라는 제안부터 검토하겠다:

| BTC 가격 | 0.002 BTC 노셔널 | 최소($100) 충족? |
|-----------|------------------|-----------------|
| $40,000 | $80 | **미달** |
| $50,000 | $100 | 경계 (위험) |
| $72,800 | $145.60 | 충족 |
| $92,000 | $184 | 충족 |
| $100,000 | $200 | 충족 |
| $120,000 | $240 | 과잉 여유 |

BTC가 $50,000 아래로 내려가면 0.002로도 부족하다. **고정값은 미래를 보장하지 못한다.** 내가 투자할 때 항상 하는 말이 있다 -- "가격이 변하면 가정도 바뀌어야 한다."

**동적 최소 수량을 계산해야 한다:**
```
min_tranche_qty = ceil($110 / current_price, step=0.001)
```
$100이 아니라 **$110**으로 10% 버퍼를 둔다. 왜? 주문 시점과 체결 시점의 가격 차이, 소수점 반올림 오차를 흡수해야 하기 때문이다.

### Jamie Dimon (기관 리스크)

Buffett 의견에 동의하면서 한 가지를 추가한다. **기관 트레이딩 데스크에서는 거래소 제약을 항상 동적으로 처리한다.** 고정 하드코딩은 프로토타이프에서나 쓴다.

그러나 완전 동적 계산의 **복잡성 비용**도 따져야 한다:

1. **계산 자체는 단순하다.** `ceil(110 / price, 0.001)` -- 한 줄이다.
2. **문제는 이 값이 분할 로직 전체에 영향을 준다는 것이다.** tranche qty가 최소값 미만이면 합쳐야 하고, 합치는 로직이 진입 전략의 의미를 바꿀 수 있다.
3. **Binance가 최소 노셔널을 올릴 수도 있다.** 현재 $100이지만 과거 $5 -> $10 -> $100으로 올라왔다. 설정으로 빼둬야 한다.

내 제안: `min_notional`은 이미 `LiveTradingSettings`에 있다 ($100). 여기에 **버퍼 계수**를 추가하고, tranche 최소 수량은 런타임에 계산한다.

---

## Round 2: 합치는 로직 설계

### Warren Buffett

동적 최소 수량에 합의했으니, 핵심 질문으로 넘어가자: **최소 미달 tranche를 어떻게 처리하는가?**

세 가지 옵션이 있다:

**옵션 A: 뒤에서부터 앞으로 합치기 (tail merge)**
```
원래: 0.003 / 0.001 / 0.001  (min=0.002)
-> 3번째 0.001 < 0.002 → 2번째에 합침 → 0.003 / 0.002
-> 2분할로 축소
```

**옵션 B: 균등 재분배**
```
원래: 0.005 total, min=0.002
-> 0.005 / 0.002 = 2.5 → 2개 tranche
-> 0.003 / 0.002 또는 0.002 / 0.003
```

**옵션 C: 해당 tranche 스킵 (앞에 합치지 않음)**
```
원래: 0.003 / 0.001 / 0.001
-> 2,3번째 스킵 → 0.003만 시장가 → 사실상 일괄 진입
```

나는 **옵션 A (tail merge)**를 지지한다. 이유:

1. **첫 tranche는 항상 시장가(market order)다.** 이것은 건드리면 안 된다 -- 즉시 체결의 의미가 있다.
2. **뒤에서부터 합치면 "평단 최적화"의 본질이 유지된다.** 첫 50%는 그대로, 나머지가 2번째 가격에 합쳐지면 평단 효과는 여전히 발생한다.
3. **마지막 tranche(가장 역행한 가격)의 수량이 작아서 합쳐지는 것은 자연스럽다.** 가격이 그렇게 많이 역행하면 SL이 먼저 작동할 가능성이 높다.

### Jamie Dimon

옵션 A에 동의한다. 그리고 **엣지 케이스**를 명확히 해야 한다:

**케이스 1: 총 수량 자체가 min_tranche_qty 미만**
```
total_qty = 0.001 < min_tranche_qty = 0.002
```
이 경우 **분할 없이 전액 시장가 진입**이 맞다. 그런데 0.001 x $92,000 = $92 < $100이므로 이미 `min_notional` 체크에서 걸린다. 즉, 이 케이스는 **상위 레벨에서 이미 거부된다.** 별도 처리 불필요.

**케이스 2: total_qty >= min_tranche_qty but 분할하면 미달**
```
total_qty = 0.003, min_tranche_qty = 0.002
-> 50/30/20 = 0.002 / 0.001 / 0.000
-> 2,3번째 미달 → 모두 1번째에 합침 → 0.003 시장가 일괄 진입
```
이것도 괜찮다. 소자본에서 일괄 진입은 자연스럽다.

**케이스 3: 합쳐도 여전히 미달**
```
total_qty = 0.004, min_tranche_qty = 0.002
-> 50/30/20 = 0.002 / 0.001 / 0.001
-> 3번째를 2번째에 합침 → 0.002 / 0.002 → 둘 다 충족!
```
tail merge가 잘 작동하는 케이스다.

**합치는 알고리즘:**
```
1. 뒤에서부터 순회 (마지막 → 첫 번째)
2. 현재 tranche qty < min_tranche_qty이면:
   a. 바로 앞 tranche에 qty 합산
   b. 현재 tranche 제거
3. 합산 후에도 앞 tranche가 min_tranche_qty 미만이면 → 그 앞으로 계속 합침
4. 최종적으로 첫 tranche만 남으면 → 일괄 시장가 진입
```

---

## Round 3: 구체적 구현 합의

### Warren Buffett

최종 정리하겠다. 코드 변경 범위를 명확히 하자.

**1. `LiveTradingSettings`에 추가할 파라미터:**
```python
min_notional_buffer: float = 1.10  # 최소 노셔널에 10% 버퍼
```
기존 `min_notional = $100`과 함께 사용. tranche 최소 수량 계산:
```python
min_tranche_notional = min_notional * min_notional_buffer  # $110
min_tranche_qty = ceil(min_tranche_notional / current_price, 0.001)
```

**2. `_create_entry_tranches()` 수정:**

현재 `engine.py:724-744`의 함수를 수정하되, **PaperTradingEngine에서도 동작해야 한다.** Paper에는 min_notional이 없으므로, 파라미터로 min_tranche_qty를 받되 기본값을 None(=검증 안 함)으로 설정.

```python
def _create_entry_tranches(
    self, side, base_price, total_qty, pos_id, now,
    offsets_override=None, split_override=None,
    min_tranche_qty=None,  # 추가
) -> list[TrancheOrder]:
    # 기존 로직으로 tranches 생성
    ...
    # min_tranche_qty가 있으면 tail merge
    if min_tranche_qty:
        tranches = self._merge_small_tranches(tranches, min_tranche_qty)
    return tranches
```

**3. `_merge_small_tranches()` 새 메서드:**
```python
def _merge_small_tranches(
    self, tranches: list[TrancheOrder], min_qty: Decimal,
) -> list[TrancheOrder]:
    """뒤에서부터 최소 수량 미달 tranche를 앞에 합침."""
    while len(tranches) > 1:
        last = tranches[-1]
        if last.quantity >= min_qty:
            break
        # 마지막 tranche를 그 앞에 합침
        tranches[-2].quantity += last.quantity
        tranches.pop()
    return tranches
```

**4. LiveTradingEngine의 `open_position()`에서 호출:**
```python
min_tranche_notional = self.settings.min_notional * Decimal(str(self.settings.min_notional_buffer))
min_tranche_qty = (min_tranche_notional / current_price).quantize(Decimal("0.001"), rounding=ROUND_UP)

entry_tranches = self._create_entry_tranches(
    side, current_price, total_qty, pos_id, now,
    offsets_override=entry_offsets, split_override=entry_split,
    min_tranche_qty=min_tranche_qty,
)
```

### Jamie Dimon

완벽하다. 몇 가지 보완:

**5. Exit tranche에도 같은 로직 필요:**

Exit tranche(TP1/TP2/TP3)도 동일한 문제가 발생할 수 있다. `_create_exit_tranches()`에도 같은 `min_tranche_qty` 파라미터와 tail merge를 적용해야 한다.

**6. 로깅 강화:**

tranche가 합쳐질 때 반드시 로그를 남겨야 한다:
```python
logger.info(f"[TRANCHE] Merged: {original_count} -> {len(tranches)} tranches "
            f"(min_qty={min_qty}, total_qty={total_qty})")
```

이것은 디버깅과 전략 검증에 필수적이다. 합쳐지는 빈도가 너무 높으면 자본이 분할 진입에 적합하지 않다는 신호다.

**7. 텔레그램 알림에 분할 수 포함:**

포지션 오픈 알림에 `"Entry: 2/3 tranches (1 merged due to min notional)"` 같은 정보를 포함하면 운영자가 상황을 인지할 수 있다.

---

## 최종 합의

| 항목 | 결정 |
|------|------|
| 최소 수량 방식 | **동적 계산** (`ceil(min_notional * 1.10 / price, 0.001)`) |
| 고정 0.002 BTC | **기각** (BTC $50K 미만에서 깨짐) |
| 합치는 방식 | **Tail merge** (뒤에서부터 앞으로 합침) |
| 적용 범위 | Entry + Exit tranches 모두 |
| 새 파라미터 | `min_notional_buffer: float = 1.10` in `LiveTradingSettings` |
| Paper engine | min_tranche_qty=None (검증 없음, 시뮬레이션이므로) |
| 총 수량 < 최소 | 상위 min_notional 체크에서 이미 거부됨 |
| 로깅 | 합침 발생 시 INFO 로그 필수 |

### 코드 변경 요약

**파일 1: `backend/app/trading/schemas.py`**
- `LiveTradingSettings`에 `min_notional_buffer: float = 1.10` 추가

**파일 2: `backend/app/trading/engine.py`**
- `_create_entry_tranches()`에 `min_tranche_qty` 파라미터 추가
- `_create_exit_tranches()`에 `min_tranche_qty` 파라미터 추가
- `_merge_small_tranches()` 새 메서드 추가

**파일 3: `backend/app/trading/live_engine.py`**
- `open_position()`에서 동적 `min_tranche_qty` 계산 후 전달
- exit tranche 생성 시에도 동일하게 전달

### 수치 검증

| 자본 | BTC가격 | 총 qty | min_tranche_qty | 원래 분할 | merge 후 |
|------|---------|--------|-----------------|-----------|----------|
| $200 | $92,000 | 0.005 | 0.002 | 0.003/0.001/0.001 | 0.003/0.002 (2분할) |
| $200 | $72,800 | 0.006 | 0.002 | 0.003/0.002/0.001 | 0.003/0.003 (2분할) |
| $200 | $50,000 | 0.009 | 0.003 | 0.005/0.003/0.001 | 0.005/0.004 (2분할) |
| $200 | $40,000 | 0.011 | 0.003 | 0.006/0.003/0.002 | 0.006/0.003/0.002 (3분할 유지) |
| $500 | $92,000 | 0.012 | 0.002 | 0.006/0.004/0.002 | 0.006/0.004/0.002 (3분할 유지) |
| $1000 | $92,000 | 0.024 | 0.002 | 0.012/0.007/0.005 | 0.012/0.007/0.005 (3분할 유지) |

자본이 커지면 자연스럽게 3분할이 유지된다. 소자본에서만 2분할 또는 일괄 진입으로 자동 조정된다.

---

*Buffett: "시장은 변하고, 가격도 변한다. 고정값에 의존하지 마라."*
*Dimon: "거래소 제약은 설정으로 빼고, 로직은 동적으로 처리하라. 기관의 기본이다."*
