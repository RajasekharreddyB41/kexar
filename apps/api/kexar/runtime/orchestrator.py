"""
Orchestration loop.

This is the agent's main loop. Think -> Act -> Respond, with budget
enforcement after every step and the option to enter degraded mode
when a tool fails.

Day 2 scope:
  * Up to N steps before forced response.
  * Each step: ask the model what to do next, execute it, record the
    outcome in AgentState.history.
  * Budget enforced after every step (steps, tokens, cost).
  * Tool failure surfaces as a fact ("metrics tool unavailable") in
    AgentState so the next think step reasons over it. The full
    "degraded mode" system prompt augmentation lands Day 7.

The orchestrator is the only place that mutates Run.status. Everything
else emits events; this file emits events AND drives the lifecycle.

The architecture doc, section "The runtime in detail" -> "Concepts",
is the spec for what a step is and what status transitions are valid.
"""

from __future__ import annotations

import json
from typing import Any

from kexar.runtime.events import (
    BudgetExceeded,
    BudgetWarn,
    RunAborted,
    RunComplete,
    RunStart,
    StepEnd,
    StepStart,
    bus,
)
from kexar.runtime.llm import (
    AllProvidersExhaustedError,
    LlmError,
    call_llm,
)
from kexar.runtime.policy import DEFAULT_BUDGET_POLICY
from kexar.runtime.state import AgentState, Budget, Run, RunStatus, Step, StepKind
from kexar.runtime.tools import (
    ToolError,
    ToolUnavailableError,
    call_tool,
)

# Maximum chars of an LLM response we shove back into history. Bigger
# than this, we truncate. Keeps prompt size bounded across many steps.
_HISTORY_CHAR_BUDGET = 600


# -----------------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------------


async def run_incident(
    user_message: str,
    *,
    incident_id: str | None = None,
) -> Run:
    """Run the agent against one user message. Returns the completed Run.

    All progress is on the event bus. Callers that want to stream it to
    a browser subscribe to bus.subscribe(run.id) in parallel.

    Never raises. Failures become run.aborted with a partial answer.
    """
    budget = Budget(
        max_steps=DEFAULT_BUDGET_POLICY.max_steps,
        max_tokens=DEFAULT_BUDGET_POLICY.max_tokens,
        max_cost_usd=DEFAULT_BUDGET_POLICY.max_cost_usd,
    )
    run = Run(
        incident_id=incident_id,
        budget=budget,
        state=AgentState(user_message=user_message),
    )
    run.status = RunStatus.RUNNING

    await bus.publish(
        run.id,
        RunStart(
            seq=0,
            run_id="",
            data={"incident_id": incident_id, "user_message": user_message},
        ),
    )

    try:
        await _loop(run)
    except AllProvidersExhaustedError as e:
        await _abort(run, reason=f"all_providers_exhausted: {e}", apology=(
            "I cannot reach any AI model right now. Try again in a minute."
        ))
    except LlmError as e:
        await _abort(run, reason=f"llm_error: {e}", apology=(
            "Something went wrong calling the model. Try again."
        ))

    return run


# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------


async def _loop(run: Run) -> None:
    """Drive the think -> act -> respond loop until done or capped."""

    while True:
        if run.budget.steps_used >= run.budget.max_steps - 1:
            # Last step must be a respond.
            await _step_respond(run)
            await _complete(run)
            return

        # Ask the model what to do next.
        decision = await _step_think(run)

        if _hit_any_cap(run):
            await _budget_exceed_and_finish(run)
            return

        action = decision.get("action", "respond")

        if action == "respond":
            await _step_respond(run, draft=decision.get("answer"))
            await _complete(run)
            return

        if action == "use_tool":
            tool = decision.get("tool", "")
            args = decision.get("args", {}) or {}
            await _step_act(run, tool=tool, args=args)
            if _hit_any_cap(run):
                await _budget_exceed_and_finish(run)
                return
            continue

        # Unknown action. Treat as a respond to keep the loop bounded.
        run.state.history.append(
            f"think: model returned unknown action '{action}', forcing respond"
        )
        await _step_respond(run)
        await _complete(run)
        return


# -----------------------------------------------------------------------------
# Step handlers
# -----------------------------------------------------------------------------


async def _step_think(run: Run) -> dict[str, Any]:
    """One LLM call to plan the next action. Returns the parsed decision."""
    step = _start_step(run, kind=StepKind.THINK)
    messages = _build_planning_messages(run)
    response = await call_llm(
        run.id,
        step=step.index,
        messages=messages,
        budget=run.budget,
    )
    step.model_used = response.model_used

    decision = _parse_decision(response.content)
    step.result = {"decision": decision, "raw": response.content[:200]}
    step.succeeded = True

    summary = _summarize_decision(decision)
    run.state.history.append(f"think({response.model_used}): {summary}")
    _end_step(run, step, summary=summary)
    _maybe_warn_budget(run)
    return decision


