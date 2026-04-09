export interface KlineRaw {
  t: number;
  o: string;
  h: string;
  l: string;
  c: string;
  v: string;
}

export interface KlineResponse {
  symbol: string;
  interval: string;
  klines: KlineRaw[];
}

export interface TickerResponse {
  symbol: string;
  price: string;
  change_24h: string;
  high_24h: string;
  low_24h: string;
  volume_24h: string;
}
