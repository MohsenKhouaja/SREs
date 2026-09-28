from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import asyncpg

from .config import Settings
from .docker_ops import StaleResource


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


BLOCKING_QUERY = """
SELECT blocker.pid, blocker.backend_start, blocker.application_name,
       blocked.pid AS blocked_pid, blocked.application_name AS blocked_application,
       blocked.wait_event_type, blocked.wait_event,
       left(blocker.query, 500) AS blocker_query,
       left(blocked.query, 500) AS blocked_query
FROM pg_stat_activity blocked
CROSS JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS blocker_pid
JOIN pg_stat_activity blocker ON blocker.pid = blocker_pid
WHERE blocked.datname = current_database()
ORDER BY blocked.query_start
LIMIT 20
"""


class PostgresOperations:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock_connections: dict[str, asyncpg.Connection] = {}

    async def create_blocker(self, run_id: str, ttl_seconds: int) -> dict[str, Any]:
        connection = await asyncpg.connect(self.settings.postgres_url, server_settings={"application_name": f"sres-lab-blocker:{run_id}"})
        try:
            await connection.fetchval("SELECT set_config('idle_in_transaction_session_timeout', $1, false)", f"{ttl_seconds}s")
            transaction = connection.transaction()
            await transaction.start()
            await connection.execute("LOCK TABLE users IN ACCESS EXCLUSIVE MODE")
            row = await connection.fetchrow("SELECT pg_backend_pid() AS pid, backend_start FROM pg_stat_activity WHERE pid = pg_backend_pid()")
            self._lock_connections[run_id] = connection
            return {
                "resource_id": "postgres:incident_db",
                "database": "incident_db",
                "pid": row["pid"],
                "backend_start": row["backend_start"].isoformat(),
                "observed_at": utc_iso(),
            }
        except Exception:
            await connection.close()
            raise

    async def inspect_blocking(self) -> list[dict[str, Any]]:
        connection = await asyncpg.connect(self.settings.postgres_url, server_settings={"application_name": "sres-lab-observer"})
        try:
            rows = await connection.fetch(BLOCKING_QUERY)
            return [
                {
                    **dict(row),
                    "resource_id": "postgres:incident_db",
                    "backend_start": row["backend_start"].isoformat(),
                    "observation_id": f"postgres-blocker:{row['pid']}:{row['backend_start'].isoformat()}",
                    "database": "incident_db",
                    "observed_at": utc_iso(),
                }
                for row in rows
            ]
        finally:
            await connection.close()

    async def terminate_blocker(self, database: str, pid: int, backend_start: str) -> dict[str, Any]:
        if database != "incident_db":
            raise ValueError("Database is outside the lab allowlist")
        connection = await asyncpg.connect(self.settings.postgres_url, server_settings={"application_name": "sres-lab-operator"})
        try:
            row = await connection.fetchrow(
                """
                SELECT pid, backend_start, application_name,
                       EXISTS (SELECT 1 FROM pg_locks WHERE pid = $1 AND relation = 'users'::regclass) AS holds_users_lock
                FROM pg_stat_activity WHERE pid = $1 AND datname = current_database()
                """,
                pid,
            )
            if not row or row["backend_start"].isoformat() != backend_start:
                raise StaleResource("Database session identity changed after approval")
            if not row["application_name"].startswith("sres-lab-blocker:") or not row["holds_users_lock"]:
                raise ValueError("Session is not an active lab blocker")
            terminated = await connection.fetchval("SELECT pg_terminate_backend($1)", pid)
            if not terminated:
                raise RuntimeError("PostgreSQL refused to terminate the blocking session")
            return {"before": dict(row), "after": {"pid": pid, "terminated": True, "observed_at": utc_iso()}}
        finally:
            await connection.close()

    async def cleanup(self, run_id: str) -> dict[str, Any]:
        connection = self._lock_connections.pop(run_id, None)
        if connection and not connection.is_closed():
            await connection.close()
            return {"status": "cleaned", "method": "owned_connection_closed", "observed_at": utc_iso()}
        operator = await asyncpg.connect(self.settings.postgres_url, server_settings={"application_name": "sres-lab-cleanup"})
        try:
            rows = await operator.fetch(
                "SELECT pid FROM pg_stat_activity WHERE application_name = $1",
                f"sres-lab-blocker:{run_id}",
            )
            results = [await operator.fetchval("SELECT pg_terminate_backend($1)", row["pid"]) for row in rows]
            return {"status": "cleaned", "terminated": sum(bool(item) for item in results), "observed_at": utc_iso()}
        finally:
            await operator.close()
