import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.analysis.engine import (
    compute_all,
    compute_basic_indicators,
)
from app.analysis.indicators.fibonacci import compute_fibonacci_retracement
from app.analysis.signals import generate_signals
from app.binance.kline_store import kline_store

router = APIRouter(prefix="/api/analysis")


def _get_df(symbol: str, interval: str):
    """로컬 kline_store에서 DataFrame 읽기. API 호출 없음."""
    df = kline_store.get_dataframe(symbol, interval)
    if df is None or len(df) < 10:
        raise HTTPException(status_code=503, detail=f"Data not ready for {interval}")
    return df


@router.get("/indicators")
async def get_indicators(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
):
    df = _get_df(symbol, interval)
    indicators = await asyncio.to_thread(compute_basic_indicators, df)
    return {"symbol": symbol, "interval": interval, **indicators}


@router.get("/fibonacci")
async def get_fibonacci(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="4h"),
    lookback: int = Query(default=100),
):
    df = _get_df(symbol, interval)
    result = await asyncio.to_thread(compute_fibonacci_retracement, df, lookback)
    return {"symbol": symbol, "interval": interval, **result}


@router.get("/signals")
async def get_signals(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
):
    df = _get_df(symbol, interval)
    signals = await asyncio.to_thread(generate_signals, df, symbol, interval)
    return {"symbol": symbol, "signals": signals}


@router.get("/full")
async def get_full_analysis(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
):
    df = _get_df(symbol, interval)
    analysis = await asyncio.to_thread(compute_all, df)
    signals = await asyncio.to_thread(generate_signals, df, symbol, interval)
    return {"symbol": symbol, "interval": interval, **analysis, "signals": signals}


@router.get("/overlay")
async def get_indicator_overlay(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
    indicator: str = Query(description="rsi, macd, bb, sma, ema, fib, elliott, vp"),
):
    """차트 오버레이용 지표 시계열 데이터."""
    import math
    import ta
    import numpy as np
    df = _get_df(symbol, interval)
    times = [int(t / 1000) for t in df["open_time"].tolist()]

    def safe(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return round(float(v), 2)

    if indicator == "rsi":
        rsi = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi().tolist()
        return {"indicator": "rsi", "interval": interval, "data": [
            {"time": t, "value": safe(v)} for t, v in zip(times, rsi) if safe(v) is not None
        ]}

    elif indicator == "macd":
        macd_ind = ta.trend.MACD(close=df["close"])
        ml = macd_ind.macd().tolist()
        sl = macd_ind.macd_signal().tolist()
        hl = macd_ind.macd_diff().tolist()
        return {"indicator": "macd", "interval": interval, "data": [
            {"time": t, "macd": safe(m), "signal": safe(s), "histogram": safe(h)}
            for t, m, s, h in zip(times, ml, sl, hl) if safe(m) is not None
        ]}

    elif indicator == "bb":
        bb = ta.volatility.BollingerBands(close=df["close"], window=20, window_dev=2)
        ul = bb.bollinger_hband().tolist()
        ml = bb.bollinger_mavg().tolist()
        ll = bb.bollinger_lband().tolist()
        return {"indicator": "bb", "interval": interval, "data": [
            {"time": t, "upper": safe(u), "middle": safe(m), "lower": safe(l)}
            for t, u, m, l in zip(times, ul, ml, ll) if safe(u) is not None
        ]}

    elif indicator == "sma":
        s20 = df["close"].rolling(20).mean().tolist()
        s50 = df["close"].rolling(50).mean().tolist()
        s200 = df["close"].rolling(200).mean().tolist() if len(df) >= 200 else [None] * len(df)
        return {"indicator": "sma", "interval": interval, "data": [
            {"time": t, "sma20": safe(a), "sma50": safe(b), "sma200": safe(c)}
            for t, a, b, c in zip(times, s20, s50, s200)
        ]}

    elif indicator == "ema":
        e12 = df["close"].ewm(span=12).mean().tolist()
        e26 = df["close"].ewm(span=26).mean().tolist()
        return {"indicator": "ema", "interval": interval, "data": [
            {"time": t, "ema12": safe(a), "ema26": safe(b)}
            for t, a, b in zip(times, e12, e26)
        ]}

    elif indicator == "fib":
        from app.analysis.indicators.fibonacci import compute_fibonacci_retracement
        result = await asyncio.to_thread(compute_fibonacci_retracement, df)
        # 피보나치는 수평선이므로 시작~끝 시간의 2점 반환
        levels = result["levels"]
        t_start = times[0]
        t_end = times[-1]
        return {"indicator": "fib", "interval": interval, "data": [
            {"ratio": k, "price": float(v), "time_start": t_start, "time_end": t_end}
            for k, v in levels.items()
        ]}

    elif indicator == "elliott":
        from app.analysis.indicators.elliott import compute_elliott_wave
        result = await asyncio.to_thread(compute_elliott_wave, df)
        markers = []
        for idx, price in result.get("swing_highs", []):
            if idx < len(times):
                markers.append({"time": times[idx], "price": price, "type": "high"})
        for idx, price in result.get("swing_lows", []):
            if idx < len(times):
                markers.append({"time": times[idx], "price": price, "type": "low"})
        return {"indicator": "elliott", "interval": interval, "data": sorted(markers, key=lambda x: x["time"]),
                "pattern": result.get("impulse_pattern")}

    elif indicator == "vp":
        from app.analysis.indicators.volume import compute_volume_profile
        result = await asyncio.to_thread(compute_volume_profile, df)
        return {"indicator": "vp", "interval": interval,
                "profile": result["profile"],
                "poc": result["poc"],
                "value_area": result["value_area"]}

    raise HTTPException(status_code=400, detail=f"Unknown indicator: {indicator}")


@router.get("/scan")
async def get_scan_results():
    """전체 TF 최신 스캔 결과 조회. 1초마다 갱신됨."""
    from app.tasks.scheduler import latest_results, SIGNAL_TIMEFRAMES
    from app.trading.engine import trading_engine
    ctx = trading_engine._trend_context
    return {
        "timeframes": SIGNAL_TIMEFRAMES,
        "results": latest_results,
        "trend": {
            "directions": ctx.tf_directions,
            "strengths": ctx.tf_strengths,
        },
    }


@router.get("/scan/{tf}")
async def get_scan_result_by_tf(tf: str):
    """특정 TF 스캔 결과 조회."""
    from app.tasks.scheduler import latest_results
    result = latest_results.get(tf)
    if not result:
        raise HTTPException(status_code=404, detail=f"No scan result for {tf}")
    return result


@router.get("/trend-context")
async def get_trend_context():
    """현재 multi-TF trend context 조회 (counter-trend 분류에 사용)."""
    from app.trading.engine import trading_engine
    ctx = trading_engine._trend_context
    return {
        "tf_directions": ctx.tf_directions,
        "tf_strengths": ctx.tf_strengths,
        "updated_at": ctx.updated_at,
    }
