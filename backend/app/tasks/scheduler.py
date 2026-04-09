import asyncio
import logging
import time
from decimal import Decimal

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.analysis.engine import compute_basic_indicators
from app.analysis.signals import generate_signals
from app.analysis.trend_filter import build_trend_context
from app.binance.kline_store import kline_store
from app.trading.engine import trading_engine
from app.ws.manager import ConnectionManager

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

SIGNAL_TIMEFRAMES = ["15m", "30m", "1h", "4h", "1d", "1w"]

# 독립 진입 가능한 TF (15m은 분석만, 1d/1w는 필터만)
ENTRY_TIMEFRAMES = {"30m", "1h", "4h"}

analyzing = False

# TF별 최근 분석 결과 저장 (API에서 조회용)
latest_results: dict[str, dict] = {}


def _analyze_tf(symbol: str, tf: str) -> tuple[dict, list[dict], Decimal] | None:
    df = kline_store.get_dataframe(symbol, tf)
    if df is None or len(df) < 30:
        return None
    indicators = compute_basic_indicators(df)
    signals = generate_signals(df, symbol, timeframe=tf)
    current_price = Decimal(str(df["close"].iloc[-1]))
    return indicators, signals, current_price


def _analyze_all(symbol: str) -> dict[str, tuple[dict, list[dict], Decimal]]:
    results = {}
    for tf in SIGNAL_TIMEFRAMES:
        result = _analyze_tf(symbol, tf)
        if result:
            results[tf] = result
    return results


async def signal_scan(mgr: ConnectionManager):
    global analyzing, latest_results

    if not kline_store.is_initialized:
        return

    analyzing = True
    try:
        results = await asyncio.to_thread(_analyze_all, "BTCUSDT")

        all_confluence = []
        scan_time = int(time.time() * 1000)

        for tf, (indicators, signals, current_price) in results.items():
            # TF별 결과 저장
            confluence_in_tf = [s for s in signals if s["type"].startswith("confluence_")]
            individual_in_tf = [s for s in signals if not s["type"].startswith("confluence_")]

            # 점수 집계 (UI에서 threshold 대비 표시용)
            from app.analysis.signals import CONFLUENCE_THRESHOLDS, DEFAULT_THRESHOLD, STRONG_TRIGGER_MIN_WEIGHT
            thresh = CONFLUENCE_THRESHOLDS.get(tf, DEFAULT_THRESHOLD)
            bull_w = sum(s.get("strength", 0) * 1.5 for s in individual_in_tf if s.get("direction") == "bullish")
            bear_w = sum(s.get("strength", 0) * 1.5 for s in individual_in_tf if s.get("direction") == "bearish")
            bull_count = sum(1 for s in individual_in_tf if s.get("direction") == "bullish")
            bear_count = sum(1 for s in individual_in_tf if s.get("direction") == "bearish")
            strong_count = sum(1 for s in individual_in_tf if s.get("strength", 0) >= 1.0)

            latest_results[tf] = {
                "timeframe": tf,
                "scanned_at": scan_time,
                "indicators": indicators,
                "confluence": confluence_in_tf,
                "individual": individual_in_tf,
                "signal_count": len(signals),
                "confluence_count": len(confluence_in_tf),
                "threshold": thresh,
                "bull_score": round(bull_w, 1),
                "bear_score": round(bear_w, 1),
                "bull_count": bull_count,
                "bear_count": bear_count,
                "strong_triggers": strong_count,
            }

            # 브로드캐스트
            await mgr.broadcast({
                "type": "indicators",
                "data": {"symbol": "BTCUSDT", "interval": tf, **indicators},
            })
            for signal in signals:
                await mgr.broadcast({
                    "type": "signal",
                    "data": {"symbol": "BTCUSDT", "timeframe": tf, **signal},
                })

            # 진입 가능한 TF만 trading에 전달 (15m은 분석만, 1d/1w는 필터만)
            if tf in ENTRY_TIMEFRAMES:
                for sig in confluence_in_tf:
                    all_confluence.append((tf, sig, current_price))
                for sig in signals:
                    if sig["type"].startswith("consensus_override"):
                        all_confluence.append((tf, sig, current_price))

        # ── Update multi-TF trend context ──
        trend_ctx = build_trend_context(latest_results)
        trading_engine.update_trend_context(trend_ctx)

        # confluence → trading
        for tf, signal, price in all_confluence:
            tagged = {**signal, "message": f"[{tf}] {signal['message']}", "timeframe": tf}
            position = await trading_engine.on_signal(tagged, price)
            if position:
                side_kr = "롱" if position.side.value == "long" else "숏"
                await mgr.broadcast({
                    "type": "trade_opened",
                    "data": {
                        "position_id": position.id,
                        "symbol": position.symbol,
                        "side": position.side.value,
                        "leverage": position.leverage,
                        "message": (
                            f"{side_kr} 포지션 진입 ({position.leverage}x, "
                            f"TF: {tf}, 분할매수 {len(position.entry_tranches)}회)"
                        ),
                    },
                })

        if all_confluence:
            logger.info(f"[SCAN] {len(all_confluence)} confluence across {list(results.keys())}")

    except Exception as e:
        logger.error(f"[SCAN] failed: {e}")
    finally:
        analyzing = False


