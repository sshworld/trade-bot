"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WSMessage } from "@/types/ws";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

interface ToastItem {
  id: number;
  type: string;
  message: string;
  timestamp: number;
}

const STYLE: Record<string, { label: string; bg: string }> = {
  trade_opened:    { label: "OPEN",  bg: "bg-blue-900/90 border-blue-700" },
  trade_closed:    { label: "CLOSE", bg: "bg-purple-900/90 border-purple-700" },
  tranche_filled:  { label: "FILL",  bg: "bg-yellow-900/90 border-yellow-700" },
};

export default function ToastWrapper() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [mounted, setMounted] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const idRef = useRef(0);

  useEffect(() => {
    setMounted(true);
  }, []);

  const addToast = useCallback((type: string, message: string) => {
    const id = ++idRef.current;
    setToasts((prev) => [{ id, type, message, timestamp: Date.now() }, ...prev].slice(0, 5));
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 8000);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const ws = new WebSocket(`${WS_URL}/ws/market`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        if (msg.type === "trade_opened" || msg.type === "trade_closed" || msg.type === "tranche_filled") {
          addToast(msg.type, msg.data.message);
        }
      } catch {}
    };
    ws.onerror = () => ws.close();

    return () => ws.close();
  }, [mounted, addToast]);

  if (!mounted || toasts.length === 0) return null;

  return (
    <div className="fixed top-12 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2 w-[480px] max-w-[90vw]">
      {toasts.map((toast) => {
        const s = STYLE[toast.type] ?? { label: "INFO", bg: "bg-zinc-800 border-zinc-600" };
        return (
          <div
            key={toast.id}
            className={`rounded border px-4 py-2.5 text-xs text-white shadow-lg cursor-pointer ${s.bg}`}
            onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
          >
            <div className="flex items-center gap-2">
              <span className="font-bold text-[10px] rounded bg-black/30 px-1.5 py-0.5">{s.label}</span>
              <span className="flex-1">{toast.message}</span>
              <span className="text-zinc-400 text-[10px]">
                {new Date(toast.timestamp).toLocaleTimeString("ko-KR")}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
