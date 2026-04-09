"use client";

import { formatPrice } from "@/lib/utils";
import type { DailySummary as DailySummaryType } from "@/types/trading";

interface DailySummaryProps {
  summary: DailySummaryType | null;
}

export default function DailySummary({ summary }: DailySummaryProps) {
  if (!summary) return null;

  const todayPnl = parseFloat(summary.today_pnl);
  const totalPnl = parseFloat(summary.total_pnl);

  return (
    <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
        <div className="text-[10px] text-zinc-500">Today PnL</div>
        <div
          className={`mt-1 text-sm font-mono font-bold ${
            todayPnl > 0 ? "text-emerald-400" : todayPnl < 0 ? "text-red-400" : "text-zinc-300"
          }`}
        >
          {todayPnl >= 0 ? "+" : ""}${formatPrice(summary.today_pnl)}
        </div>
      </div>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
        <div className="text-[10px] text-zinc-500">Today Trades</div>
        <div className="mt-1 text-sm font-mono font-bold text-white">{summary.today_trades}</div>
      </div>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
        <div className="text-[10px] text-zinc-500">Today Win Rate</div>
        <div className="mt-1 text-sm font-mono font-bold text-white">{summary.today_win_rate}%</div>
      </div>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
        <div className="text-[10px] text-zinc-500">Total PnL</div>
        <div
          className={`mt-1 text-sm font-mono font-bold ${
            totalPnl > 0 ? "text-emerald-400" : totalPnl < 0 ? "text-red-400" : "text-zinc-300"
          }`}
        >
          {totalPnl >= 0 ? "+" : ""}${formatPrice(summary.total_pnl)}
        </div>
      </div>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
        <div className="text-[10px] text-zinc-500">Total Trades</div>
        <div className="mt-1 text-sm font-mono font-bold text-white">{summary.total_trades}</div>
      </div>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
        <div className="text-[10px] text-zinc-500">Overall Win Rate</div>
        <div className="mt-1 text-sm font-mono font-bold text-white">
          {summary.overall_win_rate}%
        </div>
      </div>
    </div>
  );
}
