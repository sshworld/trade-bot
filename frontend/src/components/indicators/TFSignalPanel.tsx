"use client";

import { useEffect, useState } from "react";
import type { TFScanResult, TrendInfo } from "@/types/analysis";

interface TFSignalPanelProps {
  timeframes: string[];
  results: Record<string, TFScanResult>;
  trend?: TrendInfo;
  highlightTF?: string;
  onIndicatorClick?: (tf: string, indicator: string) => void;
}

const DIR_ICON: Record<string, { sym: string; color: string }> = {
  bullish: { sym: "▲", color: "text-emerald-400" },
  bearish: { sym: "▼", color: "text-red-400" },
  neutral: { sym: "─", color: "text-zinc-500" },
};

export default function TFSignalPanel({ timeframes, results, trend, highlightTF, onIndicatorClick }: TFSignalPanelProps) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const sortedTFs = [...timeframes].reverse();

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 space-y-3">
      {/* Header: Trend Filter + Time */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xs text-zinc-500">TREND FILTER</span>
          <div className="flex items-center gap-2">
            {["1d", "4h", "1h", "30m", "15m"].map((tf) => {
              const dir = trend?.directions[tf] ?? "neutral";
              const d = DIR_ICON[dir] ?? DIR_ICON.neutral;
              return (
                <span key={tf} className="flex items-center gap-0.5 text-[11px]">
                  <span className="text-zinc-600 font-mono">{tf}</span>
                  <span className={d.color}>{d.sym}</span>
                </span>
              );
            })}
          </div>
        </div>
        <span className="text-xs font-mono text-zinc-400">
          {now.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </span>
      </div>

      {/* TF Pipeline */}
      <div className="space-y-2">
        {sortedTFs.map((tf) => {
          const r = results[tf];
          if (!r) return null;
          return <TFRow key={tf} tf={tf} data={r} trend={trend} highlightTF={highlightTF} onIndicatorClick={onIndicatorClick} />;
        })}
      </div>
    </div>
  );
}

