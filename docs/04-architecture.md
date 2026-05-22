cat > ~/kexar/docs/04-architecture.md << 'ARCHEOF'

# Architecture

**For:** Kexar
**Date:** 2026-05-20
**Status:** Locked, drives the build plan
**Source of truth for:** Tech choices, system boundaries, data flow, failure modes

---

## Guiding principles

Five rules that resolve every architecture argument that comes up later.

1. The orchestration layer is the product. It is not a framework we hide behind. We write it. It is small (200 to 400 lines of Python).
2. Resilience is a first-class concept, not a try-except block. Failures are typed events, not exceptions. The runtime emits them, the UI renders them.
3. The control panel reads from the same event stream the runtime writes to. No separate API for the UI. One log, two consumers (the agent and the user).
4. Everything user-facing has a degraded mode. Every LLM call has a fallback chain. Every tool call has a "I cannot do this, here is what I can still do" path. Nothing throws unhandled.
5. The TrueFoundry Gateway is the only path to any LLM. No direct OpenAI calls, no direct Anthropic calls. The gateway is non-negotiable, both because the challenge requires it and because routing through one place is the only way the demo makes sense.

---

## System diagram

Browser runs Next.js. It has two panes side by side. Chat on the left, control panel on the right. Both read the same Server-Sent Events stream from the backend.

Backend is FastAPI. Inside it lives the Kexar Runtime: an orchestrator that loops, a step executor that calls LLMs and tools, an event bus that records everything, a budget tracker that enforces step and cost caps, and a circuit breaker for tools and providers.

Runtime talks to three external things: TrueFoundry Gateway for LLMs (Claude, GPT-4o, Gemini, Groq), a local MCP server in the same container that exposes three tools (query_logs, fetch_metrics, lookup_runbook), and Supabase Postgres for storing seeded incident data and the event log.

Chaos controls trigger killswitches in two places. They fake a provider as down at the gateway layer (in our code, not in TrueFoundry UI), and they make MCP tools return 503 or timeout.

---

## Stack decisions

### Frontend: Next.js 15 + TypeScript + Tailwind + shadcn/ui

App Router. Server components for the shell, client components for chat and control panel. Streaming via Server-Sent Events not websockets, since the flow is one-directional (server pushes events, user posts messages via HTTP). shadcn/ui because it looks production-grade out of the box. Hosted on Vercel free tier.

### Backend: FastAPI + Python 3.14

Kexar Runtime is Python because the LLM ecosystem is Python-first. FastAPI for HTTP because it has native SSE support and async without ceremony. Async throughout: orchestration loop, tool calls, LLM calls. This matters because we use timeouts everywhere and async is how Python does timeouts well. Hosted on Render free web service.

### LLM access: TrueFoundry AI Gateway

Single base URL, single API key in our backend. Models configured in TrueFoundry: Claude Sonnet 4.5, GPT-4o, Gemini 2.5 Flash, Groq Llama 3.3 70B. Failover happens both at the gateway level and in our application code. App-level failover exists so we can emit "switched to backup model" events to the UI; the gateway alone cannot do that because it does not know about our event bus.

### MCP server: local, Python, three tools

One server we write, runs in the same container as the backend. Tools: query_logs, fetch_metrics, lookup_runbook. Pre-seeded data in Postgres, tools query it. Each tool has a kill switch we toggle via chaos controls. We do not use a community MCP server because we need precise failure control that real servers do not give us.

### Database: Supabase Postgres

Free tier 500MB, instant Postgres, web dashboard for inspecting data. Stores seeded incident data, MCP tool data, and the event log for replay. No auth tables, no user data.

### Event bus: in-process pub/sub + SSE

Runtime emits typed events to an in-process bus. SSE endpoint subscribes to the bus and streams to the browser. No Redis, no Kafka. In-memory is enough for one backend instance.

### Deployment

