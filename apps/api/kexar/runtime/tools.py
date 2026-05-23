"""
Tool layer.

Day 2: stub. One tool, always succeeds, returns a fixed payload. Lets us
write and exercise the orchestrator before MCP exists.

Day 3: replaced by call_tool_with_resilience() that wraps the real MCP
server with timeout, retry, and circuit breaker. Same signature.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from kexar.runtime.events import (
    ToolCallFailure,
    ToolCallStart,
    ToolCallSuccess,
    bus,
)

# -----------------------------------------------------------------------------
# Typed exceptions
# -----------------------------------------------------------------------------


class ToolError(Exception):
    """Base for all tool-layer failures."""


class ToolUnavailableError(ToolError):
    """The tool cannot be called right now.

    Day 2: never raised (stub always succeeds).
    Day 3: raised when the circuit is open, or when chaos controls killed
    the tool. The orchestrator catches this specifically and routes the
    next step into degraded-mode reasoning.
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
# Stub tool registry
# -----------------------------------------------------------------------------


# Hardcoded mock responses keyed by tool name. Realistic enough to support
# the orchestrator while we build it. Day 3 replaces this with real MCP
# tools backed by seeded Postgres data.
_STUB_RESPONSES: dict[str, dict[str, Any]] = {
    "query_logs": {
        "service": "checkout",
        "window": "02:10 to 02:30",
        "entries": [
            {"ts": "02:13:42", "level": "INFO", "msg": "Deploy 1f3a started"},
            {"ts": "02:13:58", "level": "INFO", "msg": "Deploy 1f3a complete"},
            {"ts": "02:14:11", "level": "WARN", "msg": "p99 latency 4200ms"},
        ],
    },
    "fetch_metrics": {
        "service": "checkout",
        "metric": "p99_latency_ms",
        "samples": [
            {"ts": "02:10", "value": 81},
            {"ts": "02:12", "value": 84},
            {"ts": "02:14", "value": 4231},
            {"ts": "02:16", "value": 4180},
        ],
    },
    "lookup_runbook": {
        "title": "Rollback a checkout deploy",
        "steps": [
            "Identify the bad deploy with `kubectl rollout history checkout`",
            "Run `kubectl rollout undo checkout`",
            "Verify p99 drops below 200ms within 60s",
        ],
    },
}


async def call_tool(
    run_id: str,
    step: int,
    tool: str,
    args: dict[str, Any] | None = None,
) -> ToolResult:
    """Call a tool. Day 2 stub implementation.

    Emits tool.call.start, then either tool.call.success or
    tool.call.failure depending on whether the tool is registered.

    Always succeeds for any tool in _STUB_RESPONSES. Raises
    ToolUnavailableError for unknown tools (so the orchestrator's
    degraded-mode handling is exercised by Day 2 tests).
    """
    args = args or {}
    await bus.publish(
        run_id,
        ToolCallStart(
            seq=0, run_id="", step=step, data={"tool": tool, "args": args}
        ),
    )

    start = time.perf_counter()

    if tool not in _STUB_RESPONSES:
        # Unknown tool. Treat as unavailable so the orchestrator's
        # degraded-mode path is reachable end-to-end on Day 2.
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

    # Simulate a small amount of work so latency numbers in the UI are
    # not all zero on Day 2.
    await asyncio.sleep(0.05)

    payload = _STUB_RESPONSES[tool]
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

    return ToolResult(tool=tool, payload=payload, latency_ms=latency_ms)


def _summarize(tool: str, payload: dict[str, Any]) -> str:
    """One-line description of the tool result for the event log."""
    if tool == "query_logs":
        n = len(payload.get("entries", []))
        return f"{n} log entries for {payload.get('service')}"
    if tool == "fetch_metrics":
        n = len(payload.get("samples", []))
        return f"{n} metric samples for {payload.get('service')}"
    if tool == "lookup_runbook":
        return f"runbook: {payload.get('title')}"
    return f"{tool} returned"
