"""
Initialize the Kexar database with schema and seed data.

Idempotent: drops and recreates tables. Safe to run multiple times.

Usage:
    uv run python scripts/init_db.py
"""

import asyncio
import sys
from pathlib import Path

import asyncpg

from kexar.config import settings


SCHEMA_PATH = Path(__file__).parent.parent / "kexar" / "db" / "schema.sql"


async def main() -> None:
    if not settings.database_url:
        print("DATABASE_URL not set in .env", file=sys.stderr)
        sys.exit(1)

    if not SCHEMA_PATH.exists():
        print(f"Schema file not found: {SCHEMA_PATH}", file=sys.stderr)
        sys.exit(1)

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    masked_host = settings.database_url.split("@")[-1] if "@" in settings.database_url else "?"
    print(f"Connecting to ...@{masked_host}")
    conn = await asyncpg.connect(settings.database_url)

    try:
        # asyncpg executes one statement per call, but we can wrap the whole
        # schema in a transaction. Use execute() which accepts a script.
        await conn.execute(schema_sql)
        print("Schema applied.")

        # Quick sanity check on the seed data.
        incident_count = await conn.fetchval("SELECT COUNT(*) FROM incidents")
        signal_count = await conn.fetchval("SELECT COUNT(*) FROM incident_signals")
        log_count = await conn.fetchval(
            "SELECT COUNT(*) FROM incident_signals WHERE signal_type = 'log'"
        )
        metric_count = await conn.fetchval(
            "SELECT COUNT(*) FROM incident_signals WHERE signal_type = 'metric'"
        )
        runbook_count = await conn.fetchval(
            "SELECT COUNT(*) FROM incident_signals WHERE signal_type = 'runbook'"
        )

        print()
        print(f"  incidents:        {incident_count}")
        print(f"  incident_signals: {signal_count} total")
        print(f"    logs:           {log_count}")
        print(f"    metrics:        {metric_count}")
        print(f"    runbooks:       {runbook_count}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
