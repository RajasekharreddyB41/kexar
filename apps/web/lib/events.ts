/**
 * Event types for the SSE stream.
 *
 * Mirrors the Python schema in apps/api/kexar/runtime/events.py.
 * Discriminated union on `type`. Each variant has its own data shape.
 *
 * When the Python side adds a new event type, add the matching TS type
 * here and extend the KexarEvent union. The SSE client validates against
 * this at parse time so a missing variant fails loudly.
 */

export interface EventEnvelope {
  seq: number;
  run_id: string;
  ts: string; // ISO timestamp
  step: number | null;
}

// ---------------------------------------------------------------------------
// Step lifecycle
// ---------------------------------------------------------------------------

export interface StepStart extends EventEnvelope {
  type: "step.start";
  data: { kind: "think" | "act" | "respond" };
}

export interface StepEnd extends EventEnvelope {
  type: "step.end";
  data: {
    kind: "think" | "act" | "respond";
    duration_ms: number;
    succeeded: boolean;
    summary: string;
  };
}

// ---------------------------------------------------------------------------
// LLM calls
// ---------------------------------------------------------------------------

export interface LlmCallStart extends EventEnvelope {
  type: "llm.call.start";
  data: { model: string; attempt: number };
}

export interface LlmCallSuccess extends EventEnvelope {
  type: "llm.call.success";
  data: {
    model: string;
    latency_ms: number;
    tokens_prompt: number;
    tokens_completion: number;
    cost_usd: number;
  };
}

export interface LlmCallFailure extends EventEnvelope {
  type: "llm.call.failure";
  data: {
    model: string;
    attempt: number;
    reason: string;
    retryable: boolean;
  };
}

export interface LlmFailover extends EventEnvelope {
  type: "llm.failover";
  data: {
    from_model: string;
    to_model: string;
    reason: string;
    latency_ms_added: number;
  };
}

// ---------------------------------------------------------------------------
// Tool calls
// ---------------------------------------------------------------------------

export interface ToolCallStart extends EventEnvelope {
  type: "tool.call.start";
  data: { tool: string; args: Record<string, unknown> };
}

export interface ToolCallSuccess extends EventEnvelope {
  type: "tool.call.success";
  data: { tool: string; latency_ms: number; result_summary: string };
}

export interface ToolCallFailure extends EventEnvelope {
  type: "tool.call.failure";
  data: {
    tool: string;
    attempt: number;
    reason: string;
    retryable: boolean;
  };
}

export interface ToolCircuitOpen extends EventEnvelope {
  type: "tool.circuit_open";
  data: {
    tool: string;
    cooldown_seconds: number;
    recent_failures: number;
  };
}

export interface ToolCircuitClose extends EventEnvelope {
  type: "tool.circuit_close";
  data: { tool: string };
}

// ---------------------------------------------------------------------------
// Degraded mode
// ---------------------------------------------------------------------------

export interface DegradeEntered extends EventEnvelope {
  type: "degrade.entered";
  data: { unavailable_tools: string[]; reason: string };
}

export interface DegradeExited extends EventEnvelope {
  type: "degrade.exited";
  data: { restored_tools: string[] };
}

// ---------------------------------------------------------------------------
// Budget
// ---------------------------------------------------------------------------

export interface BudgetWarn extends EventEnvelope {
  type: "budget.warn";
  data: {
    axis: "steps" | "tokens" | "cost";
    used: number;
    max: number;
    pct: number;
  };
}

export interface BudgetExceeded extends EventEnvelope {
  type: "budget.exceeded";
  data: { axis: "steps" | "tokens" | "cost"; used: number; max: number };
}

// ---------------------------------------------------------------------------
// Run lifecycle
// ---------------------------------------------------------------------------

export interface RunStart extends EventEnvelope {
  type: "run.start";
  data: { incident_id: string | null; user_message: string };
}

export interface RunComplete extends EventEnvelope {
  type: "run.complete";
  data: {
    steps_used: number;
    tokens_used: number;
    cost_usd: number;
    duration_ms: number;
  };
}

export interface RunAborted extends EventEnvelope {
  type: "run.aborted";
  data: { reason: string; partial_answer?: string };
}

// ---------------------------------------------------------------------------
// Tagged union
// ---------------------------------------------------------------------------

export type KexarEvent =
  | StepStart
  | StepEnd
  | LlmCallStart
  | LlmCallSuccess
  | LlmCallFailure
  | LlmFailover
  | ToolCallStart
  | ToolCallSuccess
  | ToolCallFailure
  | ToolCircuitOpen
  | ToolCircuitClose
  | DegradeEntered
  | DegradeExited
  | BudgetWarn
  | BudgetExceeded
  | RunStart
  | RunComplete
  | RunAborted;

export type KexarEventType = KexarEvent["type"];

// Lifecycle types that close the SSE stream.
export const TERMINAL_EVENT_TYPES: ReadonlySet<KexarEventType> = new Set([
  "run.complete",
  "run.aborted",
] as const);

export function isTerminal(event: KexarEvent): boolean {
  return TERMINAL_EVENT_TYPES.has(event.type);
}
