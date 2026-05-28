# Market Scan

**For:** Kexar
**Date:** 2026-05-19
**Status:** Locked, informs build and pitch
**Scope:** 30 minutes of research, not a McKinsey deck. We name competitors, what they do, where the gap is, and where we land.

---

## TL;DR

The LLM gateway market is crowded and mature. The agent framework market is crowded and mature. Almost nobody owns the user-visible resilience layer that wraps agent execution and makes graceful degradation a primitive.

Gateways do routing and failover at the HTTP layer. Agent frameworks do orchestration. Observability tools watch after the fact. None of them own what the user sees when things break. That seam is our wedge.

---

## The categories we are competing with (and against)

There are four adjacent categories. We are not exactly in any of them. That is a feature, not a bug, for a hackathon. It is a risk for the long-term business and we will name it.

1. **LLM gateways.** Route requests across providers, failover on errors, track cost. (OpenRouter, Portkey, LiteLLM, TrueFoundry Gateway, Vercel AI Gateway, Cloudflare AI Gateway.)
2. **Agent frameworks.** Define agent logic, state, tool calls, multi-step reasoning. (LangGraph, CrewAI, AutoGen, Microsoft Agent Framework, Agno.)
3. **Agent observability and runtime infra.** Watch agents in production, debug them. (LangSmith, Helicone, Arize Phoenix, Northflank-style runtimes.)
4. **Incident response tools (the demo surface only).** PagerDuty, incident.io, Rootly, FireHydrant. We are not competing here, the copilot is just our demo skin.

---

## Competitor breakdown

### Category 1: LLM gateways

**TrueFoundry AI Gateway** (the sponsor)

- What it does: OpenAI-compatible gateway, multi-provider routing, fallback chains, RBAC, per-team budgets. MCP guardrails at 4 execution points (LLM input, LLM output, MCP pre-tool, MCP post-tool). Metadata-scoped policy lets one budget rule fan out into per-team counters.
- Strengths: Enterprise-grade governance, Kubernetes-native, real production tool. The MCP guardrail model and the metadata-scoped failover are the two features that make them strongest in the sponsor's category.
- Gaps: It is infrastructure. It does not know about your agent's semantic state. When the third fallback model fails, it returns an error to your app. What you do with that error is your problem.
- Pricing: Enterprise sales.
- **Relevance to us:** We sit on top of it. TrueFoundry is the gateway layer, not the product. The gateway handles HTTP-level retry and routing. We handle the semantic-level "now what."

**Portkey**

- What it does: Gateway plus observability plus prompt management. Conditional routing, circuit breakers, semantic caching.
- Strengths: Most mature feature set in the gateway space. ~8k GitHub stars.
- Gaps: Same as TrueFoundry. They route, they do not reason. Failure handling stops at the HTTP boundary.
- Pricing: Per-log, starts free, scales to enterprise.

**OpenRouter**

- What it does: Hosted marketplace for 300+ models. Automatic fallback baked in. Zero infra.
- Strengths: Two-minute setup. Huge model catalog.
- Gaps: Black-box fallback (you do not control or see the policy). 5.5% fee. US-only routing. No agent-level concepts.
- Pricing: Pay per token + 5.5% credit fee.

**LiteLLM**

- What it does: Open-source Python proxy. Self-hosted. 100+ providers. Configurable retries and fallbacks via YAML.
- Strengths: Free, full control, no markup.
- Gaps: You run it. No first-class agent concepts. Fallback policy is in YAML, not in the application logic where it should live for agent decisions.
- Pricing: Free, self-hosted.

**Vercel AI Gateway, Cloudflare AI Gateway**

- What they do: Platform-native gateways. Decent failover, basic observability.
- Strengths: Tight integration with their platforms.
- Gaps: Limited routing logic. Cloudflare does not even do failover.
- Pricing: Free tier + usage.

**Pattern.** Every gateway in this category does the same job at slightly different levels of polish. None of them know what your agent is doing. They are dumb pipes with smart routing.

### Category 2: Agent frameworks

**LangGraph**

- What it does: Graph-based state machine for agents. Conditional branching, loops, checkpointing.
- Strengths: Most production deployments in 2026. Mature ecosystem. Checkpointing helps with recovery.
- Gaps: Resilience is not a first-class concept. You build it as a node in your graph. The user-visible failure messaging is your problem. Tool failure handling is your problem. There is no "graceful degradation" primitive.
- Pricing: OSS, paid LangSmith for observability.

**CrewAI**

- What it does: Multi-agent collaboration with role-based agents.
- Strengths: Easy to think in roles. Quick prototyping.
- Gaps: Resilience story is even thinner than LangGraph. Crashes are crashes.
- Pricing: OSS.

**AutoGen / Microsoft Agent Framework 1.0** (GA April 2026)

- What it does: Microsoft's consolidated framework, .NET and Python. Workflows are graph-based.
- Strengths: Enterprise backing, long-term support, strong tool calling.
- Gaps: Optimized for Microsoft stack. Resilience is again your problem to assemble. Heavy.
- Pricing: OSS, paid Foundry hosting.

**Agno**

- What it does: Fast Python framework with built-in FastAPI runtime and UI.
- Strengths: Quick to deploy, has its own UI out of the box.
- Gaps: Still framework-shaped. Resilience patterns are not the headline feature.
- Pricing: OSS.

**Pattern.** Frameworks define how an agent thinks and acts. They treat failure as an exception path, not a design pillar. You can build resilience in them, but you build it from scratch every time.

### Category 3: Agent observability and runtime infra

**LangSmith, Helicone, Arize Phoenix**

