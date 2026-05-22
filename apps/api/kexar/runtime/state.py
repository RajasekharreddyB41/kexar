"""
Typed state for the Kexar runtime.

These classes are the in-memory shape of a run. The event log persisted
to Postgres is a separate concern (see events.py). This module is pure
types - no I/O, no side effects, no DB.

The architecture doc, section "The runtime in detail", is the source of
truth for what each of these represents. Keep them in sync.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    """Timezone-aware UTC now. Naive datetimes are forbidden."""
    return datetime.now(UTC)


def _new_run_id() -> str:
    """Short, URL-safe run identifier. Used in API paths and SSE channels."""
    return f"run_{uuid4().hex[:16]}"


class RunStatus(StrEnum):
    """Lifecycle states for a run.

    PENDING:   created, not yet started.
    RUNNING:   orchestrator loop is active.
    COMPLETED: orchestrator returned a final answer to the user.
    ABORTED:   stopped early (budget exceeded, all LLMs failed, etc).
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"


class StepKind(StrEnum):
    """What a single step does.

    THINK:   one LLM call to plan or analyze.
    ACT:     one tool call (MCP).
    RESPOND: produce the final answer for the user.
    """

    THINK = "think"
    ACT = "act"
    RESPOND = "respond"


class Step(BaseModel):
    """One iteration of the orchestration loop.

    Steps are append-only. A Step is created when work starts and mutated
    to record the outcome (succeeded / failed / fallback_used). The runtime
    emits events for each transition.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    index: int = Field(description="Zero-indexed position in the run.")
    kind: StepKind
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None

    # Filled in by the kind-specific handler.
    model_used: str | None = Field(
        default=None,
        description="Model identifier the gateway returned a response from. "
                    "Differs from the requested model if failover happened.",
    )
    tool_name: str | None = Field(
        default=None,
        description="MCP tool name, only set when kind == ACT.",
    )
    succeeded: bool = False

    # Free-form result. Kept as dict so we can shape it per step kind without
    # a hierarchy of subclasses. The event log is the strongly-typed surface.
    result: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_ms(self) -> int | None:
        """Wall-clock duration of the step, or None if still running."""
        if self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds() * 1000)


class Budget(BaseModel):
    """Per-run hard caps and live counters.

    Caps come from config (KEXAR_MAX_*). The runtime increments counters
    after every LLM call and tool call. When any counter exceeds its cap,
    the orchestrator emits budget.exceeded and aborts.
    """

    model_config = ConfigDict(extra="forbid")

    # Caps (set once at run start, never mutated).
    max_steps: int
    max_tokens: int
    max_cost_usd: float

    # Counters (mutated as the run progresses).
    steps_used: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0

    def is_exceeded(self) -> bool:
        """Whether any cap has been hit. Checked after each step."""
        return (
            self.steps_used >= self.max_steps
            or self.tokens_used >= self.max_tokens
            or self.cost_usd >= self.max_cost_usd
        )

    def remaining_steps(self) -> int:
        return max(0, self.max_steps - self.steps_used)


class AgentState(BaseModel):
    """What the agent knows during a run.

    This is the working context passed into each LLM call. It accumulates
    as steps complete. Kept small on purpose - prompt size is a real cost.

    user_message: the original request that kicked off the run.
    history:      transcript of think/act/respond steps for the agent to
                  reason over. Each entry is a short string, not a Step.
                  Keeps prompt size predictable.
    facts:        structured findings the agent has accumulated (e.g.
                  parsed log entries, metric values, runbook excerpts).
                  Survives even if the source tool later goes down -
                  this is what enables degraded-mode responses.
    unavailable_tools: tools the agent has been told it cannot use right
                  now. The orchestrator augments the system prompt with
                  this list so the model knows what is off-limits.
    """

    model_config = ConfigDict(extra="forbid")

    user_message: str
    history: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    unavailable_tools: set[str] = Field(default_factory=set)


class Run(BaseModel):
    """One end-to-end execution of the agent for one user message.

    A Run is the top-level container. It owns the budget, the agent state,
    and the list of completed steps. The event log lives on the event bus
    and is persisted separately - it is not duplicated here.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_run_id)
    incident_id: str | None = Field(
        default=None,
        description="Set when the run is tied to a seeded incident. "
                    "Null for ad-hoc runs.",
    )
    status: RunStatus = RunStatus.PENDING
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None

    budget: Budget
    state: AgentState
    steps: list[Step] = Field(default_factory=list)

    # The final answer sent to the user. None until the run completes or
    # aborts. On abort, this holds the apology / partial answer.
    final_answer: str | None = None

    @property
    def duration_ms(self) -> int | None:
        """Wall-clock duration of the run."""
        if self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds() * 1000)

    def is_terminal(self) -> bool:
        """Whether the run can no longer make progress."""
        return self.status in (RunStatus.COMPLETED, RunStatus.ABORTED)
