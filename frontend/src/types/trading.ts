export interface TradingStatus {
  balance: string;
  equity: string;
  unrealized_pnl: string;
  margin_used: string;
  total_fees: string;
  daily_pnl: string;
  daily_trades: number;
  open_positions_count: number;
  total_trades: number;
  win_rate: number;
}

export interface IndicatorDetail {
  indicator: string;
  weight: number;
  reason: string;
}

export interface SignalDetails {
  bullish_score: number;
  bearish_score: number;
  net_score: number;
  indicators: IndicatorDetail[];
}

export interface OrderInfo {
  price: string;
  qty: string;
  status: "pending" | "filled" | "cancelled";
  filled_price: string | null;
}

export interface OpenPosition {
  id: string;
  symbol: string;
  side: "long" | "short";
  leverage: number;
  avg_entry_price: string;
  mark_price: string;
  quantity: string;
  unrealized_pnl: string;
  pnl_percent: number;
  margin: string;
  status: string;
  filled_entries: number;
  total_entries: number;
  filled_exits: number;
  total_exits: number;
  stop_loss_price: string;
  entry_orders: OrderInfo[];
  exit_orders: OrderInfo[];
  signal_type: string;
  signal_message: string;
  signal_details: SignalDetails | null;
  opened_at: number;
}

export interface ClosedTrade {
  id: string;
  symbol: string;
  side: "long" | "short";
  leverage: number;
  avg_entry_price: string;
  avg_exit_price: string;
  quantity: string;
  realized_pnl: string;
  pnl_percent: number;
  signal_type: string;
  signal_message: string;
  signal_details: SignalDetails | null;
  close_reason: string;
  opened_at: number;
  closed_at: number;
  duration_seconds: number;
}

export interface DailySnapshot {
  date: string;
  open_balance: string;
  close_balance: string;
  pnl: string;
  trades: number;
  fees: string;
}

export interface DailySummary {
  today_pnl: string;
  today_trades: number;
  today_win_rate: number;
  total_pnl: string;
  total_trades: number;
  overall_win_rate: number;
}
