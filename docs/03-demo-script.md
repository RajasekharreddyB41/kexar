# Demo Script

**For:** Kexar
**Format:** Pre-recorded video, 2:45 to 3:00 final length
**Date:** 2026-05-19
**Status:** Locked, drives architecture
**Recording plan:** Multiple takes, edited. Not live. Even at the in-person event we play the video.

---

## Why this doc matters

This is the contract for what we build. Every feature in the architecture doc has to appear in this script. If it does not appear here, we do not build it. If something is here, it ships.

Hackathon submission needs: demo video 1 to 3 minutes, project page write-up, screenshots. This doc covers the video. The write-up and screenshots come from the same material.

---

## The story in one paragraph

A senior SRE is paged at 2am. She opens Kexar IR and starts working the incident with the AI copilot. Halfway through, the LLM provider has a partial outage. Then a tool times out. Then the gateway hits a rate limit. A normal agent would have died three times. Kexar keeps going, tells her in plain language what is degraded, and helps her resolve the incident anyway. The control panel shows the failovers in real time. Cut to pitch slide.

That paragraph is the whole video. Everything below is execution detail.

---

## Pre-roll setup (before recording)

- Browser at 1920x1080, clean profile, no extensions visible.
- Two tabs ready: Kexar IR (our app) and the TrueFoundry Gateway dashboard (their real dashboard, logged in).
- Kexar IR loaded with the incident scenario pre-seeded: "API latency spiking on checkout service since 02:14 UTC."
- Chaos controls in the control panel, hidden by default, revealed with a toggle. Operator (us) clicks them on cue.
- Audio: clean mic, no room echo. Voiceover recorded separately, not live.
- Background music: subtle, low volume, ends before the pitch slide.

---

## Beat-by-beat script

Total runtime target: 2:50. Three acts.

### Act 1: The problem (0:00 to 0:30)

**Visual:** Hard cut. Black screen. White text fades in. "It is 2:14 AM. Your checkout API is dying. Your AI copilot is supposed to help."

Cut to a fake terminal showing a typical agent crashing. Stack trace. `openai.RateLimitError`. `MCPConnectionError`. Red text. Make it ugly.

**Voiceover (0:00 to 0:15):**
"AI agents are fragile. When the LLM rate-limits, your agent hangs. When a tool times out, it crashes. When the gateway browns out, your user sees a stack trace."

**Visual:** The crashing agent freezes mid-stack-trace. Text overlay: "This is every agent in production."

**Voiceover (0:15 to 0:30):**
"Every team building agents in 2026 is reinventing the same retry logic, the same fallback chains, the same broken degraded-mode behavior. We are building the runtime that bakes resilience in. This is Kexar."

**Visual:** Kexar logo. 1.5 seconds. Cut.

### Act 2: The happy path (0:30 to 1:15)

**Visual:** Cut to Kexar IR app. Clean, split view. Chat on the left, control panel on the right. The SRE has just typed: "Checkout API p99 latency went from 80ms to 4.2s at 02:14. What broke?"

The agent responds in a streamed message. As it streams, the control panel lights up.

**Control panel shows:**

- Active model: Claude Sonnet 4.5 (green dot)
- Step 1: "Query logs for checkout-service" (calling MCP tool)
- Step 2: "Fetch p99 latency from metrics" (calling MCP tool)
- Tokens used so far: 1,247
- Cost so far: $0.018
- Status: Healthy

**Voiceover (0:30 to 0:55):**
"Kexar wraps your agent in a resilience runtime. It routes through TrueFoundry's AI Gateway for multi-provider failover. It calls MCP tools with timeouts, retries, and circuit breakers. And it makes every decision visible in the control panel."

**Visual:** Agent finishes its first analysis. Shows a summary: "Latency spike correlates with a deploy at 02:13. New version of checkout-service introduced a synchronous call to the fraud-check service. Recommend rollback."

**Voiceover (0:55 to 1:15):**
"On the happy path, this is just a good agent. The interesting part is what happens when things break."

### Act 3: The chaos (1:15 to 2:30)

This is the part the judges came for. Three staged failures, in order. The pace picks up. Music gets tighter.

