# Trade Bot — Agent & Command System

## Slash Commands

| 명령 | 용도 |
|------|------|
| `/trade-review <주제>` | 트레이딩 파라미터 변경 전 Buffett×Dimon 토론 |
| `/check` | 시스템 전체 상태 점검 (API, 포지션, 시그널, DB) |
| `/audit` | 트레이딩 엔진 코드 감사 (CRITICAL~LOW 분류) |
| `/deploy` | 빌드 검증 + Git 커밋 + GitHub push |
| `/implement <기능>` | 기능 구현 자동 루프 (계획→구현→검증 반복) |
| `/analyze [기간]` | 거래 성과 분석 + 전문가 피드백 |

## 자동 Hook

### 트레이딩 파라미터 보호
`schemas.py`, `signals.py`, `trend_filter.py`에서 TP/SL/레버리지/임계값 등을 수정하려 하면 **자동 차단** + 경고:
> "⚠️ 트레이딩 파라미터 변경 감지. /trade-review 로 전문가 토론을 먼저 실행하세요."

## 전문가 페르소나

### Warren Buffett
- 자본 보존 최우선, 레버리지 보수적
- "잃지 않는 것 > 버는 것"
- 단순한 구조 선호, 복잡성 경계

### Jamie Dimon
- JP Morgan 트레이딩 데스크 관점
- 다단계 리스크 제어, 통계적 검증
- 시스템적 방어 인프라

### 토론이 필요한 변경
- TP/SL/레버리지/포지션 사이즈
- 진입/청산 조건, 리스크 파라미터
- 새 지표/전략, Auto-halt 규칙

### 토론 없이 진행 가능
- 버그 수정, UI 개선, 리팩토링
- 새 API 엔드포인트 (기존 로직 활용)

## 코드 컨벤션
- Python: 3.12+, async/await, Decimal for money
- TypeScript: strict, "use client" for interactive
- 지표 추가: `INDICATOR_REGISTRY`에 scorer 함수 등록
- DB 변경: `persistence.py`에 테이블/함수 추가
- Paper 설정: `schemas.py`의 `TradingSettings`
- Live 설정: `schemas.py`의 `LiveTradingSettings` (TradingSettings 상속)
- 레버리지: **5x 고정** (2026-04-10 회의록)
- 리스크: **순수 balance × 2%**, 클램프 없음 (2026-04-11 회의록)
- 진입: **평단 최적화** [0, -0.3, -0.6] (2026-04-11 회의록)
- 시그널 스로틀: **5초** (2026-04-11 회의록)
- 잔고: **Binance 실잔고 기준** (cross margin, 로컬 차감 없음)
- **실거래 서버 --reload 절대 금지, 재시작은 반드시 사용자 승인**
- push 시 **CLAUDE.md, README.md 등 관련 문서 반드시 같이 업데이트**

## 워크플로우

### 기능 요청 시
```
사용자 요청 → 파라미터 변경 포함?
  ├─ Yes → /trade-review → 토론 → 회의록 → 승인 → 구현 → 검증
  └─ No  → 구현 → 검증
```

### 이슈 발견 시
```
이슈 감지 → 트레이딩 관련?
  ├─ Yes → 전문가 토론 → 결론 → 구현 → 검증
  └─ No  → 직접 수정 → 검증
```

### 배포 시
```
/deploy → 빌드 검증 → 커밋 → push → CLAUDE.md 업데이트
```
