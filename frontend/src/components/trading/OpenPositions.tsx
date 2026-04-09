"use client";

import { Fragment, useState } from "react";
import { formatPrice } from "@/lib/utils";
import type { OpenPosition } from "@/types/trading";

interface OpenPositionsProps {
  positions: OpenPosition[];
}

export default function OpenPositions({ positions }: OpenPositionsProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <span className="text-sm text-zinc-400">Open Positions ({positions.length})</span>
      </div>

      {positions.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-zinc-600">
          진행 중인 포지션이 없습니다
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500">
                <th className="px-4 py-2 text-left">Symbol</th>
                <th className="px-4 py-2 text-left">Side</th>
                <th className="px-4 py-2 text-right">Leverage</th>
                <th className="px-4 py-2 text-right">Size</th>
                <th className="px-4 py-2 text-right">Entry</th>
                <th className="px-4 py-2 text-right">Mark</th>
                <th className="px-4 py-2 text-right">PnL</th>
                <th className="px-4 py-2 text-right">PnL%</th>
                <th className="px-4 py-2 text-center">Entries</th>
                <th className="px-4 py-2 text-center">Exits</th>
                <th className="px-4 py-2 text-right">Stop Loss</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => {
                const pnl = parseFloat(pos.unrealized_pnl);
                const pnlColor =
                  pnl > 0 ? "text-emerald-400" : pnl < 0 ? "text-red-400" : "text-zinc-300";
                const isExpanded = expandedId === pos.id;

                return (
                  <Fragment key={pos.id}>
                    <tr
                      className="border-b border-zinc-800/50 hover:bg-zinc-800/30 cursor-pointer"
                      onClick={() => setExpandedId(isExpanded ? null : pos.id)}
                    >
                      <td className="px-4 py-2.5 font-mono">{pos.symbol}</td>
                      <td className="px-4 py-2.5">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            pos.side === "long"
                              ? "bg-emerald-900/50 text-emerald-400"
                              : "bg-red-900/50 text-red-400"
                          }`}
                        >
                          {pos.side.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-yellow-400">
                        {pos.leverage}x
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        <div>
                          {pos.quantity}
                          <span className="text-zinc-500 text-[10px] ml-1">
                            (${formatPrice(String(parseFloat(pos.quantity) * parseFloat(pos.avg_entry_price)))})
                          </span>
                        </div>
                        {pos.filled_entries < pos.total_entries && (
                          <div className="text-[10px] text-yellow-500">
                            체결 {pos.filled_entries}/{pos.total_entries} · 대기 {pos.total_entries - pos.filled_entries}건
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        <div>${formatPrice(pos.avg_entry_price)}</div>
                        {pos.filled_entries > 1 && (
                          <div className="text-[10px] text-zinc-500">
                            avg({pos.filled_entries}건)
                          </div>
                        )}
                        {pos.filled_entries < pos.total_entries && (
                          <div className="text-[10px] text-yellow-600">
                            {pos.entry_orders?.filter(o => o.status === "pending").map((o, i) => (
                              <span key={i} className="mr-1">${formatPrice(o.price)}</span>
                            ))}
                            대기
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono">
                        ${formatPrice(pos.mark_price)}
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono ${pnlColor}`}>
                        {pnl >= 0 ? "+" : ""}${formatPrice(pos.unrealized_pnl)}
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono ${pnlColor}`}>
                        {pos.pnl_percent >= 0 ? "+" : ""}
                        {pos.pnl_percent.toFixed(2)}%
                      </td>
                      <td className="px-4 py-2.5 text-center text-zinc-400">
                        {pos.filled_entries}/{pos.total_entries}
                      </td>
                      <td className="px-4 py-2.5 text-center text-zinc-400">
                        {pos.filled_exits}/{pos.total_exits}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-red-400/70">
                        ${formatPrice(pos.stop_loss_price)}
                      </td>
                    </tr>

                    {/* 진입 근거 상세 (클릭 시 펼침) */}
                    {isExpanded && (
                      <tr className="bg-zinc-800/20">
                        <td colSpan={11} className="px-4 py-3">
                          <div className="text-xs space-y-2">
                            <div className="text-zinc-400 font-medium">진입 근거</div>
                            <div className="text-zinc-300">{pos.signal_message}</div>
                            {pos.signal_details && (
                              <div className="flex flex-wrap gap-3">
                                <span className="text-emerald-400">
                                  Bull: {pos.signal_details.bullish_score}
                                </span>
                                <span className="text-red-400">
                                  Bear: {pos.signal_details.bearish_score}
                                </span>
                                <span className="text-blue-400">
                                  Net: {pos.signal_details.net_score}
                                </span>
                              </div>
                            )}
                            {pos.signal_details?.indicators && (
                              <div className="space-y-1 mt-1">
                                {pos.signal_details.indicators.map((ind, i) => (
                                  <div
                                    key={i}
                                    className="flex items-center gap-2 text-[11px]"
                                  >
                                    <span className="rounded bg-zinc-700 px-1.5 py-0.5 text-zinc-300">
                                      {ind.indicator}
                                    </span>
                                    <span className="text-yellow-400">w={ind.weight}</span>
                                    <span className="text-zinc-400">{ind.reason}</span>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* 주문 상세: Entry + Exit + SL */}
                            <div className="grid grid-cols-1 gap-3 mt-3 md:grid-cols-3">
                              {/* Entry Orders */}
                              <div>
                                <div className="text-zinc-500 font-medium mb-1">분할 진입</div>
                                {pos.entry_orders?.map((o, i) => (
                                  <div key={i} className="flex items-center gap-2 text-[11px] py-0.5">
                                    <span className={`w-12 text-center rounded px-1 py-0.5 text-[10px] font-bold ${
                                      o.status === "filled" ? "bg-emerald-900/50 text-emerald-400" :
                                      o.status === "pending" ? "bg-yellow-900/30 text-yellow-400" :
                                      "bg-zinc-800 text-zinc-500"
                                    }`}>
                                      {o.status === "filled" ? "체결" : o.status === "pending" ? "대기" : "취소"}
                                    </span>
                                    <span className="font-mono text-zinc-300">
                                      ${formatPrice(o.filled_price ?? o.price)}
                                    </span>
                                    <span className="text-zinc-500">{o.qty} BTC</span>
                                  </div>
                                ))}
                              </div>

                              {/* Exit Orders (TP) */}
                              <div>
                                <div className="text-zinc-500 font-medium mb-1">분할 익절 (TP)</div>
                                {pos.exit_orders?.length ? pos.exit_orders.map((o, i) => (
                                  <div key={i} className="flex items-center gap-2 text-[11px] py-0.5">
                                    <span className={`w-12 text-center rounded px-1 py-0.5 text-[10px] font-bold ${
                                      o.status === "filled" ? "bg-emerald-900/50 text-emerald-400" :
                                      o.status === "pending" ? "bg-blue-900/30 text-blue-400" :
                                      "bg-zinc-800 text-zinc-500"
                                    }`}>
                                      {o.status === "filled" ? "체결" : o.status === "pending" ? "대기" : "취소"}
                                    </span>
                                    <span className="font-mono text-emerald-400/70">
                                      ${formatPrice(o.price)}
                                    </span>
                                    <span className="text-zinc-500">{o.qty} BTC</span>
                                  </div>
                                )) : (
                                  <div className="text-[11px] text-zinc-600">진입 완료 후 생성</div>
                                )}
                              </div>

                              {/* Stop Loss */}
                              <div>
                                <div className="text-zinc-500 font-medium mb-1">손절 (SL)</div>
                                <div className="flex items-center gap-2 text-[11px]">
                                  <span className="w-12 text-center rounded px-1 py-0.5 text-[10px] font-bold bg-red-900/30 text-red-400">
                                    SL
                                  </span>
                                  <span className="font-mono text-red-400">
                                    ${formatPrice(pos.stop_loss_price)}
                                  </span>
                                  <span className="text-zinc-500">전량 청산</span>
                                </div>
                              </div>
                            </div>
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