#### Failure 1: LLM provider goes down (1:15 to 1:40)

**Visual:** Operator clicks the chaos control: "Kill Claude." A red X appears on Claude in the control panel.

The SRE types her next message: "Show me the deploy diff."

Agent starts responding. The control panel updates:

- Active model: Claude Sonnet 4.5 (red dot, "failing")
- Failover triggered: Claude -> GPT-4o
- Active model: GPT-4o (green dot)
- Latency on this step: +340ms (failover overhead)

A small toast notification in the chat: "Switched to backup model. Continuing."

The agent's response continues without breaking. The SRE never sees the failure as an error.

**Voiceover (1:15 to 1:40):**
"Watch the control panel. We just killed Claude. The runtime detected it through the gateway, failed over to GPT-4o, and told the user in one line. The agent did not stop. The user did not see a stack trace."

**Cut to TrueFoundry dashboard for 3 seconds.** Show the actual failover event logged in their UI. This is the sponsor moment.

**Voiceover (1:40):**
"TrueFoundry's gateway handles the HTTP-level routing. Kexar handles what the user sees."

#### Failure 2: MCP tool dies (1:40 to 2:05)

**Visual:** Operator clicks "Kill metrics MCP." The metrics tool icon in the control panel goes red.

The SRE asks: "What is the current error rate?"

The agent starts to call the metrics tool. Tool times out. The control panel shows:

- Tool: fetch_metrics (red, "circuit open")
- Retry 1: timeout
- Retry 2: timeout
- Circuit breaker: opened, cooling for 30s

Then the agent does the thing that wins this category. It responds:

"I cannot reach the metrics service right now. I can still help. Based on the logs I already pulled and the runbook for this service, the error rate is likely elevated on the /checkout endpoint specifically. The deploy at 02:13 is still the most likely cause. Want me to draft a rollback command using the runbook?"

**Voiceover (1:40 to 2:05):**
"This is where most agents would crash or hallucinate. Kexar does neither. It recognizes the tool failure, tells the user exactly what is degraded, and reasons over what it can still do. That is the runtime owning the user-visible failure story. No framework gives you this."

#### Failure 3: Cost ceiling and rate limit (2:05 to 2:30)

**Visual:** Operator clicks "Trigger rate limit on GPT-4o."

The SRE asks one more question, something open-ended like: "Give me a full incident summary."

The control panel shows:

- GPT-4o: rate limited (red)
- Failover: GPT-4o -> Gemini 2.5 (green)
- Active model: Gemini 2.5 Flash
- Step count: 7 of 10 max
- Cost: $0.14 of $0.50 budget

The agent finishes the summary on the third model. The control panel shows the full cascade in the event log: Claude (down) -> GPT-4o (rate limited) -> Gemini (success).

**Voiceover (2:05 to 2:30):**
"Three providers, two failures, one budget cap. The agent stays within the per-run cost limit, the runtime cascades through providers, and the user gets her summary. This is what production resilience looks like as a primitive instead of a project."

### Act 4: The pitch (2:30 to 2:50)

**Visual:** Cut to a clean slide. Kexar logo at top.

Three lines stagger in:

- Gateways route.
- Frameworks orchestrate.
- **Nobody owns what your agent does when all of that runs out. Kexar does.**

**Voiceover (2:30 to 2:50):**
"Gateways route. Frameworks orchestrate. Observability watches. Nobody owns the user-visible resilience layer that wraps agent execution. That is Kexar. Built on TrueFoundry. Open source core. We think every production agent needs this."

**Final frame:** Kexar logo, GitHub URL, one line: "Try it: github.com/RajasekharreddyB41/kexar"

Hold for 2 seconds. Fade to black.

---

## What this script forces us to build

Working backwards from the script. If it is not here, we do not build it.

**Kexar IR app (the demo surface):**

- Two-pane layout: chat on left, control panel on right.
- Streamed agent responses.
- Pre-seeded incident: "Checkout API latency."
- Chaos controls (kill Claude, kill metrics MCP, trigger rate limit).
- Chaos controls hidden behind a toggle so the UI looks clean by default.
- One incident pre-loaded; replay button to re-run it.