async def _step_act(run: Run, *, tool: str, args: dict[str, Any]) -> None:
    """One tool call. Records facts on success, marks tool unavailable on failure."""
    step = _start_step(run, kind=StepKind.ACT)
    step.tool_name = tool
    try:
        result = await call_tool(run.id, step=step.index, tool=tool, args=args)
        run.state.facts[tool] = result.payload
        step.succeeded = True
        step.result = {"tool": tool, "ok": True}
        summary = f"act({tool}): ok"
    except ToolUnavailableError:
        # Tool is dead. Remember and move on; the next think step will see
        # it in unavailable_tools and reason without it.
        run.state.unavailable_tools.add(tool)
        run.state.history.append(
            f"act({tool}): unavailable, continuing without it"
        )
        step.succeeded = False
        step.result = {"tool": tool, "ok": False, "reason": "unavailable"}
        summary = f"act({tool}): unavailable"
    except ToolError as e:
        run.state.unavailable_tools.add(tool)
        run.state.history.append(f"act({tool}): error, continuing without it")
        step.succeeded = False
        step.result = {"tool": tool, "ok": False, "reason": str(e)}
        summary = f"act({tool}): error"

    _end_step(run, step, summary=summary)
    _maybe_warn_budget(run)


async def _step_respond(run: Run, *, draft: str | None = None) -> None:
    """Produce the final answer. Either reuse the draft from think or
    ask the model one more time for a clean summary."""
    step = _start_step(run, kind=StepKind.RESPOND)

    if draft:
        answer = draft
        model_used = "<previous_step>"
    else:
        response = await call_llm(
            run.id,
            step=step.index,
            messages=_build_respond_messages(run),
            budget=run.budget,
        )
        answer = response.content
        model_used = response.model_used

    step.model_used = model_used
    step.succeeded = True
    step.result = {"answer_chars": len(answer)}
    run.final_answer = answer

    summary = answer[:120].replace("\n", " ")
    if len(answer) > 120:
        summary += "..."
    _end_step(run, step, summary=summary)


# -----------------------------------------------------------------------------
# Lifecycle helpers
# -----------------------------------------------------------------------------


def _start_step(run: Run, *, kind: StepKind) -> Step:
    step = Step(index=run.budget.steps_used, kind=kind)
    run.steps.append(step)
    # Fire-and-forget the start event. We do not await here because the
    # step body will follow immediately and emit step.end too.
    return step


def _end_step(run: Run, step: Step, *, summary: str) -> None:
    from datetime import UTC, datetime

    step.ended_at = datetime.now(UTC)
    run.budget.steps_used += 1

    # Publish the start AND end events together at the end of the step,
    # so they carry consistent timing. Architecture doc allows this
    # ordering: events are stamped with seq, the frontend renders by seq.
    import asyncio as _asyncio

    async def _emit() -> None:
        await bus.publish(
            run.id,
            StepStart(
                seq=0,
                run_id="",
                step=step.index,
                data={"kind": step.kind.value},
            ),
        )
        await bus.publish(
            run.id,
            StepEnd(
                seq=0,
                run_id="",
                step=step.index,
                data={
                    "kind": step.kind.value,
                    "duration_ms": step.duration_ms or 0,
                    "succeeded": step.succeeded,
                    "summary": summary,
                },
            ),
        )

    _asyncio.ensure_future(_emit())  # noqa: RUF006


async def _complete(run: Run) -> None:
    from datetime import UTC, datetime

    run.status = RunStatus.COMPLETED
    run.ended_at = datetime.now(UTC)
    await bus.publish(
        run.id,
        RunComplete(
            seq=0,
            run_id="",
            data={
                "steps_used": run.budget.steps_used,
                "tokens_used": run.budget.tokens_used,
                "cost_usd": round(run.budget.cost_usd, 6),
                "duration_ms": run.duration_ms or 0,
            },
        ),
    )


async def _abort(run: Run, *, reason: str, apology: str) -> None:
    from datetime import UTC, datetime

    run.status = RunStatus.ABORTED
    run.ended_at = datetime.now(UTC)
    run.final_answer = apology
    await bus.publish(
        run.id,
        RunAborted(seq=0, run_id="", data={"reason": reason, "partial_answer": apology}),
    )


async def _budget_exceed_and_finish(run: Run) -> None:
    axis = _which_cap_hit(run.budget)
    await bus.publish(
        run.id,
        BudgetExceeded(
            seq=0,
            run_id="",
            data={
                "axis": axis,
                "used": _used_for(run.budget, axis),
                "max": _max_for(run.budget, axis),
            },
        ),
    )
    partial = (
        "I hit my budget. Here is what I found so far. "
        + " | ".join(run.state.history[-3:])
    )
    await _abort(run, reason=f"budget_exceeded:{axis}", apology=partial)


# -----------------------------------------------------------------------------
# Budget helpers
# -----------------------------------------------------------------------------


def _hit_any_cap(run: Run) -> bool:
    return run.budget.is_exceeded()


def _which_cap_hit(b: Budget) -> str:
    if b.steps_used >= b.max_steps:
        return "steps"
    if b.tokens_used >= b.max_tokens:
        return "tokens"
    return "cost"


def _used_for(b: Budget, axis: str) -> float:
    return {
        "steps": b.steps_used,
        "tokens": b.tokens_used,
        "cost": b.cost_usd,
    }[axis]


