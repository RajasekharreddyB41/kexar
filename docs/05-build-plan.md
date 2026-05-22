# Build Plan

**For:** Sentinel
**Date:** 2026-05-19
**Status:** Locked, drives daily execution
**Deadline:** Thursday, May 28, 2026, 10:00 AM PT (final submissions due)
**Recording target:** End of Day 8 (May 27), so Day 9 is buffer + submission

---

## Operating principles

Five rules that govern every day.

1. **End every day with something that runs.** Even if it does nothing useful, it boots. No "I'll finish tomorrow" half-states.
2. **Daily demo.** At the end of each day, run the demo flow we have built so far. If it breaks, we fix before adding.
3. **Cut before you crunch.** When a day runs long, cut scope from later days. Do not work past midnight.
4. **The chaos demo is sacred.** Anything that threatens the three failure modes from the demo script gets priority over everything else.
5. **Commit after every step.** Small commits, descriptive messages. If the laptop dies, we lose hours, not days.

---

## The 9 days at a glance

| Day | Date       | Theme                       | Ships                                                                                |
| --- | ---------- | --------------------------- | ------------------------------------------------------------------------------------ |
| 1   | Tue May 20 | Foundations                 | TrueFoundry confirmed, repo, accounts, deploy pipeline, "hello world" on real domain |
| 2   | Wed May 21 | Runtime core                | Orchestration loop, LLM failover, basic event log, CLI demo, latency instrumented    |
| 3   | Thu May 22 | MCP and tools               | Local MCP server, 3 tools, seeded data, tool resilience                              |
| 4   | Fri May 23 | Backend API                 | FastAPI endpoints, SSE stream, chaos endpoint, replay                                |
| 5   | Sat May 24 | Frontend shell              | Next.js app, two-pane layout, chat working end to end                                |
| 6   | Sun May 25 | Control panel               | The hero UI, real-time event rendering, JSON fixtures captured                       |
| 7   | Mon May 26 | Degraded mode + polish pass | The "I cannot reach X" reasoning, prompt tuning, landing page, polish                |
| 8   | Tue May 27 | Demo dry runs + video       | 3 to 5 full rehearsals, then record, then edit, backups taken                        |
| 9   | Wed May 28 | Buffer + submit             | Bug fixes, write-up, screenshots, submit by 10 AM PT                                 |

Day 9 is morning-only. Submission deadline is 10:00 AM PT which is 1:00 PM ET. Plan accordingly.

---

## Day 1, Tuesday May 20: Foundations

**Why this matters:** Day 1 removes the dependency risks that could kill the whole project. If TrueFoundry, Vercel, Railway, or Supabase blocks us, we want to know today, not on Day 4.

**Tasks (in this order, the order matters):**

1. **TrueFoundry first.** Create account. Get API key. Make one test call from a Python REPL to confirm the gateway works. Confirm free tier limits. Set $20 budget cap in their dashboard. If any of this is blocked, escalate via the hackathon Discord immediately and pivot to OpenRouter as a temporary gateway.
2. Create GitHub repo `sentinel` (private until Day 8).
3. Set up monorepo structure per architecture doc (`apps/web`, `apps/api`, `docs`).
4. Create Vercel project, connect to repo, deploy a placeholder Next.js page.
5. Create Railway project, connect to repo, deploy a placeholder FastAPI app.
6. Create Supabase project. Run schema.sql.
7. Buy custom domain. Configure DNS to Vercel.
8. Set up `.env.example` files for both apps.
9. Configure ruff for Python, ESLint + Prettier for TypeScript.
10. Add minimal CI workflow: lint + typecheck only.
11. Verify both apps deploy on push.
12. Write `README.md` with one paragraph and a "build status" badge.

**End-of-day demo:** Visit the custom domain, see the Sentinel placeholder page. Hit the backend health endpoint, get 200. Make one LLM call through TrueFoundry from your laptop, see a response.

**Cut list (if running long):** Custom domain can wait until Day 8. CI can wait until Day 2.

**Risks:** TrueFoundry signup friction. Mitigation: it is task 1 today, not buried.

---

## Day 2, Wednesday May 21: Runtime core

**Why this matters:** The runtime is the product. Today we prove the orchestration loop works end-to-end before we commit to the architecture around it.

**Tasks:**