function TFRow({ tf, data, trend, highlightTF, onIndicatorClick }: {
  tf: string; data: TFScanResult; trend?: TrendInfo; highlightTF?: string;
  onIndicatorClick?: (tf: string, indicator: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const thresh = data.threshold ?? { min_count: 3, min_score: 3.0, min_net: 2.0 };
  const hasConf = data.confluence_count > 0;

  // 지배 방향
  const dominant = data.bull_score > data.bear_score ? "bullish" : data.bear_score > data.bull_score ? "bearish" : "neutral";
  const domFamilies = dominant === "bullish" ? (data.bull_families ?? data.bull_count) : (data.bear_families ?? data.bear_count);
  const domScore = dominant === "bullish" ? data.bull_score : data.bear_score;
  const oppScore = dominant === "bullish" ? data.bear_score : data.bull_score;
  const netScore = domScore - oppScore;

  // 진행도 (score 기준)
  const progress = Math.min(domScore / thresh.min_score, 1.0);
  const progressPct = Math.round(progress * 100);

  // 부족한 것
  const needCount = Math.max(0, thresh.min_count - domFamilies);
  const needScore = Math.max(0, thresh.min_score - domScore);
  const needNet = Math.max(0, thresh.min_net - netScore);
  const needTrigger = data.strong_triggers < 1;
  const isClose = progressPct >= 60 && !hasConf;

  // 배경색
  let bgClass = "";
  if (hasConf) {
    bgClass = data.confluence[0]?.direction === "bullish"
      ? "bg-emerald-900/15 border border-emerald-800/50"
      : "bg-red-900/15 border border-red-800/50";
  } else if (isClose) {
    bgClass = "bg-yellow-900/10 border border-yellow-800/30";
  }

  const isExpanded = expanded || hasConf;
  const hlClass = tf === highlightTF ? "border-l-2 border-l-blue-500" : "";

  return (
    <div className={`rounded p-2 ${bgClass} ${hlClass} cursor-pointer`} onClick={() => setExpanded(!expanded)}>
      {/* TF 헤더 */}
      <div className="flex items-center gap-2 text-xs">
        <span className="text-zinc-600 text-[10px] w-3">{isExpanded ? "▾" : "▸"}</span>
        <span className="font-mono font-bold text-zinc-200 w-8">{tf}</span>

        {/* 패밀리 수/점수/트리거 */}
        <span className={`${
          domFamilies >= thresh.min_count
            ? (dominant === "bearish" ? "text-red-400" : "text-emerald-400")
            : "text-zinc-500"
        }`}>
          {domFamilies}/{thresh.min_count}
        </span>
        <span className={`font-mono ${
          domScore >= thresh.min_score
            ? (dominant === "bearish" ? "text-red-400" : "text-emerald-400")
            : "text-zinc-500"
        }`}>
          {domScore.toFixed(1)}/{thresh.min_score}
        </span>
        <span className={`text-[10px] ${data.strong_triggers >= 1 ? "text-yellow-400" : "text-zinc-600"}`}>
          {data.strong_triggers >= 1 ? `★${data.strong_triggers}` : "no★"}
        </span>

        {/* 진행도 바 */}
        <div className="flex-1 h-1.5 rounded-full bg-zinc-800 mx-1">
          <div
            className={`h-1.5 rounded-full transition-all ${
              hasConf ? "bg-yellow-500" :
              isClose ? "bg-yellow-700" :
              dominant === "bullish" ? "bg-emerald-600/50" : "bg-red-600/50"
            }`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <span className={`text-[10px] w-8 text-right ${
          progressPct >= 60
            ? (dominant === "bearish" ? "text-red-400" : "text-emerald-400")
            : "text-zinc-600"
        }`}>{progressPct}%</span>

        {/* Confluence / Entry 뱃지 */}
        {hasConf && data.confluence.map((conf, i) => (
          <span
            key={i}
            className={`rounded px-2 py-0.5 text-[10px] font-bold ${
              conf.direction === "bullish"
                ? "bg-emerald-800 text-emerald-300"
                : "bg-red-800 text-red-300"
            }`}
          >
            ENTRY {conf.direction === "bullish" ? "▲ LONG" : "▼ SHORT"}
          </span>
        ))}

        {isClose && !hasConf && (
          <span className="text-[10px] text-yellow-500">~ NEAR</span>
        )}
      </div>

      {/* 개별 지표 리스트 (펼침 시만) */}
      {isExpanded && <div className="ml-12 mt-1 space-y-0.5">
        {data.individual.map((sig, i) => {
          const d = DIR_ICON[sig.direction] ?? DIR_ICON.neutral;
          const isStrong = sig.strength >= 1.0;
          // 지표 타입 추출: indicator_rsi → rsi, indicator_bb → bb, indicator_ma_align → sma
          const sigType = sig.type?.replace("indicator_", "") ?? "";
          const overlayType = sigType.startsWith("rsi") ? "rsi"
            : sigType.startsWith("macd") ? "macd"
            : sigType.startsWith("bb") ? "bb"
            : sigType.startsWith("ma_align") || sigType.startsWith("ma_cross") ? "sma"
            : sigType.startsWith("ema") ? "ema"
            : sigType.startsWith("fib") ? "fib"
            : sigType.startsWith("elliott") ? "elliott"
            : sigType.startsWith("vp") ? "vp"
            : null;

          const family = sig.family;

          return (
            <div
              key={i}
              className={`flex items-center gap-1.5 text-[11px] ${overlayType ? "cursor-pointer hover:bg-zinc-800/50 rounded px-1 -mx-1" : ""}`}
              onClick={(e) => {
                if (overlayType && onIndicatorClick) {
                  e.stopPropagation();
                  onIndicatorClick(tf, overlayType);
                }
              }}
            >
              <span className={d.color}>{d.sym}</span>
              {family && <span className="text-zinc-600 font-mono text-[9px] w-7 shrink-0">{family}</span>}
              <span className="text-zinc-400 flex-1 truncate">{sig.message}</span>
              {isStrong && <span className="text-yellow-400">★</span>}
              <span className="text-zinc-600 w-8 text-right">
                {(sig.strength * 1.5).toFixed(1)}
              </span>
            </div>
          );
        })}
      </div>

      }

      {/* 부족한 것 (펼침 시만) */}
      {isExpanded && !hasConf && domFamilies >= 1 && (
        <div className="ml-10 mt-1 text-[10px] text-zinc-600">
          {needCount > 0 && <span className="mr-3">+{needCount} 패밀리</span>}
          {needScore > 0 && <span className="mr-3">+{needScore.toFixed(1)} score</span>}
          {needNet > 0 && <span className="mr-3">net +{needNet.toFixed(1)}</span>}
          {needTrigger && <span className="text-yellow-600">★ 트리거 필요</span>}
        </div>
      )}
    </div>
  );
}