Frontend on Vercel auto-deploy on git push. Backend on Render auto-deploy on git push. Postgres on Supabase. Optional custom domain $12 if we buy one, otherwise free Vercel subdomain.

---

## The runtime in detail

This is the 200 to 400 lines of Python that everything else exists to support.

### Concepts

Run: one end-to-end execution of the agent for one user message. Has a unique ID, a budget, a step cap, start and end times.

Step: one iteration of the orchestration loop. Does one of: think (LLM call), act (tool call), respond (final answer). Each step is logged.

Event: a typed record emitted during a step. Events are the only thing the UI reads. Event types include step.start, step.end, llm.call.start, llm.call.success, llm.call.failure, llm.failover, tool.call.start, tool.call.success, tool.call.failure, tool.circuit_open, tool.circuit_close, degrade.entered, degrade.exited, budget.warn, budget.exceeded, run.complete, run.aborted.

Policy: configuration controlling retries, fallbacks, timeouts, circuit thresholds. Lives in code, not YAML.

### Event schema

Every event follows this shape. Frontend types match this exactly.

```json
{
  "seq": 42,
  "run_id": "run_01HW3...",
  "ts": "2026-05-21T14:23:11.482Z",
  "type": "llm.failover",
  "step": 3,
  "data": {
    "from": "claude-sonnet-4-5",
    "to": "gpt-4o",
    "reason": "timeout_after_2_retries",
    "latency_ms_added": 340
  }
}
```

The seq field is monotonic per run. Frontend renders in seq order, not arrival order. The data field is a discriminated union on type.

### Latency budgets

User-visible performance targets the runtime must hit on the happy path.

First token in chat: under 1.2 seconds from user submit.
First control-panel event: under 800ms from submit.
Full happy-path response: under 12 seconds.
SSE reconnect: under 2 seconds, transparent to user.
Failover overhead: under 500ms added latency per fallback.

### LLM failover policy

Cascade order: Claude Sonnet 4.5 -> GPT-4o -> Gemini 2.5 Flash -> Groq Llama 3.3 70B.

For each provider: 30s timeout, 2 retries with exponential backoff and jitter (1s, 3s), then move to next. After all four exhausted, emit run.aborted with hardcoded apology.

Order rationale: Claude for reasoning quality, GPT-4o as close substitute, Gemini Flash for speed and cost, Groq Llama as the always-works backstop.

### Tool resilience policy

For each tool call: 8s timeout, 1 retry with 500ms delay, circuit breaker on 3 failures in 60s opens for 30s. When circuit is open, emit tool.circuit_open and return ToolUnavailable without calling the tool. Agent receives ToolUnavailable and is prompted to reason without it.

### Budget and step caps

Per run: 10 steps max, 20000 tokens max across all LLM calls, $0.50 max cost. Tracked after each LLM call. On hit: emit budget.exceeded, stop loop, return whatever partial answer the agent has so far, framed honestly ("I hit my budget. Based on what I found so far...").

Numbers chosen because the seeded incident normally completes in 4 to 6 steps and $0.10 to $0.20. Caps are 2-3x normal for chaos headroom.

### Degraded mode (the differentiator)

When a tool returns ToolUnavailable, the runtime does not bubble it up. It modifies the next LLM call's system prompt:

This prompt augmentation produces the "I cannot reach metrics but here is what I can still tell you" response. 10 lines of code, biggest product moment in the demo.

---

## Data model

Three Postgres tables.

incidents (seeded, read-only during demo): id, title, description, severity, started_at, service.

incident_signals (seeded, queried by MCP tools): id, incident_id, type (log | metric | runbook), payload (jsonb), timestamp.

runs (written by the runtime): id, incident_id, started_at, ended_at, status, event_log (jsonb array).

Why a JSONB array on runs is enough: every user-visible event is appended in order, the array preserves that order, and replay is just stream the list with delays. No separate events table needed at our scale.

---

## API surface

Four endpoints, small on purpose.

