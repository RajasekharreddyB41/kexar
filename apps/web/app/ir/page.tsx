/**
 * Kexar IR page.
 *
 * Two-pane layout. Chat on the left, control panel on the right. Both
 * read from the same reducer state, fed by the SSE event stream.
 */

"use client";

import { useReducer, useState, type FormEvent } from "react";
import { Activity, AlertCircle, Send } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { startRun, toggleChaos } from "@/lib/api";
import type { KexarEvent } from "@/lib/events";
import { useEventStream } from "@/lib/sse";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

type RunStatus = "idle" | "running" | "complete" | "aborted";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

interface ToolState {
  killed: boolean;
  lastLatencyMs: number | null;
  circuitOpen: boolean;
}

interface PageState {
  status: RunStatus;
  currentRunId: string | null;
  messages: Message[];
  events: KexarEvent[];
  activeModel: string | null;
  tokensUsed: number;
  costUsd: number;
  stepsUsed: number;
  budgetMax: { tokens: number; cost: number; steps: number };
  tools: Record<string, ToolState>;
  errorMessage: string | null;
}

const KNOWN_TOOLS = ["query_logs", "fetch_metrics", "lookup_runbook"] as const;

const INITIAL_STATE: PageState = {
  status: "idle",
  currentRunId: null,
  messages: [],
  events: [],
  activeModel: null,
  tokensUsed: 0,
  costUsd: 0,
  stepsUsed: 0,
  budgetMax: { tokens: 20000, cost: 0.5, steps: 10 },
  tools: Object.fromEntries(
    KNOWN_TOOLS.map((t) => [t, { killed: false, lastLatencyMs: null, circuitOpen: false }])
  ),
  errorMessage: null,
};

type Action =
  | { type: "user_submit"; message: string; runId: string }
  | { type: "event"; event: KexarEvent }
  | { type: "chaos_toggled"; tool: string; killed: boolean }
  | { type: "error"; message: string }
  | { type: "reset" };

