import pandas as pd

FIBONACCI_RATIOS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]


def compute_fibonacci_retracement(df: pd.DataFrame, lookback: int = 100) -> dict:
    """피보나치 되돌림 레벨 계산.

    최근 lookback 기간의 고점/저점을 기준으로 되돌림 레벨을 산출.
    상승 추세: 저점→고점 기준, 하락 추세: 고점→저점 기준.
    """
    recent = df.tail(lookback)
    high = recent["high"].max()
    low = recent["low"].min()
    current_price = df["close"].iloc[-1]

    high_idx = recent["high"].idxmax()
    low_idx = recent["low"].idxmin()

    # 고점이 저점 이후에 나오면 상승추세
    if high_idx > low_idx:
        trend = "uptrend"
        diff = high - low
        levels = {str(r): round(high - diff * r, 2) for r in FIBONACCI_RATIOS}
    else:
        trend = "downtrend"
        diff = high - low
        levels = {str(r): round(low + diff * r, 2) for r in FIBONACCI_RATIOS}

    # 현재가에 가장 가까운 레벨 찾기
    nearest_level = min(levels.items(), key=lambda x: abs(x[1] - current_price))

    return {
        "levels": levels,
        "trend": trend,
        "swing_high": round(high, 2),
        "swing_low": round(low, 2),
        "current_price": round(current_price, 2),
        "nearest_level": {"ratio": nearest_level[0], "price": nearest_level[1]},
    }