POST /api/runs starts a new run. Body: incident_id and user_message. Returns run_id.

GET /api/runs/{run_id}/events is the SSE stream of events for this run.

POST /api/runs/{run_id}/replay re-emits the stored event log for a completed run.

POST /api/demo/chaos toggles a chaos condition. Body: target and enabled. Demo-only and rate-limited via token bucket.

The /api/demo/chaos endpoint is the only non-product endpoint. The path name makes that explicit.

---

## Failure modes

LLM rate-limit (gateway returns 429): failover to next provider, emit llm.failover, user sees "switched to backup model" toast, agent continues.

All LLMs fail in cascade: all four providers exhausted, emit run.aborted, return apology. User sees "I cannot reach any AI model right now. Try again in a minute."

Tool times out (exceeds 8s): retry once, then open circuit. User sees "metrics tool unavailable, reasoning without it."

Tool returns malformed data: treat as failure, same path as timeout.

Circuit open on a tool: skip call, return ToolUnavailable, same UI message.

Budget exceeded mid-run: stop loop, return partial answer. User sees "I hit my budget. Here is what I found so far."

Step cap hit: same as budget exceeded.

Postgres unreachable: backend returns 500. UI shows "Cannot start a new run, retrying" with retry button.

Backend down entirely: frontend cannot reach API. UI shows "Kexar backend is unreachable."

Every row gets exercised at least once during testing.

---

## Security and secrets

API keys in environment variables, never in code, never in client. .env.example committed, .env gitignored.

Chaos endpoint is demo-only and rate-limited via token bucket. No auth, the demo URL is shared with judges who need to use chaos controls.

CORS configured to allow only the Vercel frontend domain.

TrueFoundry budget cap set at gateway level: $20 hard ceiling for the whole hackathon period.

---

## Observability

Backend logs to stdout, captured by Render.

Sentry on both frontend and backend, free tier.

TrueFoundry dashboard for LLM-level observability, briefly shown on camera in the demo.

The control panel itself is observability for the runtime, by design. We are not building a Grafana stack. The control panel is the dashboard.

---

## What we are not building

Multi-tenancy. Real auth (Supabase auth tables exist but unused). Tests above smoke level for the demo path. CI/CD beyond Vercel and Render auto-deploy on git push. Mobile responsive beyond "does not look broken on a laptop in the recording." Internationalization. Rate limiting on the public API except chaos endpoint. A published SDK or package. The runtime is a Python module in the repo.

If we have extra time after the demo is locked, we add tests for the runtime, not features.

---

## Folder structure

Nothing in this tree is optional. Nothing missing from it gets built.

---

## Tradeoffs

Monorepo over two repos: simpler for solo build, loses some deploy independence we do not need.

In-process event bus over Redis: simpler, cannot scale past one backend instance, fine because we have one instance.

App-level plus gateway-level failover: more code, more correctness, worth it because UI events depend on app-level visibility.

No agent framework: more code to write, but the orchestration layer is what we are showcasing.

No tests beyond smoke: risk, mitigated by manually testing the demo flow daily.

Custom MCP server: real ones do not fail on command, loses some realism, demo needs precise failures.

---

## Risks

TrueFoundry account limits: confirmed Day 1 to be 50k requests/month on Developer Plan. Free.

SSE behind some CDNs: Vercel handles it. If we ever put backend behind Cloudflare, SSE needs Cache-Control: no-cache.

Cold starts on Render free tier: web service sleeps. Ping backend before demo. Easy.

MCP server failure during testing: we are the MCP server. Bugs there break the whole demo. Tests on MCP code mandatory.

Prompt engineering for degraded mode: hardest part technically. Agent must handle tool-unavailable prompts without hallucinating. Time-box to 1 day. If not good enough by Day 7, ship deterministic fallback labeled honestly in README.

---

**Locked:** Yes
**Stack swap noted:** Render replaces Railway (2026-05-20).
ARCHEOF
