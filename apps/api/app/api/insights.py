from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.observations import get_db
from app.services.insights import (
    analytics_overview,
    data_status,
    location_history,
    sites_geojson,
)


router = APIRouter(prefix="/api/v1", tags=["History and status"])


@router.get("/sites/geojson")
def thermal_sites(
    site_class: Literal["persistent", "recurrent", "seasonal"] | None = None,
    db: Session = Depends(get_db),
):
    """Locations with repeated activity across months (precomputed)."""
    return sites_geojson(db.connection(), site_class)


@router.get("/history/location")
def history_at_location(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_m: float = Query(default=750, gt=0, le=5000),
    db: Session = Depends(get_db),
):
    """Monthly detections, FRP and recent detections around a point."""
    return location_history(db.connection(), latitude, longitude, radius_m)


@router.get("/status")
def status(db: Session = Depends(get_db)):
    """Data freshness, coverage gaps, pipeline runs and model card."""
    return data_status(db.connection())


@router.get("/analytics/overview")
def analytics(db: Session = Depends(get_db)):
    """National monthly trend and site counts by class and context."""
    return analytics_overview(db.connection())
