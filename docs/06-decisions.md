# Decisions Log

**For:** Kexar
**Purpose:** One line per non-obvious decision. Captures what, when, and why. Future-you reads this when you cannot remember why something is the way it is.
**Format:** Date | Decision | Why | Status (active / revisited / reversed)
**Rule:** Add a row when you make a call that is not obvious from the code. Skip the obvious ones.

---

## Planning phase decisions (May 19, 2026)

| Date       | Decision                                                      | Why                                                                                                                      | Status |
| ---------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------ |
| 2026-05-19 | Target TrueFoundry track, not Perfect Corp                    | Better fit for backend depth, less crowded, sponsor judges care about resilience                                         | active |
| 2026-05-19 | Build a runtime, demo as incident copilot (Option B)          | TrueFoundry's customer is the platform engineer; selling to that buyer scores higher on feasibility                      | active |
| 2026-05-19 | Name: Kexar (was Sentinel)                                  | Short, credible. Renamed from Sentinel to avoid collision with Microsoft Sentinel (SIEM product) | active |
| 2026-05-19 | No agent framework (no LangGraph, no CrewAI)                  | The orchestration layer is the product. Frameworks hide the failure modes we are showcasing                              | active |
| 2026-05-19 | Next.js for frontend, not Streamlit                           | Streamlit caps perceived quality at "internal tool." 4 extra hours buys us a real-product look                           | active |
| 2026-05-19 | FastAPI + Python 3.12 backend                                 | Async, native SSE, sits where the LLM ecosystem lives                                                                    | active |
| 2026-05-19 | TrueFoundry Gateway is the only path to LLMs                  | Required by challenge, and routing through one place is how the demo makes sense                                         | active |
| 2026-05-19 | App-level failover plus gateway-level failover (both)         | Gateway does HTTP retry, app loop emits UI events. Need both                                                             | active |
| 2026-05-19 | Custom MCP server, not a real one                             | Real MCP servers do not fail on command. We need precise control                                                         | active |
| 2026-05-19 | Cascade order: Claude -> GPT-4o -> Gemini Flash -> Groq Llama | Reasoning quality first, speed/cost in the middle, "always works" backstop last                                          | active |
| 2026-05-19 | In-process event bus, no Redis                                | One backend instance, no scale requirement                                                                               | active |
| 2026-05-19 | Monorepo, apps/web + apps/api                                 | Solo build, simpler than two repos                                                                                       | active |
| 2026-05-19 | Supabase Postgres for storage                                 | Free tier, instant Postgres, no Auth tables used                                                                         | active |
| 2026-05-19 | Vercel for frontend, render for backend                       | Free tiers, git-push deploys, no DevOps tax                                                                              | active |
| 2026-05-19 | $20 hard cap on TrueFoundry spend for the whole hackathon     | Cascading fallbacks could surprise us during testing                                                                     | active |
| 2026-05-19 | Per-run caps: 10 steps, 20k tokens, $0.50                     | 2-3x normal run for headroom on chaos scenarios                                                                          | active |
| 2026-05-19 | Three failure modes in the demo, not four                     | Four becomes a list, three is a story                                                                                    | active |
| 2026-05-19 | Pre-recorded video, not live demo                             | The chaos demo must work on first take. Multi-take recording is the only safe path                                       | active |
| 2026-05-19 | Chaos endpoint named /api/demo/chaos                          | Path name makes the demo-only nature explicit                                                                            | active |
| 2026-05-19 | runs.event_log as JSONB array, no separate events table       | Events are append-only per run, array preserves order, replay is trivial                                                 | active |
| 2026-05-19 | Capture JSON fixtures on Day 6 for frontend independence      | Decouples UI work from backend uptime, gives us fallback content for the video                                           | active |
| 2026-05-19 | Day 1 task order: TrueFoundry first, repo second              | Signup risk is the single biggest Day 1 blocker                                                                          | active |

---

## Build phase decisions (fill in as we go)

| Date | Decision | Why | Status |
| ---- | -------- | --- | ------ |

---

## Daily standup log

End of every build day, answer these four. Five minutes max.

### Day 1 - Tue May 20

- Shipped:
- Slipped:
- Learned:
- Tomorrow's most important thing:

### Day 2 - Wed May 21

- Shipped:
- Slipped:
- Learned:
- Tomorrow's most important thing:

### Day 3 - Thu May 22

- Shipped:
- Slipped:
- Learned:
- Tomorrow's most important thing:

### Day 4 - Fri May 23

- Shipped:
- Slipped:
- Learned:
- Tomorrow's most important thing:

### Day 5 - Sat May 24

- Shipped:
- Slipped:
- Learned:
- Tomorrow's most important thing:

### Day 6 - Sun May 25

- Shipped:
- Slipped:
- Learned:
- Tomorrow's most important thing:

### Day 7 - Mon May 26

- Shipped:
- Slipped:
- Learned:
- Tomorrow's most important thing:

### Day 8 - Tue May 27

- Shipped:
- Slipped:
- Learned:
- Tomorrow's most important thing:

### Day 9 - Wed May 28

- Shipped:
- Slipped:
- Learned:
- Submitted: yes / no

---

## Post-hackathon decisions

Decisions made after submission go below this line. Things like renames, OSS release strategy, what to do next.

| Date | Decision | Why | Status |
| ---- | -------- | --- | ------ |
