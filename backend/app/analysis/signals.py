"""Confluence 기반 매매 시그널 생성.

지표를 플러그인으로 등록하여 확장 가능한 구조.
새 지표 추가: scorer 함수를 만들고 INDICATOR_REGISTRY에 등록하면 끝.
"""

import time
from dataclasses import dataclass

import pandas as pd

from app.analysis.indicators.basic import (
    compute_bollinger,
    compute_macd,
    compute_moving_averages,
    compute_rsi,
)
from app.analysis.indicators.fibonacci import compute_fibonacci_retracement
from app.analysis.indicators.elliott import compute_elliott_wave
from app.analysis.indicators.volume import compute_volume_profile


@dataclass
class Score:
    indicator: str
    direction: str  # "bullish" | "bearish" | "neutral"
    weight: float
    reason: str
    family: str = ""           # 지표 패밀리 (macd, rsi, bb, ma, elliott, vp, fib)
    is_lagging_state: bool = False


# ── 지표별 Scorer ──────────────────────────────────────────────

def score_rsi(df: pd.DataFrame, cache: dict) -> list[Score]:
    rsi = cache.setdefault("rsi", compute_rsi(df))
    v = rsi["value"]
    # 극단값만 (40~60 중립구간 제거 — 노이즈)
    if v < 30:
        return [Score("RSI", "bullish", 1.5, f"RSI {v} 과매도 구간", family="rsi")]
    if v > 70:
        return [Score("RSI", "bearish", 1.5, f"RSI {v} 과매수 구간", family="rsi")]
    return []


def score_macd(df: pd.DataFrame, cache: dict) -> list[Score]:
    if len(df) <= 26:
        return []
    macd = cache.setdefault("macd", compute_macd(df))
    prev_macd = cache.setdefault("prev_macd", compute_macd(df.iloc[:-1]))
    scores = []

    if prev_macd["macd"] <= prev_macd["signal"] and macd["macd"] > macd["signal"]:
        scores.append(Score("MACD", "bullish", 1.5, "MACD 골든 크로스", family="macd"))
    elif prev_macd["macd"] >= prev_macd["signal"] and macd["macd"] < macd["signal"]:
        scores.append(Score("MACD", "bearish", 1.5, "MACD 데드 크로스", family="macd"))

    if macd["histogram"] > 0 and macd["histogram"] > prev_macd["histogram"]:
        scores.append(Score("MACD_hist", "bullish", 0.3, "MACD 히스토그램 상승 중", family="macd"))
    elif macd["histogram"] < 0 and macd["histogram"] < prev_macd["histogram"]:
        scores.append(Score("MACD_hist", "bearish", 0.3, "MACD 히스토그램 하락 중", family="macd"))

    return scores


def score_bollinger(df: pd.DataFrame, cache: dict) -> list[Score]:
    bb = cache.setdefault("bb", compute_bollinger(df))
    if bb["position"] == "below_lower":
        return [Score("BB", "bullish", 1.5, f"볼린저밴드 하단 이탈 (하단: {bb['lower']:.0f})", family="bb")]
    if bb["position"] == "above_upper":
        return [Score("BB", "bearish", 1.5, f"볼린저밴드 상단 이탈 (상단: {bb['upper']:.0f})", family="bb")]
    return []


