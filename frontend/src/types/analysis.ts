export interface RSIResult {
  value: number;
  signal: "overbought" | "oversold" | "neutral";
  period: number;
}

export interface MACDResult {
  macd: number;
  signal: number;
  histogram: number;
  trend: "bullish" | "bearish";
}

export interface BollingerResult {
  upper: number;
  middle: number;
  lower: number;
  bandwidth: number;
  position: "above_upper" | "below_lower" | "within";
}

export interface MovingAveragesResult {
  sma_20: number;
  sma_50: number;
  sma_200: number | null;
  ema_12: number;
  ema_26: number;
}

export interface IndicatorsResponse {
  symbol: string;
  interval: string;
  rsi: RSIResult;
  macd: MACDResult;
  bollinger: BollingerResult;
  moving_averages: MovingAveragesResult;
}

export interface Signal {
  type: string;
  direction: "bullish" | "bearish";
  strength: number;
  message: string;
  timestamp: number;
  family?: string;
}

export interface SignalsResponse {
  symbol: string;
  signals: Signal[];
}

export interface TFScanResult {
  timeframe: string;
  scanned_at: number;
  indicators: {
    rsi: RSIResult;
    macd: MACDResult;
    bollinger: BollingerResult;
    moving_averages: MovingAveragesResult;
  };
  confluence: Signal[];
  individual: Signal[];
  signal_count: number;
  confluence_count: number;
  confirmed?: boolean;
  threshold: { min_count: number; min_score: number; min_net: number };
  bull_score: number;
  bear_score: number;
  bull_count: number;
  bear_count: number;
  bull_families?: number;
  bear_families?: number;
  strong_triggers: number;
}

export interface TrendInfo {
  directions: Record<string, string>;
  strengths: Record<string, number>;
}

export interface ScanResponse {
  timeframes: string[];
  results: Record<string, TFScanResult>;
  trend: TrendInfo;
}
