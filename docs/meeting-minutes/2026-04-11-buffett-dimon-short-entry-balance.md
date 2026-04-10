# Buffett x Dimon 토론: 숏 분할 진입 방향 + Live 잔고 관리

**일시**: 2026-04-11  
**참석**: Warren Buffett (자본 보존 최우선), Jamie Dimon (기관 리스크 관리)  
**주제 1**: WITH_TREND 숏 진입 시 offset 방향을 반전해야 하는가?  
**주제 2**: Live 엔진의 잔고 관리를 Binance 실잔고 기준으로 전환할 것인가?

---

## 주제 1: 숏 분할 진입 방향 수정

### 현행 코드

```python
# _create_entry_tranches() — engine.py L736-739
if side == PositionSide.LONG:
    target = base_price * (1 + Decimal(str(offset / 100)))
else:
    target = base_price * (1 - Decimal(str(offset / 100)))
```

WITH_TREND offsets = [0.0, +0.3, +0.6]:

| Tranche | LONG target | 의미 | SHORT target | 의미 |
|---------|-------------|------|-------------|------|
| 0 | base * 1.000 | 즉시 | base * 1.000 | 즉시 |
| 1 | base * 1.003 | +0.3% 올라야 체결 | base * 0.997 | -0.3% 내려야 체결 |
| 2 | base * 1.006 | +0.6% 올라야 체결 | base * 0.994 | -0.6% 내려야 체결 |

COUNTER_TREND offsets = [0.0, -0.3]:

| Tranche | LONG target | 의미 | SHORT target | 의미 |
|---------|-------------|------|-------------|------|
| 0 | base * 1.000 | 즉시 | base * 1.000 | 즉시 |
| 1 | base * 0.997 | -0.3% 물타기 | base * 1.003 | +0.3% 물타기 |

### 문제 분석

**LONG WITH_TREND**: 가격이 올라갈 때 추가 매수 → 방향 확인, 평단 불리 (비싸게 삼)  
**SHORT WITH_TREND**: 가격이 내려갈 때 추가 매도 → 방향 확인, 평단 불리 (싸게 팖)

사용자 제안: SHORT에서 offset을 반대로 적용하여 가격이 올라갈 때 추가 매도 → 평단 유리 (비싸게 팖)

---

## Round 1: 기본 입장

### Warren Buffett (현행 유지 — WITH_TREND 방향 확인)

> "이 논의의 핵심을 짚겠네. LONG에서 +0.3% 오를 때 추가 매수하는 건 '시장이 내 방향으로 움직이고 있다'는 확인이야. SHORT에서 -0.3% 내릴 때 추가 매도하는 것도 정확히 같은 논리지 — '시장이 내 방향으로 움직이고 있다'는 확인이야."

- **확인 진입의 가치**: WITH_TREND는 이름 자체가 '추세를 따른다'는 뜻. 추세가 맞는지 확인한 후 추가하는 것이 원래 의도
- **평단 불리 = 보험료**: +0.3% 비싸게 사거나 -0.3% 싸게 파는 건 "방향이 맞다"는 확인에 대한 보험료. 방향이 틀렸을 때 나머지 50%가 체결되지 않아 손실이 줄어듦
- **수치 예시**:
  - SHORT @ $80,000, 3 tranche (50/30/20)
  - 현행: 즉시 50%, $79,760(−0.3%) 30%, $79,520(−0.6%) 20%
  - 가격이 반등하면 → tranche 1,2 미체결 → 50%만 손실
  - 제안대로라면: 즉시 50%, $80,240(+0.3%) 30%, $80,480(+0.6%) 20%
  - 가격이 반등하면 → tranche 1,2 체결 → 100% 포지션 진입 후 전체 손실

> "평단이 유리하다는 건 반만 맞는 말이야. 가격이 올라갈 때 숏을 추가한다는 건, 역행하는 시장에서 포지션을 키운다는 뜻이네. 그건 물타기지, 확인 진입이 아니야."

### Jamie Dimon (제안 수정 찬성 — 단, 조건부)

> "기관 관점에서 보면, 숏 포지션의 분할 진입에서 '확인'이라는 개념이 좀 이상해. LONG에서 가격이 오를 때 추가 매수하면 추격 매수(momentum chase)인데, 기관에서는 이걸 선호하지 않아. 오히려 LONG도 내릴 때 추가하는 게 기관 전략이지."

