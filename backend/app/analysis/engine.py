import pandas as pd

from app.analysis.indicators.basic import (
    compute_bollinger,
    compute_macd,
    compute_moving_averages,
    compute_rsi,
)
from app.analysis.indicators.elliott import compute_elliott_wave
from app.analysis.indicators.fibonacci import compute_fibonacci_retracement
from app.analysis.indicators.volume import compute_volume_profile
from app.binance.schemas import KlineData


def klines_to_dataframe(klines: list[KlineData]) -> pd.DataFrame:
    """KlineData 리스트를 pandas DataFrame으로 변환."""
    data = [
        {
            "open_time": k.open_time,
            "open": float(k.open),
            "high": float(k.high),
            "low": float(k.low),
            "close": float(k.close),
            "volume": float(k.volume),
        }
        for k in klines
    ]
    return pd.DataFrame(data)


def compute_basic_indicators(df: pd.DataFrame) -> dict:
    """기본 기술적 지표 일괄 계산."""
    return {
        "rsi": compute_rsi(df),
        "macd": compute_macd(df),
        "bollinger": compute_bollinger(df),
        "moving_averages": compute_moving_averages(df),
    }


def compute_advanced_analysis(df: pd.DataFrame) -> dict:
    """고급 분석 일괄 계산."""
    return {
        "fibonacci": compute_fibonacci_retracement(df),
        "elliott_wave": compute_elliott_wave(df),
        "volume_profile": compute_volume_profile(df),
    }


def compute_all(df: pd.DataFrame) -> dict:
    """모든 분석 실행."""
    basic = compute_basic_indicators(df)
    advanced = compute_advanced_analysis(df)
    return {**basic, **advanced}
