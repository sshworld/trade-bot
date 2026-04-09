"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WSMessage } from "@/types/ws";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

interface ToastItem {
  id: number;
  type: "open" | "close" | "fill";
  message: string;
  color: string;
  timestamp: number;
}

const TYPE_STYLES = {
  open:  { label: "OPEN",  bg: "bg-blue-900/80 border-blue-700" },
  close: { label: "CLOSE", bg: "bg-purple-900/80 border-purple-700" },
  fill:  { label: "FILL",  bg: "bg-yellow-900/80 border-yellow-700" },
};

export default function ToastProvider() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const idRef = useRef(0);

  const addToast = useCallback((type: ToastItem["type"], message: string) => {
    const id = ++idRef.current;
    setToasts((prev) => [{ id, type, message, color: "", timestamp: Date.now() }, ...prev].slice(0, 5));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 8000);
  }, []);

  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}/ws/market`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const msg: WSMessage = JSON.parse(event.data);
      if (msg.type === "trade_opened") {
        addToast("open", msg.data.message);
      } else if (msg.type === "trade_closed") {
        addToast("close", msg.data.message);
      } else if (msg.type === "tranche_filled") {
        addToast("fill", msg.data.message);
      }
    };

    ws.onerror = () => ws.close();
    ws.onclose = () => {
      setTimeout(() => {
        // reconnect handled by page-level WS
      }, 5000);
    };

    return () => ws.close();
  }, [addToast]);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-14 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-2 w-[480px] max-w-[90vw]">
      {toasts.map((toast) => {
        const style = TYPE_STYLES[toast.type];
        return (
          <div
            key={toast.id}
            className={`rounded border px-4 py-2.5 text-xs text-white shadow-lg animate-in slide-in-from-top-2 ${style.bg}`}
            onClick={() => setToasts((prev) => prev.filter((t) => t.id !== toast.id))}
          >
            <div className="flex items-center gap-2">
              <span className="font-bold text-[10px] rounded bg-black/30 px-1.5 py-0.5">
                {style.label}
              </span>
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
