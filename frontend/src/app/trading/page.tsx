"use client";

import { useState } from "react";
import Header from "@/components/layout/Header";
import AccountSummary from "@/components/trading/AccountSummary";
import DailySummary from "@/components/trading/DailySummary";
import OpenPositions from "@/components/trading/OpenPositions";
import TradeHistory from "@/components/trading/TradeHistory";
import EventLog from "@/components/trading/EventLog";
import DailyHistory from "@/components/trading/DailyHistory";
import { useTrading } from "@/hooks/useTrading";
import { useMarketWebSocket } from "@/hooks/useWebSocket";
import { useMarketData } from "@/hooks/useMarketData";
import { resetTradingAccount } from "@/lib/api";

export default function TradingPage() {
  const {
    status,
    positions,
    history,
    historyTotal,
    todayHistory,
    todayTotal,
    summary,
    events,
    loading,
    connected,
    refetch,
  } = useTrading();

  const { ticker } = useMarketData("BTCUSDT", "1h");
  const { connected: wsConnected } = useMarketWebSocket();
  const [historyTab, setHistoryTab] = useState<"today" | "all">("today");

  const botStatus = (() => {
    if (positions.length > 0) {
      const p = positions[0];
      return { state: p.side as "long" | "short", leverage: p.leverage, pnl: p.unrealized_pnl, pnlPercent: p.pnl_percent };
    }
    return { state: "scanning" as const };
  })();

  const handleReset = async () => {
    if (confirm("계좌를 초기화하시겠습니까?")) {
      await resetTradingAccount();
      refetch();
    }
  };

  return (
    <div className="flex h-screen flex-col bg-zinc-950 text-white">
      <Header ticker={ticker} connected={connected || wsConnected} botStatus={botStatus} />

      <main className="flex-1 overflow-auto p-4">
        {loading ? (
          <div className="flex h-full items-center justify-center text-zinc-500">
            Loading trading data...
          </div>
        ) : (
          <div className="mx-auto max-w-7xl flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">Paper Trading</h2>
              <button
                onClick={handleReset}
                className="rounded border border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-red-700 hover:text-red-400"
              >
                Reset Account
              </button>
            </div>

            <AccountSummary status={status} />
            <DailySummary summary={summary} />
            <OpenPositions positions={positions} />

            {/* Trade History + Daily Performance / Event Log */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <TradeHistory
                trades={historyTab === "today" ? todayHistory : history}
                total={historyTab === "today" ? todayTotal : historyTotal}
                activeTab={historyTab}
                todayTotal={todayTotal}
                allTotal={historyTotal}
                onTabChange={setHistoryTab}
              />
              <div className="flex flex-col gap-4">
                <DailyHistory />
                <EventLog events={events} />
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
