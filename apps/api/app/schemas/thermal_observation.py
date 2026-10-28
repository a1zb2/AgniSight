from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ThermalObservationCreate(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    satellite: str | None = Field(default=None, max_length=50)
    instrument: str | None = Field(default=None, max_length=50)
    observed_at: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    brightness_ti4: float | None = None
    scan: float | None = None
    track: float | None = None
    brightness_ti5: float | None = None
    frp: float | None = None
    confidence: str | None = Field(default=None, max_length=20)
    day_night: str | None = Field(default=None, max_length=1)
    processing_version: str | None = Field(default=None, max_length=50)


class ThermalObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    satellite: str | None
    instrument: str | None
    observed_at: datetime
    latitude: float
    longitude: float
    brightness_ti4: float | None
    scan: float | None
    track: float | None
    brightness_ti5: float | None
    frp: float | None
    confidence: str | None
    day_night: str | None
    processing_version: str | None
