import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.observations import get_db
from app.services.spatial_context import context_for_points

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/context",
    tags=["Industrial context"],
)


@router.get("/nearby-industrial")
def nearby_industrial_context(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=5.0, gt=0, le=10),
    db: Session = Depends(get_db),
):
    """Mapped industrial, mining, waste and power features around a point.

    Uses the same normalized OSM features as event assessments.
    """
    try:
        summary = context_for_points(
            db.connection(), [(longitude, latitude)], radius_m=radius_km * 1000
        )[0]
    except SQLAlchemyError:
        logger.exception("Local PostGIS context lookup failed")
        raise HTTPException(
            status_code=500,
            detail="The local industrial-context query failed.",
        )

    return {
        "query_center": {"latitude": latitude, "longitude": longitude},
        "radius_km": radius_km,
        **summary,
        "data_provider": "Local OpenStreetMap extract (Geofabrik) in PostGIS",
        "note": "Mapped context only. Nearby infrastructure does not "
                "confirm that a thermal anomaly is a fire or identify its "
                "source; OSM coverage of Indian industry is incomplete.",
    }
