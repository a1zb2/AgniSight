from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.thermal_observation import ThermalObservation
from app.schemas.thermal_observation import (
    ThermalObservationCreate,
    ThermalObservationResponse,
)


router = APIRouter(
    prefix="/api/v1/observations",
    tags=["observations"],
)


MAX_OBSERVATIONS_PER_REQUEST = 5000


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


@router.post(
    "",
    response_model=ThermalObservationResponse,
    status_code=201,
)
def create_observation(
    observation: ThermalObservationCreate,
    db: Session = Depends(get_db),
):
    # Create a PostGIS point from longitude/latitude.
    geometry = from_shape(
        Point(
            observation.longitude,
            observation.latitude,
        ),
        srid=4326,
    )

    db_observation = ThermalObservation(
        fingerprint=(
            f"manual-{observation.latitude}-"
            f"{observation.longitude}-"
            f"{observation.observed_at.timestamp()}"
        ),
        source=observation.source,
        satellite=observation.satellite,
        instrument=observation.instrument,
        observed_at=observation.observed_at,
        latitude=observation.latitude,
        longitude=observation.longitude,
        brightness_ti4=observation.brightness_ti4,
        scan=observation.scan,
        track=observation.track,
        brightness_ti5=observation.brightness_ti5,
        frp=observation.frp,
        confidence=observation.confidence,
        day_night=observation.day_night,
        processing_version=observation.processing_version,
        geometry=geometry,
    )

    db.add(db_observation)
    db.commit()
    db.refresh(db_observation)

    return db_observation


def _filtered_observations(
    db: Session,
    start: datetime | None,
    end: datetime | None,
    bbox: str | None,
    limit: int,
):
    # The table holds the full multi-year archive, so every listing is
    # bounded and newest-first.
    statement = select(ThermalObservation)

    if start is not None:
        statement = statement.where(ThermalObservation.observed_at >= start)
    if end is not None:
        statement = statement.where(ThermalObservation.observed_at < end)

    if bbox:
        try:
            west, south, east, north = (float(v) for v in bbox.split(","))
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="bbox must be 'west,south,east,north'",
            )
        statement = statement.where(
            ThermalObservation.geometry.intersects(
                func.ST_MakeEnvelope(west, south, east, north, 4326)
            )
        )

    return db.scalars(
        statement
        .order_by(ThermalObservation.observed_at.desc())
        .limit(limit)
    ).all()


@router.get(
    "",
    response_model=list[ThermalObservationResponse],
)
def list_observations(
    start: datetime | None = None,
    end: datetime | None = None,
    bbox: str | None = Query(default=None, description="west,south,east,north"),
    limit: int = Query(default=500, ge=1, le=MAX_OBSERVATIONS_PER_REQUEST),
    db: Session = Depends(get_db),
):
    return _filtered_observations(db, start, end, bbox, limit)


@router.get("/geojson")
def observations_geojson(
    start: datetime | None = None,
    end: datetime | None = None,
    bbox: str | None = Query(default=None, description="west,south,east,north"),
    limit: int = Query(default=500, ge=1, le=MAX_OBSERVATIONS_PER_REQUEST),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    observations = _filtered_observations(db, start, end, bbox, limit)

    features = []

    for observation in observations:
        point = to_shape(observation.geometry)

        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        point.x,
                        point.y,
                    ],
                },
                "properties": {
                    "id": observation.id,
                    "source": observation.source,
                    "satellite": observation.satellite,
                    "instrument": observation.instrument,
                    "observed_at": observation.observed_at.isoformat(),
                    "latitude": observation.latitude,
                    "longitude": observation.longitude,
                    "brightness_ti4": observation.brightness_ti4,
                    "scan": observation.scan,
                    "track": observation.track,
                    "brightness_ti5": observation.brightness_ti5,
                    "frp": observation.frp,
                    "confidence": observation.confidence,
                    "day_night": observation.day_night,
                    "processing_version": observation.processing_version,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


@router.get(
    "/{observation_id}",
    response_model=ThermalObservationResponse,
)
def get_observation(
    observation_id: int,
    db: Session = Depends(get_db),
):
    observation = db.get(
        ThermalObservation,
        observation_id,
    )

    if observation is None:
        raise HTTPException(
            status_code=404,
            detail="Thermal observation not found",
        )

    return observation