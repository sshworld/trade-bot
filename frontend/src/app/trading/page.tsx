"use client";

import { useEffect, useState } from "react";
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

  const { ticker, updatePriceFromWS } = useMarketData("BTCUSDT", "1h");
  const { price, connected: wsConnected } = useMarketWebSocket();

  useEffect(() => {
    if (price) updatePriceFromWS(price);
  }, [price, updatePriceFromWS]);
  const [historyTab, setHistoryTab] = useState<"today" | "all">("today");

  const botStatus = (() => {
    if (positions.length > 0) {
      const p = positions[0];
      return { state: p.side as "long" | "short", leverage: p.leverage, pnl: p.unrealized_pnl, pnlPercent: p.pnl_percent };
    }
    return { state: "idle" as const };
  })();

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
              <h2 className="text-lg font-bold">Live Trading</h2>
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
