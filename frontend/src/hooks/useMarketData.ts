"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getKlines, getTicker } from "@/lib/api";
import type { KlineRaw, TickerResponse } from "@/types/market";
import type { WSKline } from "@/types/ws";

export function useMarketData(symbol = "BTCUSDT", interval = "1h") {
  const [klines, setKlines] = useState<KlineRaw[]>([]);
  const [ticker, setTicker] = useState<TickerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tickerInterval = useRef<ReturnType<typeof setInterval>>(undefined);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [klineRes, tickerRes] = await Promise.all([
        getKlines(symbol, interval),
        getTicker(symbol),
      ]);
      setKlines(klineRes.klines);
      setTicker(tickerRes);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch data");
    } finally {
      setLoading(false);
    }
  }, [symbol, interval]);

  // 초기 로드 + 주기적 ticker 갱신 (10초)
  useEffect(() => {
    fetchData();
    tickerInterval.current = setInterval(async () => {
      try {
        const tickerRes = await getTicker(symbol);
        setTicker(tickerRes);
      } catch {
        // 조용히 실패
      }
    }, 10_000);
    return () => clearInterval(tickerInterval.current);
  }, [fetchData, symbol]);

  // WebSocket 실시간 가격으로 ticker만 갱신 (차트는 ref로 직접 업데이트)
  const updatePriceFromWS = useCallback((price: string) => {
    setTicker((prev) => (prev ? { ...prev, price } : prev));
  }, []);

  // WebSocket kline으로 차트 실시간 업데이트
  const updateKlineFromWS = useCallback(
    (wsKline: WSKline["data"]) => {
      // 현재 interval과 다르면 무시
      if (wsKline.interval !== interval) return;

      setKlines((prev) => {
        if (prev.length === 0) return prev;

        const newKline: KlineRaw = {
          t: wsKline.t,
          o: wsKline.o,
          h: wsKline.h,
          l: wsKline.l,
          c: wsKline.c,
          v: wsKline.v,
        };

        const lastIdx = prev.length - 1;
        // 같은 시간의 캔들이면 업데이트, 새 캔들이면 추가
        if (prev[lastIdx].t === wsKline.t) {
          const updated = [...prev];
          updated[lastIdx] = newKline;
          return updated;
        } else if (wsKline.t > prev[lastIdx].t) {
          return [...prev.slice(1), newKline];
        }
        return prev;
      });
    },
    [interval]
  );

  return {
    klines,
    ticker,
    loading,
    error,
    refetch: fetchData,
    updatePriceFromWS,
    updateKlineFromWS,
  };
}
