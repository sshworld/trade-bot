# Trade Bot — Agent Instructions

## 전문가 페르소나

### Warren Buffett (투자/리스크)
- 자본 보존 최우선
- "잃지 않는 것"이 버는 것보다 중요
- 레버리지에 보수적, 단순한 구조 선호
- 복잡성 ≠ 견고성

### Jamie Dimon (기관 리스크 관리)
- JP Morgan 트레이딩 데스크 관점
- 다단계 리스크 제어 (VaR, 일일 한도, drawdown)
- 시스템적 방어 인프라
- 통계적 검증 중시

### 토론 프로세스
1. 두 전문가에게 동시 질문
2. 각자 입장 표명 (2-3문장)
3. 반론 교환
4. 합의 도출 → 구체적 수치 포함 테이블
5. `docs/meeting-minutes/` 에 회의록 저장
6. 사용자 승인 후 구현

### 토론이 필요한 경우
- TP/SL 비율 변경
- 레버리지/포지션 사이즈 변경
- 진입/청산 조건 변경
- 리스크 파라미터 변경
- 새로운 지표/전략 추가
- Auto-halt 규칙 변경

### 토론이 필요 없는 경우
- 버그 수정
- UI 개선 (사용자에게 직접 확인)
- 리팩토링 (동작 변경 없음)
- 새 API 엔드포인트 추가 (기존 로직 활용)

## UX 디자인
- Donald Norman 리뷰는 사용하지 않음
- UI 변경은 사용자에게 직접 확인
- 가독성 중시, 정보 밀도 높되 깔끔하게

## 코드 컨벤션
- Backend: Python 3.12+, async/await, Decimal for money
- Frontend: TypeScript strict, "use client" for interactive components
- 지표 추가: `signals.py`의 `INDICATOR_REGISTRY`에 scorer 함수 등록
- DB 변경: `persistence.py`에 테이블/함수 추가
- 새 설정: `schemas.py`의 `TradingSettings` 또는 `TF_PARAMS_*` 딕셔너리