def score_moving_averages(df: pd.DataFrame, cache: dict) -> list[Score]:
    if len(df) < 50:
        return []
    ma = cache.setdefault("ma", compute_moving_averages(df))
    current_price = df["close"].iloc[-1]
    scores = []

    # 정배열/역배열 — 지연 상태지표 (추세 전환 시 반대 점수 할인 대상)
    if ma["sma_20"] > ma["sma_50"]:
        scores.append(Score("MA_align", "bullish", 0.7,
                            f"이동평균 정배열 (SMA20 {ma['sma_20']:.0f} > SMA50 {ma['sma_50']:.0f})",
                            family="ma", is_lagging_state=True))
    else:
        scores.append(Score("MA_align", "bearish", 0.7,
                            f"이동평균 역배열 (SMA20 {ma['sma_20']:.0f} < SMA50 {ma['sma_50']:.0f})",
                            family="ma", is_lagging_state=True))

    # SMA 크로스 — 이벤트이므로 높은 가중치
    sma20 = cache.setdefault("sma20_series", df["close"].rolling(20).mean())
    sma50 = cache.setdefault("sma50_series", df["close"].rolling(50).mean())
    if sma20.iloc[-2] <= sma50.iloc[-2] and sma20.iloc[-1] > sma50.iloc[-1]:
        scores.append(Score("MA_cross", "bullish", 1.5, "SMA 20/50 골든 크로스", family="ma"))
    elif sma20.iloc[-2] >= sma50.iloc[-2] and sma20.iloc[-1] < sma50.iloc[-1]:
        scores.append(Score("MA_cross", "bearish", 1.5, "SMA 20/50 데드 크로스", family="ma"))

    # EMA 구조 — 지연 상태지표
    if current_price > ma["ema_12"] > ma["ema_26"]:
        scores.append(Score("EMA_pos", "bullish", 0.5, "가격 > EMA12 > EMA26 상승 구조",
                            family="ma", is_lagging_state=True))
    elif current_price < ma["ema_12"] < ma["ema_26"]:
        scores.append(Score("EMA_pos", "bearish", 0.5, "가격 < EMA12 < EMA26 하락 구조",
                            family="ma", is_lagging_state=True))

    return scores


def score_fibonacci(df: pd.DataFrame, cache: dict) -> list[Score]:
    fib = cache.setdefault("fib", compute_fibonacci_retracement(df))
    current_price = df["close"].iloc[-1]
    nearest = fib["nearest_level"]
    distance_pct = abs(current_price - nearest["price"]) / current_price * 100

    if distance_pct >= 0.5:
        return []

    fib_ratio = float(nearest["ratio"])
    if fib_ratio not in (0.382, 0.5, 0.618):
        return []

    if fib["trend"] == "uptrend":
        return [Score("FIB", "bullish", 1.0,
                       f"피보나치 {nearest['ratio']} 지지 ({nearest['price']:.0f}) 근접", family="fib")]
    if fib["trend"] == "downtrend":
        return [Score("FIB", "bearish", 1.0,
                       f"피보나치 {nearest['ratio']} 저항 ({nearest['price']:.0f}) 근접", family="fib")]
    return []


def score_elliott(df: pd.DataFrame, cache: dict) -> list[Score]:
    elliott = cache.setdefault("elliott", compute_elliott_wave(df))
    impulse = elliott.get("impulse_pattern")
    if not impulse:
        return []

    if impulse["pattern"] == "bullish_impulse":
        wave = impulse.get("current_wave", 0)
        if wave <= 3:
            return [Score("ELLIOTT", "bullish", 1.0, f"엘리엇 상승 임펄스 Wave {wave} 진행 중", family="elliott")]
        if wave >= 5:
            return [Score("ELLIOTT", "bearish", 0.8, "엘리엇 5파 완성 - 조정 임박", family="elliott")]
    return []


def score_volume_profile(df: pd.DataFrame, cache: dict) -> list[Score]:
    vp = cache.setdefault("vp", compute_volume_profile(df))
    current_price = df["close"].iloc[-1]
    va_high = vp["value_area"]["high"]
    va_low = vp["value_area"]["low"]
    poc = vp["poc"]["price"]

    if current_price < va_low:
        return [Score("VP", "bullish", 0.8,
                       f"Value Area 하단({va_low:.0f}) 아래 → POC({poc:.0f})로 회귀 가능", family="vp")]
    if current_price > va_high:
        return [Score("VP", "bearish", 0.8,
                       f"Value Area 상단({va_high:.0f}) 위 → POC({poc:.0f})로 회귀 가능", family="vp")]
    return []


INDICATOR_REGISTRY: list[callable] = [
    score_rsi,
    score_macd,
    score_bollinger,
    score_moving_averages,
    score_fibonacci,
    score_elliott,
    score_volume_profile,
]


# ── TF별 Confluence 임계값 ─────────────────────────────────────
# 짧은 TF는 노이즈 많으므로 엄격, 긴 TF는 신뢰도 높으므로 완화