- **기관 관행**: 대부분의 기관 분할 진입은 DCA(Dollar Cost Averaging) — 유리한 가격에 추가
- **대칭성 문제**: 사용자의 지적이 맞음. LONG이 비싸게 사는데(불리한 평단), SHORT이 싸게 파는 것(불리한 평단)은 대칭이지만, 경제적으로는 두 경우 모두 "역행 시 미체결"이라는 같은 보호 효과
- **그러나**: WITH_TREND라는 라벨은 "추세 확인 후 추가"라는 의미. 이미 COUNTER_TREND에서 물타기(유리한 평단 방향 추가)를 하고 있음

> "잠깐, 다시 생각해보면... COUNTER_TREND에서 이미 유리한 평단 방향으로 추가하고 있잖아. SHORT COUNTER는 +0.3% 올라갈 때 추가 매도 — 이게 바로 사용자가 원하는 거 아닌가?"

---

## Round 2: 심화 논쟁

### Warren Buffett (현행 유지 강화)

> "Jamie가 핵심을 짚었네. 시스템에 이미 두 가지 모드가 있어:
> - WITH_TREND: 방향 확인 후 추가 (평단 불리, 미체결 보호)
> - COUNTER_TREND: 역방향 추가 (평단 유리, 체결 보장)
>
> 제안대로 SHORT의 WITH_TREND를 반전하면, SHORT WITH_TREND가 SHORT COUNTER_TREND와 같은 방향이 되어버려. 두 모드의 구분이 무너지지."

- **구체적 비교**:
  - SHORT WITH_TREND 제안: [0%, +0.3%, +0.6%] → 올라갈 때 추가
  - SHORT COUNTER_TREND 현행: [0%, +0.3%] → 올라갈 때 추가
  - 거의 동일한 동작! 의미가 없어짐

- **리스크 시나리오**: BTC $80,000에서 숏 진입
  - 현행: 50% 즉시, 나머지는 $79,760/$79,520에서 체결 대기
  - 가격이 $80,500으로 반등 → tranche 1,2 미체결, SL은 50%에만 적용 = 손실 절반
  - 제안: 50% 즉시, 나머지는 $80,240/$80,480에서 체결 대기
  - 가격이 $80,500으로 반등 → tranche 1,2 **체결됨**, 그 후 SL → 100% 포지션 전체 손실

> "WITH_TREND의 진짜 가치는 '방향이 맞을 때만 전체 포지션을 구축한다'는 점이야. 방향이 틀리면 자동으로 포지션이 작아져. 이건 내장된 안전장치지."

### Jamie Dimon (현행 유지로 선회)

> "Buffett 말이 맞아. 내가 처음에 간과한 게 있어. 이건 단순히 평단이 유리하냐 불리하냐의 문제가 아니야. **방향이 틀렸을 때 포지션 크기가 자동으로 제어되느냐**의 문제야."

- **리스크 분석표**:

| 시나리오 | 현행 (방향 확인) | 제안 (평단 유리) |
|---------|-----------------|-----------------|
| 방향 맞음 (숏 후 하락) | 100% 체결, 평단 약간 불리 | 50%만 체결, 평단 유리 |
| 방향 틀림 (숏 후 상승) | 50%만 체결, 손실 제한 | 100% 체결, 전체 손실 |
| 횡보 | 50%~80% 체결, 중간 | 50%~100% 체결, 중간 |

> "방향이 맞을 때 평단이 약간 불리한 건 수용 가능해. 그 차이는 0.3~0.6%야. 하지만 방향이 틀렸을 때 50%만 잡히는 것과 100% 잡히는 것의 차이는 **리스크의 2배**지. 자본 보존이 수익 최적화보다 우선이야."

- **정량 분석** (1% 리스크 = $2, SL 1.5ATR 가정):
  - 현행: 방향 틀림 → 실제 손실 ~$1.0 (50%만 체결)
  - 제안: 방향 틀림 → 실제 손실 ~$2.0 + 슬리피지 (100% 체결 후 SL)
  - 차이: 약 2배

---

## Round 3: 최종 합의

### 공동 의견

