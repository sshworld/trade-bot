"use client";

import { useCallback, useEffect, useImperativeHandle, useRef, forwardRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  ColorType,
} from "lightweight-charts";
import type { KlineRaw } from "@/types/market";

interface CandlestickChartProps {
  klines: KlineRaw[];
  interval?: string;
  className?: string;
}

export interface ChartHandle {
  updateTickPrice: (price: number) => void;
  setOverlay: (type: string, data: Record<string, unknown>[]) => void;
  clearOverlay: () => void;
}

function toTime(t: number) {
  return (t / 1000) as import("lightweight-charts").UTCTimestamp;
}

const CandlestickChart = forwardRef<ChartHandle, CandlestickChartProps>(
  function CandlestickChart({ klines, interval, className }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const overlaySeriesRef = useRef<ISeriesApi<"Line">[]>([]);
    const initializedRef = useRef(false);
    const lastCandleRef = useRef<{
      time: number; open: number; high: number; low: number; close: number;
    } | null>(null);

    useImperativeHandle(ref, () => ({
      updateTickPrice(price: number) {
        const candle = lastCandleRef.current;
        const series = candleSeriesRef.current;
        if (!candle || !series) return;
        candle.close = price;
        if (price > candle.high) candle.high = price;
        if (price < candle.low) candle.low = price;
        series.update({
          time: toTime(candle.time),
          open: candle.open, high: candle.high, low: candle.low, close: candle.close,
        });
      },

      setOverlay(type: string, data: Record<string, unknown>[]) {
        const chart = chartRef.current;
        if (!chart) return;
        // 기존 오버레이 제거
        for (const s of overlaySeriesRef.current) {
          try { chart.removeSeries(s); } catch {}
        }
        overlaySeriesRef.current = [];

        if (type === "rsi") {
          const s = chart.addSeries(LineSeries, { color: "#a78bfa", lineWidth: 2, priceScaleId: "overlay" }, 1);
          chart.priceScale("overlay").applyOptions({ scaleMargins: { top: 0.05, bottom: 0.05 } });
          s.setData(data.map((d) => ({ time: d.time as unknown as import("lightweight-charts").UTCTimestamp, value: d.value as number })));
          overlaySeriesRef.current.push(s);
        } else if (type === "macd") {
          const sM = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 2, priceScaleId: "macd_overlay" }, 1);
          const sS = chart.addSeries(LineSeries, { color: "#f97316", lineWidth: 1, priceScaleId: "macd_overlay" }, 1);
          chart.priceScale("macd_overlay").applyOptions({ scaleMargins: { top: 0.05, bottom: 0.05 } });
          sM.setData(data.map((d) => ({ time: d.time as unknown as import("lightweight-charts").UTCTimestamp, value: (d.macd as number) ?? 0 })));
          sS.setData(data.map((d) => ({ time: d.time as unknown as import("lightweight-charts").UTCTimestamp, value: (d.signal as number) ?? 0 })));
          overlaySeriesRef.current.push(sM, sS);
        } else if (type === "bb") {
          const colors = ["#ef4444", "#a1a1aa", "#10b981"];
          const keys = ["upper", "middle", "lower"] as const;
          for (let i = 0; i < 3; i++) {
            const s = chart.addSeries(LineSeries, {
              color: colors[i], lineWidth: 1, priceScaleId: "right",
              crosshairMarkerVisible: false,
            });
            s.setData(data.map((d) => ({ time: d.time as unknown as import("lightweight-charts").UTCTimestamp, value: (d[keys[i]] as number) ?? 0 })));
            overlaySeriesRef.current.push(s);
          }
        } else if (type === "sma") {
          const colors = ["#f59e0b", "#8b5cf6", "#06b6d4"];
          const keys = ["sma20", "sma50", "sma200"] as const;
          for (let i = 0; i < 3; i++) {
            const filtered = data.filter((d) => d[keys[i]] != null);
            if (filtered.length === 0) continue;
            const s = chart.addSeries(LineSeries, { color: colors[i], lineWidth: 1, priceScaleId: "right" });
            s.setData(filtered.map((d) => ({ time: d.time as unknown as import("lightweight-charts").UTCTimestamp, value: d[keys[i]] as number })));
            overlaySeriesRef.current.push(s);
          }
        } else if (type === "ema") {
          const s12 = chart.addSeries(LineSeries, { color: "#fb923c", lineWidth: 1, priceScaleId: "right" });
          const s26 = chart.addSeries(LineSeries, { color: "#c084fc", lineWidth: 1, priceScaleId: "right" });
          s12.setData(data.filter((d) => d.ema12 != null).map((d) => ({ time: d.time as unknown as import("lightweight-charts").UTCTimestamp, value: d.ema12 as number })));
          s26.setData(data.filter((d) => d.ema26 != null).map((d) => ({ time: d.time as unknown as import("lightweight-charts").UTCTimestamp, value: d.ema26 as number })));
          overlaySeriesRef.current.push(s12, s26);
        } else if (type === "fib") {
          // 피보나치 수평선: 각 레벨을 LineSeries 2점으로
          const fibColors: Record<string, string> = { "0.0": "#64748b", "0.236": "#94a3b8", "0.382": "#f59e0b", "0.5": "#ef4444", "0.618": "#f59e0b", "0.786": "#94a3b8", "1.0": "#64748b" };
          for (const d of data) {
            const color = fibColors[String(d.ratio)] ?? "#94a3b8";
            const s = chart.addSeries(LineSeries, { color, lineWidth: 1, priceScaleId: "right", crosshairMarkerVisible: false, lineStyle: 2 });
            s.setData([
              { time: (d.time_start as number) as unknown as import("lightweight-charts").UTCTimestamp, value: d.price as number },
              { time: (d.time_end as number) as unknown as import("lightweight-charts").UTCTimestamp, value: d.price as number },
            ]);
            overlaySeriesRef.current.push(s);
          }
        } else if (type === "elliott") {
          // 스윙 포인트 마커를 선으로 연결
          if (data.length > 1) {
            const s = chart.addSeries(LineSeries, { color: "#e879f9", lineWidth: 2, priceScaleId: "right", crosshairMarkerVisible: false });
            s.setData(data.map((d) => ({ time: d.time as unknown as import("lightweight-charts").UTCTimestamp, value: d.price as number })));
            overlaySeriesRef.current.push(s);
          }
        } else if (type === "vp") {
          // VP는 수평 히스토그램인데 lightweight-charts에서는 수평선으로 POC + VA 표시
          const poc = (data as unknown as { poc?: { price: number }; value_area?: { high: number; low: number } });
          if (poc.poc) {
            // 이 경우 data 구조가 다르므로 직접 처리
          }
        }
      },

      clearOverlay() {
        const chart = chartRef.current;
        if (!chart) return;
        for (const s of overlaySeriesRef.current) {
          try { chart.removeSeries(s); } catch {}
        }
        overlaySeriesRef.current = [];
      },
    }));

    // 차트 생성 (1회)
    useEffect(() => {
      if (!containerRef.current) return;

      const chart = createChart(containerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: "#09090b" },
          textColor: "#a1a1aa",
        },
        grid: {
          vertLines: { color: "#27272a" },
          horzLines: { color: "#27272a" },
        },
        crosshair: { mode: 0 },
        rightPriceScale: { borderColor: "#27272a" },
        timeScale: { borderColor: "#27272a", timeVisible: true },
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      });

      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#10b981",
        downColor: "#ef4444",
        borderDownColor: "#ef4444",
        borderUpColor: "#10b981",
        wickDownColor: "#ef4444",
        wickUpColor: "#10b981",
      });

      const volumeSeries = chart.addSeries(HistogramSeries, {
        color: "#3b82f6",
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
      });

      chart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });

      chartRef.current = chart;
      candleSeriesRef.current = candleSeries;
      volumeSeriesRef.current = volumeSeries;

      const handleResize = () => {
        if (containerRef.current) {
          chart.applyOptions({
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight,
          });
        }
      };

      window.addEventListener("resize", handleResize);
      return () => {
        window.removeEventListener("resize", handleResize);
        chart.remove();
        initializedRef.current = false;
      };
    }, []);

    // interval 변경 시 차트 리셋
    useEffect(() => {
      initializedRef.current = false;
    }, [interval]);

    // klines 데이터 업데이트 (초기 로드 + kline 스트림)
    useEffect(() => {
      if (!candleSeriesRef.current || !volumeSeriesRef.current || klines.length === 0) return;

      const candleSeries = candleSeriesRef.current;
      const volumeSeries = volumeSeriesRef.current;

      if (!initializedRef.current) {
        const candleData = klines.map((k) => ({
          time: toTime(k.t),
          open: parseFloat(k.o),
          high: parseFloat(k.h),
          low: parseFloat(k.l),
          close: parseFloat(k.c),
        }));
        const volumeData = klines.map((k) => ({
          time: toTime(k.t),
          value: parseFloat(k.v),
          color: parseFloat(k.c) >= parseFloat(k.o) ? "#10b98133" : "#ef444433",
        }));
        candleSeries.setData(candleData);
        volumeSeries.setData(volumeData);
        chartRef.current?.timeScale().fitContent();
        initializedRef.current = true;
      } else {
        // kline 스트림 업데이트
        const last = klines[klines.length - 1];
        candleSeries.update({
          time: toTime(last.t),
          open: parseFloat(last.o),
          high: parseFloat(last.h),
          low: parseFloat(last.l),
          close: parseFloat(last.c),
        });
        volumeSeries.update({
          time: toTime(last.t),
          value: parseFloat(last.v),
          color: parseFloat(last.c) >= parseFloat(last.o) ? "#10b98133" : "#ef444433",
        });
      }

      // lastCandleRef 동기화
      const last = klines[klines.length - 1];
      lastCandleRef.current = {
        time: last.t,
        open: parseFloat(last.o),
        high: parseFloat(last.h),
        low: parseFloat(last.l),
        close: parseFloat(last.c),
      };
    }, [klines]);

    return <div ref={containerRef} className={className ?? "w-full h-[500px]"} />;
  }
);

export default CandlestickChart;
