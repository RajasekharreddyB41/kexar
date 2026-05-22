"""
Typed event bus for the Kexar runtime.

Every meaningful runtime moment is an event. Failures are events.
Successes are events. Budget warnings are events. Failures are not
exceptions in our code, they are first-class data the UI renders.

Design:
  * One bus per process. The bus is global because there is one runtime
    per backend instance and we are not building for horizontal scale.
  * Each subscriber gets its own asyncio.Queue. Slow consumers do not
    block fast ones.
  * Every event carries a monotonic seq number scoped to its run_id.
    The frontend renders by seq, not by arrival order.
  * Event types are a tagged union (discriminated by `type` field).
    Frontend TypeScript mirrors this discriminator exactly.

The event schema is locked. Architecture doc, "Event schema" section,
is the contract. Do not add a field without updating both ends.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# -----------------------------------------------------------------------------
# Event payload shapes.
#
# One class per event type. Each has a literal `type` discriminator and a
# `data` dict with fields specific to that event. The discriminator lets
# Pydantic and the frontend route events to the right handler.
# -----------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _EventBase(BaseModel):
    """Common envelope. Concrete events extend this with a literal type."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(description="Monotonic position within this run.")
    run_id: str
    ts: datetime = Field(default_factory=_utcnow)
    step: int | None = Field(
        default=None,
        description="Step index this event belongs to. None for run-level events.",
    )


# --- Step lifecycle ---------------------------------------------------------


class StepStart(_EventBase):
    type: Literal["step.start"] = "step.start"
    data: dict[str, Any] = Field(
        description="Keys: kind (think|act|respond)."
    )


class StepEnd(_EventBase):
    type: Literal["step.end"] = "step.end"
    data: dict[str, Any] = Field(
        description="Keys: kind, duration_ms, succeeded, summary (str)."
    )


# --- LLM calls --------------------------------------------------------------


class LlmCallStart(_EventBase):
    type: Literal["llm.call.start"] = "llm.call.start"
    data: dict[str, Any] = Field(
        description="Keys: model, attempt (1-indexed)."
    )


class LlmCallSuccess(_EventBase):
    type: Literal["llm.call.success"] = "llm.call.success"
    data: dict[str, Any] = Field(
        description="Keys: model, latency_ms, tokens_prompt, tokens_completion, "
                    "cost_usd."
    )


class LlmCallFailure(_EventBase):
    type: Literal["llm.call.failure"] = "llm.call.failure"
    data: dict[str, Any] = Field(
        description="Keys: model, attempt, reason (str), retryable (bool)."
    )


class LlmFailover(_EventBase):
    """Application-level failover. Emitted when we move from one model to
    the next in the cascade. Distinct from llm.call.failure because the
    UI renders these differently (failover is the headline event)."""

    type: Literal["llm.failover"] = "llm.failover"
    data: dict[str, Any] = Field(
        description="Keys: from_model, to_model, reason, latency_ms_added."
    )


# --- Tool calls -------------------------------------------------------------


class ToolCallStart(_EventBase):
    type: Literal["tool.call.start"] = "tool.call.start"
    data: dict[str, Any] = Field(description="Keys: tool, args (dict).")


class ToolCallSuccess(_EventBase):
    type: Literal["tool.call.success"] = "tool.call.success"
    data: dict[str, Any] = Field(
        description="Keys: tool, latency_ms, result_summary (str)."
    )


class ToolCallFailure(_EventBase):
    type: Literal["tool.call.failure"] = "tool.call.failure"
    data: dict[str, Any] = Field(
        description="Keys: tool, attempt, reason, retryable."
    )


class ToolCircuitOpen(_EventBase):
    type: Literal["tool.circuit_open"] = "tool.circuit_open"
    data: dict[str, Any] = Field(
        description="Keys: tool, cooldown_seconds, recent_failures."
    )


class ToolCircuitClose(_EventBase):
    type: Literal["tool.circuit_close"] = "tool.circuit_close"
    data: dict[str, Any] = Field(description="Keys: tool.")


# --- Degraded mode (the differentiator) -------------------------------------


class DegradeEntered(_EventBase):
    """Agent acknowledged one or more tools are unavailable and is
    reasoning without them. The control panel surfaces this prominently."""

    type: Literal["degrade.entered"] = "degrade.entered"
    data: dict[str, Any] = Field(
        description="Keys: unavailable_tools (list[str]), reason."
    )


