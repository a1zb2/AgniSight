from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.observations import get_db
from app.core.config import settings
from app.services.event_snapshots import SNAPSHOT_DAYS, stored_event, stored_layer
from app.services.events import detections_layer, event_detail, events_map_layer


router = APIRouter(
    prefix="/api/v1/events",
    tags=["Thermal events"],
)

NOT_IN_WINDOW = (
    "Event not found in the current window; events are regrouped when new "
    "detections arrive."
)


def _snapshot(payload: str | None, missing: str) -> Response:
    if payload is None:
        raise HTTPException(status_code=404, detail=missing)
    # Snapshots change only when refresh_data.py runs.
    return Response(payload, media_type="application/json",
                    headers={"Cache-Control": "public, max-age=300"})


def _snapshot_window(days: int) -> None:
    if days != SNAPSHOT_DAYS:
        raise HTTPException(
            status_code=404,
            detail=f"Only the last {SNAPSHOT_DAYS} days are published.",
        )


@router.get("/geojson")
def thermal_events_geojson(
    days: int = Query(default=14, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Recent events with category and priority, light enough for the map."""
    if settings.events_source == "snapshot":
        _snapshot_window(days)
        return _snapshot(stored_layer(db.connection(), "events"),
                         "No events have been published yet.")
    return events_map_layer(db, days)


@router.get("/detections")
def thermal_detections(
    days: int = Query(default=14, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Every detection in the window with its event, for heat rendering."""
    if settings.events_source == "snapshot":
        _snapshot_window(days)
        return _snapshot(stored_layer(db.connection(), "detections"),
                         "No detections have been published yet.")
    return detections_layer(db, days)


# Declared last so it does not capture /geojson or /detections.
@router.get("/{event_id}")
def thermal_event(
    event_id: str,
    days: int = Query(default=14, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Full assessment: evidence, history, context, model and priority."""
    if settings.events_source == "snapshot":
        _snapshot_window(days)
        return _snapshot(stored_event(db.connection(), event_id), NOT_IN_WINDOW)
    feature = event_detail(db, event_id, days)
    if feature is None:
        raise HTTPException(status_code=404, detail=NOT_IN_WINDOW)
    return feature
