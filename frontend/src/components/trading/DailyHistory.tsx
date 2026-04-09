"use client";

import { useCallback, useEffect, useState } from "react";
import { formatPrice } from "@/lib/utils";
import { getDailySnapshots } from "@/lib/api";
import type { DailySnapshot } from "@/types/trading";

export default function DailyHistory() {
  const [snapshots, setSnapshots] = useState<DailySnapshot[]>([]);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    try {
      const res = await getDailySnapshots();
      setSnapshots(res.snapshots);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const t = setInterval(fetch, 30_000);
    return () => clearInterval(t);
  }, [fetch]);

  if (loading) return null;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900">
      <div className="border-b border-zinc-800 px-4 py-3">
        <span className="text-sm text-zinc-400">Daily Performance</span>
      </div>

      {snapshots.length === 0 ? (
        <div className="px-4 py-6 text-center text-xs text-zinc-600">
          일자별 데이터가 아직 없습니다 (다음 날 00:00에 기록 시작)
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500">
                <th className="px-4 py-2 text-left">Date</th>
                <th className="px-4 py-2 text-right">Open</th>
                <th className="px-4 py-2 text-right">Close</th>
                <th className="px-4 py-2 text-right">PnL</th>
                <th className="px-4 py-2 text-right">PnL%</th>
                <th className="px-4 py-2 text-center">Trades</th>
                <th className="px-4 py-2 text-right">Fees</th>
              </tr>
            </thead>
            <tbody>
              {snapshots.map((s) => {
                const pnl = parseFloat(s.pnl);
                const openBal = parseFloat(s.open_balance);
                const closeBal = parseFloat(s.close_balance);
                const pnlPct = openBal > 0 ? (pnl / openBal) * 100 : 0;
                const pnlColor =
                  pnl > 0 ? "text-emerald-400" : pnl < 0 ? "text-red-400" : "text-zinc-300";

                return (
                  <tr key={s.date} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                    <td className="px-4 py-2.5 font-mono text-zinc-300">{s.date}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-zinc-400">
                      ${formatPrice(s.open_balance)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-zinc-200">
                      ${formatPrice(s.close_balance)}
                    </td>
                    <td className={`px-4 py-2.5 text-right font-mono ${pnlColor}`}>
                      {pnl >= 0 ? "+" : ""}${formatPrice(s.pnl)}
                    </td>
                    <td className={`px-4 py-2.5 text-right font-mono ${pnlColor}`}>
                      {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
                    </td>
                    <td className="px-4 py-2.5 text-center text-zinc-400">{s.trades}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-orange-400/70">
                      -${formatPrice(s.fees)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            {snapshots.length > 0 && (
              <tfoot>
                <tr className="border-t border-zinc-700 text-zinc-300">
                  <td className="px-4 py-2 font-bold">Total</td>
                  <td className="px-4 py-2 text-right font-mono">
                    ${formatPrice(snapshots[snapshots.length - 1]?.open_balance ?? "0")}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    ${formatPrice(snapshots[0]?.close_balance ?? "0")}
                  </td>
                  <td className={`px-4 py-2 text-right font-mono ${
                    snapshots.reduce((a, s) => a + parseFloat(s.pnl), 0) >= 0 ? "text-emerald-400" : "text-red-400"
                  }`}>
                    {snapshots.reduce((a, s) => a + parseFloat(s.pnl), 0) >= 0 ? "+" : ""}
                    ${formatPrice(String(snapshots.reduce((a, s) => a + parseFloat(s.pnl), 0).toFixed(2)))}
                  </td>
                  <td />
                  <td className="px-4 py-2 text-center text-zinc-400">
                    {snapshots.reduce((a, s) => a + s.trades, 0)}
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  );
}
