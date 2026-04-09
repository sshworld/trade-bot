"use client";

import { Fragment, useState } from "react";
import { formatPrice, formatTimestamp } from "@/lib/utils";
import type { ClosedTrade } from "@/types/trading";

interface TradeHistoryProps {
  trades: ClosedTrade[];
  total: number;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

const REASON_LABELS: Record<string, { text: string; color: string }> = {
  take_profit: { text: "익절", color: "text-emerald-400" },
  breakeven: { text: "본전", color: "text-blue-400" },
  stop_loss: { text: "손절", color: "text-red-400" },
  replaced_by_signal: { text: "교체", color: "text-yellow-400" },
  upgraded_to_normal: { text: "업그레이드", color: "text-yellow-400" },
  manual: { text: "수동", color: "text-zinc-400" },
};

export default function TradeHistory({
  trades,
  total,
  activeTab,
  todayTotal,
  allTotal,
  onTabChange,
}: TradeHistoryProps & {
  activeTab?: "today" | "all";
  todayTotal?: number;
  allTotal?: number;
  onTabChange?: (tab: "today" | "all") => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        {onTabChange ? (
          <div className="flex items-center gap-2">
            <span className="text-sm text-zinc-400">Trade History</span>
            <div className="flex items-center gap-1 ml-2">
              <button
                onClick={() => onTabChange("today")}
                className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                  activeTab === "today"
                    ? "bg-blue-600 text-white"
                    : "text-zinc-500 hover:bg-zinc-800"
                }`}
              >
                Today ({todayTotal ?? 0})
              </button>
              <button
                onClick={() => onTabChange("all")}
                className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                  activeTab === "all"
                    ? "bg-blue-600 text-white"
                    : "text-zinc-500 hover:bg-zinc-800"
                }`}
              >
                All ({allTotal ?? 0})
              </button>
            </div>
          </div>
        ) : (
          <span className="text-sm text-zinc-400">Trade History ({total})</span>
        )}
      </div>

      {trades.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-zinc-600">
          거래 내역이 없습니다
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500">
                <th className="px-4 py-2 text-left">Time</th>
                <th className="px-4 py-2 text-left">Side</th>
                <th className="px-4 py-2 text-right">Lev</th>
                <th className="px-4 py-2 text-right">Entry</th>
                <th className="px-4 py-2 text-right">Exit</th>
                <th className="px-4 py-2 text-right">PnL</th>
                <th className="px-4 py-2 text-right">PnL%</th>
                <th className="px-4 py-2 text-center">종료</th>
                <th className="px-4 py-2 text-right">Duration</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => {
                const pnl = parseFloat(trade.realized_pnl);
                const pnlColor =
                  pnl > 0 ? "text-emerald-400" : pnl < 0 ? "text-red-400" : "text-zinc-300";
                const reason = REASON_LABELS[trade.close_reason] ?? {
                  text: trade.close_reason,
                  color: "text-zinc-400",
                };
                const isExpanded = expandedId === trade.id;

                return (
                  <Fragment key={trade.id}>
                    <tr
                      className="border-b border-zinc-800/50 hover:bg-zinc-800/30 cursor-pointer"
                      onClick={() => setExpandedId(isExpanded ? null : trade.id)}
                    >
                      <td className="px-4 py-2.5 text-zinc-400">
                        {formatTimestamp(trade.closed_at)}
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            trade.side === "long"
                              ? "bg-emerald-900/50 text-emerald-400"
                              : "bg-red-900/50 text-red-400"
                          }`}
                        >
                          {trade.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-yellow-400">
                        {trade.leverage}x
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        ${formatPrice(trade.avg_entry_price)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        ${formatPrice(trade.avg_exit_price)}
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono ${pnlColor}`}>
                        {pnl >= 0 ? "+" : ""}${formatPrice(trade.realized_pnl)}
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono ${pnlColor}`}>
                        {trade.pnl_percent >= 0 ? "+" : ""}
                        {trade.pnl_percent.toFixed(2)}%
                      </td>
                      <td className={`px-4 py-2.5 text-center font-bold ${reason.color}`}>
                        {reason.text}
                      </td>
                      <td className="px-4 py-2.5 text-right text-zinc-400">
                        {formatDuration(trade.duration_seconds)}
                      </td>
                    </tr>

                    {/* 근거 상세 (클릭 시 펼침) */}
                    {isExpanded && (
                      <tr className="bg-zinc-800/20">
                        <td colSpan={9} className="px-4 py-3">
                          <div className="text-xs space-y-2">
                            <div className="text-zinc-400 font-medium">진입 근거</div>
                            <div className="text-zinc-300">{trade.signal_message}</div>
                            {trade.signal_details && (
                              <>
                                <div className="flex flex-wrap gap-3">
                                  <span className="text-emerald-400">
                                    Bull: {trade.signal_details.bullish_score}
                                  </span>
                                  <span className="text-red-400">
                                    Bear: {trade.signal_details.bearish_score}
                                  </span>
                                  <span className="text-blue-400">
                                    Net: {trade.signal_details.net_score}
                                  </span>
                                </div>
                                <div className="space-y-1">
                                  {trade.signal_details.indicators.map((ind, i) => (
                                    <div key={i} className="flex items-center gap-2 text-[11px]">
                                      <span className="rounded bg-zinc-700 px-1.5 py-0.5 text-zinc-300">
                                        {ind.indicator}
                                      </span>
                                      <span className="text-yellow-400">w={ind.weight}</span>
                                      <span className="text-zinc-400">{ind.reason}</span>
                                    </div>
                                  ))}
                                </div>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
