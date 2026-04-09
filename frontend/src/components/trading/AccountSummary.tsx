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

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      <StatCard label="Balance" value={`$${formatPrice(status.balance)}`} />
      <StatCard label="Equity" value={`$${formatPrice(status.equity)}`} />
      <StatCard
        label="Unrealized PnL"
        value={`${pnl >= 0 ? "+" : ""}$${formatPrice(status.unrealized_pnl)}`}
        color={pnlColor}
      />
      <StatCard label="Margin Used" value={`$${formatPrice(status.margin_used)}`} />
      <StatCard
        label="Total Fees"
        value={`-$${formatPrice(status.total_fees)}`}
        color="text-orange-400"
      />
    </div>
  );
}
