"""Matplotlib 기반 캔들 차트 PNG 렌더.

`/chart [TF]` 명령에서 호출. 의존성: matplotlib (Agg backend, GUI 없음).
"""

import io
import logging
import time

import matplotlib

matplotlib.use("Agg")  # headless

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

logger = logging.getLogger(__name__)

VALID_TFS = {"5m", "15m", "30m", "1h", "4h", "1d"}


async def render_chart(tf: str, symbol: str = "BTCUSDT", n_candles: int = 120) -> tuple[bytes, str]:
    """캔들 + 진입/TP/SL 마커가 그려진 PNG 바이트 반환.

    Returns: (png_bytes, caption)
    """
    if tf not in VALID_TFS:
        raise ValueError(f"unsupported tf: {tf}")

    from app.binance.kline_store import kline_store
    from app.trading.engine import trading_engine

    df = kline_store.get_dataframe(symbol, tf)
    if df is None or df.empty:
        raise RuntimeError(f"no kline data for {symbol} {tf}")

    df = df.tail(n_candles).reset_index(drop=True)

    # 포지션 정보 (있으면 entry/TP/SL 마커)
    positions = trading_engine.get_open_positions()

    png_bytes = _draw(df, tf, symbol, positions)

    last_close = float(df.iloc[-1]["close"])
    caption = f"<b>{symbol} {tf}</b> — last ${last_close:,.2f}"
    if positions:
        p = positions[0]
        caption += f"\n{p['side'].upper()} {p['quantity']} @ ${p['avg_entry_price']} (PnL {p['pnl_percent']:+.2f}%)"
    return png_bytes, caption


def _draw(df, tf: str, symbol: str, positions: list[dict]) -> bytes:
    """matplotlib 캔들 + 마커 렌더 → PNG bytes."""
    fig, ax = plt.subplots(figsize=(10, 5), dpi=110)

    # 시간축
    times = [time.localtime(t / 1000) for t in df["open_time"]]
    x = list(range(len(df)))

    width = 0.7
    for i, (o, h, l, c) in enumerate(zip(df["open"], df["high"], df["low"], df["close"])):
        color = "#26a69a" if c >= o else "#ef5350"
        # wick
        ax.plot([i, i], [l, h], color=color, linewidth=0.8, zorder=1)
        # body
        bottom = min(o, c)
        height = abs(c - o) or (h - l) * 0.001
        ax.add_patch(Rectangle((i - width / 2, bottom), width, height, facecolor=color, edgecolor=color, linewidth=0.5, zorder=2))

    # 현재가 수평선
    last_close = float(df.iloc[-1]["close"])
    ax.axhline(last_close, color="#888", linestyle="--", linewidth=0.7, alpha=0.6)

    # 포지션 마커 (entry / TP / SL)
    if positions:
        p = positions[0]
        try:
            entry = float(p["avg_entry_price"])
            sl = float(p["stop_loss_price"]) if p.get("stop_loss_price") else None
            side = p["side"]
            entry_color = "#42a5f5" if side == "long" else "#ab47bc"
            ax.axhline(entry, color=entry_color, linestyle="-", linewidth=1.3, alpha=0.9, label=f"Entry ${entry:,.2f}")
            if sl:
                ax.axhline(sl, color="#ef5350", linestyle=":", linewidth=1.2, alpha=0.9, label=f"SL ${sl:,.2f}")
            for i, o in enumerate(p.get("exit_orders", []), 1):
                tp_price = float(o["price"])
                tp_color = "#66bb6a" if o.get("status") != "filled" else "#aaa"
                ax.axhline(tp_price, color=tp_color, linestyle="-.", linewidth=1.0, alpha=0.8, label=f"TP{i} ${tp_price:,.2f}")
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"[chart] position marker skipped: {e}")

    # x축 시간 라벨 (5~7개)
    n = len(df)
    if n > 0:
        step = max(1, n // 6)
        ticks = list(range(0, n, step))
        labels = [time.strftime("%m-%d %H:%M", times[i]) for i in ticks]
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, rotation=0, fontsize=8)

    ax.set_xlim(-1, n)
    ax.set_title(f"{symbol}  {tf}  (last {n} candles)", fontsize=11)
    ax.grid(True, linestyle="--", linewidth=0.3, alpha=0.5)
    if positions:
        ax.legend(loc="upper left", fontsize=8, framealpha=0.85)

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()


