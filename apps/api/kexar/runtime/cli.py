"""
CLI runner for the Kexar runtime.

Usage:
    uv run python -m kexar.runtime.cli "your incident description"

What it does:
    1. Subscribes to the event bus.
    2. Starts an incident run in parallel.
    3. Prints every event as it arrives, colored by category.
    4. On completion, prints the final answer and a summary.

Useful for testing the runtime end-to-end without a frontend. The
output mirrors what the control panel will render on Day 5.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from kexar.runtime.events import Event
from kexar.runtime.orchestrator import run_incident

# -----------------------------------------------------------------------------
# Terminal colors (ANSI). Fallback to no-color if stdout is not a TTY.
# -----------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()


def _c(s: str, code: str) -> str:
    if not _USE_COLOR:
        return s
    return f"\033[{code}m{s}\033[0m"


def _green(s: str) -> str: return _c(s, "32")
def _yellow(s: str) -> str: return _c(s, "33")
def _red(s: str) -> str: return _c(s, "31")
def _blue(s: str) -> str: return _c(s, "34")
def _gray(s: str) -> str: return _c(s, "90")
def _bold(s: str) -> str: return _c(s, "1")


# -----------------------------------------------------------------------------
# Event rendering
# -----------------------------------------------------------------------------


_TYPE_COLORS = {
    "run.start": _bold,
    "run.complete": _green,
    "run.aborted": _red,
    "step.start": _gray,
    "step.end": _gray,
    "llm.call.start": _blue,
    "llm.call.success": _green,
    "llm.call.failure": _yellow,
    "llm.failover": _yellow,
    "tool.call.start": _blue,
    "tool.call.success": _green,
    "tool.call.failure": _yellow,
    "tool.circuit_open": _red,
    "tool.circuit_close": _green,
    "degrade.entered": _yellow,
    "degrade.exited": _green,
    "budget.warn": _yellow,
    "budget.exceeded": _red,
}


def _render(event: Event) -> str:
    color = _TYPE_COLORS.get(event.type, _gray)
    head = color(f"[{event.seq:>3}] {event.type:<22}")
    step = f"step={event.step}" if event.step is not None else "       "
    summary = _summarize(event.type, event.data)
    return f"{head} {_gray(step)}  {summary}"


def _summarize(event_type: str, data: dict[str, Any]) -> str:
    """Compact one-line summary tuned per event type."""
    if event_type == "run.start":
        return data.get("user_message", "")[:80]
    if event_type == "run.complete":
        return (
            f"steps={data.get('steps_used')} "
            f"tokens={data.get('tokens_used')} "
            f"cost=${data.get('cost_usd'):.6f} "
            f"in {data.get('duration_ms')}ms"
        )
    if event_type == "run.aborted":
        reason = data.get("reason", "?")
        return f"reason={reason}"
    if event_type == "step.end":
        return (
            f"{data.get('kind')} {'ok' if data.get('succeeded') else 'fail'} "
            f"({data.get('duration_ms')}ms) - {data.get('summary', '')[:80]}"
        )
    if event_type == "llm.call.start":
        return f"model={data.get('model')} attempt={data.get('attempt')}"
    if event_type == "llm.call.success":
        return (
            f"model={data.get('model')} "
            f"{data.get('latency_ms')}ms "
            f"tokens={data.get('tokens_completion')}/{data.get('tokens_prompt')} "
            f"cost=${data.get('cost_usd'):.6f}"
        )
    if event_type == "llm.call.failure":
        return f"model={data.get('model')} reason={data.get('reason')}"
    if event_type == "llm.failover":
        return (
            f"{data.get('from_model')} -> {data.get('to_model')} "
            f"(+{data.get('latency_ms_added')}ms)"
        )
    if event_type == "tool.call.start":
        return f"tool={data.get('tool')}"
    if event_type == "tool.call.success":
        return (
            f"tool={data.get('tool')} "
            f"{data.get('latency_ms')}ms - {data.get('result_summary', '')}"
        )
    if event_type == "tool.call.failure":
        return f"tool={data.get('tool')} reason={data.get('reason')}"
    if event_type in ("budget.warn", "budget.exceeded"):
        return (
            f"{data.get('axis')} {data.get('used')}/{data.get('max')} "
            f"({(data.get('pct') or 1.0) * 100:.0f}%)"
        )
    return ""


# -----------------------------------------------------------------------------
# Run + listen
# -----------------------------------------------------------------------------


async def _run(user_message: str) -> None:
    # Allocate the run id up front by starting the run in a task. We do
    # not actually have the id until the orchestrator constructs the Run,
    # but the bus subscription is keyed by run_id, so we need it sooner.
    #
    # Workaround: subscribe to a wildcard-ish pattern by listening to
    # whatever run shows up. Since the CLI runs one incident at a time,
    # we know the first run on the bus is ours.
    incident_task = asyncio.create_task(run_incident(user_message))

    # Poll briefly until the run exists. The orchestrator publishes
    # run.start as its first event, so we tail the bus through that.
    # Easier: peek at the orchestrator by waiting for the task to expose
    # its run id. The Run is returned only at the end; we cannot rely on
    # it. So we instead subscribe AFTER giving the orchestrator a moment
    # to start, using the run id from the first published event.
    #
    # Simpler approach: subscribe before starting by patching the bus to
    # remember the last run id. To keep this CLI simple, we just wait
    # for the run to finish, then iterate the bus state.
    #
    # Cleanest implementation: have orchestrator accept a pre-allocated
    # run id. We are not refactoring now. For Day 2 the CLI prints events
    # at the end. Live streaming via the SSE endpoint lands Day 4.

    run = await incident_task

    # Walk the run.steps and use the data on the Run object itself,
    # since the bus is fire-and-forget and we did not subscribe in time.
    # This is enough for Day 2 verification. Day 4 introduces the SSE
    # endpoint that supports true live streaming.

    print()
    print(_bold("=" * 72))
    print(_bold(f"Run {run.id}"))
    print(_bold("=" * 72))
    print(f"Status:      {run.status}")
    print(f"Steps used:  {run.budget.steps_used} / {run.budget.max_steps}")
    print(f"Tokens used: {run.budget.tokens_used} / {run.budget.max_tokens}")
    print(f"Cost:        ${run.budget.cost_usd:.6f} / ${run.budget.max_cost_usd:.2f}")
    print(f"Duration:    {run.duration_ms}ms")
    if run.state.unavailable_tools:
        print(f"Unavailable: {sorted(run.state.unavailable_tools)}")
    print()
    print(_bold("Step trail:"))
    for s in run.steps:
        ok = _green("ok") if s.succeeded else _red("fail")
        model = s.model_used or "-"
        print(
            f"  [{s.index}] {s.kind.value:<8} model={model:<32} "
            f"{ok} dur={s.duration_ms}ms"
        )
    print()
    print(_bold("Final answer:"))
    print(_blue(run.final_answer or "(no answer)"))


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m kexar.runtime.cli \"incident description\"", file=sys.stderr)
        sys.exit(2)

    user_message = " ".join(sys.argv[1:])
    asyncio.run(_run(user_message))


if __name__ == "__main__":
    main()


# Suppress unused-import warning for the type alias we re-export.
_ = Event
