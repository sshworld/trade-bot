import numpy as np
import pandas as pd


def compute_volume_profile(df: pd.DataFrame, num_bins: int = 24) -> dict:
    """볼륨 프로파일 (VPVR) 계산.

    가격 범위를 num_bins 구간으로 나누고 각 구간의 거래량 합산.
    POC(Point of Control): 거래량이 가장 많은 가격대.
    VA(Value Area): 전체 거래량의 70%가 집중된 가격 범위.
    """
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    closes = df["close"].values.astype(float)
    volumes = df["volume"].values.astype(float)

    price_min = lows.min()
    price_max = highs.max()

    bin_edges = np.linspace(price_min, price_max, num_bins + 1)
    bin_volumes = np.zeros(num_bins)

    # 각 캔들의 거래량을 해당 가격 범위 bin에 분배
    for i in range(len(df)):
        candle_low = lows[i]
        candle_high = highs[i]
        candle_vol = volumes[i]

        for j in range(num_bins):
            bin_low = bin_edges[j]
            bin_high = bin_edges[j + 1]

            # 캔들과 bin의 겹치는 범위 계산
            overlap_low = max(candle_low, bin_low)
            overlap_high = min(candle_high, bin_high)

            if overlap_high > overlap_low:
                candle_range = candle_high - candle_low
                if candle_range > 0:
                    proportion = (overlap_high - overlap_low) / candle_range
                    bin_volumes[j] += candle_vol * proportion

    # POC (Point of Control)
    poc_idx = int(np.argmax(bin_volumes))
    poc_price = round((bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2, 2)

    # Value Area (70% of total volume)
    total_volume = bin_volumes.sum()
    target_volume = total_volume * 0.70

    sorted_indices = np.argsort(bin_volumes)[::-1]
    cumulative = 0.0
    va_indices = []
    for idx in sorted_indices:
        va_indices.append(int(idx))
        cumulative += bin_volumes[idx]
        if cumulative >= target_volume:
            break

    va_low = round(bin_edges[min(va_indices)], 2)
    va_high = round(bin_edges[max(va_indices) + 1], 2)

    # 프로파일 데이터
    profile = []
    for j in range(num_bins):
        price_level = round((bin_edges[j] + bin_edges[j + 1]) / 2, 2)
        profile.append({
            "price": price_level,
            "volume": round(float(bin_volumes[j]), 2),
        })

    return {
        "poc": {"price": poc_price, "volume": round(float(bin_volumes[poc_idx]), 2)},
        "value_area": {"high": va_high, "low": va_low},
        "profile": profile,
        "current_price": round(float(closes[-1]), 2),
    }
