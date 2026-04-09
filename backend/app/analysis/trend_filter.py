"""Multi-timeframe trend filter for counter-trend trade classification.

Higher timeframe trend 방향을 파악하여 lower TF 시그널이
with-trend / counter-trend / blocked 인지 분류한다.

Tier 분류 규칙:
  WITH_TREND   : 시그널 방향 == 상위 TF 다수 방향 (or 상위 TF 중립)
  COUNTER_TREND: 시그널 방향 != 상위 TF 다수 방향이지만, 완전 일치 아님
  BLOCKED      : 1d + 4h + 1h 모두 강하게 한 방향 → 반대 방향 거래 금지
"""

from app.trading.schemas import TradeTier, TrendContext

# 시그널 TF → 참조해야 할 상위 TF 목록 (순서: 중요도 높은 순)
HIGHER_TF_MAP: dict[str, list[str]] = {
    "15m": ["1h", "4h", "1d"],
    "30m": ["1h", "4h", "1d"],
    "1h":  ["4h", "1d"],
    "4h":  ["1d", "1w"],
    "1d":  ["1w"],
    "1w":  [],
}

# 강한 추세 판정 기준 (TF net_score 이상이면 "강한" 추세)
STRONG_TREND_THRESHOLD = 2.0


def classify_trade(
    signal_direction: str,
    signal_tf: str,
    trend_ctx: TrendContext,
) -> TradeTier:
    """시그널 방향 + 상위 TF trend context → TradeTier 반환.

    Args:
        signal_direction: "bullish" or "bearish"
        signal_tf: 시그널이 발생한 타임프레임 (e.g. "15m")
        trend_ctx: 각 TF별 방향/강도 정보

    Returns:
        TradeTier enum
    """
    higher_tfs = HIGHER_TF_MAP.get(signal_tf, [])

    if not higher_tfs:
        # 최고 TF (1w) 시그널은 상위 참조 없음 → 항상 with-trend
        return TradeTier.WITH_TREND

    # 상위 TF 중 데이터가 있는 것만 사용
    available = [(tf, trend_ctx.tf_directions.get(tf)) for tf in higher_tfs]
    available = [(tf, d) for tf, d in available if d and d != "neutral"]

    if not available:
        # 상위 TF 모두 중립이거나 데이터 없음 → with-trend 취급
        return TradeTier.WITH_TREND

    # 상위 TF 방향 집계
    bullish_count = sum(1 for _, d in available if d == "bullish")
    bearish_count = sum(1 for _, d in available if d == "bearish")
    dominant = "bullish" if bullish_count > bearish_count else "bearish" if bearish_count > bullish_count else "neutral"

    if dominant == "neutral":
        return TradeTier.WITH_TREND

    # 시그널이 상위 TF 다수 방향과 같으면 → WITH_TREND
    if signal_direction == dominant:
        return TradeTier.WITH_TREND

    # ── Counter-trend 후보 ──

    # BLOCKED 조건: 1d + 4h + 1h 모두 같은 방향이고 모두 강한 추세
    block_tfs = ["1d", "4h", "1h"]
    block_directions = [trend_ctx.tf_directions.get(tf) for tf in block_tfs]
    block_strengths = [trend_ctx.tf_strengths.get(tf, 0) for tf in block_tfs]

    all_same_direction = (
        all(d == "bullish" for d in block_directions if d)
        or all(d == "bearish" for d in block_directions if d)
    )
    all_present = all(d and d != "neutral" for d in block_directions)
    all_strong = all(s >= STRONG_TREND_THRESHOLD for s in block_strengths)

    if all_present and all_same_direction and all_strong:
        # 1d + 4h + 1h 모두 강하게 한 방향 → 반대 방향 진입 차단
        return TradeTier.BLOCKED

    return TradeTier.COUNTER_TREND


def build_trend_context(tf_analysis: dict[str, dict]) -> TrendContext:
    """스캔 결과 dict에서 TrendContext를 구성.

    tf_analysis: scheduler의 latest_results 형태
        {
            "1h": {"confluence": [...], "individual": [...]},
            "4h": {...},
            ...
        }
    """
    import time

    directions: dict[str, str] = {}
    strengths: dict[str, float] = {}

    for tf, data in tf_analysis.items():
        confluence_list = data.get("confluence", [])

        if not confluence_list:
            # confluence 없으면 individual 지표들로 방향 판단
            individuals = data.get("individual", [])
            bull_w = sum(
                s.get("strength", 0) for s in individuals if s.get("direction") == "bullish"
            )
            bear_w = sum(
                s.get("strength", 0) for s in individuals if s.get("direction") == "bearish"
            )
            if bull_w > bear_w and (bull_w - bear_w) >= 0.5:
                directions[tf] = "bullish"
                strengths[tf] = round(bull_w - bear_w, 1)
            elif bear_w > bull_w and (bear_w - bull_w) >= 0.5:
                directions[tf] = "bearish"
                strengths[tf] = round(bear_w - bull_w, 1)
            else:
                directions[tf] = "neutral"
                strengths[tf] = 0.0
            continue

        # Confluence가 있는 경우 → 가장 강한 confluence 사용
        best = max(confluence_list, key=lambda c: c.get("strength", 0))
        directions[tf] = best.get("direction", "neutral")
        net = best.get("details", {}).get("net_score", 0)
        strengths[tf] = round(net, 1)

    return TrendContext(
        tf_directions=directions,
        tf_strengths=strengths,
        updated_at=int(time.time() * 1000),
    )