**Control panel (the hero UI):**

- Active model with health indicator (green / red dot).
- Current step description.
- Event log: every failover, retry, circuit-breaker event.
- Tokens used, cost so far, step count, budget cap.
- Tool health row for each MCP tool (logs, metrics, runbook).
- Updates in real time as the agent runs.

**Runtime (the actual product):**

- Multi-provider failover through TrueFoundry Gateway: Claude -> GPT-4o -> Gemini -> Groq Llama.
- MCP tool calls with timeout, retry, circuit breaker.
- "Degraded mode" reasoning: when a tool is unavailable, agent reasons over what it still has.
- Per-run hard limits: max steps, max tokens, max dollars.
- Structured event log that the control panel reads from.

**MCP server (faked but real):**

- Three tools: query_logs, fetch_metrics, lookup_runbook.
- Each tool can be killed via a chaos control.
- Pre-seeded data realistic enough to support the incident story.

**TrueFoundry Gateway:**

- Real account, real key, real dashboard.
- Failover policy configured to match the cascade order.
- Used live in the demo, briefly shown on screen for the sponsor moment.

**What we are NOT building (re-confirmed from brief):**

- Auth, accounts, billing.
- Real integrations with Datadog, PagerDuty, Slack.
- Mobile.
- Postmortems, on-call schedules, alert routing.
- Anything not on screen in the script above.

---

## Failures NOT included in the demo (and why)

- **Network partition / total internet outage.** Hard to demo, the recovery story is "wait." Skip.
- **Hallucination detection.** Different category, would dilute the message.
- **Prompt injection defense.** Same. Different category.
- **Multi-agent coordination failures.** Kexar IR uses a single agent. Multi-agent is a future story.

If asked "what about X" in Q&A, the answer is "the runtime supports it, the demo focuses on the three failure modes most teams hit in production today."

---

## The "is this faked" defense

Judges will wonder if the chaos demo is staged. It is, in the sense that we trigger the failures. It is not, in the sense that the failover behavior is real. Defenses:

1. **Replay button.** Re-runs the recorded event log on a fresh request. Proves the system actually does this, not just plays a video.
2. **TrueFoundry dashboard on screen.** Their UI logs the real failover. We do not control that UI. If a failover did not happen, it would not appear.
3. **Show the code in the README.** The retry, circuit breaker, and fallback code is in the repo. Link it in the write-up.
4. **Offer a live demo URL.** If a judge wants to try it, they can. We make sure the deploy is up during judging.

---

## Voiceover style notes

- Calm, confident, slightly fast. Not a TED talk. Not a salesperson.
- No "imagine if" or "in today's world."
- No filler. Every sentence carries weight.
- Read it out loud and time it. If it does not fit in the beat, cut words, do not speed up.

---

## Production checklist (for shoot day)

- [ ] App deployed to production URL on real domain.
- [ ] TrueFoundry account active, free tier confirmed, dashboard accessible.
- [ ] Chaos controls tested end-to-end. Each failure mode reliably produces the intended UI behavior.
- [ ] Replay button works on the seeded incident.
- [ ] Browser zoom, resolution, and color profile checked.
- [ ] Screen recorder set to 1080p60.
- [ ] Voiceover recorded clean, separate file, ready to mix.
- [ ] Music track selected, licensed if needed, faded in/out.
- [ ] Logo and pitch slide ready as PNG, not generated live.
- [ ] Final video under 3:00. Hard cap.

---

## What the write-up needs (from the same material)

Devpost submission requires a project page. We reuse the script:

- **Inspiration:** The 2am SRE story.
- **What it does:** One paragraph, from Act 2 and Act 3.
- **How we built it:** Architecture diagram + the "What this script forces us to build" section.
- **Challenges:** Honest. The MCP failure handling was the hardest part. Designing the degraded-mode reasoning was the technically interesting problem.
- **What we learned:** Resilience is a UX problem more than an infra problem. Mentioning this in the write-up signals the maturity TrueFoundry's judges look for.
- **What is next:** OSS core, hosted control plane, native LangGraph / CrewAI adapters.

---