function reducer(state: PageState, action: Action): PageState {
  switch (action.type) {
    case "user_submit": {
      const userMsg: Message = {
        id: `u_${Date.now()}`,
        role: "user",
        content: action.message,
      };
      return {
        ...state,
        status: "running",
        currentRunId: action.runId,
        messages: [...state.messages, userMsg],
        events: [],
        activeModel: null,
        tokensUsed: 0,
        costUsd: 0,
        stepsUsed: 0,
        errorMessage: null,
      };
    }

    case "event": {
      const e = action.event;
      const events = [...state.events, e];
      let next: PageState = { ...state, events };

      if (e.type === "llm.call.start") {
        next = { ...next, activeModel: e.data.model };
      } else if (e.type === "llm.call.success") {
        next = {
          ...next,
          activeModel: e.data.model,
          tokensUsed: next.tokensUsed + (e.data.tokens_prompt + e.data.tokens_completion),
          costUsd: Number((next.costUsd + e.data.cost_usd).toFixed(6)),
        };
      } else if (e.type === "llm.failover") {
        next = { ...next, activeModel: e.data.to_model };
      } else if (e.type === "tool.call.success") {
        next = {
          ...next,
          tools: {
            ...next.tools,
            [e.data.tool]: {
              ...(next.tools[e.data.tool] ?? { killed: false, lastLatencyMs: null, circuitOpen: false }),
              lastLatencyMs: e.data.latency_ms,
              circuitOpen: false,
            },
          },
        };
      } else if (e.type === "tool.circuit_open") {
        next = {
          ...next,
          tools: {
            ...next.tools,
            [e.data.tool]: {
              ...(next.tools[e.data.tool] ?? { killed: false, lastLatencyMs: null, circuitOpen: false }),
              circuitOpen: true,
            },
          },
        };
      } else if (e.type === "step.end") {
        next = { ...next, stepsUsed: next.stepsUsed + 1 };

        // The respond step carries the final answer in its summary.
        // The orchestrator truncates summary to ~120 chars; for the
        // full text we would need a dedicated event, which we add
        // server-side later. For Day 5 the summary is good enough.
        if (e.data.kind === "respond" && e.data.summary) {
          const assistantMsg: Message = {
            id: `a_${e.seq}`,
            role: "assistant",
            content: e.data.summary,
          };
          next = { ...next, messages: [...next.messages, assistantMsg] };
        }
      } else if (e.type === "run.complete") {
        next = {
          ...next,
          status: "complete",
          stepsUsed: e.data.steps_used,
          tokensUsed: e.data.tokens_used,
          costUsd: Number(e.data.cost_usd.toFixed(6)),
        };
      } else if (e.type === "run.aborted") {
        const apology = e.data.partial_answer ?? "Run aborted.";
        next = {
          ...next,
          status: "aborted",
          messages: [
            ...next.messages,
            { id: `a_${e.seq}`, role: "assistant", content: apology },
          ],
        };
      }

      return next;
    }

    case "chaos_toggled": {
      const existing = state.tools[action.tool] ?? {
        killed: false,
        lastLatencyMs: null,
        circuitOpen: false,
      };
      return {
        ...state,
        tools: {
          ...state.tools,
          [action.tool]: { ...existing, killed: action.killed },
        },
      };
    }

    case "error":
      return { ...state, status: "idle", errorMessage: action.message };

    case "reset":
      return INITIAL_STATE;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(used: number, max: number): number {
  if (max <= 0) return 0;
  return Math.min(100, (used / max) * 100);
}

function shortModel(model: string | null): string {
  if (!model) return "—";
  if (model.startsWith("simulated-")) return model.replace("simulated-", "[sim] ");
  if (model.startsWith("groq/")) return model.replace("groq/", "");
  if (model.includes("/")) return model.split("/").slice(-1)[0]!;
  return model;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function IrPage() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const [input, setInput] = useState("");
  const [chaosOpen, setChaosOpen] = useState(false);

  useEventStream(state.currentRunId, (event) => {
    dispatch({ type: "event", event });
  });

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const message = input.trim();
    if (!message || state.status === "running") return;

    setInput("");
    const result = await startRun(message);
    if (!result.ok) {
      dispatch({ type: "error", message: result.error });
      return;
    }
    dispatch({ type: "user_submit", message, runId: result.data.run_id });
  };

  const onChaosToggle = async (tool: string, killed: boolean) => {
    const result = await toggleChaos(tool, killed);
    if (!result.ok) {
      dispatch({ type: "error", message: result.error });
      return;
    }
    dispatch({ type: "chaos_toggled", tool, killed });
  };

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="border-b border-zinc-800 px-6 py-3 flex items-center justify-between bg-zinc-950">
        <div className="flex items-center gap-3">
          <span className="text-xs uppercase tracking-widest text-zinc-500">Kexar</span>
          <Separator orientation="vertical" className="h-4 bg-zinc-800" />
          <span className="text-sm text-zinc-300">IR copilot</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          <span>demo mode</span>
          <Switch checked={chaosOpen} onCheckedChange={setChaosOpen} />
        </div>
      </header>

      <div className="grid grid-cols-[1fr_380px] gap-4 p-4 h-[calc(100vh-49px)]">
        {/* Chat pane */}
        <section className="bg-zinc-900 border border-zinc-800 rounded-xl flex flex-col overflow-hidden">
          <ScrollArea className="flex-1 px-6 py-4">
            {state.messages.length === 0 && state.status === "idle" && (
              <div className="text-zinc-500 text-sm leading-relaxed">
                Pre-seeded incident:{" "}
                <span className="text-zinc-300">Checkout API p99 latency spike at 02:14 UTC.</span>
                <br />
                Ask anything to start the agent.
              </div>
            )}
            <div className="space-y-3">
              {state.messages.map((m) => (
                <div
                  key={m.id}
                  className={
                    m.role === "user"
                      ? "ml-auto max-w-prose bg-zinc-100 text-zinc-900 px-4 py-2.5 rounded-2xl rounded-tr-sm"
                      : "mr-auto max-w-prose bg-zinc-800 text-zinc-100 px-4 py-2.5 rounded-2xl rounded-tl-sm border border-zinc-700"
                  }
                >
                  <div className="text-sm whitespace-pre-wrap leading-relaxed">{m.content}</div>
                </div>
              ))}
              {state.status === "running" && (
                <div className="mr-auto text-zinc-500 text-sm flex items-center gap-2">
                  <Activity className="h-3 w-3 animate-pulse" />
                  agent working...
                </div>
              )}
            </div>
          </ScrollArea>
          {state.errorMessage && (
            <div className="px-6 py-2 text-xs text-red-400 border-t border-zinc-800 flex items-center gap-2">
              <AlertCircle className="h-3 w-3" />
              {state.errorMessage}
            </div>
          )}
          <form onSubmit={onSubmit} className="border-t border-zinc-800 p-3 flex items-center gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Why is the checkout API slow?"
              disabled={state.status === "running"}
              className="bg-zinc-950 border-zinc-800 text-zinc-100 placeholder:text-zinc-600"
            />
            <Button type="submit" disabled={state.status === "running" || !input.trim()}>
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </section>

        {/* Control panel */}
        <aside className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col gap-5 overflow-y-auto">
          <section>
            <div className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Active model</div>
            <div className="font-mono text-sm text-zinc-100">{shortModel(state.activeModel)}</div>
          </section>

          <Separator className="bg-zinc-800" />

          <section>
            <div className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Budget</div>
            <div className="space-y-2.5 text-xs">
              <BudgetBar label="Steps" used={state.stepsUsed} max={state.budgetMax.steps} format={(v) => String(v)} />
              <BudgetBar label="Tokens" used={state.tokensUsed} max={state.budgetMax.tokens} format={(v) => v.toLocaleString()} />
              <BudgetBar label="Cost" used={state.costUsd} max={state.budgetMax.cost} format={(v) => `$${v.toFixed(4)}`} />
            </div>
          </section>

          <Separator className="bg-zinc-800" />

          <section>
            <div className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Tools</div>
            <div className="space-y-2">
              {KNOWN_TOOLS.map((tool) => {
                const t = state.tools[tool]!;
                const status = t.killed
                  ? "killed"
                  : t.circuitOpen
                    ? "circuit open"
                    : t.lastLatencyMs !== null
                      ? `${t.lastLatencyMs}ms`
                      : "—";
                return (
                  <div key={tool} className="flex items-center justify-between text-xs">
                    <div className="font-mono text-zinc-400">{tool}</div>
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={t.killed || t.circuitOpen ? "destructive" : "secondary"}
                        className="font-mono"
                      >
                        {status}
                      </Badge>
                      {chaosOpen && (
                        <Switch
                          checked={!t.killed}
                          onCheckedChange={(checked) => onChaosToggle(tool, !checked)}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            {chaosOpen && (
              <div className="text-xs text-zinc-600 mt-2 leading-relaxed">
                Flip a switch to kill that tool. The next run reroutes around it.
              </div>
            )}
          </section>

          <Separator className="bg-zinc-800" />

          <section className="flex-1 min-h-0 flex flex-col">
            <div className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Event log</div>
            <ScrollArea className="flex-1 max-h-72 -mr-2 pr-2">
              <div className="space-y-1 text-xs font-mono text-zinc-500">
                {state.events.length === 0 && <div className="text-zinc-700">(no events yet)</div>}
                {state.events.map((e) => (
                  <div key={e.seq} className="leading-tight">
                    <span className="text-zinc-700">{String(e.seq).padStart(3, "0")}</span>{" "}
                    <span className={eventColor(e.type)}>{e.type}</span>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </section>
        </aside>
      </div>
    </main>
  );
}

function BudgetBar({
  label,
  used,
  max,
  format,
}: {
  label: string;
  used: number;
  max: number;
  format: (v: number) => string;
}) {
  const p = pct(used, max);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-zinc-400">{label}</span>
        <span className="text-zinc-500 font-mono">
          {format(used)} / {format(max)}
        </span>
      </div>
      <div className="h-1 bg-zinc-800 rounded overflow-hidden">
        <div
          className={p >= 80 ? "h-full bg-amber-400" : "h-full bg-emerald-500"}
          style={{ width: `${p}%` }}
        />
      </div>
    </div>
  );
}

function eventColor(type: string): string {
  if (type.includes("failure") || type.includes("aborted") || type.includes("exceeded")) return "text-red-400";
  if (type.includes("success") || type.includes("complete")) return "text-emerald-400";
  if (type.includes("failover")) return "text-amber-400";
  if (type.includes("warn") || type.includes("circuit")) return "text-amber-400";
  return "text-zinc-400";
}
