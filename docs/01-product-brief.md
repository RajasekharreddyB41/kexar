# Product Brief

**Project:** Kexar
**Working name:** Kexar Runtime (the resilient agent runtime)
**Demo surface:** Kexar IR (an AI incident response copilot built on the runtime)
**Author:** Rajasekhar
**Date:** 2026-05-20
**Status:** Locked for hackathon scope

---

## One sentence

Kexar is the resilient runtime for production AI agents, keeping them alive when LLMs, MCP tools, or networks fail, demoed as Kexar IR, an incident response copilot that stays useful during the outages it helps resolve.

## The problem

Every team shipping AI agents in 2026 is reinventing the same resilience code, badly. When the primary LLM rate-limits, the agent hangs. When an MCP tool times out, the agent crashes or returns a stack trace. When a provider has a brownout, the user sees garbage. Teams patch this with ad-hoc retries and try-except blocks, then ship anyway because deadlines.

The result is agents that work in demos and fall over in production. This is not a model problem, it is a runtime problem. Nobody is solving it as a primitive.

## Who it is for

Primary buyer: platform engineering leads at companies with 20+ engineers who are building or shipping internal AI agents. They own the AI infrastructure layer. They have budget. They are TrueFoundry's actual customer.

Secondary user: the application engineers on those teams who write the agents and currently spend 30% of their time on retry logic and failure handling instead of features.

End user of the demo: the on-call SRE using the incident copilot, who feels the resilience because their tool keeps working at 2am when the rest of the stack is on fire.

## Why this wins the hackathon

- TrueFoundry's challenge is literally "build resilient agents." We are building the runtime for that, not a one-off agent. Higher feasibility score.
- The demo dramatizes the value. We break things on camera and the agent keeps going. Judges see the resilience, do not have to imagine it.
- The pitch lands in one line. "Vercel for AI agents, except instead of edge functions we give you resilience as a primitive."
- TrueFoundry's gateway is the centerpiece, not an add-on. Sponsor sees their product driving the demo.

## What we are building (scope, in)

1. **Kexar Runtime.** A Python library + service that wraps agent calls with:
   - Multi-provider LLM routing via TrueFoundry Gateway, with cascading fallback (Claude -> GPT-4o -> Gemini -> Groq Llama).
   - MCP tool calls with timeouts, retries, circuit breakers, and graceful degradation.
   - Structured failure events the UI can render as plain English status.
   - Per-run hard limits: max steps, max tokens, max dollars. Exact numbers set in the architecture doc.

2. **Kexar IR (the demo app).** An incident response copilot that uses the runtime to:
   - Take an incident description in chat.
   - Call MCP tools to fetch logs, metrics, runbooks. All signals are simulated via a local MCP server, no real production integrations.
   - Synthesize a probable cause and suggested fix.
   - Keep working through staged outages of LLMs and tools.

3. **The control panel.** Co-equal with the chat in the UI, this is the hero surface. Shows live runtime state. Which model is active, which tools are healthy, recent failover events, cost so far, step count. This is how we make resilience visible.

4. **Incident timeline + export.** A scrollable view of every event in the current run (LLM call, fallback, tool call, failure, retry). Export button downloads the run as JSON. Reuses the event log we are already building for the control panel.

5. **Replay button.** Re-runs the last incident from the event log. Lets a judge see the chaos sequence twice without us re-typing. Also proves we are not faking the demo.

## What we are not building (scope, out)

- Real integrations with PagerDuty, Datadog, Slack, or any production system. All signals are simulated MCP.
- Multi-tenancy, billing, user accounts beyond a single demo login.
- A published SDK or installer. The runtime is one Python module in the repo, not a package on PyPI.
- Mobile app.
- On-call schedules, postmortems, alert routing, anything that looks like incident management. We are an AI runtime, not an incident tool.
- LangGraph, CrewAI, AutoGen, or any agent framework that hides the orchestration layer. We use real libraries for primitives (Pydantic, httpx, tenacity, pybreaker) and write the orchestration loop ourselves because the orchestration layer is the product.
- Any feature that does not appear in the demo video.

## Success criteria

For the hackathon:

- Win the TrueFoundry track ($1,000 or $1,500).
- Place in top 5 overall for the stage slot.
- Demo video is shareable as a portfolio piece on its own.

For the build:

- The runtime survives at least 4 staged failures on camera without the user-facing experience breaking.
- The control panel updates in real time and looks like a real product.
- Total cloud and API cost during the hackathon stays under $30.

Nice to have after, not build criteria:

- GitHub traction.
- Inbound from platform engineering leads or AI infra companies.

## What "winning" looks like to the judge

A platform engineer watches the 3 minute video and thinks "I want to put this in front of my team on Monday." They do not need to read the README. The value is obvious from the demo.

## Constraints

- 8 days to submit (May 28, 2026, 10am PT).
- Solo build unless team confirmed later.
- Budget under $50 total. Free tiers for everything possible.
- Tech lock-in: TrueFoundry Gateway is required by the challenge. Everything else is our choice.

## Risks (called out so they do not surprise us)

- **Streamlit-trap.** Tempted to use Streamlit for speed. It looks like a school project. We pay the 4 hour cost and use Next.js. Locked.
- **Framework-trap.** Tempted to use LangGraph or CrewAI. They hide the failure modes we are trying to showcase. We write the orchestration loop by hand and call it out as a deliberate choice.
- **Demo-fragility.** The chaos demo has to work cleanly. We pre-record the video over multiple takes, not live demo. Even at the in-person event, we play the video.
- **Scope creep into incident management.** Every time someone says "what if we added X" and X is an incident management feature, the answer is no. We are a runtime.
- **TrueFoundry account access.** Need to confirm credentials and free tier limits on day 1 before architecting around them.
- **Cost runaway.** Cascading fallbacks could rack up tokens during testing. We set a hard $20 spend cap on the gateway from day 1, plus per-run runtime limits.

## Open questions to resolve before architecture

- Confirm TrueFoundry credentials and any sponsor credits.
- Decide on fake data layer: generate on the fly, or seed Postgres? (Leaning Postgres for realism.)
- Decide if video is recorded at the venue or before traveling. (Leaning before.)

## What this doc is not

This is not a spec. It is the north star. When we argue about scope mid-build, we come back here and ask "does this serve the brief or not." If the answer is no, it gets cut.

---

**Locked:** Yes
**Next doc:** 02-market-scan.md
