"use client";

interface EventLogProps {
  events: { message: string; type: string; time: number }[];
}

export default function EventLog({ events }: EventLogProps) {
  if (events.length === 0) return null;

  const getColor = (type: string) => {
    if (type === "trade_opened") return "text-blue-400";
    if (type === "tranche_filled") return "text-yellow-400";
    if (type === "trade_closed") return "text-purple-400";
    return "text-zinc-400";
  };

  const getLabel = (type: string) => {
    if (type === "trade_opened") return "OPEN";
    if (type === "tranche_filled") return "FILL";
    if (type === "trade_closed") return "CLOSE";
    return "INFO";
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900">
      <div className="border-b border-zinc-800 px-4 py-3">
        <span className="text-sm text-zinc-400">Event Log</span>
      </div>
      <div className="max-h-48 overflow-y-auto p-3 space-y-1.5">
        {events.map((ev, i) => (
          <div key={i} className="flex items-start gap-2 text-xs">
            <span
              className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold bg-zinc-800 ${getColor(ev.type)}`}
            >
              {getLabel(ev.type)}
            </span>
            <span className="text-zinc-300">{ev.message}</span>
            <span className="ml-auto shrink-0 text-zinc-600">
              {new Date(ev.time).toLocaleTimeString("ko-KR")}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
