import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def find_swing_points(df: pd.DataFrame, order: int = 5) -> tuple[list, list]:
    """극값(스윙 포인트) 탐색."""
    highs = df["high"].values
    lows = df["low"].values

    high_indices = argrelextrema(highs, np.greater, order=order)[0]
    low_indices = argrelextrema(lows, np.less, order=order)[0]

    swing_highs = [(int(i), round(float(highs[i]), 2)) for i in high_indices]
    swing_lows = [(int(i), round(float(lows[i]), 2)) for i in low_indices]

    return swing_highs, swing_lows


def detect_impulse_wave(swing_highs: list, swing_lows: list) -> dict | None:
    """5파동 임펄스 패턴 탐지 (기본 규칙 기반).

    엘리엇 파동 규칙:
    1. Wave 2는 Wave 1의 시작점 아래로 내려갈 수 없다
    2. Wave 3은 가장 짧은 파동이 될 수 없다
    3. Wave 4는 Wave 1의 영역에 진입할 수 없다
    """
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return None

    # 모든 스윙 포인트를 인덱스 순으로 정렬
    all_points = []
    for idx, price in swing_highs:
        all_points.append({"idx": idx, "price": price, "type": "high"})
    for idx, price in swing_lows:
        all_points.append({"idx": idx, "price": price, "type": "low"})
    all_points.sort(key=lambda x: x["idx"])

    if len(all_points) < 6:
        return None

    # 최근 포인트들에서 5파동 패턴 탐색
    for i in range(len(all_points) - 5):
        points = all_points[i : i + 6]

        # 상승 임펄스: low-high-low-high-low-high 패턴
        types = [p["type"] for p in points]
        if types == ["low", "high", "low", "high", "low", "high"]:
            w1_start, w1_end = points[0]["price"], points[1]["price"]
            w2_end = points[2]["price"]
            w3_end = points[3]["price"]
            w4_end = points[4]["price"]
            w5_end = points[5]["price"]

            wave1 = w1_end - w1_start
            wave3 = w3_end - w2_end
            wave5 = w5_end - w4_end

            # Rule 1: Wave 2 cannot retrace below Wave 1 start
            if w2_end <= w1_start:
                continue
            # Rule 2: Wave 3 cannot be the shortest
            if wave3 < wave1 and wave3 < wave5:
                continue
            # Rule 3: Wave 4 cannot enter Wave 1 territory
            if w4_end <= w1_end:
                continue

            return {
                "pattern": "bullish_impulse",
                "waves": {
                    "wave_1": {"start": w1_start, "end": w1_end},
                    "wave_2": {"start": w1_end, "end": w2_end},
                    "wave_3": {"start": w2_end, "end": w3_end},
                    "wave_4": {"start": w3_end, "end": w4_end},
                    "wave_5": {"start": w4_end, "end": w5_end},
                },
                "current_wave": 5,
                "confidence": round(min(wave3 / wave1, 2.0) * 0.5, 2),
            }

    return None


def compute_elliott_wave(df: pd.DataFrame) -> dict:
    """엘리엇 파동 분석."""
    swing_highs, swing_lows = find_swing_points(df)

    impulse = detect_impulse_wave(swing_highs, swing_lows)

    return {
        "swing_highs": swing_highs[-10:],
        "swing_lows": swing_lows[-10:],
        "impulse_pattern": impulse,
        "analysis": "impulse_detected" if impulse else "no_clear_pattern",
    }