> **Buffett**: "WITH_TREND의 본질은 '확인 후 추가'야. LONG이든 SHORT이든, 시장이 내 방향으로 움직일 때만 포지션을 키우는 거지. 평단 최적화는 COUNTER_TREND 모드에서 이미 처리하고 있어."
>
> **Dimon**: "동의해. 시스템 설계의 일관성도 중요해. WITH_TREND와 COUNTER_TREND가 서로 다른 행동을 해야 의미가 있어. SHORT만 특별 처리하면 코드 복잡성만 증가하고 유지보수가 어려워져."

### 주제 1 결론: 현행 유지 (변경 없음)

**근거**:
1. WITH_TREND의 핵심 가치는 "방향 확인"이며, 이는 LONG/SHORT 대칭적으로 동작
2. 방향이 틀렸을 때 미체결 tranche가 자동 손실 제한 역할 (포지션 크기 50% 축소 효과)
3. 평단 유리한 진입은 이미 COUNTER_TREND 모드에서 제공
4. SHORT만 예외 처리하면 WITH_TREND/COUNTER_TREND 구분이 무너짐
5. 최악의 시나리오에서 리스크 2배 차이 (현행 $1.0 vs 제안 $2.0)

**코드 변경**: 없음. 현행 `_create_entry_tranches()` 유지.

---

## 주제 2: Live 엔진 잔고 관리 방식

### 현행 코드

```python
# live_engine.py L423-424
self.account.balance -= margin
self.account.margin_used += margin

# _close_position() — engine.py L471-472
self.account.balance += margin + pos.realized_pnl
self.account.margin_used -= margin
```

### 문제

Binance Cross Margin에서는 마진이 잔고에서 별도 차감되지 않음:
- 로컬: balance=$119, margin_used=$80 → 가용=$119
- Binance: availableBalance=$200, position open

로컬 추적과 실제 잔고의 불일치가 발생하며, 이로 인해:
1. 새 포지션 진입 시 마진 부족으로 거부될 수 있음 (실제로는 가능)
2. 리스크 계산(balance * 2%)이 실제보다 작은 금액 기준으로 됨
3. 일일 손실 % 계산이 부정확

### 방법 비교

| | 방법 A: Binance 실잔고 기준 | 방법 B: 로컬 추적 + 주기적 교정 |
|---|---|---|
| 정확성 | 높음 (source of truth) | 중간 (교정 주기에 따라) |
| API 부하 | 진입/청산 시 + 주기적 | 주기적만 |
| 구현 복잡도 | 중간 (margin 로직 제거) | 높음 (교정 로직 추가) |
| 장애 시 | API 실패하면 판단 불가 | 로컬 값이 fallback |

---

## Round 1: 기본 입장

### Warren Buffett (방법 B — 로컬 추적 + 교정)

> "내가 평생 투자에서 배운 건, 네 돈이 어디 있는지 항상 알고 있어야 한다는 거야. 로컬 추적을 제거하면, Binance API가 응답하지 않는 순간 우리는 잔고를 모르게 되네."

- **로컬 추적의 가치**: 매 거래의 마진/PnL을 즉시 계산 가능. API 지연 없이 리스크 판단
- **API 의존 위험**: Binance API가 429 (rate limit)나 서버 에러를 반환하면?
  - 방법 A: 잔고를 모름 → 거래 불가 or 위험한 추정
  - 방법 B: 로컬 값으로 계속 운영 → 다음 교정 시 동기화
- **교정 주기**: 현재 reconciliation이 5초마다 실행됨. 여기에 잔고 교정도 추가하면 됨

> "단, 로컬 추적이 Paper 엔진의 isolated margin 모델이라는 점은 인정하네. Cross margin에서는 margin_used라는 개념이 다르지."

### Jamie Dimon (방법 A — Binance 기준, 단 하이브리드)

> "기관에서는 항상 prime broker(여기서는 Binance)의 잔고가 source of truth야. 로컬 장부가 다르면 로컬을 맞추는 거지, 반대가 아니야."

- **Cross Margin 현실**: `balance -= margin`은 isolated margin 모델. Cross margin에서는:
  - 잔고는 변하지 않음 (unrealized PnL만 equity에 반영)
  - 실현 PnL은 잔고에 즉시 반영
  - 마진은 "사용 중"이라는 개념이지 "차감"이 아님
