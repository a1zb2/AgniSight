from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.observations import get_db
from app.services.events import event_detail, events_map_layer


router = APIRouter(
    prefix="/api/v1/events",
    tags=["Thermal events"],
)


@router.get("/geojson")
def thermal_events_geojson(
    days: int = Query(default=14, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Recent events with category and priority, light enough for the map."""
    return events_map_layer(db, days)


@router.get("/{event_id}")
def thermal_event(
    event_id: str,
    days: int = Query(default=14, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Full assessment: evidence, history, context, model and priority."""
    feature = event_detail(db, event_id, days)
    if feature is None:
        raise HTTPException(
            status_code=404,
            detail="Event not found in the current window; events are "
                   "regrouped when new detections arrive.",
        )
    return feature
