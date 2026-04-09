"use client";

import type { MACDResult } from "@/types/analysis";

interface MACDPanelProps {
  macd: MACDResult | null;
}

export default function MACDPanel({ macd }: MACDPanelProps) {
  if (!macd) return <div className="text-zinc-500 text-sm">Loading MACD...</div>;

  const isBullish = macd.trend === "bullish";

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-zinc-400">MACD (12, 26, 9)</span>
        <span
          className={`text-xs px-2 py-0.5 rounded ${
            isBullish ? "bg-emerald-900/50 text-emerald-400" : "bg-red-900/50 text-red-400"
          }`}
        >
          {isBullish ? "Bullish" : "Bearish"}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className="text-[10px] text-zinc-500">MACD</div>
          <div className="text-sm font-mono text-zinc-200">{macd.macd}</div>
        </div>
        <div>
          <div className="text-[10px] text-zinc-500">Signal</div>
          <div className="text-sm font-mono text-zinc-200">{macd.signal}</div>
        </div>
        <div>
          <div className="text-[10px] text-zinc-500">Histogram</div>
          <div
            className={`text-sm font-mono ${macd.histogram >= 0 ? "text-emerald-400" : "text-red-400"}`}
          >
            {macd.histogram}
          </div>
        </div>
      </div>
    </div>
  );
}
