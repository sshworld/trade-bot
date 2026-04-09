"use client";

import { formatTimestamp } from "@/lib/utils";
import type { Signal } from "@/types/analysis";

interface SignalCardProps {
  signals: Signal[];
}

export default function SignalCard({ signals }: SignalCardProps) {
  if (signals.length === 0) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <span className="text-sm text-zinc-400">Signals</span>
        <p className="mt-2 text-xs text-zinc-500">현재 활성 시그널 없음</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <span className="text-sm text-zinc-400">Signals ({signals.length})</span>
      <div className="mt-2 space-y-2">
        {signals.map((signal, i) => (
          <div
            key={i}
            className={`rounded border p-2 text-xs ${
              signal.direction === "bullish"
                ? "border-emerald-800 bg-emerald-950/30"
                : "border-red-800 bg-red-950/30"
            }`}
          >
            <div className="flex items-center justify-between">
              <span
                className={
                  signal.direction === "bullish" ? "text-emerald-400" : "text-red-400"
                }
              >
                {signal.direction === "bullish" ? "LONG" : "SHORT"}
              </span>
              <span className="text-zinc-500">{formatTimestamp(signal.timestamp)}</span>
            </div>
            <p className="mt-1 text-zinc-300">{signal.message}</p>
            <div className="mt-1 flex items-center gap-1">
              <span className="text-zinc-500">Strength:</span>
              <div className="h-1.5 w-16 rounded-full bg-zinc-700">
                <div
                  className={`h-1.5 rounded-full ${
                    signal.direction === "bullish" ? "bg-emerald-500" : "bg-red-500"
                  }`}
                  style={{ width: `${signal.strength * 100}%` }}
                />
              </div>
              <span className="text-zinc-400">{(signal.strength * 100).toFixed(0)}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