- What they do: Trace agent runs, log prompts and responses, debug.
- Strengths: Essential for production agents.
- Gaps: Post-hoc. They tell you what failed after it failed. They do not intervene during the run.
- Pricing: SaaS, free tiers exist.

**Northflank, E2B, Modal-style runtimes**

- What they do: Execute agent code in sandboxes. Compute infrastructure.
- Strengths: Solve a real problem (where does agent-generated code run safely).
- Gaps: Different problem from ours. They are the substrate, not the resilience layer.

**Pattern.** Observability watches, sandboxes execute, neither owns the in-flight resilience policy.

### Category 4: Incident response (demo surface only)

PagerDuty, incident.io, Rootly, FireHydrant. All have started bolting AI features on. None of them are building an AI-native runtime. We are not competing here; if anything, they are eventual customers of Kexar-the-runtime.

---

## Where the gap is

The honest version of the gap:

1. Every gateway stops at the HTTP boundary. They retry, they failover, they cache. They do not reason about your agent's state when all of that fails.
2. Every agent framework treats failure as an exception. Resilience is something you bolt on, not something the framework expresses.
3. Every observability tool is post-hoc. By the time you see the failure in LangSmith, the user already saw the broken response.
4. Nobody owns the user-visible resilience story. When the third fallback model fails, the agent should not throw. It should say, in plain language, "I cannot do X right now, here is what I can still do." That is a runtime-level product behavior. No tool ships it as a primitive.

**Kexar sits in this gap.** A runtime that wraps agent execution, owns the failure semantics, expresses degradation as a first-class concept, and surfaces it to users in plain English. We use the gateway underneath. We are not replacing it. We are using it the way it should be used.

---

## Where we land (positioning)

One line: **The resilience runtime for AI agents. Sits on top of your LLM gateway, reduces the try-except scaffolding you wrote, makes graceful degradation a primitive instead of a project.**

Comparison shorthand for the pitch:

| Layer                    | What owns it today                       | What Kexar adds                                                                           |
| ------------------------ | ---------------------------------------- | -------------------------------------------------------------------------------------------- |
| Provider routing         | LLM gateway (TrueFoundry, Portkey, etc.) | Uses the gateway, does not replace it.                                                       |
| Orchestration            | Frameworks (LangGraph, CrewAI)           | Optional. We expose orchestration too because the resilience semantics live here, not above. |
| Observability            | LangSmith, Helicone                      | In-flight, not post-hoc. Surfaces to UI, not just dashboards.                                |
| User-visible degradation | Nobody, you DIY it                       | First-class. Built in. The differentiator.                                                   |

---

## Pricing (what we are not solving in 9 days, but the pitch needs)

Reference points so the feasibility story holds up:

- LiteLLM: free OSS, enterprise quoted.
- Portkey: free dev tier, around $36/mo at 500K requests, $171/mo at 2M requests.
- OpenRouter: pay per token + 5.5% credit fee.
- LangSmith: free tier, paid plans for teams.

A plausible Kexar pricing (for the pitch, not the build):

- OSS core. Self-hosted, MIT or Apache 2.0.
- Hosted control plane: $99/mo per project for teams, $999/mo for orgs with RBAC, SSO, audit logs.
- This mirrors the LangSmith / LangGraph split that the market has already accepted.

We do not build any of this. We just need to be able to answer "how would you make money" in one breath.

---

## Risks the market scan surfaced

- **Microsoft Agent Framework 1.0 GA in April 2026.** Microsoft is moving into this space hard with enterprise backing. If they ship first-class resilience primitives in v1.1, our window narrows. For the hackathon this is irrelevant. For a real business it is the biggest competitive risk.
- **Gateway vendors will eat upward.** Portkey already has circuit breakers and semantic caching. It is one step from adding "graceful degradation policies" as a feature. Our moat has to be the orchestration semantics, not just the failure handling.
- **"Resilience" is hard to demo on a slide.** This is why the chaos demo matters so much. If we do not show it, the category does not click for the judge.
- **Open source pressure.** LiteLLM is free, OSS, and improving fast. If we ever charge for Kexar, the OSS core must be strong enough to compete with self-hosted LiteLLM plus a hand-rolled retry layer.
- **Naming collision with Microsoft Sentinel.** Microsoft Sentinel is a major SIEM product, so the original working name (Sentinel) was changed to Kexar to avoid the clash. Logged in decisions doc.

---

## What this means for the build

- **Use TrueFoundry as the gateway underneath us, not as a competitor.** Their dashboard appears in the demo. We are an additive layer.
- **Do not reinvent LLM routing.** The gateway handles that. We handle what happens semantically when the routing has run out of options.
- **The control panel is the differentiator.** It is the visible artifact of the runtime owning the failure semantics. Build it like a real product.
- **The "graceful degradation API" is the conceptual headline.** A developer using Kexar should write something like `@degrades_to(use_cache=True, partial_ok=True)` on an agent step, and the runtime handles the rest. We probably do not ship this exact API in 9 days, but the demo should imply it exists.
- **The 30-second pitch in the demo video should land the gap.** "Gateways route. Frameworks orchestrate. Observability watches. Nobody owns what your agent does when all of that runs out. Kexar does." That is the line.

---

## Doc decisions captured

- Kexar is not a gateway, not a framework, not an observability tool. It is a runtime layer with a specific job: own the user-visible resilience semantics of an agent.
- We use TrueFoundry Gateway underneath. Show it in the demo.
- We do not use LangGraph or CrewAI. Frameworks hide the layer we are trying to make visible.
- Pitch positioning: "The resilience runtime for AI agents."
- Naming risk (Microsoft Sentinel SIEM) acknowledged. Renamed from Sentinel to Kexar.

---
