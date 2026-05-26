"""
Run persistence to Postgres.

Subscribes to the event bus for one run, accumulates events as they
stream, writes the full event log to runs.event_log when the run
finishes (run.complete or run.aborted).

Design choices, all deliberate:

  * Side-channel subscriber, not in the orchestrator. The orchestrator
    publishes events; this module persists them. Single responsibility
    on both sides. Same pattern as the SSE endpoint.

  * Two DB writes per run, not N. INSERT at start with empty event_log,
    UPDATE at end with the accumulated array and final status. JSONB is
    cheap, the array is small (~10-70 events), and one bulk update
    beats N appends.

  * Fire-and-forget. If Postgres is down, the SSE stream still works.
    The run completes for the user. The log just is not persisted.
    That is the correct failure mode for the demo, where the user-facing
    path matters more than the audit trail.

  * Events are stored exactly as the bus stamps them (model_dump), so
    the replay endpoint can re-emit them byte-for-byte. The frontend
    cannot tell a replay from a live run.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from kexar.db.client import acquire
from kexar.runtime.events import bus

logger = logging.getLogger(__name__)

# Event types that end a run. Once we see one of these, we flush and exit.
_TERMINAL_TYPES = {"run.complete", "run.aborted"}


async def register_persistence(
    run_id: str, incident_id: str | None
) -> asyncio.Queue:
    """Set up persistence synchronously. Caller MUST await this before
    publishing the first event for the run.

    Two things happen here, both awaited so the caller knows persistence
    is ready when this returns:
      1. Register a subscriber queue with the bus. After this returns,
         any event published to run_id lands in this queue.
      2. INSERT the run row with status=running and empty event_log.

    Returns the queue. The orchestrator hands the queue to _consume(),
    which is spawned as a background task and drains the queue until a
    terminal event arrives.

    Why split this from the consume loop: bus.subscribe() registers the
    queue, but the actual iteration happens later. If we fire-and-forget
    the whole subscribe-and-consume, the bus.subscribe() call may not
    have registered the queue yet when RunStart is published, dropping
    the first event.
    """
    # Step 1: register queue with the bus. This is what closes the race.
    queue: asyncio.Queue = asyncio.Queue(maxsize=bus._queue_maxsize)  # noqa: SLF001
    async with bus._lock:  # noqa: SLF001
        bus._queues[run_id].append(queue)  # noqa: SLF001

    # Step 2: INSERT initial row. Best-effort; the consume task will
    # still flush even if this fails (UPDATE will be a no-op then).
    try:
        await _insert_run_row(run_id, incident_id)
    except Exception as e:
        logger.warning(
            "register_persistence: insert failed for %s: %s", run_id, e
        )

    return queue


async def _consume(run_id: str, queue: asyncio.Queue) -> None:
    """Background task. Drains the queue until a terminal event, then
    flushes the accumulated log to Postgres.

    Never raises: errors are logged and swallowed so the user-facing
    run is unaffected.
    """
    events: list[dict] = []
    final_status = "running"
    try:
        while True:
            event = await queue.get()
            events.append(event.model_dump(mode="json"))
            if event.type in _TERMINAL_TYPES:
                final_status = (
                    "completed" if event.type == "run.complete" else "aborted"
                )
                break
    except asyncio.CancelledError:
        logger.info("_consume: cancelled mid-stream for %s", run_id)
        await _flush_run(run_id, events, status="aborted")
        # Clean the subscriber out of the bus before re-raising.
        _detach_queue(run_id, queue)
        raise
    except Exception as e:
        logger.warning("_consume: loop failed for %s: %s", run_id, e)
        _detach_queue(run_id, queue)
        return

    _detach_queue(run_id, queue)
    await _flush_run(run_id, events, status=final_status)


def _detach_queue(run_id: str, queue: asyncio.Queue) -> None:
    """Remove our queue from the bus subscriber list. Mirrors the cleanup
    that bus.subscribe()'s finally block does for the normal async-iterator
    path."""
    queues = bus._queues.get(run_id, [])  # noqa: SLF001
    if queue in queues:
        queues.remove(queue)
    if not queues:
        bus._queues.pop(run_id, None)  # noqa: SLF001


async def _insert_run_row(run_id: str, incident_id: str | None) -> None:
    """Initial row with empty event_log and status=running."""
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO runs (id, incident_id, started_at, status, event_log)
            VALUES ($1, $2, $3, 'running', '[]'::jsonb)
            ON CONFLICT (id) DO NOTHING
            """,
            run_id,
            incident_id,
            datetime.now(UTC),
        )


async def _flush_run(
    run_id: str,
    events: list[dict],
    *,
    status: str,
) -> None:
    """Single UPDATE: event_log, status, ended_at. Best-effort, swallows
    DB errors so the run still appears successful to the user."""
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                UPDATE runs
                SET event_log = $1::jsonb,
                    status = $2,
                    ended_at = $3
                WHERE id = $4
                """,
                events,
                status,
                datetime.now(UTC),
                run_id,
            )
        logger.info(
            "_flush_run: flushed %d events for %s (status=%s)",
            len(events),
            run_id,
            status,
        )
    except Exception as e:
        logger.warning("_flush_run: flush failed for %s: %s", run_id, e)
