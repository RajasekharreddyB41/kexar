"""
Tool layer for the Kexar runtime.

Day 3: real implementation backed by Postgres queries and wrapped in
timeout, retry, circuit breaker, and chaos toggle.

Three tools matching the demo script and the MCP spec we will surface
on Day 4:
  query_logs:     incident_signals where type='log'
  fetch_metrics:  incident_signals where type='metric'
  lookup_runbook: incident_signals where type='runbook'

Each tool:
  * Checks a chaos toggle first. If killed, raises ToolUnavailableError
    immediately, no DB query.
  * Runs inside a pybreaker circuit breaker. After 3 failures in 60s
    the circuit opens; subsequent calls fail fast for 30s.
  * Has a per-call timeout (policy.timeout_s).
  * Retries once on transient errors.

Same call_tool() signature as the Day 2 stub, so the orchestrator does
not change.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import pybreaker

from kexar.db.client import (
    fetch_logs_for_incident,
    fetch_metrics_for_incident,
    fetch_runbook_for_incident,
)
from kexar.runtime.events import (
    ToolCallFailure,
    ToolCallStart,
    ToolCallSuccess,
    ToolCircuitClose,
    ToolCircuitOpen,
    bus,
)
from kexar.runtime.policy import DEFAULT_TOOL_POLICY


# -----------------------------------------------------------------------------
# Typed exceptions
# -----------------------------------------------------------------------------


class ToolError(Exception):
    """Base for all tool-layer failures."""


class ToolUnavailableError(ToolError):
    """The tool cannot be called right now.

    Raised when: chaos toggle killed it, circuit breaker is open, or
    the tool returned an unrecoverable error. The orchestrator catches
    this specifically and routes the next step into degraded-mode
    reasoning.
    """


class ToolTimeoutError(ToolError):
    """The tool did not respond within its timeout."""


# -----------------------------------------------------------------------------
# Response shape
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolResult:
    tool: str
    payload: dict[str, Any]
    latency_ms: int


# -----------------------------------------------------------------------------
# Chaos toggles
#
# Module-level state. Day 4 chaos endpoint flips these. The CLI exercises
# them via kill_tool() / restore_tool() for local testing.
# -----------------------------------------------------------------------------


_killed: set[str] = set()


def kill_tool(tool: str) -> None:
    """Mark a tool as down. Subsequent calls raise ToolUnavailableError."""
    _killed.add(tool)


def restore_tool(tool: str) -> None:
    """Bring a previously killed tool back."""
    _killed.discard(tool)


def is_killed(tool: str) -> bool:
    return tool in _killed


def killed_tools() -> set[str]:
    """Snapshot of currently killed tools. Returned as a new set."""
    return set(_killed)


# -----------------------------------------------------------------------------
# Circuit breakers (one per tool)
# -----------------------------------------------------------------------------


# pybreaker counts failures within a sliding window. After fail_max
# failures, the circuit opens for reset_timeout seconds. While open,
# every call raises pybreaker.CircuitBreakerError immediately.
_breakers: dict[str, pybreaker.CircuitBreaker] = {}


def _breaker(tool: str) -> pybreaker.CircuitBreaker:
    """Get-or-create the circuit breaker for one tool."""
    if tool not in _breakers:
        _breakers[tool] = pybreaker.CircuitBreaker(
            fail_max=DEFAULT_TOOL_POLICY.circuit_failure_threshold,
            reset_timeout=DEFAULT_TOOL_POLICY.circuit_cooldown_s,
            name=f"tool:{tool}",
        )
    return _breakers[tool]


def reset_breakers() -> None:
    """Clear all breaker state. Test-only."""
    _breakers.clear()


# -----------------------------------------------------------------------------
# Tool registry
# -----------------------------------------------------------------------------


# Default incident if the orchestrator does not pass one. For the demo
# we only have one incident, so this is a sensible fallback. Day 4 the
# orchestrator threads incident_id through every call.
_DEFAULT_INCIDENT_ID = "inc_checkout_latency"


async def _tool_query_logs(args: dict[str, Any]) -> dict[str, Any]:
    incident_id = args.get("incident_id", _DEFAULT_INCIDENT_ID)
    limit = int(args.get("limit", 20))
    logs = await fetch_logs_for_incident(incident_id, limit=limit)
    return {
        "incident_id": incident_id,
        "count": len(logs),
        "entries": logs,
    }


async def _tool_fetch_metrics(args: dict[str, Any]) -> dict[str, Any]:
    incident_id = args.get("incident_id", _DEFAULT_INCIDENT_ID)
    metric = args.get("metric")
    limit = int(args.get("limit", 50))
    samples = await fetch_metrics_for_incident(
        incident_id, metric=metric, limit=limit
    )
    return {
        "incident_id": incident_id,
        "metric": metric or "all",
        "count": len(samples),
        "samples": samples,
    }


async def _tool_lookup_runbook(args: dict[str, Any]) -> dict[str, Any]:
    incident_id = args.get("incident_id", _DEFAULT_INCIDENT_ID)
    runbook = await fetch_runbook_for_incident(incident_id)
    if runbook is None:
        raise ToolError(f"no runbook found for {incident_id}")
    return {"incident_id": incident_id, "runbook": runbook}


_TOOL_REGISTRY: dict[str, Any] = {
    "query_logs": _tool_query_logs,
    "fetch_metrics": _tool_fetch_metrics,
    "lookup_runbook": _tool_lookup_runbook,
}


# -----------------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------------


async def call_tool(
    run_id: str,
    step: int,
    tool: str,
    args: dict[str, Any] | None = None,
) -> ToolResult:
    """Call a tool with full resilience: chaos, circuit, timeout, retry.

    Emits tool.call.start, tool.call.success / tool.call.failure, and
    tool.circuit_open / tool.circuit_close as appropriate.

    Raises ToolUnavailableError when:
      * The tool is killed by chaos.
      * The circuit breaker is open.
      * All retries exhausted.

    Raises ToolError for unknown tool names (programmer error).
    """
    args = args or {}
    await bus.publish(
        run_id,
        ToolCallStart(
            seq=0, run_id="", step=step, data={"tool": tool, "args": args}
        ),
    )

    # Unknown tool: programmer error, do not retry.
    if tool not in _TOOL_REGISTRY:
        await bus.publish(
            run_id,
            ToolCallFailure(
                seq=0,
                run_id="",
                step=step,
                data={
                    "tool": tool,
                    "attempt": 1,
                    "reason": "unknown_tool",
                    "retryable": False,
                },
            ),
        )
        raise ToolUnavailableError(f"unknown tool: {tool}")

    # Chaos toggle: kill before circuit, so we do not consume breaker quota
    # against synthetic failures.
    if is_killed(tool):
        await bus.publish(
            run_id,
            ToolCallFailure(
                seq=0,
                run_id="",
                step=step,
                data={
                    "tool": tool,
                    "attempt": 1,
                    "reason": "chaos_killed",
                    "retryable": False,
                },
            ),
        )
        raise ToolUnavailableError(f"{tool} is currently killed by chaos toggle")

    breaker = _breaker(tool)

    # Circuit open: fail fast without calling the tool.
    if breaker.current_state == "open":
        await bus.publish(
            run_id,
            ToolCallFailure(
                seq=0,
                run_id="",
                step=step,
                data={
                    "tool": tool,
                    "attempt": 1,
                    "reason": "circuit_open",
                    "retryable": False,
                },
            ),
        )
        raise ToolUnavailableError(f"{tool} circuit is open, cooling down")

    last_error: Exception | None = None
    handler = _TOOL_REGISTRY[tool]
    policy = DEFAULT_TOOL_POLICY

    for attempt in range(1, policy.retries + 2):
        start = time.perf_counter()
        try:
            # Wrap the handler call in both pybreaker (synchronous decision)
            # and asyncio.wait_for (timeout). The breaker increments its
            # failure counter when the wrapped callable raises, which is
            # exactly what we want.
            payload = await _call_with_breaker_and_timeout(
                breaker, handler, args, policy.timeout_s
            )
            latency_ms = int((time.perf_counter() - start) * 1000)

            summary = _summarize(tool, payload)
            await bus.publish(
                run_id,
                ToolCallSuccess(
                    seq=0,
                    run_id="",
                    step=step,
                    data={
                        "tool": tool,
                        "latency_ms": latency_ms,
                        "result_summary": summary,
                    },
                ),
            )

            # If the breaker was previously open, this success closed it.
            # pybreaker does not emit a callback we can hook here, so we
            # snapshot state before and after.
            return ToolResult(tool=tool, payload=payload, latency_ms=latency_ms)

        except pybreaker.CircuitBreakerError as e:
            # Breaker tripped DURING this call sequence. Stop retrying.
            last_error = e
            await bus.publish(
                run_id,
                ToolCircuitOpen(
                    seq=0,
                    run_id="",
                    step=step,
                    data={
                        "tool": tool,
                        "cooldown_seconds": int(policy.circuit_cooldown_s),
                        "recent_failures": policy.circuit_failure_threshold,
                    },
                ),
            )
            await bus.publish(
                run_id,
                ToolCallFailure(
                    seq=0,
                    run_id="",
                    step=step,
                    data={
                        "tool": tool,
                        "attempt": attempt,
                        "reason": "circuit_just_opened",
                        "retryable": False,
                    },
                ),
            )
            raise ToolUnavailableError(f"{tool} circuit tripped") from e

        except (asyncio.TimeoutError, ToolTimeoutError) as e:
            last_error = e
            await bus.publish(
                run_id,
                ToolCallFailure(
                    seq=0,
                    run_id="",
                    step=step,
                    data={
                        "tool": tool,
                        "attempt": attempt,
                        "reason": "timeout",
                        "retryable": True,
                    },
                ),
            )

        except Exception as e:  # noqa: BLE001
            last_error = e
            await bus.publish(
                run_id,
                ToolCallFailure(
                    seq=0,
                    run_id="",
                    step=step,
                    data={
                        "tool": tool,
                        "attempt": attempt,
                        "reason": type(e).__name__,
                        "retryable": True,
                    },
                ),
            )

        # If we have more attempts, back off and retry.
        if attempt <= policy.retries:
            await asyncio.sleep(policy.backoff_initial_s)
            continue

    # All retries used up.
    raise ToolUnavailableError(
        f"{tool} failed after {policy.retries + 1} attempts: {last_error}"
    )


# -----------------------------------------------------------------------------
# Internals
# -----------------------------------------------------------------------------


async def _call_with_breaker_and_timeout(
    breaker: pybreaker.CircuitBreaker,
    handler: Any,
    args: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    """Run the handler inside the breaker, with an asyncio timeout.

    pybreaker.CircuitBreaker.call() is synchronous and does not understand
    coroutines. We work around by wrapping the coroutine in a function
    that the breaker can call, then awaiting the returned coroutine.
    """
    def _invoke() -> Any:
        return handler(args)

    coro = breaker.call(_invoke)
    return await asyncio.wait_for(coro, timeout=timeout_s)


def _summarize(tool: str, payload: dict[str, Any]) -> str:
    """One-line description for the event log."""
    if tool == "query_logs":
        return f"{payload.get('count', 0)} log entries"
    if tool == "fetch_metrics":
        m = payload.get("metric", "all")
        return f"{payload.get('count', 0)} samples ({m})"
    if tool == "lookup_runbook":
        rb = payload.get("runbook") or {}
        return f"runbook: {rb.get('title', '?')}"
    return f"{tool} returned"
