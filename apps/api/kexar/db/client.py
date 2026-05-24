"""
Async database client for the Kexar runtime.

One asyncpg connection pool per process. Singleton, lazy-initialized
on first use, closed on process shutdown.

Everything that talks to Postgres goes through here:
  * MCP tools (query_logs, fetch_metrics, lookup_runbook) on Day 3
  * Run persistence and event log writes on Day 4
  * Replay queries on Day 4

Why a pool, not connection-per-query:
  * asyncpg connects in ~50-100ms. Per-query that adds up fast.
  * Pool keeps a handful of connections warm.
  * Free Render Postgres caps at ~97 connections; pool of 5-10 is safe.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from kexar.config import settings


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Run once per new pool connection.

    Registers a JSONB codec so JSONB columns come back as parsed Python
    dicts, not raw JSON strings. Without this, payload->>"key" works
    but row["payload"] is a string and you have to json.loads() it.
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


# Module-level state. Reset only via close_pool() (tests / shutdown).
_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    """Return the shared connection pool, creating it on first call.

    Thread-safe via asyncio lock so two coroutines starting at the same
    time do not both create pools. Subsequent calls return immediately.
    """
    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        # Re-check after acquiring the lock. Standard double-check pattern.
        if _pool is not None:
            return _pool

        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Run scripts/init_db.py once "
                "you have a Postgres URL in .env."
            )

        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=5,
            # Render free tier closes idle connections after 5 min.
            # Keep our pool well under that with periodic recycling.
            max_inactive_connection_lifetime=240.0,
            # Statement timeout protects against runaway queries.
            command_timeout=10.0,
            # JSONB columns -> Python dicts. Without this, payload is str.
            init=_init_connection,
        )
        return _pool


async def close_pool() -> None:
    """Close the pool. Call this on application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def acquire():
    """Acquire one connection from the pool.

    Usage:
        async with acquire() as conn:
            row = await conn.fetchrow("SELECT 1")

    Just sugar over pool.acquire() so callers do not have to import
    the pool directly.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


# -----------------------------------------------------------------------------
# Query helpers used by the MCP tools.
#
# These keep SQL in one place. The tool layer (mcp/server.py on Day 3) calls
# these and shapes the response. The runtime never writes raw SQL elsewhere.
# -----------------------------------------------------------------------------


async def fetch_logs_for_incident(
    incident_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return log signals for an incident, oldest first.

    The MCP tool query_logs surfaces this to the agent.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT payload, occurred_at
            FROM incident_signals
            WHERE incident_id = $1 AND signal_type = 'log'
            ORDER BY occurred_at ASC
            LIMIT $2
            """,
            incident_id,
            limit,
        )
    return [
        {
            "ts": row["occurred_at"].isoformat(),
            **row["payload"],
        }
        for row in rows
    ]


async def fetch_metrics_for_incident(
    incident_id: str,
    *,
    metric: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return metric signals for an incident, oldest first.

    Optionally filter to one metric name (e.g. "p99_latency_ms").
    """
    async with acquire() as conn:
        if metric is not None:
            rows = await conn.fetch(
                """
                SELECT payload, occurred_at
                FROM incident_signals
                WHERE incident_id = $1
                  AND signal_type = 'metric'
                  AND payload->>'metric' = $2
                ORDER BY occurred_at ASC
                LIMIT $3
                """,
                incident_id,
                metric,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT payload, occurred_at
                FROM incident_signals
                WHERE incident_id = $1 AND signal_type = 'metric'
                ORDER BY occurred_at ASC
                LIMIT $2
                """,
                incident_id,
                limit,
            )
    return [
        {
            "ts": row["occurred_at"].isoformat(),
            **row["payload"],
        }
        for row in rows
    ]


async def fetch_runbook_for_incident(incident_id: str) -> dict[str, Any] | None:
    """Return the first runbook signal for an incident, if any."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT payload
            FROM incident_signals
            WHERE incident_id = $1 AND signal_type = 'runbook'
            ORDER BY occurred_at ASC
            LIMIT 1
            """,
            incident_id,
        )
    return dict(row["payload"]) if row else None


async def fetch_incident(incident_id: str) -> dict[str, Any] | None:
    """Return one incident by id, or None if it does not exist."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, description, severity, service, started_at
            FROM incidents
            WHERE id = $1
            """,
            incident_id,
        )
    if not row:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "severity": row["severity"],
        "service": row["service"],
        "started_at": row["started_at"].isoformat(),
    }
