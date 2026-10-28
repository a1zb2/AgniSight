import csv
import io
from datetime import date, datetime, timezone

import httpx

from app.core.config import settings


FIRMS_BASE_URL = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
)


class FIRMSProvider:
    def __init__(
        self,
        source: str = "VIIRS_NOAA21_NRT",
    ):
        self.source = source

    async def fetch_area(
        self,
        west: float,
        south: float,
        east: float,
        north: float,
        day_range: int = 1,
        start_date: date | None = None,
    ) -> list[dict]:
        if not 1 <= day_range <= 5:
            raise ValueError("day_range must be between 1 and 5")
        if not settings.firms_map_key:
            raise RuntimeError("FIRMS_MAP_KEY is not set")

        area = f"{west},{south},{east},{north}"

        url = (
            f"{FIRMS_BASE_URL}/"
            f"{settings.firms_map_key}/"
            f"{self.source}/"
            f"{area}/"
            f"{day_range}"
        )
        if start_date is not None:
            # Optional first day of the window; otherwise the most recent days.
            url += f"/{start_date.isoformat()}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            response.raise_for_status()

        # FIRMS reports some errors (e.g. invalid key) as plain text with 200.
        if not response.text.startswith("latitude"):
            raise RuntimeError(
                f"Unexpected FIRMS response: {response.text[:200]!r}"
            )

        reader = csv.DictReader(io.StringIO(response.text))

        return list(reader)

    @staticmethod
    def parse_observed_at(
        acq_date: str,
        acq_time: str,
    ) -> datetime:
        # FIRMS acquisition time is expressed as HHMM.
        timestamp = datetime.strptime(
            f"{acq_date} {acq_time.zfill(4)}",
            "%Y-%m-%d %H%M",
        )

        return timestamp.replace(tzinfo=timezone.utc)