1. Implement `state.py`: `AgentState`, `Run`, `Step` types.
2. Implement `events.py`: typed event bus, in-process pub/sub. Lock the event schema to the canonical example in the architecture doc.
3. Implement `policy.py`: cascade order, timeouts, retry config.
4. Implement `llm.py`: `call_llm_with_failover` using TrueFoundry gateway. Cascade: Claude -> GPT-4o -> Gemini -> Groq. Emits `llm.call.*` and `llm.failover` events.
5. Implement `budget.py`: token and dollar tracking, step counting, cap enforcement.
6. Implement `orchestrator.py`: the main loop (think -> act -> respond).
7. Stub `tools.py` with one fake tool that always succeeds.
8. Add latency timing to every LLM call. Log: first token time, full response time, retries, failover overhead. These map to the latency budgets in the architecture doc.
9. Write a CLI runner: `python -m sentinel.runtime.cli "incident description"`. Prints events as they happen, with timing.

**End-of-day demo:** Run the CLI with a test prompt. See the agent reason, call the fake tool, return an answer. See events stream to the terminal. Manually fail Claude by setting a bogus model name, see failover to GPT-4o. Check that first-token latency is under 1.2 seconds.

**Cut list:** Skip the manual failover test, do it Day 3.

**Risks:** TrueFoundry gateway request format. Mitigation: copy from their docs, do not invent.

---

## Day 3, Thursday May 22: MCP server and tools

**Why this matters:** Today we prove the agent can actually do something useful with real tools, and that tool failures degrade gracefully. Without this, the demo has no incident to investigate.

**Tasks:**

1. Implement local MCP server in `apps/api/sentinel/mcp/server.py`.
2. Implement `query_logs` tool. Reads from `incident_signals` table where type='log'.
3. Implement `fetch_metrics` tool. Reads from `incident_signals` where type='metric'.
4. Implement `lookup_runbook` tool. Reads from `incident_signals` where type='runbook'.
5. Seed the database with realistic data for the "checkout latency" incident. Logs reference the 02:13 deploy. Metrics show p99 spike. Runbook describes rollback procedure.
6. Implement `call_tool_with_resilience` in `tools.py`. Timeout, retry, circuit breaker via pybreaker.
7. Implement chaos toggles: each tool checks a "killed" flag and returns 503 or hangs if set.
8. Wire tools into the orchestrator. Replace the fake stub.

**End-of-day demo:** CLI run with the real incident. Agent calls all 3 tools, synthesizes an answer. Then run again with `fetch_metrics` killed, see the agent recover. Then kill it 3 times fast, see the circuit open.

**Cut list:** Runbook tool data can be hardcoded instead of in DB. Saves 30 min.

**Risks:** MCP protocol details. Mitigation: use the simplest MCP server pattern from the spec, do not get fancy.

---

## Day 4, Friday May 23: Backend API

**Why this matters:** Today the runtime becomes reachable from a browser. Until now it has only run in our terminal. This is the bridge to the UI.

**Tasks:**

1. Implement `POST /api/runs`. Creates a run row, kicks off the orchestrator in a background task, returns run_id.
2. Implement `GET /api/runs/{run_id}/events`. SSE endpoint. Subscribes to the event bus, streams to client.
3. Implement `POST /api/demo/chaos`. Toggles tool / provider kill switches. Rate-limited via token bucket.
4. Implement `POST /api/runs/{run_id}/replay`. Re-emits stored event log from DB with realistic timing.
5. Persist event log to `runs.event_log` as events fire.
6. Configure CORS for the Vercel domain.
7. Test SSE reconnection: drop the connection mid-stream, confirm it reconnects within 2 seconds.
8. Deploy to Railway, confirm end-to-end via curl + an SSE client.

**End-of-day demo:** From the terminal, curl `POST /api/runs` with the seeded incident. Open SSE stream in another terminal. See events stream live. Trigger chaos via curl, see the next run handle it.

**Cut list:** Replay can slip to Day 7 if needed. Not on the critical path until video day.

**Risks:** SSE in Railway. Mitigation: test SSE on Railway with a hello-world before building the full endpoint.

---

## Day 5, Saturday May 24: Frontend shell

**Why this matters:** Today the project becomes something a human can see and use. Everything before this was for engineers only.

**Tasks:**

1. Scaffold Next.js 15 with App Router, Tailwind, shadcn.
2. Build `/ir` page with two-pane layout. Chat on left, control panel placeholder on right.
3. Build `ChatPane` component. Composer at bottom, messages stream from top.
4. Build `Message` component for user + assistant turns.
5. Build `lib/sse.ts` client. Connects to backend SSE endpoint, parses events, validates against the schema.
6. Connect chat submit to `POST /api/runs`.
7. Stream the assistant's text response as `step.end` events arrive with final answer.
8. Style with shadcn so it looks like a real product, not a demo.
9. Add a minimal landing page at `/` so the domain root is not blank.

**End-of-day demo:** Open the deployed site, type "Why is checkout slow?", see the agent respond in the chat pane. Control panel shows a placeholder.

