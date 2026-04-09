"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getDailySummary,
  getPositions,
  getTradeHistory,
  getTradingStatus,
} from "@/lib/api";
import type { TradingStatus, OpenPosition, ClosedTrade, DailySummary } from "@/types/trading";
import type { WSMessage } from "@/types/ws";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

export function useTrading() {
  const [status, setStatus] = useState<TradingStatus | null>(null);
  const [positions, setPositions] = useState<OpenPosition[]>([]);
  const [history, setHistory] = useState<ClosedTrade[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [todayHistory, setTodayHistory] = useState<ClosedTrade[]>([]);
  const [todayTotal, setTodayTotal] = useState(0);
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [events, setEvents] = useState<{ message: string; type: string; time: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const pollTimer = useRef<ReturnType<typeof setInterval>>(undefined);

  const fetchAll = useCallback(async () => {
    try {
      const [statusRes, posRes, histRes, todayRes, sumRes] = await Promise.all([
        getTradingStatus(),
        getPositions(),
        getTradeHistory("50", "0", "all"),
        getTradeHistory("50", "0", "today"),
        getDailySummary(),
      ]);
      setStatus(statusRes);
      setPositions(posRes.positions);
      setHistory(histRes.trades);
      setHistoryTotal(histRes.total);
      setTodayHistory(todayRes.trades);
      setTodayTotal(todayRes.total);
      setSummary(sumRes);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  // WebSocket for trading events
  useEffect(() => {
    const connect = () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) return;
      const ws = new WebSocket(`${WS_URL}/ws/market`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        const msg: WSMessage = JSON.parse(event.data);

        if (msg.type === "account_update") {
          setStatus(msg.data);
        } else if (
          msg.type === "trade_opened" ||
          msg.type === "tranche_filled" ||
          msg.type === "trade_closed"
        ) {
          setEvents((prev) => [
            { message: msg.data.message, type: msg.type, time: Date.now() },
            ...prev.slice(0, 19),
          ]);
          // Refetch positions and history on trade events
          fetchAll();
        }
      };

      ws.onclose = () => {
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [fetchAll]);

  // Initial fetch + polling
  useEffect(() => {
    fetchAll();
    pollTimer.current = setInterval(fetchAll, 5_000);
    return () => clearInterval(pollTimer.current);
  }, [fetchAll]);

  return {
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
    refetch: fetchAll,
  };
}
