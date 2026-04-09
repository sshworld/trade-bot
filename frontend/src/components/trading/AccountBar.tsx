"use client";

import { formatPrice } from "@/lib/utils";
import type { TradingStatus } from "@/types/trading";

interface AccountBarProps {
  status: TradingStatus | null;
}

export default function AccountBar({ status }: AccountBarProps) {
  if (!status) return null;

  const pnl = parseFloat(status.unrealized_pnl);
  const pnlColor = pnl > 0 ? "text-emerald-400" : pnl < 0 ? "text-red-400" : "text-zinc-300";

  return (
    <div className="flex items-center gap-6 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2 text-xs">
      <div>
        <span className="text-zinc-500">Balance </span>
        <span className="font-mono text-white">${formatPrice(status.balance)}</span>
      </div>
      <div>
        <span className="text-zinc-500">Equity </span>
        <span className="font-mono text-white">${formatPrice(status.equity)}</span>
      </div>
      <div>
        <span className="text-zinc-500">PnL </span>
        <span className={`font-mono ${pnlColor}`}>
          {pnl >= 0 ? "+" : ""}${formatPrice(status.unrealized_pnl)}
        </span>
      </div>
      <div>
        <span className="text-zinc-500">Margin </span>
        <span className="font-mono text-zinc-300">${formatPrice(status.margin_used)}</span>
      </div>
      <div>
        <span className="text-zinc-500">Fees </span>
        <span className="font-mono text-orange-400">-${formatPrice(status.total_fees)}</span>
      </div>
      <div>
        <span className="text-zinc-500">Today </span>
        <span className={`font-mono ${parseFloat(status.daily_pnl ?? "0") >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          {parseFloat(status.daily_pnl ?? "0") >= 0 ? "+" : ""}${formatPrice(status.daily_pnl ?? "0")}
        </span>
        <span className="text-zinc-600 ml-1">({status.daily_trades ?? 0}trades)</span>
      </div>
    </div>
  );
}
