export interface WSTick {
  type: "tick";
  data: {
    symbol: string;
    price: string;
    quantity: string;
    timestamp: number;
    side: "buy" | "sell";
  };
}

export interface WSKline {
  type: "kline";
  data: {
    symbol: string;
    interval: string;
    t: number;
    o: string;
    h: string;
    l: string;
    c: string;
    v: string;
    closed: boolean;
  };
}

export interface WSIndicators {
  type: "indicators";
  data: {
    symbol: string;
    interval: string;
    rsi: { value: number; signal: string };
    macd: { macd: number; signal: number; histogram: number };
    bollinger: { upper: number; middle: number; lower: number };
  };
}

export interface WSSignal {
  type: "signal";
  data: {
    symbol: string;
    signal_type: string;
    direction: "bullish" | "bearish";
    strength: number;
    message: string;
    timestamp: number;
  };
}

export interface WSStatus {
  type: "status";
  data: {
    connected?: boolean;
    binance_connected?: boolean;
    message: string;
  };
}

export interface WSTradeOpened {
  type: "trade_opened";
  data: {
    position_id: string;
    symbol: string;
    side: string;
    leverage: number;
    message: string;
  };
}

export interface WSTrancheFilled {
  type: "tranche_filled";
  data: {
    position_id: string;
    is_entry: boolean;
    filled_price: string;
    quantity: string;
    filled_count: number;
    total_count: number;
    message: string;
  };
}

export interface WSTradeClosed {
  type: "trade_closed";
  data: {
    position_id: string;
    reason: string;
    realized_pnl: string;
    pnl_percent: number;
    message: string;
  };
}

export interface WSAccountUpdate {
  type: "account_update";
  data: {
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
  };
}

export type WSMessage =
  | WSTick
  | WSKline
  | WSIndicators
  | WSSignal
  | WSStatus
  | WSTradeOpened
  | WSTrancheFilled
  | WSTradeClosed
  | WSAccountUpdate;
