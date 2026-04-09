# /analyze — 거래 성과 분석

거래 기록을 분석하고 전문가 피드백을 받습니다.

## 분석 내용

1. **데이터 수집**
   - `GET /api/trading/history` — 전체 거래 기록
   - `GET /api/trading/summary` — 금일/전체 요약
   - `GET /api/trading/daily-snapshots` — 일자별 성과

2. **통계 계산**
   - 총 수익/손실, 승률
   - 평균 이익/평균 손실, Profit Factor
   - TF별 성과 비교
   - WITH_TREND vs COUNTER_TREND 성과
   - 수수료 대비 수익률
   - 최대 연승/연패
   - Drawdown 이력

3. **전문가 리뷰**
   - 분석 결과를 Buffett + Dimon에게 전달
   - 파라미터 조정이 필요한지 토론
   - 구체적 개선 방안 도출

4. **보고**
   - 분석 결과 + 전문가 의견 요약
   - 조치 필요 사항 리스트

$ARGUMENTS 가 있으면 특정 기간/TF에 집중하여 분석합니다.
