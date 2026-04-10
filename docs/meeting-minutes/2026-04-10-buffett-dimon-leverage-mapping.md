# Buffett × Dimon: 레버리지-시그널 매핑
## 2026-04-10

### 문제
strength = net_score / 8.0 → 실질 3-4x만 사용. 5x 죽은 코드.

### 합의: divisor 8.0 → 4.0
net_score 1.5 → 3x, 2.5 → 4x, 4.0 → 5x

### 적용
signals.py: `strength = min(net / 4.0, 1.0)` (기존 8.0)