- **현재 문제의 심각성**:
  - balance=$200으로 시작, margin=$80 진입 → 로컬 balance=$120
  - risk_per_trade_pct=2% → 다음 거래 리스크 = $120 * 2% = $2.40
  - 실제 가용 잔고는 $200(Cross) → 실제로는 $4.00까지 가능
  - **리스크 계산이 40% 과소** → 기회 손실
- **API 부하 우려**: 이미 `_get_real_balance()`에 5초 캐시가 있음. 추가 호출 없이 기존 캐시 활용

> "다만 Buffett의 우려도 맞아. API가 죽으면? 그래서 하이브리드를 제안하지."

---

## Round 2: 하이브리드 설계

### Jamie Dimon (구체적 하이브리드 제안)

> "이렇게 하자:
> 1. 잔고의 primary source는 Binance (캐시된 실잔고)
> 2. margin_used 차감 로직은 제거 — Cross margin에서는 의미 없음
> 3. API 실패 시 마지막 성공 캐시를 사용 (TTL을 60초로 확장)
> 4. 리스크 계산은 항상 '가용 잔고'(Binance availableBalance) 기준"

**구체적 변경 사항**:
```python
# AS-IS (live_engine.py L423-424)
self.account.balance -= margin
self.account.margin_used += margin

# TO-BE
# margin 차감 제거. balance는 Binance 실잔고에서 주기적 동기화.
# margin_used는 Binance positionInitialMargin에서 조회.
self.account.margin_used = margin  # 참고용 기록만 (차감 아님)
```

### Warren Buffett (하이브리드 수용, 추가 조건)

> "하이브리드는 받아들이겠네. 하지만 조건이 있어:
> 1. **잔고 캐시 실패 시 보수적 fallback**: 마지막 캐시가 60초 이상 오래되면, 거래 사이즈를 50%로 줄여야 해
> 2. **잔고 불일치 경고**: 로컬 추적치와 Binance 잔고 차이가 2% 넘으면 Telegram 알림
> 3. **daily_start_balance는 00:00에 Binance에서 갱신**: 일일 손실 계산의 기준점은 정확해야 해"

- **fallback 안전장치**:
  ```python
  async def _get_safe_balance(self) -> Decimal:
      try:
          return await self._get_real_balance()
      except Exception:
          if self._balance_cache:
              cached_time, cached_bal = self._balance_cache
              age = time.monotonic() - cached_time
              if age < 60:  # 60초 이내 캐시
                  return cached_bal
              else:  # 오래된 캐시 → 보수적
                  return cached_bal * Decimal("0.5")
          return self.account.balance  # 최후의 fallback
  ```

---

## Round 3: 최종 합의

### 공동 의견

> **Dimon**: "Buffett의 보수적 fallback이 좋아. 기관에서도 데이터 불확실성이 있으면 포지션 사이즈를 줄이는 게 원칙이야."
>
> **Buffett**: "Cross margin 현실을 반영하는 건 맞네. 로컬 장부가 실제와 40% 괴리나면 그건 장부가 틀린 거야. Binance를 기준으로 삼되, 안전장치를 갖추자."

### 주제 2 결론: 방법 A 채택 (Binance 기준 하이브리드)

**합의 사항**:

1. **`balance -= margin` 제거**: Cross margin에서는 마진이 잔고에서 차감되지 않음
2. **리스크 계산 기준 변경**: `self.account.balance` 대신 Binance availableBalance 사용
3. **잔고 동기화**: reconcile_orders() 주기(5초)에 잔고도 함께 동기화
4. **안전장치**:
   - 캐시 실패 + 60초 초과 → 사이즈 50% 축소
   - 로컬 vs Binance 차이 2% 초과 → Telegram 경고
   - 00:00 daily reset 시 Binance 실잔고로 `daily_start_balance` 갱신

**구체적 코드 변경**:

### 변경 1: live_engine.py on_signal() — margin 차감 제거

```python
# AS-IS (L423-424)
self.account.balance -= margin
self.account.margin_used += margin

# TO-BE
self.account.margin_used += margin  # 참고용 추적만 유지
# balance는 Binance에서 동기화되므로 로컬 차감하지 않음
```

### 변경 2: live_engine.py on_signal() — 리스크 계산 기준

