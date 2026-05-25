/**
 * ToolRow.
 *
 * One row per tool in the control panel. Three states:
 *   * healthy   - circuit closed, last call succeeded.
 *                 emerald dot, normal text, latency in zinc grey.
 *   * degraded  - circuit half-open or recent failure within 5s.
 *                 amber dot, normal text, latency in amber.
 *                 (Reserved; backend does not emit half-open events
 *                 today. Component supports it for future use.)
 *   * down      - killed via chaos OR circuit open after repeated
 *                 failures. Rose dot, text dimmed, latency shows
 *                 --ms in red.
 *
 * Optional chaos switch is shown when demo mode is on. The switch is
 * inverse logic: ON means the tool is healthy, OFF means kill it.
 * Matches how users think about "is this thing working".
 */

"use client";

import { Switch } from "@/components/ui/switch";

export type ToolStatus = "healthy" | "degraded" | "down";

interface ToolRowProps {
  name: string;
  status: ToolStatus;
  lastLatencyMs: number | null;
  chaosVisible: boolean;
  onChaosToggle?: (killed: boolean) => void;
  killed: boolean;
}

const STATUS_COLORS: Record<ToolStatus, { dot: string; latency: string; text: string }> = {
  healthy: {
    dot: "bg-emerald-500",
    latency: "text-zinc-400 bg-zinc-800",
    text: "text-zinc-300",
  },
  degraded: {
    dot: "bg-amber-400",
    latency: "text-amber-300 bg-amber-950",
    text: "text-zinc-300",
  },
  down: {
    dot: "bg-rose-500",
    latency: "text-rose-300 bg-rose-950",
    text: "text-zinc-500",
  },
};

export function ToolRow({
  name,
  status,
  lastLatencyMs,
  chaosVisible,
  onChaosToggle,
  killed,
}: ToolRowProps) {
  const colors = STATUS_COLORS[status];
  const latencyLabel = status === "down" || lastLatencyMs === null ? "--ms" : `${lastLatencyMs}ms`;

  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="relative inline-flex h-2 w-2 shrink-0">
          {status === "down" && (
            <span className="absolute inline-flex h-full w-full rounded-full bg-rose-500 opacity-60 animate-ping" />
          )}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${colors.dot}`} />
        </span>
        <span className={`font-mono text-xs truncate ${colors.text}`}>{name}</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${colors.latency}`}>
          {latencyLabel}
        </span>
        {chaosVisible && onChaosToggle && (
          <Switch
            checked={!killed}
            onCheckedChange={(checked) => onChaosToggle(!checked)}
            className="scale-75"
          />
        )}
      </div>
    </div>
  );
}
