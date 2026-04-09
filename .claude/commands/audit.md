# /audit — 트레이딩 엔진 코드 감사

전문가 에이전트를 사용하여 트레이딩 엔진 코드를 감사합니다.

## 감사 대상
- `backend/app/trading/engine.py` — 포지션 진입/청산/교체 로직
- `backend/app/trading/schemas.py` — 파라미터 값이 회의록과 일치하는지
- `backend/app/analysis/signals.py` — 시그널 생성 로직
- `backend/app/analysis/trend_filter.py` — 추세 필터 분류

## 점검 사항
1. 마진 계산 정확성 (리스크 2% 역산)
2. TP/SL 가격 변환 (마진% → 가격%)
3. 수수료 포함 본전 계산
4. 트레일링 SL 동작 (TP1→본전, TP2→TP1)
5. 포지션 교체 조건 (PnL < TP1)
6. Lagging state 할인 적용
7. DB 영속화 누락 없는지
8. Edge case: 잔고 0, 동시 시그널, 서버 재시작

결과를 CRITICAL / HIGH / MEDIUM / LOW로 분류하여 보고하세요.
CRITICAL이 있으면 즉시 수정하세요.
