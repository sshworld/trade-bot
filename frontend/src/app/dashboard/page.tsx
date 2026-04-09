"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Header from "@/components/layout/Header";
import TickerBar from "@/components/layout/TickerBar";
import CandlestickChart, { type ChartHandle } from "@/components/charts/CandlestickChart";
import TFSignalPanel from "@/components/indicators/TFSignalPanel";
import { useMarketData } from "@/hooks/useMarketData";
import { useMarketWebSocket } from "@/hooks/useWebSocket";
import { getScanResults, getTradingStatus, getPositions, getOverlay } from "@/lib/api";
import type { ScanResponse, TFScanResult } from "@/types/analysis";
import type { TradingStatus } from "@/types/trading";

const INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"];

export default function DashboardPage() {
  const [interval, setInterval] = useState("1h");
  const { klines, ticker, loading, error, updatePriceFromWS, updateKlineFromWS } =
    useMarketData("BTCUSDT", interval);
  const { price, lastKline, connected } = useMarketWebSocket();
  const chartRef = useRef<ChartHandle>(null);

  const [scanData, setScanData] = useState<ScanResponse | null>(null);
  const [tradingStatus, setTradingStatus] = useState<TradingStatus | null>(null);
  const [openPosition, setOpenPosition] = useState<{ side: string; leverage: number; pnl: string; pnlPercent: number } | null>(null);
  const scanTimer = useRef<number | undefined>(undefined);

  const fetchScan = useCallback(async () => {
    try {
      const [scan, status, pos] = await Promise.all([getScanResults(), getTradingStatus(), getPositions()]);
      setScanData(scan);
      setTradingStatus(status);
      if (pos.positions.length > 0) {
        const p = pos.positions[0];
        setOpenPosition({ side: p.side, leverage: p.leverage, pnl: p.unrealized_pnl, pnlPercent: p.pnl_percent });
      } else {
        setOpenPosition(null);
      }
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    fetchScan();
    scanTimer.current = window.setInterval(fetchScan, 1000);
    return () => clearInterval(scanTimer.current);
  }, [fetchScan]);

  useEffect(() => {
    if (price) {
      updatePriceFromWS(price);
      chartRef.current?.updateTickPrice(parseFloat(price));
    }
  }, [price, updatePriceFromWS]);

  useEffect(() => {
    if (lastKline) updateKlineFromWS(lastKline);
  }, [lastKline, updateKlineFromWS]);

  const currentTF: TFScanResult | null = scanData?.results[interval] ?? null;
  const [activeOverlay, setActiveOverlay] = useState<string | null>(null);

  const handleIndicatorClick = useCallback(async (tf: string, indicator: string) => {
    // 같은 걸 다시 누르면 토글 off
    const key = `${tf}:${indicator}`;
    if (activeOverlay === key) {
      chartRef.current?.clearOverlay();
      setActiveOverlay(null);
      return;
    }

    // TF 전환 + 오버레이
    setInterval(tf);
    try {
      const res = await getOverlay(tf, indicator);
      // VP는 별도 구조: profile/poc/value_area
      if (indicator === "vp" && res.profile) {
        // POC + VA를 수평선으로 표시
        const klines = res.profile as { price: number; volume: number }[];
        const poc = (res as Record<string, unknown>).poc as { price: number } | undefined;
        const va = (res as Record<string, unknown>).value_area as { high: number; low: number } | undefined;
        const fakeData = [];
        if (poc) fakeData.push({ ratio: "POC", price: poc.price, time_start: 0, time_end: 0 });
        if (va) {
          fakeData.push({ ratio: "VA_H", price: va.high, time_start: 0, time_end: 0 });
          fakeData.push({ ratio: "VA_L", price: va.low, time_start: 0, time_end: 0 });
        }
        chartRef.current?.setOverlay("fib", fakeData as Record<string, unknown>[]);
      } else {
        chartRef.current?.setOverlay(indicator, (res.data ?? res) as Record<string, unknown>[]);
      }
      setActiveOverlay(key);
    } catch {
      // silent
    }
  }, [activeOverlay]);

  const botStatus = (() => {
    if (openPosition) {
      return {
        state: openPosition.side as "long" | "short",
        leverage: openPosition.leverage,
        pnl: openPosition.pnl,
        pnlPercent: openPosition.pnlPercent,
      };
    }
    if (scanData) {
      const hasNear = Object.values(scanData.results).some(
        (r) => r.confluence_count > 0 || (r.bull_count >= 2 || r.bear_count >= 2)
      );
      if (hasNear) return { state: "near" as const };
    }
    return { state: "scanning" as const };
  })();

  return (
    <div className="flex h-screen flex-col bg-zinc-950 text-white">
      <Header ticker={ticker} connected={connected} botStatus={botStatus} />
      <TickerBar ticker={ticker} />

      <main className="flex-1 overflow-auto p-4">
        {error && (
          <div className="mb-4 rounded border border-red-800 bg-red-950/30 p-3 text-sm text-red-400">
            {error}
          </div>
        )}

        {loading && klines.length === 0 ? (
          <div className="flex h-full items-center justify-center text-zinc-500">
            Loading market data...
          </div>
        ) : (
          <div className="mx-auto max-w-7xl flex flex-col gap-4">
            {/* 포지션 스트립 (교차 참조) */}
            {openPosition && (
              <a
                href="/trading"
                className={`flex items-center justify-between rounded-lg px-4 py-2 text-xs border ${
                  openPosition.side === "long"
                    ? "border-emerald-800/50 bg-emerald-900/10"
                    : "border-red-800/50 bg-red-900/10"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className={`font-bold ${openPosition.side === "long" ? "text-emerald-400" : "text-red-400"}`}>
                    ACTIVE: {openPosition.side.toUpperCase()} {openPosition.leverage}x
                  </span>
                  <span className={`font-mono ${openPosition.pnlPercent >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {openPosition.pnlPercent >= 0 ? "+" : ""}{openPosition.pnlPercent.toFixed(2)}%
                  </span>
                </div>
                <span className="text-zinc-500">Trading →</span>
              </a>
            )}

            {/* Interval + Chart + 선택된 TF 지표 */}
            <div className="rounded-lg border border-zinc-800 bg-zinc-900">
              {/* Interval 버튼 */}
              <div className="flex items-center gap-1 px-3 py-2 border-b border-zinc-800">
                {INTERVALS.map((iv) => (
                  <button
                    key={iv}
                    onClick={() => setInterval(iv)}
                    className={`rounded px-3 py-1 text-xs transition-colors ${
                      interval === iv
                        ? "bg-blue-600 text-white"
                        : "text-zinc-400 hover:bg-zinc-800 hover:text-white"
                    }`}
                  >
                    {iv}
                  </button>
                ))}
              </div>

              {/* Chart */}
              <div className="p-2">
                <CandlestickChart ref={chartRef} klines={klines} interval={interval} className="w-full h-[450px]" />
              </div>

              {/* 선택된 interval 지표 */}
              {currentTF && <SelectedTFIndicators tf={interval} data={currentTF} />}
            </div>

            {/* Signal Analysis (전체 TF) */}
            {scanData && (
              <TFSignalPanel
                timeframes={scanData.timeframes}
                results={scanData.results}
                trend={scanData.trend}
                highlightTF={interval}
                onIndicatorClick={handleIndicatorClick}
              />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

/* ── 선택된 Interval의 지표 바 ──────────────────────────────── */

function SelectedTFIndicators({ tf, data }: { tf: string; data: TFScanResult }) {
  const rsi = data.indicators?.rsi;
  const macd = data.indicators?.macd;
  const bb = data.indicators?.bollinger;
  const ma = data.indicators?.moving_averages;

  return (
    <div className="border-t border-zinc-800 px-4 py-3">
      <div className="text-[10px] text-zinc-600 mb-1.5">INDICATORS ({tf})</div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
        {/* RSI */}
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">RSI</span>
          <span className={`font-mono font-bold ${
            rsi && rsi.value > 70 ? "text-red-400" :
            rsi && rsi.value < 30 ? "text-emerald-400" : "text-zinc-200"
          }`}>
            {rsi?.value ?? "-"}
          </span>
          {rsi && rsi.signal !== "neutral" && (
            <span className={`text-[10px] ${
              rsi.signal === "overbought" ? "text-red-400" : "text-emerald-400"
            }`}>
              {rsi.signal === "overbought" ? "과매수" : "과매도"}
            </span>
          )}
        </div>

        <div className="h-4 w-px bg-zinc-700" />

        {/* MACD */}
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">MACD</span>
          <span className={`font-mono ${
            macd?.trend === "bullish" ? "text-emerald-400" : "text-red-400"
          }`}>
            {macd?.histogram ?? "-"}
          </span>
          <span className={`text-[10px] ${
            macd?.trend === "bullish" ? "text-emerald-400/60" : "text-red-400/60"
          }`}>
            {macd?.trend ?? "-"}
          </span>
        </div>

        <div className="h-4 w-px bg-zinc-700" />

        {/* Bollinger */}
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">BB</span>
          <span className="font-mono text-red-400/70">{bb?.upper?.toLocaleString() ?? "-"}</span>
          <span className="text-zinc-600">/</span>
          <span className="font-mono text-zinc-300">{bb?.middle?.toLocaleString() ?? "-"}</span>
          <span className="text-zinc-600">/</span>
          <span className="font-mono text-emerald-400/70">{bb?.lower?.toLocaleString() ?? "-"}</span>
        </div>

        <div className="h-4 w-px bg-zinc-700" />

        {/* SMA */}
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">SMA</span>
          <span className={`font-mono ${
            ma && ma.sma_20 > ma.sma_50 ? "text-emerald-400/70" : "text-red-400/70"
          }`}>
            {ma ? (ma.sma_20 > ma.sma_50 ? "정배열" : "역배열") : "-"}
          </span>
          <span className="text-zinc-500 text-[10px]">
            20:{ma?.sma_20?.toLocaleString() ?? "-"} 50:{ma?.sma_50?.toLocaleString() ?? "-"}
          </span>
        </div>

        <div className="h-4 w-px bg-zinc-700" />

        {/* EMA */}
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">EMA</span>
          <span className={`font-mono ${
            ma && ma.ema_12 > ma.ema_26 ? "text-emerald-400/70" : "text-red-400/70"
          }`}>
            {ma && ma.ema_12 > ma.ema_26 ? "▲" : "▼"}
          </span>
          <span className="text-zinc-500 text-[10px]">
            12:{ma?.ema_12?.toLocaleString() ?? "-"} 26:{ma?.ema_26?.toLocaleString() ?? "-"}
          </span>
        </div>
      </div>
    </div>
  );
}
