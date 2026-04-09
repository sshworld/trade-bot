"use client";

import { useCallback, useEffect, useState } from "react";
import { getIndicators, getSignals } from "@/lib/api";
import type { IndicatorsResponse, Signal } from "@/types/analysis";

export function useIndicators(symbol = "BTCUSDT", interval = "1h") {
  const [indicators, setIndicators] = useState<IndicatorsResponse | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [indRes, sigRes] = await Promise.all([
        getIndicators(symbol, interval),
        getSignals(symbol),
      ]);
      setIndicators(indRes);
      setSignals(sigRes.signals);
    } catch {
      // Silently fail - indicators are supplementary
    } finally {
      setLoading(false);
    }
  }, [symbol, interval]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 60_000); // 1분마다 갱신
    return () => clearInterval(timer);
  }, [fetchData]);

  return { indicators, signals, loading, refetch: fetchData };
}