CONFLUENCE_THRESHOLDS = {
    "15m": {"min_count": 4, "min_score": 3.5, "min_net": 2.5},
    "30m": {"min_count": 3, "min_score": 3.0, "min_net": 1.5},
    "1h":  {"min_count": 3, "min_score": 3.0, "min_net": 1.5},
    "4h":  {"min_count": 3, "min_score": 2.5, "min_net": 1.5},
    "1d":  {"min_count": 2, "min_score": 2.5, "min_net": 1.5},
    "1w":  {"min_count": 2, "min_score": 2.5, "min_net": 1.5},
}

# 지연 상태지표 할인율: 트리거 있을 때 반대 방향 lagging 지표 weight를 30%로
LAGGING_STATE_DISCOUNT = 0.3

# 기본값 (TF 미지정 시)
DEFAULT_THRESHOLD = {"min_count": 3, "min_score": 3.0, "min_net": 2.0}

# 강한 트리거 최소 가중치 (이벤트성 시그널: RSI극단, MACD크로스, BB돌파, MA크로스)
STRONG_TRIGGER_MIN_WEIGHT = 1.5


def _has_strong_trigger(scores: list[Score]) -> bool:
    """최소 1개의 강한 이벤트 트리거가 있는지 확인."""
    return any(s.weight >= STRONG_TRIGGER_MIN_WEIGHT for s in scores)


# ── 메인 시그널 생성 ───────────────────────────────────────────

