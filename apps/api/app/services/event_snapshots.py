"""Events built ahead of time and stored for a small hosted API.

refresh_data.py builds the default window after each ingestion and stores
the map layer, the detection layer and every event's full assessment as
JSON. With EVENTS_SOURCE=snapshot the API returns these rows as stored
text, so it never loads the model or holds a whole build in memory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.services.events import build_events, detection_rows, map_layer

SNAPSHOT_DAYS = 14


def _json(value: Any) -> str:
    return json.dumps(jsonable_encoder(value), allow_nan=False,
                      separators=(",", ":"))


def publish_snapshot(db: Session, days: int = SNAPSHOT_DAYS) -> dict[str, Any]:
    """Build the window and replace the stored snapshot in one transaction."""
    full = build_events(db, days)
    built_at = datetime.now(timezone.utc)
    conn = db.connection()
    conn.execute(text("DELETE FROM event_snapshot_layers"))
    conn.execute(text("DELETE FROM event_snapshot_events"))
    conn.execute(text("""
        INSERT INTO event_snapshot_layers (name, built_at, payload)
        VALUES (:name, :built_at, CAST(:payload AS json))
    """), [
        {"name": "events", "built_at": built_at, "payload": _json(map_layer(full))},
        {"name": "detections", "built_at": built_at,
         "payload": _json(detection_rows(full))},
    ])
    if full["features"]:
        conn.execute(text("""
            INSERT INTO event_snapshot_events (event_id, payload)
            VALUES (:event_id, CAST(:payload AS json))
        """), [
            {"event_id": f["id"], "payload": _json(f)} for f in full["features"]
        ])
    db.commit()
    return {
        "days": days,
        "built_at": built_at.isoformat(),
        "events": len(full["features"]),
        "detections": len(full["detections"]["rows"]),
        "build_seconds": full["metadata"]["build_seconds"],
    }


def stored_layer(conn: Connection, name: str) -> str | None:
    return conn.execute(text(
        "SELECT payload::text FROM event_snapshot_layers WHERE name = :name"
    ), {"name": name}).scalar()


def stored_event(conn: Connection, event_id: str) -> str | None:
    return conn.execute(text(
        "SELECT payload::text FROM event_snapshot_events WHERE event_id = :id"
    ), {"id": event_id}).scalar()
