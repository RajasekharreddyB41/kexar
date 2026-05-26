"""
CLI runner for the Kexar runtime.

Usage:
    uv run python -m kexar.runtime.cli "incident description"
    uv run python -m kexar.runtime.cli "..." --kill fetch_metrics
    uv run python -m kexar.runtime.cli --kill query_logs --kill fetch_metrics "..."

What it does:
    1. Parses --kill <tool> flags (any order, any count).
    2. Kills those tools via the chaos toggle BEFORE the run starts.
    3. Runs the incident through the orchestrator.
    4. Prints status, step trail, and final answer.

Useful for testing the runtime end-to-end without a frontend. The
real-time SSE event stream lands Day 4 with the API endpoint.
"""

from __future__ import annotations

import asyncio
import sys

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
def _red(s: str) -> str: return _c(s, "31")
def _blue(s: str) -> str: return _c(s, "34")
def _bold(s: str) -> str: return _c(s, "1")


# -----------------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> tuple[str, list[str]]:
    """Pull --kill <tool> flags out of argv. Return (message, killed_tools).

    Order does not matter. Multiple --kill flags accumulate.
    """
    killed: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--kill":
            if i + 1 >= len(argv):
                print("--kill needs a tool name", file=sys.stderr)
                sys.exit(2)
            killed.append(argv[i + 1])
            i += 2
            continue
        rest.append(arg)
        i += 1
    return " ".join(rest), killed


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------


async def _run(user_message: str) -> None:
    run = await run_incident(user_message)

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


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------


async def _main_async(user_message: str, to_kill: list[str]) -> None:
    """Async body of main(). Single event loop so the DB pool is happy."""
    # Late imports so module loading does not require Postgres reachable.
    from kexar.db.client import close_pool
    from kexar.runtime.tools import kill_tool

    for t in to_kill:
        kill_tool(t)
        print(_red(f"[chaos] killed tool: {t}"))

    try:
        await _run(user_message)
    finally:
        # Wait for background tasks (e.g. persist_run flushing event log
        # to Postgres) BEFORE closing the pool. Without this, the pool
        # closes underneath the persist task and the UPDATE fails with
        # 'pool is closing'. Short timeout caps shutdown latency.
        pending = [
            t for t in asyncio.all_tasks() if t is not asyncio.current_task()
        ]
        if pending:
            await asyncio.wait(pending, timeout=3.0)
        await close_pool()


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: python -m kexar.runtime.cli "
            "[--kill <tool>]... \"incident description\"",
            file=sys.stderr,
        )
        sys.exit(2)

    user_message, to_kill = _parse_args(sys.argv[1:])
    if not user_message:
        print("missing incident description", file=sys.stderr)
        sys.exit(2)

    asyncio.run(_main_async(user_message, to_kill))


if __name__ == "__main__":
    main()