def generate_signals(
    df: pd.DataFrame, symbol: str = "BTCUSDT", timeframe: str = ""
) -> list[dict]:
    now = int(time.time() * 1000)
    cache: dict = {}

    all_scores: list[Score] = []
    for scorer in INDICATOR_REGISTRY:
        try:
            all_scores.extend(scorer(df, cache))
        except Exception:
            pass

    bullish = [s for s in all_scores if s.direction == "bullish"]
    bearish = [s for s in all_scores if s.direction == "bearish"]
    bull_score = sum(s.weight for s in bullish)
    bear_score = sum(s.weight for s in bearish)

    # 패밀리 중복 제거: 같은 family에서 가장 높은 weight만 카운트
    def _dedup_by_family(scores: list[Score]) -> list[Score]:
        family_best: dict[str, Score] = {}
        no_family: list[Score] = []
        for s in scores:
            if not s.family:
                no_family.append(s)
                continue
            if s.family not in family_best or s.weight > family_best[s.family].weight:
                family_best[s.family] = s
        return list(family_best.values()) + no_family

    def _count_unique_families(scores: list[Score]) -> int:
        families = set(s.family for s in scores if s.family)
        return len(families)

    # TF별 임계값
    thresh = CONFLUENCE_THRESHOLDS.get(timeframe, DEFAULT_THRESHOLD)
    min_count = thresh["min_count"]
    min_score = thresh["min_score"]
    min_net = thresh["min_net"]

    signals: list[dict] = []

    # ── Net score 계산 (지연 상태지표 할인) ──
    def _effective_opposing_score(target_dir: str, opposing: list[Score], has_trigger: bool) -> float:
        """트리거 있으면 반대쪽 lagging state 지표 할인."""
        total = 0.0
        for s in opposing:
            if has_trigger and s.is_lagging_state:
                total += s.weight * LAGGING_STATE_DISCOUNT
            else:
                total += s.weight
        return total

    # Bullish confluence — 패밀리 중복 제거 후 3+ 독립 패밀리 필수
    bull_dedup = _dedup_by_family(bullish)
    bull_families = _count_unique_families(bullish)
    if (
        bull_families >= min_count
        and bull_score >= min_score
        and _has_strong_trigger(bullish)
    ):
        effective_bear = _effective_opposing_score("bearish", bearish, True)
        net = bull_score - effective_bear
        if net >= min_net:
            strength = min(net / 8.0, 1.0)
            reasons = [s.reason for s in bullish[:4]]
            signals.append({
                "type": "confluence_long",
                "direction": "bullish",
                "strength": round(strength, 2),
                "message": f"[롱] {len(bullish)}개 지표 합류 (score: {net:.1f}) - {' / '.join(reasons)}",
                "timestamp": now,
                "details": {
                    "bullish_score": round(bull_score, 1),
                    "bearish_score": round(bear_score, 1),
                    "net_score": round(net, 1),
                    "threshold": thresh,
                    "has_strong_trigger": True,
                    "indicators": [{"indicator": s.indicator, "weight": s.weight, "reason": s.reason} for s in bullish],
                },
            })

    # Bearish confluence — 패밀리 중복 제거
    bear_dedup = _dedup_by_family(bearish)
    bear_families = _count_unique_families(bearish)
    if (
        bear_families >= min_count
        and bear_score >= min_score
        and _has_strong_trigger(bearish)
    ):
        effective_bull = _effective_opposing_score("bullish", bullish, True)
        net = bear_score - effective_bull
        if net >= min_net:
            strength = min(net / 8.0, 1.0)
            reasons = [s.reason for s in bearish[:4]]
            signals.append({
                "type": "confluence_short",
                "direction": "bearish",
                "strength": round(strength, 2),
                "message": f"[숏] {len(bearish)}개 지표 합류 (score: {net:.1f}) - {' / '.join(reasons)}",
                "timestamp": now,
                "details": {
                    "bullish_score": round(bull_score, 1),
                    "bearish_score": round(bear_score, 1),
                    "net_score": round(net, 1),
                    "threshold": thresh,
                    "has_strong_trigger": True,
                    "indicators": [{"indicator": s.indicator, "weight": s.weight, "reason": s.reason} for s in bearish],
                },
            })

    # ── Consensus Override ──
    # 트리거 없이도 5+지표 압도적 합류 시 소액 진입
    CONSENSUS_MIN_COUNT = 5
    CONSENSUS_NET_MULTIPLIER = 1.5  # net >= min_net * 1.5

    # Bullish consensus (트리거 없을 때만)
    if (
        not any(s["type"] == "confluence_long" for s in signals)
        and len(bullish) >= CONSENSUS_MIN_COUNT
        and bull_score >= min_score
    ):
        net = bull_score - bear_score
        if net >= min_net * CONSENSUS_NET_MULTIPLIER:
            signals.append({
                "type": "consensus_override_long",
                "direction": "bullish",
                "strength": round(min(net / 10.0, 0.8), 2),  # 약한 strength
                "message": f"[컨센서스 롱] {len(bullish)}개 합류 (트리거 없음, score: {net:.1f})",
                "timestamp": now,
                "details": {
                    "bullish_score": round(bull_score, 1),
                    "bearish_score": round(bear_score, 1),
                    "net_score": round(net, 1),
                    "threshold": thresh,
                    "has_strong_trigger": False,
                    "consensus_override": True,
                    "indicators": [{"indicator": s.indicator, "weight": s.weight, "reason": s.reason} for s in bullish],
                },
            })

    # Bearish consensus
    if (
        not any(s["type"] == "confluence_short" for s in signals)
        and len(bearish) >= CONSENSUS_MIN_COUNT
        and bear_score >= min_score
    ):
        net = bear_score - bull_score
        if net >= min_net * CONSENSUS_NET_MULTIPLIER:
            signals.append({
                "type": "consensus_override_short",
                "direction": "bearish",
                "strength": round(min(net / 10.0, 0.8), 2),
                "message": f"[컨센서스 숏] {len(bearish)}개 합류 (트리거 없음, score: {net:.1f})",
                "timestamp": now,
                "details": {
                    "bullish_score": round(bull_score, 1),
                    "bearish_score": round(bear_score, 1),
                    "net_score": round(net, 1),
                    "threshold": thresh,
                    "has_strong_trigger": False,
                    "consensus_override": True,
                    "indicators": [{"indicator": s.indicator, "weight": s.weight, "reason": s.reason} for s in bearish],
                },
            })

    # 개별 지표 정보 (UI 표시용)
    for s in all_scores:
        if s.direction != "neutral":
            signals.append({
                "type": f"indicator_{s.indicator.lower()}",
                "direction": s.direction,
                "strength": round(min(s.weight / 1.5, 1.0), 2),
                "message": s.reason,
                "timestamp": now,
                "is_confluence": False,
            })

    return signals
