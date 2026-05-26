"""
FastAPI app entry point.

Lifecycle:
  startup:  initialize the asyncpg pool, log readiness.
  shutdown: close the pool.

Routes:
  GET  /                            human-friendly service info
  GET  /health                      Render health check
  POST /api/runs                    kick off a run, return run_id
  GET  /api/runs/{run_id}/events    SSE stream of events for that run

Day 4 in progress. Chaos endpoint and replay land in a follow-up commit.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from kexar.config import settings
from kexar.db.client import close_pool, get_pool
from kexar.runtime.events import bus
from kexar.runtime.orchestrator import run_incident
from kexar.runtime.state import Run

logger = logging.getLogger("kexar.api")
logging.basicConfig(level=settings.log_level)


# -----------------------------------------------------------------------------
# Lifespan: init the DB pool on startup, close on shutdown.
# -----------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup. If DATABASE_URL is missing or unreachable, fail loud here so
    # Render marks the deploy as failed instead of running a broken service.
    logger.info("Kexar API starting up")
    if not settings.database_url:
        logger.error("DATABASE_URL is not set; refusing to start")
        raise RuntimeError("DATABASE_URL is required")

    try:
        await get_pool()
        logger.info("DB pool initialized")
    except Exception:
        logger.exception("Failed to initialize DB pool")
        raise

    yield

    # Shutdown.
    logger.info("Kexar API shutting down")
    await close_pool()


app = FastAPI(
    title="Kexar API",
    description="Resilience runtime for production AI agents",
    version="0.2.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Tracking in-flight runs.
#
# We need this because POST /api/runs kicks off the orchestrator in a
# background task and returns the run_id immediately. The SSE endpoint
# then subscribes to that run_id on the bus. We also keep the Run
# objects briefly so the API can answer "did this run finish" later.
# -----------------------------------------------------------------------------


_in_flight: dict[str, asyncio.Task[Run]] = {}


def _track(task: asyncio.Task[Run], run_id: str) -> None:
    _in_flight[run_id] = task

    def _done(_t: asyncio.Task[Run]) -> None:
        # Drop the entry once the task finishes. The run is still in the
        # DB (Day 4 follow-up will persist), so we do not lose anything.
        _in_flight.pop(run_id, None)

    task.add_done_callback(_done)


# -----------------------------------------------------------------------------
# Request / response shapes
# -----------------------------------------------------------------------------


class StartRunRequest(BaseModel):
    user_message: str = Field(min_length=1, max_length=2000)
    incident_id: str | None = None


class StartRunResponse(BaseModel):
    run_id: str
    status: str


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "kexar-api",
        "status": "live",
        "version": app.version,
        "demo": "May 28, 2026",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    """Render polls this. Returns 200 when the process is alive AND the
    DB pool is initialized. If startup failed, this endpoint never serves."""
    return {"status": "ok"}


@app.post("/api/runs", response_model=StartRunResponse)
async def start_run(body: StartRunRequest) -> StartRunResponse:
    """Kick off a run. Returns immediately with the run_id.

    We pre-allocate the run_id here, kick the orchestrator off as a
    background task, and return the id without waiting for the run to
    finish. SSE subscribers can connect right away and tail events live.
    """
    from kexar.runtime.state import _new_run_id

    run_id = _new_run_id()

    async def _runner() -> Run:
        return await run_incident(
            body.user_message,
            incident_id=body.incident_id,
            run_id=run_id,
        )

    task = asyncio.create_task(_runner())
    _track(task, run_id)

    return StartRunResponse(run_id=run_id, status="running")


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request) -> EventSourceResponse:
    """Server-Sent Events stream of events for one run.

    Subscribes to the in-process bus and streams every event for the
    given run_id. Closes when the run emits run.complete or run.aborted,
    or when the client disconnects.
    """

    async def event_generator():
        async for event in bus.subscribe(run_id):
            # Client closed the tab; stop pushing.
            if await request.is_disconnected():
                break

            yield {
                "event": event.type,
                "id": str(event.seq),
                "data": event.model_dump_json(),
            }

            # Terminal events close the stream.
            if event.type in ("run.complete", "run.aborted"):
                break

    return EventSourceResponse(event_generator())


# -----------------------------------------------------------------------------
# Replay endpoint
#
# Re-streams a persisted run from runs.event_log over SSE with realistic
# inter-event timing. The frontend connects to this the same way it
# connects to the live stream and renders events identically.
#
# Why bother: gives us a deterministic, network-free fallback path if a
# live run fails on camera. Anyone can replay any past run by ID. The
# replay timing comes from the stored event.ts values, sped up so the
# demo does not drag.
#
# Speed factor and cap: 3x faster than wall-clock, max 1500ms between
# events. Tuned so a typical 8-step run replays in ~3-5 seconds, with
# enough breathing room that the user can see each event land.
# -----------------------------------------------------------------------------

_REPLAY_SPEED = 3.0       # divide deltas by this
_REPLAY_MAX_GAP_MS = 1500 # cap each inter-event sleep


@app.post("/api/runs/{run_id}/replay")
async def replay_run(run_id: str, request: Request) -> EventSourceResponse:
    """Stream a persisted run back to the client over SSE.

    404 if the run is not in Postgres. 409 if the run is in Postgres
    but its event_log is empty (run is still in progress or never
    completed). Otherwise streams every persisted event with timing
    derived from the stored timestamps.
    """
    from datetime import datetime

    from kexar.db.client import acquire

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, event_log FROM runs WHERE id = $1",
            run_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    events = row["event_log"]
    if not events:
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id} has no persisted event log",
        )

    async def event_generator():
        # Parse timestamps once so the sleep loop is tight.
        ts_list: list[float] = []
        for e in events:
            ts_str = e.get("ts")
            if not ts_str:
                ts_list.append(0.0)
                continue
            # Pydantic serialized datetime as ISO 8601 with timezone.
            try:
                ts_list.append(datetime.fromisoformat(ts_str).timestamp())
            except (ValueError, TypeError):
                ts_list.append(0.0)

        for i, event in enumerate(events):
            if await request.is_disconnected():
                break

            # Inter-event delay based on original timestamps.
            if i > 0 and ts_list[i] > 0 and ts_list[i - 1] > 0:
                delta_s = max(0.0, ts_list[i] - ts_list[i - 1])
                delay_ms = min(
                    int(delta_s * 1000 / _REPLAY_SPEED),
                    _REPLAY_MAX_GAP_MS,
                )
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000)

            yield {
                "event": event.get("type", "unknown"),
                "id": str(event.get("seq", i)),
                "data": json.dumps(event),
            }

            if event.get("type") in ("run.complete", "run.aborted"):
                break

    return EventSourceResponse(event_generator())


# -----------------------------------------------------------------------------
# Chaos endpoint
#
# Demo-only. Toggles a tool's kill state. The next time the runtime tries to
# call that tool, it raises ToolUnavailableError immediately and degraded
# mode kicks in. The demo UI calls this between user messages.
#
# Rate-limited via a simple token bucket so the public URL is not a DDoS
# vector. 30 calls/minute is generous for human-driven demo use.
# -----------------------------------------------------------------------------


class ChaosToggleRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    killed: bool


class ChaosToggleResponse(BaseModel):
    tool: str
    killed: bool
    currently_killed: list[str]


_chaos_bucket: dict[str, list[float]] = {"timestamps": []}
_CHAOS_LIMIT_PER_MIN = 30


def _check_chaos_rate_limit() -> None:
    """Drop timestamps older than 60s, refuse if over the limit."""
    import time

    now = time.monotonic()
    cutoff = now - 60.0
    ts = _chaos_bucket["timestamps"]
    while ts and ts[0] < cutoff:
        ts.pop(0)
    if len(ts) >= _CHAOS_LIMIT_PER_MIN:
        raise HTTPException(
            status_code=429,
            detail="chaos endpoint rate limit: 30 calls per minute",
        )
    ts.append(now)


@app.post("/api/demo/chaos", response_model=ChaosToggleResponse)
async def chaos_toggle(body: ChaosToggleRequest) -> ChaosToggleResponse:
    """Kill or restore a tool. Demo only."""
    _check_chaos_rate_limit()

    from kexar.runtime.tools import (
        kill_tool,
        killed_tools,
        restore_tool,
    )

    if body.killed:
        kill_tool(body.tool)
    else:
        restore_tool(body.tool)

    return ChaosToggleResponse(
        tool=body.tool,
        killed=body.killed,
        currently_killed=sorted(killed_tools()),
    )


# -----------------------------------------------------------------------------
# Local dev hook: print a route list for sanity.
# -----------------------------------------------------------------------------


@app.get("/_routes")
async def _list_routes() -> list[dict[str, Any]]:
    """Debug helper: list all routes. Disabled in production by simple env check."""
    if not settings.is_dev:
        raise HTTPException(status_code=404, detail="not found")
    out = []
    for r in app.routes:
        if hasattr(r, "methods") and hasattr(r, "path"):
            out.append({"path": r.path, "methods": sorted(r.methods)})
    return out
