"""Record data-pipeline runs so the API can report data freshness."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


def start_run(conn: Connection, kind: str, details: dict[str, Any] | None = None) -> int:
    return int(conn.execute(
        text("""
            INSERT INTO pipeline_runs (kind, details)
            VALUES (:kind, CAST(:details AS jsonb))
            RETURNING id
        """),
        {"kind": kind, "details": json.dumps(details or {}, default=str)},
    ).scalar())


def finish_run(conn: Connection, run_id: int, status: str, details: dict[str, Any]) -> None:
    conn.execute(
        text("""
            UPDATE pipeline_runs
            SET finished_at = now(), status = :status,
                details = details || CAST(:details AS jsonb)
            WHERE id = :id
        """),
        {"id": run_id, "status": status, "details": json.dumps(details, default=str)},
    )


def latest_runs(conn: Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(text("""
        SELECT DISTINCT ON (kind) kind, started_at, finished_at, status, details
        FROM pipeline_runs
        WHERE status = 'success'
        ORDER BY kind, started_at DESC
    """)).mappings().all()
    return {
        row["kind"]: {
            "started_at": row["started_at"].isoformat(),
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
            "details": row["details"],
        }
        for row in rows
    }
