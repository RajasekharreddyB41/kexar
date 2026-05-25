/**
 * Kexar IR page.
 *
 * Two-pane layout. Chat on the left, control panel on the right. Both
 * read from the same reducer state, fed by the SSE event stream.
 */

"use client";

import { useReducer, useState, type FormEvent } from "react";
import { Activity, AlertCircle, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { ActiveModel, type ModelStatus } from "@/components/active-model";
import { BudgetBar } from "@/components/budget-bar";
import { EventLog } from "@/components/event-log";
import { ToolRow, type ToolStatus } from "@/components/tool-row";
import { startRun, toggleChaos } from "@/lib/api";
import { listFixtures, type Fixture } from "@/lib/fixtures";
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
  modelStatus: ModelStatus;
  failoverChain: string[];
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
  modelStatus: "healthy",
  failoverChain: [],
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
  | { type: "replay_start"; fixtureName: string; message: string }
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
        modelStatus: "calling",
        failoverChain: [],
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
        const isContinuationOfCascade = next.modelStatus === "failing";
        const chain = isContinuationOfCascade
          ? next.failoverChain
          : [e.data.model];
        next = {
          ...next,
          activeModel: e.data.model,
          modelStatus: "calling",
          failoverChain: chain,
        };
      } else if (e.type === "llm.call.success") {
        next = {
          ...next,
          activeModel: e.data.model,
          modelStatus: "healthy",
          tokensUsed: next.tokensUsed + (e.data.tokens_prompt + e.data.tokens_completion),
          costUsd: Number((next.costUsd + e.data.cost_usd).toFixed(6)),
        };
      } else if (e.type === "llm.call.failure") {
        next = { ...next, modelStatus: "failing" };
      } else if (e.type === "llm.failover") {
        const lastInChain = next.failoverChain[next.failoverChain.length - 1];
        const chain =
          lastInChain === e.data.to_model
            ? next.failoverChain
            : [...next.failoverChain, e.data.to_model];
        next = {
          ...next,
          activeModel: e.data.to_model,
          // Keep modelStatus as "failing" so the next llm.call.start
          // can detect that it is mid-cascade and preserve the chain.
          // The next call.start will flip status to "calling".
          failoverChain: chain,
        };
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
          const msgId = `a_${e.seq}`;
          const alreadyAppended = next.messages.some((m) => m.id === msgId);
          if (!alreadyAppended) {
            const assistantMsg: Message = {
              id: msgId,
              role: "assistant",
              content: e.data.summary,
            };
            next = { ...next, messages: [...next.messages, assistantMsg] };
          }
        }
      } else if (e.type === "run.complete") {
        next = {
          ...next,
          status: "complete",
          modelStatus: "healthy",
          stepsUsed: e.data.steps_used,
          tokensUsed: e.data.tokens_used,
          costUsd: Number(e.data.cost_usd.toFixed(6)),
        };
      } else if (e.type === "run.aborted") {
        const apology = e.data.partial_answer ?? "Run aborted.";
        const msgId = `a_${e.seq}`;
        const alreadyAppended = next.messages.some((m) => m.id === msgId);
        next = {
          ...next,
          status: "aborted",
          modelStatus: "exhausted",
          messages: alreadyAppended
            ? next.messages
            : [...next.messages, { id: msgId, role: "assistant", content: apology }],
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

    case "replay_start": {
      // Start a replay run. Same UI as a real run, but we will be
      // synthesizing events from a fixture instead of subscribing to SSE.
      const userMsg: Message = {
        id: `u_${Date.now()}`,
        role: "user",
        content: action.message,
      };
      return {
        ...state,
        status: "running",
        currentRunId: `replay_${action.fixtureName}_${Date.now()}`,
        messages: [...state.messages, userMsg],
        events: [],
        activeModel: null,
        modelStatus: "calling",
        failoverChain: [],
        tokensUsed: 0,
        costUsd: 0,
        stepsUsed: 0,
        errorMessage: null,
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

function formatCost(v: number): string {
  if (v < 0.01) return `$${v.toFixed(4)}`;
  if (v < 1) return `$${v.toFixed(3)}`;
  return `$${v.toFixed(2)}`;
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

  const onReplay = (fixture: Fixture) => {
    if (state.status === "running") return;
    dispatch({
      type: "replay_start",
      fixtureName: fixture.name,
      message: `[replay] ${fixture.label}`,
    });
    // Schedule each event using the original wall-clock deltas, capped
    // so the replay never crawls. Uses a 5x speed-up so the demo feels
    // snappy without losing the cascade structure.
    const events = fixture.events;
    if (events.length === 0) return;
    const t0 = new Date(events[0]!.ts).getTime();
    for (const event of events) {
      const dt = new Date(event.ts).getTime() - t0;
      const delay = Math.min(dt / 5, 3000);
      setTimeout(() => {
        dispatch({ type: "event", event });
      }, delay);
    }
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
            <ActiveModel
              model={state.activeModel}
              status={state.modelStatus}
              failoverChain={state.failoverChain}
            />
          </section>

          <Separator className="bg-zinc-800" />

          <section>
            <div className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Budget</div>
            <div className="space-y-2.5 text-xs">
              <BudgetBar label="Steps" used={state.stepsUsed} max={state.budgetMax.steps} format={(v) => String(v)} />
              <BudgetBar label="Tokens" used={state.tokensUsed} max={state.budgetMax.tokens} format={(v) => v.toLocaleString()} />
              <BudgetBar label="Cost" used={state.costUsd} max={state.budgetMax.cost} format={formatCost} />
            </div>
          </section>

          <Separator className="bg-zinc-800" />

          <section>
            <div className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Tools</div>
            <div className="space-y-0">
              {KNOWN_TOOLS.map((tool) => {
                const t = state.tools[tool]!;
                const status: ToolStatus = t.killed || t.circuitOpen ? "down" : "healthy";
                return (
                  <ToolRow
                    key={tool}
                    name={tool}
                    status={status}
                    lastLatencyMs={t.lastLatencyMs}
                    killed={t.killed}
                    chaosVisible={chaosOpen}
                    onChaosToggle={(killed) => onChaosToggle(tool, killed)}
                  />
                );
              })}
            </div>
            {chaosOpen && (
              <div className="text-xs text-zinc-600 mt-2 leading-relaxed">
                Flip a switch to kill that tool. The next run reroutes around it.
              </div>
            )}
            {chaosOpen && (
              <div className="mt-3 space-y-1">
                <div className="text-[10px] uppercase tracking-widest text-zinc-600">
                  Replay fixture
                </div>
                {listFixtures().map((fx) => (
                  <button
                    key={fx.name}
                    type="button"
                    onClick={() => onReplay(fx)}
                    disabled={state.status === "running"}
                    className="w-full text-left text-[11px] px-2 py-1.5 rounded bg-zinc-800/50 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    <div className="font-mono">{fx.label}</div>
                    <div className="text-zinc-500 text-[10px] leading-snug">{fx.description}</div>
                  </button>
                ))}
              </div>
            )}
          </section>

          <Separator className="bg-zinc-800" />

          <section className="flex-1 min-h-0 flex flex-col">
            <div className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Event log</div>
            <ScrollArea className="flex-1 max-h-80 -mr-2 pr-2">
              <EventLog events={state.events} isRunning={state.status === "running"} />
            </ScrollArea>
          </section>
        </aside>
      </div>
    </main>
  );
}

