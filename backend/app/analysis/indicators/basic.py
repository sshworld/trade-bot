import pandas as pd
import ta


def compute_rsi(df: pd.DataFrame, period: int = 14) -> dict:
    """RSI (Relative Strength Index) 계산."""
    rsi = ta.momentum.RSIIndicator(close=df["close"], window=period)
    value = rsi.rsi().iloc[-1]

    if value > 70:
        signal = "overbought"
    elif value < 30:
        signal = "oversold"
    else:
        signal = "neutral"

    return {"value": round(value, 2), "signal": signal, "period": period}


def compute_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> dict:
    """MACD (Moving Average Convergence Divergence) 계산."""
    macd_ind = ta.trend.MACD(
        close=df["close"], window_fast=fast, window_slow=slow, window_sign=signal
    )
    macd_val = macd_ind.macd().iloc[-1]
    signal_val = macd_ind.macd_signal().iloc[-1]
    histogram = macd_ind.macd_diff().iloc[-1]

    if macd_val > signal_val:
        trend = "bullish"
    else:
        trend = "bearish"

    return {
        "macd": round(macd_val, 2),
        "signal": round(signal_val, 2),
        "histogram": round(histogram, 2),
        "trend": trend,
    }


def compute_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands 계산."""
    bb = ta.volatility.BollingerBands(
        close=df["close"], window=period, window_dev=std_dev
    )
    upper = bb.bollinger_hband().iloc[-1]
    middle = bb.bollinger_mavg().iloc[-1]
    lower = bb.bollinger_lband().iloc[-1]
    bandwidth = (upper - lower) / middle if middle != 0 else 0

    current_price = df["close"].iloc[-1]
    if current_price > upper:
        position = "above_upper"
    elif current_price < lower:
        position = "below_lower"
    else:
        position = "within"

    return {
        "upper": round(upper, 2),
        "middle": round(middle, 2),
        "lower": round(lower, 2),
        "bandwidth": round(bandwidth, 4),
        "position": position,
    }


def compute_moving_averages(df: pd.DataFrame) -> dict:
    """이동평균선 계산 (SMA 20/50/200, EMA 12/26)."""
    close = df["close"]
    return {
        "sma_20": round(close.rolling(20).mean().iloc[-1], 2),
        "sma_50": round(close.rolling(50).mean().iloc[-1], 2),
        "sma_200": round(close.rolling(200).mean().iloc[-1], 2) if len(close) >= 200 else None,
        "ema_12": round(close.ewm(span=12).mean().iloc[-1], 2),
        "ema_26": round(close.ewm(span=26).mean().iloc[-1], 2),
    }
