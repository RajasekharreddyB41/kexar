/**
 * EventLog.
 *
 * Scrollable timeline of runtime events, grouped into step blocks.
 *
 * Each step shows its kind (think/act/respond), an icon, duration, and
 * the events that fired inside it. Currently-running step has a
 * pulsing border-left to draw the eye.
 *
 * Events with step=null get bucketed under the most-recently-started
 * step. Run-lifecycle events (run.start/complete/aborted) render as
 * standalone rows at the head and tail.
 */

"use client";

import { CheckCircle2, Lightbulb, MessageSquareText, Wrench, XCircle } from "lucide-react";
import type { KexarEvent, KexarEventType } from "@/lib/events";

interface EventLogProps {
  events: KexarEvent[];
  isRunning: boolean;
}

interface StepGroup {
  index: number;
  kind: "think" | "act" | "respond" | "unknown";
  events: KexarEvent[];
  durationMs: number | null;
  ended: boolean;
}

function groupByStep(events: KexarEvent[]): {
  preamble: KexarEvent[];
  steps: StepGroup[];
  tail: KexarEvent[];
} {
  const preamble: KexarEvent[] = [];
  const tail: KexarEvent[] = [];
  const stepMap = new Map<number, StepGroup>();
  let currentStepIdx: number | null = null;

  for (const e of events) {
    // Lifecycle events outside step bodies.
    if (e.type === "run.start") {
      preamble.push(e);
      continue;
    }
    if (e.type === "run.complete" || e.type === "run.aborted") {
      tail.push(e);
      continue;
    }

    // Determine which step this event belongs to.
    let stepIdx: number | null = e.step;
    if (stepIdx === null) stepIdx = currentStepIdx;
    if (stepIdx === null) {
      preamble.push(e);
      continue;
    }

    let group = stepMap.get(stepIdx);
    if (!group) {
      group = { index: stepIdx, kind: "unknown", events: [], durationMs: null, ended: false };
      stepMap.set(stepIdx, group);
    }

    if (e.type === "step.start") {
      group.kind = e.data.kind as StepGroup["kind"];
      currentStepIdx = stepIdx;
    } else if (e.type === "step.end") {
      group.kind = e.data.kind as StepGroup["kind"];
      group.durationMs = e.data.duration_ms;
      group.ended = true;
    }

    group.events.push(e);
  }

  return {
    preamble,
    steps: Array.from(stepMap.values()).sort((a, b) => a.index - b.index),
    tail,
  };
}

function kindIcon(kind: StepGroup["kind"]) {
  const cls = "h-3 w-3";
  if (kind === "think") return <Lightbulb className={`${cls} text-sky-400`} />;
  if (kind === "act") return <Wrench className={`${cls} text-emerald-400`} />;
  if (kind === "respond") return <MessageSquareText className={`${cls} text-violet-400`} />;
  return <span className="h-3 w-3 inline-block rounded-full bg-zinc-700" />;
}

function eventColor(type: KexarEventType): string {
  if (type.endsWith(".failure") || type === "run.aborted" || type === "budget.exceeded") {
    return "text-rose-400";
  }
  if (type.endsWith(".success") || type === "run.complete") return "text-emerald-400";
  if (type === "llm.failover" || type.startsWith("tool.circuit") || type === "budget.warn") {
    return "text-amber-400";
  }
  return "text-zinc-500";
}