**Cut list:** Landing page can be one paragraph + a "try the demo" button. Polish on Day 7.

**Risks:** SSE in the browser through Vercel. Mitigation: SSE works fine through Vercel for client-to-Railway, just need the right headers on the backend.

---

## Day 6, Sunday May 25: Control panel

**Why this matters:** The control panel is the hero UI. It is the visible proof that Sentinel owns the resilience layer. Today is the day judges see the differentiator.

**Tasks:**

1. Build `ModelStatus` component. Shows active model with green/red dot. Updates on `llm.failover`.
2. Build `ToolHealth` component. Row per tool, status per tool. Updates on `tool.circuit_*` and `tool.call.*`.
3. Build `BudgetMeter` component. Tokens used / max, dollars spent / max, step count / max. Animated progress bars.
4. Build `EventLog` component. Scrolling timeline of events with timestamps. Auto-scrolls to bottom on new event.
5. Build `ChaosControls` component. Three toggles: kill Claude, kill metrics, trigger rate limit. Posts to `/api/demo/chaos`.
6. Hide chaos controls behind a "demo mode" toggle so the UI is clean by default.
7. Polish: spacing, typography, color, animations.
8. Test every event type produces the correct UI change.
9. **Capture JSON fixtures.** Run the demo flow with each chaos mode and save the event log to `apps/web/lib/fixtures/`. This decouples frontend development from backend uptime and gives us fallback content for the demo video.

**End-of-day demo:** Run a full incident in the browser. Trigger each chaos mode. Watch the control panel react in real time. Take screenshots for the write-up.

**Cut list:** Animations are nice to have. Static state changes are fine. EventLog can be plain text before pretty.

**Risks:** SSE event ordering on the frontend. Mitigation: events include the `seq` field, frontend renders in seq order, not arrival order.

---

## Day 7, Monday May 26: Degraded mode + polish pass

**Why this matters:** Today we ship the moment that wins the category. The "I cannot reach metrics, but here is what I can still tell you" response is the single most product-feeling beat in the demo. Without this, we have a chatbot with a dashboard. With this, we have a runtime.

**Tasks:**

1. Implement degraded mode prompt augmentation in `llm.py`. When a tool returns `ToolUnavailable`, the next LLM call gets the degraded-mode system prompt prefix.
2. Tune the degraded mode prompt over multiple runs. Goal: agent never hallucinates calling the dead tool, always tells the user what is unavailable.
3. Implement the replay button on the frontend. Hits `POST /api/runs/{id}/replay`, re-runs the SSE stream.
4. Build a real landing page. Hero, three benefits, one CTA. Use the positioning from the market scan.
5. Write the README. Architecture diagram, quickstart, the demo script's "is this faked" defense section.
6. **Polish pass.** Walk through every screen in the app. Every loading state, every empty state, every error state. Remove anything ugly. Replace spinners with skeleton screens where it helps. Tighten spacing. Tune colors. Judges score polish subconsciously and we cannot afford to lose points here.
7. Test the full demo script end-to-end. Time it. Should fit in 2:45.

**End-of-day demo:** Full dry-run of the demo script in the browser, with the timer running.

**Cut list:** Landing page can be one screen, no scroll. README can skip the architecture diagram (link to docs instead).

**Risks:** Degraded mode prompt tuning eats the day. Mitigation: time-box to 4 hours. If it is not working, ship a deterministic fallback ("metrics unavailable, the deploy at 02:13 remains the most likely cause based on logs") and label it honestly in the README.

---

## Day 8, Tuesday May 27: Demo dry runs + record

**Why this matters:** The video is the submission. Code that does not appear in the video does not count. Today we lock the video and back up everything.

**Tasks (morning):**

1. Three to five full dry runs of the demo. Time each one. Note what feels off.
2. Fix any UI jank that shows up on camera.
3. Record voiceover as a separate audio file. Multiple takes per beat.
4. Pre-warm the backend (Railway cold start kills the first request).

**Tasks (afternoon):**

5. Screen recording in OBS or ScreenStudio. 1080p60.
6. Multiple takes of each act. Pick the best.
7. Edit in DaVinci Resolve or CapCut. Pace, voiceover sync, music bed.
8. Render final video. Watch it twice. Fix anything jarring.
9. Upload to YouTube as unlisted. Test the link.

**Tasks (evening, backups):**

10. Save a local copy of the final video to a USB drive and to Google Drive.
11. Stand up a backup backend deploy on Fly.io or a second Railway service. Test that the frontend can be pointed at it via env var.
12. Pre-take screenshots: chat in normal state, chat during chaos, control panel close-up, TrueFoundry dashboard. Save them all to the repo.
13. Capture a "canned" event stream as JSON. If the live backend dies during judging, the frontend can replay this fixture so the demo still works from a tab.
14. Write Devpost project description, lifting from market scan and demo script.

