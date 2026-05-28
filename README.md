# Kexar

**The resilience runtime for AI agents.** Sits on top of your LLM gateway. Wraps every tool call. Makes graceful degradation a primitive instead of a project you write from scratch.

Hackathon submission for the **TrueFoundry Resilient Agents** track, May 2026.

- Live demo: [kexar.vercel.app](https://kexar.vercel.app)
- IR copilot: [kexar.vercel.app/ir](https://kexar.vercel.app/ir)
- Backend API: [kexar-api.onrender.com](https://kexar-api.onrender.com)

<!--
  Drop a screenshot here once you have a clean one. Suggested shot:
  IR page mid-cascade with Claude struck through, GPT-4o calling,
  control panel showing one tool rose and two green.

  ![Kexar IR copilot during a chaos run](./docs/screenshots/ir-cascade.png)
-->

## The 30-second story

A senior SRE is paged at 2am. They open Kexar IR and start working an incident with the AI copilot. Halfway through, the LLM provider has a partial outage. Then a tool times out. Then the gateway hits a rate limit. A normal agent would have died three times. Kexar keeps going, tells the SRE in plain language what is degraded, and helps resolve the incident anyway. The control panel shows every failover live.

## Demo video

Coming May 28, 2026. A pre-recorded 3-minute walkthrough showing the happy path, three staged failures, and the runtime recovering from each.

## What's the gap

Gateways route. Frameworks orchestrate. Observability watches. Nobody owns what your agent does when all of that runs out.

Every team shipping agents in 2026 is reinventing the same retry logic, the same fallback chains, the same broken degraded-mode behavior. Kexar is the runtime layer that bakes resilience in: multi-provider failover, circuit breakers on every tool, budget caps per run, and user-visible "I cannot reach X, here is what I can still do" behavior as a primitive.

## The killer feature

When a tool dies, the agent does not crash. It does not hallucinate. It does this:

> "I could not reach the metrics service right now. I can still help. The logs show the v2.18.0 deploy landed at 02:13 and complaints followed. Roll back with `kubectl rollout undo deployment/checkout -n prod`."

That sentence is the entire product. Every other agent framework forces you to build this from scratch and most teams ship without it. Verified across three demo conditions (healthy, one tool down, two tools down) with the agent producing the appropriate response for each.

## How chaos works

The IR page has a `demo mode` toggle in the header. Flip it on and the right pane reveals kill switches for each tool plus a few canned replay scenarios. Kill a tool, then send a message. The next time the agent tries to call that tool, the runtime catches `ToolUnavailableError`, marks the tool down in state, and feeds that fact into the next planning prompt. The agent reasons over what is left and tells you what is missing.

Three pre-captured event logs live in `apps/web/lib/fixtures/` so the demo works even if the backend is asleep. The frontend replays the events with realistic timing and the control panel renders identically to a live run.

## Is this faked

The chaos demo is staged in the sense that we trigger the failures via UI toggles. The failover behavior is not faked. Four ways to verify:

1. **Replay endpoint.** `POST /api/runs/{run_id}/replay` re-streams a stored event log from Postgres. Same UI, same events, no LLM calls. Proves the system actually does this.
2. **TrueFoundry dashboard on screen.** The Request Traces view logs every real call your app makes through the gateway, tagged with the question that triggered it.
3. **Code in the repo.** Retry, circuit breaker, fallback, and event bus code are all here. See `apps/api/kexar/runtime/`.
4. **Live demo URL.** Anyone can try it. Toggle a chaos switch and watch the cascade.

## Architecture

```
Browser (Next.js)
  Chat pane  <--->  Control panel
        \             /
         \           /
          SSE event stream
                 |
                 v
Backend (FastAPI)
  Kexar Runtime
    - orchestrator (think -> act -> respond)
    - event bus (typed events, in-process pub/sub)
    - LLM cascade (Claude -> GPT-4o -> Gemini -> Groq Llama)
    - Tool resilience (timeout, retry, circuit breaker)
    - Budget enforcement (steps, tokens, dollars)
  Persistence
    - Postgres runs.event_log JSONB
    - Replay endpoint streams stored logs back
  Tool layer
    - query_logs, fetch_metrics, lookup_runbook
    - Modeled after MCP tool semantics
                 |
                 v
TrueFoundry AI Gateway
                 |
                 v
LLM providers (Claude, GPT-4o, Gemini, Groq)
```

Full product brief, market scan, demo script, and architecture are in [`docs/`](./docs).

## Tech stack

- **Frontend:** Next.js 15 (App Router), TypeScript, Tailwind, shadcn/ui, deployed to Vercel
- **Backend:** FastAPI, Python 3.14, deployed to Render
- **Database:** Render Postgres
- **LLM Gateway:** TrueFoundry AI Gateway (Developer Plan)
- **LLM Cascade:** Claude Sonnet 4.5 -> GPT-4o -> Gemini 2.5 Flash -> Groq Llama 3.3 70B
- **Tool layer:** custom Python functions modeled after MCP semantics (`query_logs`, `fetch_metrics`, `lookup_runbook`)
- **Event bus:** in-process pub/sub, SSE to browser
- **Observability:** TrueFoundry dashboard plus the control panel UI itself

No agent framework. The orchestration loop is the product. Writing it ourselves is the whole point.

## Quickstart

Clone:

```bash
git clone https://github.com/RajasekharreddyB41/kexar.git
cd kexar
```

Backend:

```bash
cd apps/api
uv sync
cp .env.example .env
# Fill in DATABASE_URL (Render Postgres) and TRUEFOUNDRY_API_KEY
uv run uvicorn kexar.api.main:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd apps/web
npm install
cp .env.example .env.local
# Set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open http://localhost:3000.

CLI smoke test (no frontend needed):

```bash
cd apps/api
uv run python -m kexar.runtime.cli "Why is checkout slow?"
uv run python -m kexar.runtime.cli "Why is checkout slow?" --kill fetch_metrics
uv run python -m kexar.runtime.cli "Why is checkout slow?" --kill fetch_metrics --kill query_logs
```

The first run is the happy path. The other two trigger degraded mode.

## Repo layout

```
apps/
  api/           FastAPI backend, runtime, tool layer
    kexar/
      api/         HTTP endpoints (runs, events, chaos, replay)
      runtime/     orchestrator, event bus, LLM cascade, tool resilience
      mcp/         (placeholder for a future MCP protocol server)
      db/          Postgres client, schema, run persistence
  web/           Next.js frontend (landing + IR copilot)
    app/
      page.tsx     landing page
      ir/          incident response copilot UI
    components/    shadcn-based control panel components
    lib/
      fixtures/    pre-captured event logs for offline replay
docs/            product brief, market scan, demo script, architecture
```

## What we are not building

- Auth, accounts, billing, multi-tenancy
- Real integrations with PagerDuty, Datadog, Slack
- A published SDK or pip package
- Mobile responsive beyond "does not look broken on a laptop"
- Tests beyond smoke-level
- Anything that does not appear in the demo video

The demo script in [`docs/03-demo-script.md`](./docs/03-demo-script.md) is the contract for what we built. If it is not in the script, it is not here.

## Credits

Built on **TrueFoundry AI Gateway** for the Resilient Agents hackathon track, May 2026.

LLM providers: Anthropic, OpenAI, Google, Groq.

UI components: [shadcn/ui](https://ui.shadcn.com). Icons: [lucide](https://lucide.dev).

## License

MIT. See [LICENSE](./LICENSE).

---

Made by [@RajasekharreddyB41](https://github.com/RajasekharreddyB41).