function shortLabel(e: KexarEvent): string {
  if (e.type === "llm.call.start") return `→ ${shortenModel(e.data.model)}`;
  if (e.type === "llm.call.success") return `✓ ${shortenModel(e.data.model)} (${e.data.latency_ms}ms)`;
  if (e.type === "llm.call.failure") return `✗ ${shortenModel(e.data.model)}: ${e.data.reason}`;
  if (e.type === "llm.failover") return `↪ ${shortenModel(e.data.from_model)} → ${shortenModel(e.data.to_model)}`;
  if (e.type === "tool.call.start") return `→ ${e.data.tool}()`;
  if (e.type === "tool.call.success") return `✓ ${e.data.tool} (${e.data.latency_ms}ms)`;
  if (e.type === "tool.call.failure") return `✗ ${e.data.tool}: ${e.data.reason}`;
  if (e.type === "tool.circuit_open") return `⊘ ${e.data.tool} circuit open`;
  if (e.type === "tool.circuit_close") return `○ ${e.data.tool} circuit closed`;
  if (e.type === "degrade.entered") return `degraded mode: ${e.data.unavailable_tools.join(", ")}`;
  if (e.type === "degrade.exited") return "degraded mode exited";
  if (e.type === "budget.warn") return `budget warn: ${e.data.axis} ${Math.round(e.data.pct)}%`;
  if (e.type === "budget.exceeded") return `budget exceeded: ${e.data.axis}`;
  if (e.type === "step.start") return "started";
  if (e.type === "step.end") return e.data.summary;
  return e.type;
}

function shortenModel(model: string): string {
  let m = model;
  if (m.startsWith("simulated-")) m = m.replace("simulated-", "");
  if (m.startsWith("groq/")) m = m.replace("groq/", "");
  return m.split("/").slice(-1)[0] ?? m;
}

export function EventLog({ events, isRunning }: EventLogProps) {
  const { preamble, steps, tail } = groupByStep(events);
  const lastStepIdx = steps.length > 0 ? steps[steps.length - 1]!.index : null;

  if (events.length === 0) {
    return <div className="text-xs font-mono text-zinc-700">(no events yet)</div>;
  }

  return (
    <div className="space-y-2 font-mono text-xs">
      {preamble.map((e) => (
        <PreambleRow key={e.seq} event={e} />
      ))}
      {steps.map((group) => {
        const isCurrent = isRunning && group.index === lastStepIdx && !group.ended;
        return (
          <div
            key={group.index}
            className={`pl-2.5 border-l-2 ${
              isCurrent ? "border-emerald-500 animate-pulse" : "border-zinc-800"
            }`}
          >
            <div className="flex items-center justify-between gap-2 mb-1">
              <div className="flex items-center gap-1.5">
                {kindIcon(group.kind)}
                <span className="text-zinc-300 text-[11px]">
                  step {group.index} · {group.kind}
                </span>
              </div>
              <span className="text-zinc-600 text-[10px]">
                {group.durationMs !== null ? `${group.durationMs}ms` : isCurrent ? "..." : ""}
              </span>
            </div>
            <div className="space-y-0.5 pl-4 text-[11px] leading-snug">
              {group.events
                .filter((e) => e.type !== "step.start" && e.type !== "step.end")
                .map((e) => (
                  <div key={e.seq} className={eventColor(e.type)}>
                    {shortLabel(e)}
                  </div>
                ))}
            </div>
          </div>
        );
      })}
      {tail.map((e) => (
        <TailRow key={e.seq} event={e} />
      ))}
    </div>
  );
}

function PreambleRow({ event }: { event: KexarEvent }) {
  if (event.type === "run.start") {
    return (
      <div className="text-zinc-500 text-[11px] flex items-center gap-2">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
        run started
      </div>
    );
  }
  return null;
}

function TailRow({ event }: { event: KexarEvent }) {
  if (event.type === "run.complete") {
    return (
      <div className="flex items-center gap-2 text-emerald-400 text-[11px] pt-1 border-t border-zinc-800/60 mt-2">
        <CheckCircle2 className="h-3 w-3" />
        run complete · {event.data.steps_used} steps · {event.data.duration_ms}ms
      </div>
    );
  }
  if (event.type === "run.aborted") {
    return (
      <div className="flex items-center gap-2 text-rose-400 text-[11px] pt-1 border-t border-zinc-800/60 mt-2">
        <XCircle className="h-3 w-3" />
        run aborted: {event.data.reason}
      </div>
    );
  }
  return null;
}