**End-of-day demo:** Watch the final video. If you are proud of it, ship it.

**Cut list:** Music is optional. Voiceover style matters more than music.

**Risks:** Demo breaks during recording. Mitigation: pre-warm backend, test all chaos toggles before recording, have a checklist taped to the monitor.

---

## Day 9, Wednesday May 28: Buffer + submit

**Why this matters:** Submitted by 10 AM PT. Anything not submitted does not count. This is not a coding day. This is a logistics day.

**Tasks (early morning, US time):**

1. Final check: backend up, frontend up, demo URL works, video plays.
2. Devpost submission: project name, tagline, description, video URL, GitHub URL, tech stack tags, challenge tags (TrueFoundry).
3. Flip GitHub repo to public.
4. Post on Twitter/X and LinkedIn with the video. Tag TrueFoundry.
5. Post in the hackathon Discord with the video.

**Tasks (after submission):**

6. Test submission as a logged-out user. Make sure everything is accessible.
7. Watch for early feedback. Be ready to respond to judge questions.

**Risks:** Time zone math. The deadline is 10 AM PT which is 1 PM ET. Set 3 alarms.

---

## What we cut first (the cut list)

In order. If we are behind, cut these in this sequence:

1. **Custom domain.** Use the Vercel default URL. Looks slightly less polished, costs nothing.
2. **Landing page polish.** One paragraph + a button is fine.
3. **Animations on the control panel.** Static state changes work.
4. **Real-time replay.** Replay can just rerun a fresh request with the same input.
5. **Three chaos failures.** Cut the rate limit one if needed. Two is still a strong story.
6. **Music in the video.** Pure voiceover is fine.
7. **README architecture diagram.** Link to the docs folder.
8. **Pretty event log component.** Plain text list is fine.

In order. If we are behind, **do not cut** these:

- The orchestration loop and event bus. These are the product.
- LLM failover. Without this, no demo.
- One MCP tool with chaos toggle. Need at least one to demo tool failure.
- Degraded mode prompt (even the deterministic fallback version).
- Control panel with model status and tool health visible. Otherwise the demo has no hero UI.
- The video. No video = no submission.

---

## Daily standup with myself

End of every day, answer four questions in `docs/06-decisions.md`:

1. What shipped today?
2. What slipped?
3. What did I learn that changes the plan?
4. What is the most important thing to ship tomorrow?

Five minutes. If you do not do this, the plan drifts and you do not notice.

---

## What can kill this plan

- **TrueFoundry account issues on Day 1.** Mitigation: do the signup immediately, before any code. If blocked, switch to OpenRouter as a temporary gateway and migrate when TrueFoundry is unlocked.
- **A deep technical rabbit hole.** Mitigation: when something is taking 2x its estimate, stop and ask "is there a simpler way that ships." Almost always yes.
- **Burnout on Day 5 or 6.** Mitigation: full day off if needed. A tired build is a buggy build. Day 9 is buffer specifically so we can take an unplanned day off.
- **A killer competitor surfaces in the Devpost gallery.** Ignore them. Build the plan.

---

## What "done" looks like at the end of each day

| Day | Definition of done                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | TrueFoundry confirmed with a real LLM call. Custom domain serves Next.js placeholder. Backend health endpoint returns 200. $20 cap configured.         |
| 2   | CLI runs an incident end-to-end with the runtime, prints events, fails over LLMs on command. First-token latency under 1.2s.                           |
| 3   | Three MCP tools work. Tool failure produces tool.circuit_open. Agent handles a tool failure in the CLI.                                                |
| 4   | curl + SSE consumer shows the full event stream from the deployed backend. Chaos endpoint works. Replay works.                                         |
| 5   | Browser at the deployed URL: type a question, see an answer streamed back.                                                                             |
| 6   | Browser shows the full control panel updating in real time during a run. Chaos toggles work in UI. JSON fixtures captured.                             |
| 7   | Degraded mode produces a believable "tool unavailable, here is what I know" response. Replay button works. Landing page is real. Polish pass complete. |
| 8   | Final video uploaded to YouTube unlisted. Backups in place. Screenshots ready. Devpost description drafted.                                            |
| 9   | Submission complete on Devpost before 10 AM PT.                                                                                                        |

If any day's "done" is not done, the next day starts by finishing it before anything new.

---

**Locked:** Yes
**Next doc:** 06-decisions.md (created empty, filled as we go)
