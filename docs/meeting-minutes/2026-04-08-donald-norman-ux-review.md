# Donald Norman UX 리뷰
## 2026-04-08

### 핵심 지적 8가지 (우선순위 순)

#### 1. Bot 상태 뱃지 (30분)
Header에 현재 봇 상태 표시. "● Live"만으로는 봇이 뭘 하는지 모름.
- SCANNING (회색) / NEAR ENTRY (노란색) / IN POSITION SHORT 3x (빨강/초록) / HALTED (빨강)
- Trading 페이지에도 ticker 가격 전달할 것

#### 2. Signal Tree 접기/펼치기 (20분)
기본 접힌 상태, 클릭 시 펼침. ENTRY/confluence TF만 자동 펼침.
현재 6개 TF × 3~7개 지표 = 30줄 → 기본 6줄로 축소.

#### 3. Trade Event 토스트 알림 (1~2시간)
거래 이벤트(OPEN/CLOSE/FILL)가 Event Log에만 표시됨 → 상단 토스트로 강조.
양 페이지에서 보이도록 Layout 레벨 NotificationProvider.

#### 4. Trading 페이지 계층 구조 (2~3시간)
현재: AccountSummary(5칸) → DailySummary(6칸) → Positions → History
변경: Account 1줄로 축소 → Position 최상단 → EventLog 바로 아래 → History/Daily

#### 5. 페이지 간 교차 참조 (1~2시간)
Dashboard에 포지션 스트립: "ACTIVE: SHORT 3x @ $71,555 PnL +$0.50 [→Trading]"
Trading에 시그널 요약: "Best: 1h 100% ENTRY ▲ [→Dashboard]"

#### 6. 선택 TF 하이라이트 (15분)
interval 버튼으로 선택한 TF를 Signal Tree에서 파란 왼쪽 보더로 하이라이트.

#### 7. 섹션 라벨링 (10분)
차트 아래 지표: "RAW INDICATORS (1h)"
시그널 트리: "SIGNAL ANALYSIS (all timeframes)"

#### 8. 모바일 대응 (2~3시간)
OpenPositions: 테이블 → 카드 레이아웃
DailySummary: 6칸 → 2칸
Signal Tree: 압축 모드

### 노먼의 총평
> "구조는 건전하다. 문제는 정보 계층과 피드백에 있다. 가장 중요한 것(포지션, 거래 이벤트)이 가장 안 보이는 곳에 있다."
