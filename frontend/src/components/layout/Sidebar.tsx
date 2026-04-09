"use client";

const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"];

interface SidebarProps {
  interval: string;
  onIntervalChange: (interval: string) => void;
}

export default function Sidebar({ interval, onIntervalChange }: SidebarProps) {
  return (
    <aside className="w-16 border-r border-zinc-800 bg-zinc-950 flex flex-col items-center py-4 gap-2">
      <span className="text-[10px] text-zinc-500 mb-1">Interval</span>
      {INTERVALS.map((iv) => (
        <button
          key={iv}
          onClick={() => onIntervalChange(iv)}
          className={`w-12 py-1.5 text-xs rounded transition-colors ${
            interval === iv
              ? "bg-blue-600 text-white"
              : "text-zinc-400 hover:bg-zinc-800 hover:text-white"
          }`}
        >
          {iv}
        </button>
      ))}
    </aside>
  );
}
