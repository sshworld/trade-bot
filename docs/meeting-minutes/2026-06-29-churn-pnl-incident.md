# 시말서 — 2026-06-29 churn 사건 (시장가 청산 PnL=0 회계 버그)

> 실거래 봇이 4분간 숏을 9연속 진입→즉시 손절하며 수수료/슬리피지를 누수했고,
> 시스템은 이를 손실로 인지하지 못했다. 자동 안전망이 작동하지 않아 **사용자가 직접 `/halt`** 했다.
> 본 문서는 무엇이, 왜 일어났고, 어떻게 고쳤으며, 무엇을 배웠는지 기록한다.

## 1. 사건 개요
- **일시**: 2026-06-29 23:00~23:04 KST (약 4분)
- **현상**: 동일 시그널 `bearish 1h strength=1.00` 으로 숏 **9연속 진입→즉시 손절** (보유 8~68초)
- **종료**: 자동 감지 아님. `23:04:26` 사용자가 텔레그램 `/halt` (로그: `Manual halt SET: manual via telegram /halt`)
- **심볼/모드**: BTCUSDT, 5x, LiveTradingEngine (Mainnet)

## 2. Ground Truth (DB `trade_history`)
9건 전부 `close_reason = stop_loss` 인데 **`realized_pnl = 0`** 으로 기록됨:

| side | dur | entry | exit | reason | 장부 pnl | 실제 pnl(추정) |
|---|---:|---:|---:|---|---:|---:|
| short | 16s | 59514.2 | 59778.7 | stop_loss | **0** | ≈ −1.32 |
| short | 9s | 59404.6 | 59799.9 | stop_loss | **0** | ≈ −1.98 |
| short | 39s | 59460.4 | 59800.0 | stop_loss | **0** | ≈ −1.70 |
| … (총 9건, 모두 숏이 가격 상승에 손절) | | | | | **0** | 합계 약 −13 |

진입 체결가(Binance `avgPrice` 실값)·SL(+0.4%)은 정상이었다 — **청산 손익 회계만** 오염됐다.

## 3. 근본 원인 (검증 완료)
시장가 청산(SL/시간/교체/emergency)의 청산 손익이 포지션에 귀속되지 않아 **0** 으로 기록됐다.

1. `live_engine.py` `_live_close_position` 이 청산 직전 로컬 WAITING exit(TP) tranche 를 **CANCELLED** 로 미리 변경.
2. 부모 `engine.py` `_close_position` 은 청산 PnL 을 **아직 WAITING 인 exit tranche 수량(`remaining_qty`)** 으로만 계산.
3. → 이미 CANCELLED 됐으니 `remaining_qty = 0` → PnL 계산 블록 skip → `realized_pnl = 0`.
4. 실제 청산 MARKET 주문의 손익은 어디에도 더해지지 않았다.
5. (TP 청산은 reconcile 에서 tranche 체결 시 `pos.realized_pnl += _calc_tranche_pnl` 로 적립돼 정상이었기에 — 시장가 청산만 구멍이 있었다.)

### 기여 요인
- **재진입 쿨다운 부재**: 손절 직후 같은 방향 재진입을 막는 가드가 없어(5초 시그널 throttle 뿐), 횡보장에서 0.4% 대칭 SL 을 반복적으로 두드림.
- **자동 안전망 비활성**: `anomaly_detector` 의 rapid-fire(60초 6주문)·fee-bleeding·연속손실 룰이 구현돼 있으나 `check_pre_order`/`check_post_trade` 가 `return None` 으로 하드 비활성(2026-05-04 사용자 요청). rapid-fire 가 켜져 있었다면 1분 내 자동 halt 됐을 사건.

## 4. 영향
- 실손실(합계 약 −13 + 수수료)이 거래단위 장부엔 0 으로 기록 → **손실 은폐**.
- 거래단위 PnL·승률·`total_realized_pnl` 통계 오염. (단, balance-anchored `real_profit` 은 실잔고 기준이라 실손실 자체는 반영됨.)
- 봇이 손실을 인지 못한 채 동일 숏을 반복 → 수수료/슬리피지 누수, 사용자 수동 개입 필요.

## 5. 시정 조치 (구현 완료, 2026-06-29)
- **S1 (fix)**: `_close_position` 이 청산 PnL 을 **실제 열려있던 수량**(`total_quantity − 체결된 exit 수량`)을 실제 청산가로 계산하도록 수정. tranche 상태에 비의존, 이미 체결된 exit PnL 중복 가산 방지. Paper 경로 결과 불변(회귀 테스트).
- **S2 (fix)**: `reentry_cooldown_after_sl_ms`(기본 5분) 설정 추가. `on_signal` 에서 직전 거래가 **같은 방향 `stop_loss`** 이고 쿨다운 이내면 신규 진입 차단. 반대방향 반전·TP 후 재진입은 허용.
- **테스트**: 신규 `test_close_pnl_accounting.py`, `test_reentry_cooldown.py` + 전체 84 PASS.

## 6. 재발 방지 / 권고
- (적용) 청산 손익은 tranche 상태가 아니라 실제 청산 수량 기준 — 회계 단일화.
- (적용) 손절 직후 같은 방향 재진입 쿨다운으로 churn 루프 차단.
- (권고, 별건) 비활성화된 `anomaly_detector` 자동 halt(특히 rapid-fire) 재가동 검토 — churn 의 최후 방어선. 2026-05-04 결정 재검토 필요. **본 수정 범위 밖.**
- (운영) 코드 반영 후 실거래 재개 전 사용자 승인 필수(서버 재시작 룰).

## 7. 교훈
- "수수료가 계속 나간다"의 진짜 원인은 재진입 빈도가 아니라 **손익 회계의 구멍**이었다 — 증상(churn)이 아니라 ground truth(DB)부터 봐야 한다.
- 시장가 청산 손익이 주문 tranche **상태**에 의존하는 설계는 취소 타이밍과 race 한다. 손익은 **실제 체결 수량·가격**이라는 사실에만 의존해야 한다.
- 자동 안전망을 끄면, 그 빈자리는 결국 사람이 손으로 메운다.