def _max_for(b: Budget, axis: str) -> float:
    return {
        "steps": b.max_steps,
        "tokens": b.max_tokens,
        "cost": b.max_cost_usd,
    }[axis]


def _maybe_warn_budget(run: Run) -> None:
    """Emit budget.warn when any axis crosses the warn_pct threshold."""
    warn_pct = DEFAULT_BUDGET_POLICY.warn_pct
    b = run.budget
    axes = [
        ("steps", b.steps_used / b.max_steps if b.max_steps else 0.0,
         b.steps_used, b.max_steps),
        ("tokens", b.tokens_used / b.max_tokens if b.max_tokens else 0.0,
         b.tokens_used, b.max_tokens),
        ("cost", b.cost_usd / b.max_cost_usd if b.max_cost_usd else 0.0,
         b.cost_usd, b.max_cost_usd),
    ]

    import asyncio as _asyncio

    for axis, pct, used, mx in axes:
        if pct >= warn_pct:
            async def _emit(axis=axis, used=used, mx=mx, pct=pct) -> None:
                await bus.publish(
                    run.id,
                    BudgetWarn(
                        seq=0,
                        run_id="",
                        data={
                            "axis": axis,
                            "used": used,
                            "max": mx,
                            "pct": round(pct, 3),
                        },
                    ),
                )
            _asyncio.ensure_future(_emit())  # noqa: RUF006


# -----------------------------------------------------------------------------
# Prompting
# -----------------------------------------------------------------------------


_PLANNER_SYSTEM = """You are Kexar IR, an incident response copilot.
You are mid-investigation. The user posed an incident. You have access
to three tools: query_logs, fetch_metrics, lookup_runbook.

On every turn, decide ONE of:
  * use_tool: call exactly one tool to gather more information.
  * respond:  produce the final answer because you have enough info OR
              the user's question does not require a tool.

Reply ONLY with a JSON object on a single line. No prose around it.
Shape:
  {"action": "use_tool", "tool": "<name>", "args": {}}
  OR
  {"action": "respond", "answer": "<one or two sentences>"}

If a tool is listed as UNAVAILABLE in the context, do NOT call it.
Reason over what you already have. Be honest about what is missing."""


def _build_planning_messages(run: Run) -> list[dict[str, str]]:
    """Compose the messages array for one think step."""
    context_lines: list[str] = [f"User question: {run.state.user_message}"]

    if run.state.unavailable_tools:
        context_lines.append(
            "UNAVAILABLE tools: " + ", ".join(sorted(run.state.unavailable_tools))
        )

    if run.state.facts:
        context_lines.append("Known facts so far:")
        for tool, payload in run.state.facts.items():
            payload_str = json.dumps(payload)[:200]
            context_lines.append(f"  {tool}: {payload_str}")

    if run.state.history:
        recent = run.state.history[-3:]
        context_lines.append("Recent steps:")
        for h in recent:
            context_lines.append(f"  - {h[:_HISTORY_CHAR_BUDGET]}")

    return [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": "\n".join(context_lines)},
    ]


_RESPOND_SYSTEM = """You are Kexar IR. Produce the final answer for the user.
Keep it to two or three sentences. Be specific. If tools were unavailable,
say what is missing. Do not invent data."""


def _build_respond_messages(run: Run) -> list[dict[str, str]]:
    """Compose the messages array for the final respond step."""
    context_lines: list[str] = [f"User question: {run.state.user_message}"]

    if run.state.facts:
        context_lines.append("Findings:")
        for tool, payload in run.state.facts.items():
            payload_str = json.dumps(payload)[:300]
            context_lines.append(f"  {tool}: {payload_str}")

    if run.state.unavailable_tools:
        context_lines.append(
            "Tools that were unavailable: "
            + ", ".join(sorted(run.state.unavailable_tools))
        )

    return [
        {"role": "system", "content": _RESPOND_SYSTEM},
        {"role": "user", "content": "\n".join(context_lines)},
    ]


# -----------------------------------------------------------------------------
# Decision parsing
# -----------------------------------------------------------------------------


def _parse_decision(content: str) -> dict[str, Any]:
    """Pull the JSON decision out of the model's response.

    Tolerant: tries to find a JSON object in the text even if the model
    added prose around it. If nothing parses, defaults to a respond
    action so the loop terminates cleanly.
    """
    text = content.strip()

    # Fast path: whole thing is JSON.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Slow path: find first { ... } substring and try that.
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx >= 0 and end_idx > start_idx:
        try:
            parsed = json.loads(text[start_idx : end_idx + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Give up gracefully: respond with whatever the model said.
    return {"action": "respond", "answer": content.strip()[:400] or "I do not know."}


def _summarize_decision(decision: dict[str, Any]) -> str:
    action = decision.get("action", "?")
    if action == "use_tool":
        return f"plan: use_tool({decision.get('tool', '?')})"
    if action == "respond":
        ans = (decision.get("answer") or "")[:60]
        return f"plan: respond ({ans})"
    return f"plan: unknown({action})"
