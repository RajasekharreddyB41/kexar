/**
 * BudgetBar.
 *
 * One row of the budget meter. Used for Steps, Tokens, Cost.
 * Threshold-driven color with animated fill width.
 *
 *   < 50%   emerald (calm)
 *   50-80%  amber (notice)
 *   80-95%  orange (urgent)
 *   >= 95%  rose, pulsing (over)
 */

"use client";

interface BudgetBarProps {
  label: string;
  used: number;
  max: number;
  format: (v: number) => string;
}

function pct(used: number, max: number): number {
  if (max <= 0) return 0;
  return Math.min(100, (used / max) * 100);
}

function barColor(p: number): string {
  if (p >= 95) return "bg-rose-500 animate-pulse";
  if (p >= 80) return "bg-orange-400";
  if (p >= 50) return "bg-amber-400";
  return "bg-emerald-500";
}

function labelColor(p: number): string {
  if (p >= 95) return "text-rose-300";
  if (p >= 80) return "text-orange-300";
  if (p >= 50) return "text-amber-300";
  return "text-zinc-500";
}

export function BudgetBar({ label, used, max, format }: BudgetBarProps) {
  const p = pct(used, max);
  const showPct = p >= 50;
  return (
    <div>
      <div className="flex items-center justify-between mb-1 text-xs">
        <div className="flex items-center gap-1.5">
          <span className="text-zinc-400">{label}</span>
          {showPct && (
            <span className={`text-[10px] font-mono ${labelColor(p)}`}>
              {Math.round(p)}%
            </span>
          )}
        </div>
        <span className="text-zinc-500 font-mono">
          {format(used)} / {format(max)}
        </span>
      </div>
      <div className="h-1 bg-zinc-800 rounded overflow-hidden">
        <div
          className={`h-full rounded transition-all duration-500 ease-out ${barColor(p)}`}
          style={{ width: `${p}%` }}
        />
      </div>
    </div>
  );
}
