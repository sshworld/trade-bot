"use client";

import { formatPrice } from "@/lib/utils";
import type { TradingStatus } from "@/types/trading";

interface AccountSummaryProps {
  status: TradingStatus | null;
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div className={`mt-1 text-lg font-mono font-bold ${color ?? "text-white"}`}>
        {value}
      </div>
    </div>
  );
}

export default function AccountSummary({ status }: AccountSummaryProps) {
  if (!status) return null;

  const pnl = parseFloat(status.unrealized_pnl);
  const pnlColor = pnl > 0 ? "text-emerald-400" : pnl < 0 ? "text-red-400" : "text-zinc-300";

  const available = parseFloat(status.balance) - parseFloat(status.margin_used);
  const dailyPnl = parseFloat(status.daily_pnl);
  const dailyColor = dailyPnl > 0 ? "text-emerald-400" : dailyPnl < 0 ? "text-red-400" : "text-zinc-300";

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
      <StatCard label="Balance" value={`$${formatPrice(status.balance)}`} />
      <StatCard
        label="Available"
        value={`$${formatPrice(String(available.toFixed(2)))}`}
        color="text-blue-400"
      />
      <StatCard label="Equity" value={`$${formatPrice(status.equity)}`} />
      <StatCard
        label="Unrealized PnL"
        value={`${pnl >= 0 ? "+" : ""}$${formatPrice(status.unrealized_pnl)}`}
        color={pnlColor}
      />
      <StatCard
        label="Daily PnL"
        value={`${dailyPnl >= 0 ? "+" : ""}$${formatPrice(status.daily_pnl)}`}
        color={dailyColor}
      />
      <StatCard
        label="Margin / Fees"
        value={`$${formatPrice(status.margin_used)} / $${formatPrice(status.total_fees)}`}
        color="text-zinc-400"
      />
    </div>
  );
}
