"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WSMessage, WSTick, WSKline } from "@/types/ws";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

interface MarketWSState {
  price: string | null;
  lastTick: WSTick["data"] | null;
  lastKline: WSKline["data"] | null;
  connected: boolean;
}

export function useMarketWebSocket() {
  const [state, setState] = useState<MarketWSState>({
    price: null,
    lastTick: null,
    lastKline: null,
    connected: false,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // tick은 ref에 즉시 저장, rAF로 매 프레임 flush (60fps)
  const latestTickRef = useRef<WSTick["data"] | null>(null);
  const rafRef = useRef<number>(0);
  const mountedRef = useRef(true);

  const flushTick = useCallback(() => {
    if (!mountedRef.current) return;

    const tick = latestTickRef.current;
    if (tick) {
      latestTickRef.current = null;
      setState((prev) => ({
        ...prev,
        price: tick.price,
        lastTick: tick,
      }));
    }

    rafRef.current = requestAnimationFrame(flushTick);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(`${WS_URL}/ws/market`);
    wsRef.current = ws;

    ws.onopen = () => {
      setState((prev) => ({ ...prev, connected: true }));
    };

    ws.onmessage = (event) => {
      const msg: WSMessage = JSON.parse(event.data);
      if (msg.type === "tick") {
        // ref에만 저장 (렌더 X, 다음 rAF에서 flush)
        latestTickRef.current = msg.data;
      } else if (msg.type === "kline") {
        setState((prev) => ({ ...prev, lastKline: msg.data }));
      }
    };

    ws.onclose = () => {
      setState((prev) => ({ ...prev, connected: false }));
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    rafRef.current = requestAnimationFrame(flushTick);

    return () => {
      mountedRef.current = false;
      clearTimeout(reconnectTimer.current);
      cancelAnimationFrame(rafRef.current);
      wsRef.current?.close();
    };
  }, [connect, flushTick]);

  return state;
}