class DegradeExited(_EventBase):
    """A previously unavailable tool came back and the agent can use it again."""

    type: Literal["degrade.exited"] = "degrade.exited"
    data: dict[str, Any] = Field(description="Keys: restored_tools (list[str]).")


# --- Budget -----------------------------------------------------------------


class BudgetWarn(_EventBase):
    """Soft warning fired at 80% utilization on any budget axis."""

    type: Literal["budget.warn"] = "budget.warn"
    data: dict[str, Any] = Field(
        description="Keys: axis (steps|tokens|cost), used, max, pct."
    )


class BudgetExceeded(_EventBase):
    type: Literal["budget.exceeded"] = "budget.exceeded"
    data: dict[str, Any] = Field(
        description="Keys: axis, used, max."
    )


# --- Run lifecycle ----------------------------------------------------------


class RunStart(_EventBase):
    type: Literal["run.start"] = "run.start"
    data: dict[str, Any] = Field(
        description="Keys: incident_id (optional), user_message."
    )


class RunComplete(_EventBase):
    type: Literal["run.complete"] = "run.complete"
    data: dict[str, Any] = Field(
        description="Keys: steps_used, tokens_used, cost_usd, duration_ms."
    )


class RunAborted(_EventBase):
    type: Literal["run.aborted"] = "run.aborted"
    data: dict[str, Any] = Field(
        description="Keys: reason, partial_answer (optional)."
    )


# -----------------------------------------------------------------------------
# Tagged union. Use this for type hints anywhere an event may be any of the
# concrete types. Pydantic discriminates on the `type` field.
# -----------------------------------------------------------------------------

Event = (
    StepStart
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
    | RunAborted
)


# -----------------------------------------------------------------------------
# In-process event bus.
#
# Multiple subscribers per run. Each gets a queue. publish() fans out.
# Slow subscribers (e.g. a stalled SSE connection) get their own buffer
# and do not block other subscribers or the publisher itself.
# -----------------------------------------------------------------------------


class EventBus:
    """One bus, many subscribers per run.

    Usage:
        bus = EventBus()
        async for ev in bus.subscribe(run_id):
            handle(ev)

        # elsewhere
        await bus.publish(run_id, LlmFailover(...))

    The seq counter is per-run and monotonic. Callers pass partially-formed
    events without `seq`; the bus stamps it before publishing. This keeps
    seq generation in one place.
    """

    def __init__(self, queue_maxsize: int = 1024) -> None:
        self._queues: dict[str, list[asyncio.Queue[Event]]] = defaultdict(list)
        self._seq: dict[str, int] = defaultdict(int)
        self._queue_maxsize = queue_maxsize
        self._lock = asyncio.Lock()

    async def publish(self, run_id: str, event: Event) -> Event:
        """Fan an event out to all current subscribers of this run.

        Stamps the event with the next seq for this run. Returns the stamped
        event so callers can also persist it.

        Drops events to slow subscribers (queue full) rather than blocking
        the publisher. Slow consumers reconnect via the replay endpoint.
        """
        async with self._lock:
            self._seq[run_id] += 1
            seq = self._seq[run_id]
            stamped = event.model_copy(update={"seq": seq, "run_id": run_id})
            queues = list(self._queues.get(run_id, ()))

        for q in queues:
            # Drop on the floor if the subscriber is too slow. The SSE
            # endpoint will reconnect via replay if needed. Production
            # system would log a counter here.
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(stamped)

        return stamped

    async def subscribe(self, run_id: str) -> AsyncIterator[Event]:
        """Async iterator over events for a run.

        Yields events as they are published. The subscriber gets its own
        bounded queue. Cancel the iterator (e.g. by closing the SSE
        connection) to clean up.
        """
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_maxsize)
        async with self._lock:
            self._queues[run_id].append(q)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            async with self._lock:
                if q in self._queues.get(run_id, []):
                    self._queues[run_id].remove(q)
                if not self._queues[run_id]:
                    del self._queues[run_id]

    def reset_run(self, run_id: str) -> None:
        """Drop all subscribers and seq state for a run. Test-only.

        Production never calls this; runs are append-only and the seq
        counter is reset implicitly when the bus process restarts.
        """
        self._queues.pop(run_id, None)
        self._seq.pop(run_id, None)


# Module-level singleton. The runtime, the API layer, and the DB writer
# all import this. One bus, one process.
bus = EventBus()