```python
# AS-IS (L296)
risk_amount = self.account.balance * Decimal(str(self.settings.risk_per_trade_pct / 100)) * size_multiplier

# TO-BE
real_balance = await self._get_real_balance()
risk_amount = real_balance * Decimal(str(self.settings.risk_per_trade_pct / 100)) * size_multiplier
```

### 변경 3: live_engine.py — 잔고 동기화 추가

```python
async def _sync_balance(self):
    """reconcile 주기에 맞춰 잔고 동기화."""
    try:
        real_balance = await self._get_real_balance()
        old_balance = self.account.balance
        self.account.balance = real_balance

        # 차이 경고
        if old_balance > 0:
            diff_pct = abs(float(real_balance - old_balance) / float(old_balance) * 100)
            if diff_pct > 2.0:
                logger.warning(f"[LIVE] Balance sync: ${old_balance} → ${real_balance} ({diff_pct:.1f}% diff)")
                await self.alert_sender._send_telegram_text(
                    f"⚠️ <b>BALANCE DISCREPANCY</b>\n\n"
                    f"Local: ${old_balance:,.2f}\n"
                    f"Binance: ${real_balance:,.2f}\n"
                    f"Diff: {diff_pct:.1f}%"
                )

        # equity 업데이트
        self.account.equity = real_balance + self.account.unrealized_pnl
        if self.account.equity > self.account.peak_equity:
            self.account.peak_equity = self.account.equity

        save_account(self.account)
    except Exception as e:
        logger.warning(f"[LIVE] Balance sync failed: {e}")
```

### 변경 4: _close_position 오버라이드

```python
# LiveTradingEngine에서 _close_position 후 balance 복원 로직 제거
# Paper 엔진의 `balance += margin + pnl` 대신 Binance 동기화에 의존
# margin_used만 차감
```

### 변경 5: 캐시 실패 시 보수적 fallback

```python
async def _get_real_balance(self) -> Decimal:
    """캐시된 실잔고. 실패 시 보수적 fallback."""
    now = time.monotonic()
    if self._balance_cache:
        cached_time, cached_bal = self._balance_cache
        if now - cached_time < self.settings.balance_cache_ttl_sec:
            return cached_bal
    try:
        balance = await binance_client.get_balance("USDT")
        self._balance_cache = (now, balance)
        return balance
    except Exception as e:
        logger.warning(f"[LIVE] get_balance failed: {e}")
        if self._balance_cache:
            cached_time, cached_bal = self._balance_cache
            age = now - cached_time
            if age < 60:
                return cached_bal
            else:
                logger.warning(f"[LIVE] Stale balance cache ({age:.0f}s), using 50% of last known")
                return (cached_bal * Decimal("0.5")).quantize(Decimal("0.01"))
        return self.account.balance
```

---

## 종합 결론

| 주제 | 결론 | 변경 필요 |
|------|------|----------|
| 숏 분할 진입 방향 | **현행 유지** — WITH_TREND 확인 진입의 보호 가치가 평단 최적화보다 큼 | 없음 |
| Live 잔고 관리 | **Binance 기준 하이브리드** — margin 차감 제거, 실잔고 동기화, 보수적 fallback | live_engine.py 수정 필요 |

### 구현 우선순위
1. `_get_real_balance()` fallback 강화 (즉시)
2. `on_signal()`에서 `balance -= margin` 제거 (즉시)
3. `_sync_balance()` 메서드 추가 + reconcile 주기에 연동 (즉시)
4. `_close_position` 오버라이드 — Paper의 margin 복원 로직 대신 동기화 의존 (즉시)
5. daily reset 시 Binance 잔고로 갱신 (즉시)

### 리스크 주의사항
- 구현 후 반드시 Paper 모드에서 회귀 테스트 (Paper는 기존 로직 유지)
- Live 전환 시 초기 잔고 일치 확인
- 첫 24시간은 Telegram 경고를 주시할 것

---

*Warren Buffett*: "돈을 잃지 않는 것이 첫 번째 규칙이야. 숏 진입 방향은 현행이 더 안전하고, 잔고는 진실(Binance)을 따르되 안전장치를 갖춰야 해."

*Jamie Dimon*: "시스템은 현실을 반영해야 해. Cross margin 환경에서 isolated margin 장부를 쓰는 건 오류의 근원이야. 고치되, 보수적으로 고치자."
