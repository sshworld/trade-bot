"use client";

import type { RSIResult } from "@/types/analysis";

interface RSIPanelProps {
  rsi: RSIResult | null;
}

export default function RSIPanel({ rsi }: RSIPanelProps) {
  if (!rsi) return <div className="text-zinc-500 text-sm">Loading RSI...</div>;

  const getColor = () => {
    if (rsi.signal === "overbought") return "text-red-400";
    if (rsi.signal === "oversold") return "text-emerald-400";
    return "text-zinc-300";
  };

  const getBarWidth = () => `${Math.min(rsi.value, 100)}%`;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-zinc-400">RSI ({rsi.period})</span>
        <span className={`text-lg font-mono font-bold ${getColor()}`}>{rsi.value}</span>
      </div>
      <div className="h-2 w-full rounded-full bg-zinc-800">
        <div
          className={`h-2 rounded-full transition-all ${
            rsi.value > 70 ? "bg-red-500" : rsi.value < 30 ? "bg-emerald-500" : "bg-blue-500"
          }`}
          style={{ width: getBarWidth() }}
        />
      </div>
      <div className="flex justify-between mt-1 text-[10px] text-zinc-600">
        <span>0</span>
        <span>30</span>
        <span>50</span>
        <span>70</span>
        <span>100</span>
      </div>
      <div className="mt-2 text-xs">
        <span className={getColor()}>
          {rsi.signal === "overbought" && "과매수 - 하락 반전 주의"}
          {rsi.signal === "oversold" && "과매도 - 상승 반전 가능"}
          {rsi.signal === "neutral" && "중립 구간"}
        </span>
      </div>
    </div>
  );
}
