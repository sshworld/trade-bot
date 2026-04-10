# Buffett × Dimon: 레버리지 5x 고정
## 2026-04-10

### 결론: 5x 고정 OK

SL 기반 사이징으로 2% 리스크가 고정이라 레버리지 변경은 마진 사용량만 바뀌고 실제 손실은 동일.

### 조건
1. 일일 drawdown circuit breaker 유지
2. 2% SL 사이징 절대 override 금지

### 적용
- min_leverage: 3 → 5
- max_leverage: 5 → 5 (고정)