async def run_analysis_for_timeframe(mgr: ConnectionManager, tf: str):
    try:
        result = await asyncio.to_thread(_analyze_tf, "BTCUSDT", tf)
        if not result:
            return
        indicators, signals, current_price = result
        scan_time = int(time.time() * 1000)

        confluence_in_tf = [s for s in signals if s["type"].startswith("confluence_")]
        individual_in_tf = [s for s in signals if not s["type"].startswith("confluence_")]

        latest_results[tf] = {
            "timeframe": tf,
            "scanned_at": scan_time,
            "indicators": indicators,
            "confluence": confluence_in_tf,
            "individual": individual_in_tf,
            "signal_count": len(signals),
            "confluence_count": len(confluence_in_tf),
            "confirmed": True,
        }

        await mgr.broadcast({
            "type": "indicators",
            "data": {"symbol": "BTCUSDT", "interval": tf, **indicators},
        })
        for signal in signals:
            await mgr.broadcast({
                "type": "signal",
                "data": {"symbol": "BTCUSDT", "timeframe": tf, "confirmed": True, **signal},
            })

        # 진입 가능한 TF만 trading에 전달
        if tf not in ENTRY_TIMEFRAMES:
            logger.info(f"[CONFIRMED] {tf} → {len(signals)} signals (filter-only, no entry)")
            return

        for sig in confluence_in_tf:
            confirmed = {**sig, "strength": min(sig["strength"] + 0.1, 1.0)}
            confirmed["message"] = f"[확정 {tf}] {sig['message']}"
            confirmed["timeframe"] = tf
            position = await trading_engine.on_signal(confirmed, current_price)
            if position:
                side_kr = "롱" if position.side.value == "long" else "숏"
                await mgr.broadcast({
                    "type": "trade_opened",
                    "data": {
                        "position_id": position.id,
                        "symbol": position.symbol,
                        "side": position.side.value,
                        "leverage": position.leverage,
                        "message": (
                            f"[확정] {side_kr} 포지션 진입 ({position.leverage}x, "
                            f"TF: {tf}, 분할매수 {len(position.entry_tranches)}회)"
                        ),
                    },
                })

        logger.info(f"[CONFIRMED] {tf} → {len(signals)} signals, {len(confluence_in_tf)} confluence")
    except Exception as e:
        logger.error(f"[CONFIRMED] {tf} failed: {e}")


async def anomaly_heartbeat():
    """주기적 이상 감지 (stale price 등)."""
    alert = trading_engine.anomaly_detector.check_heartbeat()
    if alert:
        await trading_engine.alert_sender.send(alert)


def start_scheduler(mgr: ConnectionManager):
    scheduler.add_job(
        signal_scan, "interval", seconds=1,
        args=[mgr], id="signal_scan",
        max_instances=1,
    )
    scheduler.add_job(
        anomaly_heartbeat, "interval", seconds=30,
        id="anomaly_heartbeat",
        max_instances=1,
    )
    scheduler.start()
    logger.info(f"Scheduler started: signal scan every 1s on {SIGNAL_TIMEFRAMES} (local, no API)")


def stop_scheduler():
    scheduler.shutdown(wait=False)
