"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { formatPrice } from "@/lib/utils";
import type { TickerResponse } from "@/types/market";

interface BotStatus {
  state: "scanning" | "idle" | "near" | "long" | "short" | "halted";
  leverage?: number;
  pnl?: string;
  pnlPercent?: number;
}

interface HeaderProps {
  ticker?: TickerResponse | null;
  connected?: boolean;
  botStatus?: BotStatus;
}

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  scanning: { bg: "bg-zinc-700", text: "text-zinc-300", label: "SCANNING" },
  idle:     { bg: "bg-blue-900/50", text: "text-blue-400", label: "WAITING" },
  near:     { bg: "bg-yellow-900/50", text: "text-yellow-400", label: "NEAR ENTRY" },
  long:     { bg: "bg-emerald-900/50", text: "text-emerald-400", label: "LONG" },
  short:    { bg: "bg-red-900/50", text: "text-red-400", label: "SHORT" },
  halted:   { bg: "bg-red-900", text: "text-red-300", label: "HALTED" },
};

export default function Header({ ticker, connected, botStatus }: HeaderProps) {
  const pathname = usePathname();
  const isPositive = ticker?.change_24h.startsWith("+");
  const status = botStatus ?? { state: "scanning" as const };
  const style = STATUS_STYLES[status.state] ?? STATUS_STYLES.scanning;

  return (
    <header className="flex items-center justify-between border-b border-zinc-800 bg-zinc-950 px-6 py-2.5">
      <div className="flex items-center gap-4">
        <h1 className="text-base font-bold text-white">Trade Bot</h1>
        <nav className="flex items-center gap-1">
          {[
            { href: "/dashboard", label: "Dashboard" },
            { href: "/trading", label: "Trading" },
          ].map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded px-2.5 py-1 text-xs transition-colors ${
                pathname === item.href
                  ? "bg-blue-600 text-white"
                  : "text-zinc-400 hover:bg-zinc-800 hover:text-white"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>

      {/* Price */}
      {ticker && (
        <div className="flex items-center gap-4">
          <div className="text-right">
            <span className="text-lg font-mono font-bold text-white">
              ${formatPrice(ticker.price)}
            </span>
            <span className={`ml-2 text-sm font-mono ${isPositive ? "text-emerald-400" : "text-red-400"}`}>
              {ticker.change_24h}
            </span>
          </div>
        </div>
      )}

      {/* Bot Status + Connection */}
      <div className="flex items-center gap-3">
        {/* Bot Status Badge */}
        <div className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-bold ${style.bg}`}>
          <span className={`${
            status.state === "scanning" ? "animate-pulse" :
            status.state === "near" ? "animate-pulse" : ""
          } h-1.5 w-1.5 rounded-full ${
            status.state === "long" ? "bg-emerald-400" :
            status.state === "short" ? "bg-red-400" :
            status.state === "near" ? "bg-yellow-400" :
            status.state === "halted" ? "bg-red-400" :
            "bg-zinc-400"
          }`} />
          <span className={style.text}>
            {style.label}
            {status.leverage && ` ${status.leverage}x`}
          </span>
          {status.pnl && (
            <span className={`ml-1 font-mono ${
              (status.pnlPercent ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"
            }`}>
              {(status.pnlPercent ?? 0) >= 0 ? "+" : ""}{status.pnlPercent?.toFixed(1)}%
            </span>
          )}
        </div>

        {/* Connection */}
        <div className="flex items-center gap-1.5">
          <div className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`} />
          <span className="text-[10px] text-zinc-500">
            {connected ? "Live" : "Off"}
          </span>
        </div>
      </div>
    </header>
  );
}
