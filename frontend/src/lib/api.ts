const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, API_URL);
  if (params) {
    Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getKlines(symbol = "BTCUSDT", interval = "1h", limit = "500") {
  return fetchAPI<import("@/types/market").KlineResponse>("/api/market/klines", {
    symbol,
    interval,
    limit,
  });
}

export async function getTicker(symbol = "BTCUSDT") {
  return fetchAPI<import("@/types/market").TickerResponse>("/api/market/ticker", { symbol });
}

export async function getIndicators(symbol = "BTCUSDT", interval = "1h") {
  return fetchAPI<import("@/types/analysis").IndicatorsResponse>("/api/analysis/indicators", {
    symbol,
    interval,
  });
}

export async function getSignals(symbol = "BTCUSDT") {
  return fetchAPI<import("@/types/analysis").SignalsResponse>("/api/analysis/signals", { symbol });
}

export async function getOverlay(interval: string, indicator: string) {
  return fetchAPI<Record<string, unknown>>(
    "/api/analysis/overlay",
    { interval, indicator }
  );
}

export async function getScanResults() {
  return fetchAPI<import("@/types/analysis").ScanResponse>("/api/analysis/scan");
}

// Trading API
export async function getTradingStatus() {
  return fetchAPI<import("@/types/trading").TradingStatus>("/api/trading/status");
}

export async function getPositions() {
  return fetchAPI<{ positions: import("@/types/trading").OpenPosition[] }>("/api/trading/positions");
}

export async function getTradeHistory(limit = "50", offset = "0", period = "all") {
  return fetchAPI<{ trades: import("@/types/trading").ClosedTrade[]; total: number }>(
    "/api/trading/history",
    { limit, offset, period }
  );
}

export async function getDailySnapshots() {
  return fetchAPI<{ snapshots: import("@/types/trading").DailySnapshot[] }>("/api/trading/daily-snapshots");
}

export async function getDailySummary() {
  return fetchAPI<import("@/types/trading").DailySummary>("/api/trading/summary");
}

async function postAPI<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(new URL(path, API_URL).toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function resetTradingAccount() {
  return postAPI<{ message: string }>("/api/trading/reset", {});
}
