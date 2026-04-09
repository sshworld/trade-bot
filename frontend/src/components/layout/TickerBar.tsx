"use client";

import { formatPrice, formatVolume } from "@/lib/utils";
import type { TickerResponse } from "@/types/market";

interface TickerBarProps {
  ticker: TickerResponse | null;
}

export default function TickerBar({ ticker }: TickerBarProps) {
  if (!ticker) return null;

  return (
    <div className="flex items-center gap-6 border-b border-zinc-800 bg-zinc-900/50 px-6 py-2 text-xs">
      <div>
        <span className="text-zinc-500">24h High </span>
        <span className="text-zinc-200 font-mono">${formatPrice(ticker.high_24h)}</span>
      </div>
      <div>
        <span className="text-zinc-500">24h Low </span>
        <span className="text-zinc-200 font-mono">${formatPrice(ticker.low_24h)}</span>
      </div>
      <div>
        <span className="text-zinc-500">24h Volume </span>
        <span className="text-zinc-200 font-mono">{formatVolume(ticker.volume_24h)} BTC</span>
      </div>
    </div>
  );
}
