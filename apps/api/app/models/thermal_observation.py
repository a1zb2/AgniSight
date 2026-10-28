import hashlib
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Float, Index, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ThermalObservation(Base):
    __tablename__ = "thermal_observations"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # Stable fingerprint for idempotent ingestion.
    fingerprint: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    satellite: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    instrument: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    latitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    longitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    brightness_ti4: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    scan: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    track: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    brightness_ti5: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    frp: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    confidence: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    day_night: Mapped[str | None] = mapped_column(
        String(1),
        nullable=True,
    )

    processing_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # NASA source type; present only in standard-processing archive rows.
    firms_type: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )

    geometry = mapped_column(
        Geometry(
            geometry_type="POINT",
            srid=4326,
            spatial_index=False,
        ),
        nullable=False,
    )


Index(
    "ix_thermal_observations_geometry",
    ThermalObservation.geometry,
    postgresql_using="gist",
)

Index(
    "ix_thermal_observations_observed_at",
    ThermalObservation.observed_at,
)