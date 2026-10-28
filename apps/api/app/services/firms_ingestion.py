import hashlib
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.providers.firms import FIRMSProvider
from app.services.grid import cell_of
from app.services.pipeline_runs import finish_run, start_run
from app.services.thermal_registry import refresh_cells

# India bounding box used for all live requests.
INDIA_AREA = {"west": 68.0, "south": 6.0, "east": 98.0, "north": 38.0}

INSERT_SQL = text("""
    INSERT INTO thermal_observations (
        fingerprint, source, satellite, instrument, observed_at,
        latitude, longitude, brightness_ti4, scan, track,
        brightness_ti5, frp, confidence, day_night,
        processing_version, geometry
    ) VALUES (
        :fingerprint, 'NASA_FIRMS', :satellite, :instrument, :observed_at,
        :latitude, :longitude, :brightness_ti4, :scan, :track,
        :brightness_ti5, :frp, :confidence, :day_night,
        :processing_version,
        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)
    )
    ON CONFLICT (fingerprint) DO NOTHING
""")


def _float(record: dict, key: str) -> float | None:
    value = (record.get(key) or "").strip()
    return float(value) if value else None


class FIRMSIngestionService:
    def __init__(self, db: Session):
        self.db = db
        self.provider = FIRMSProvider()

    async def ingest_area(
        self,
        west: float,
        south: float,
        east: float,
        north: float,
        day_range: int = 1,
        start_date: date | None = None,
    ) -> dict:
        records = await self.provider.fetch_area(
            west=west,
            south=south,
            east=east,
            north=north,
            day_range=day_range,
            start_date=start_date,
        )

        rows = []
        for record in records:
            latitude = float(record["latitude"])
            longitude = float(record["longitude"])
            observed_at = self.provider.parse_observed_at(
                record["acq_date"], record["acq_time"]
            )
            satellite = record.get("satellite") or None
            instrument = record.get("instrument") or None
            processing_version = record.get("version") or None

            # Unchanged from earlier releases so existing rows keep matching.
            fingerprint = hashlib.sha256("|".join([
                "NASA_FIRMS",
                satellite or "",
                instrument or "",
                record["acq_date"],
                record["acq_time"],
                str(latitude),
                str(longitude),
                processing_version or "",
            ]).encode("utf-8")).hexdigest()

            rows.append({
                "fingerprint": fingerprint,
                "satellite": satellite,
                "instrument": instrument,
                "observed_at": observed_at,
                "latitude": latitude,
                "longitude": longitude,
                "brightness_ti4": _float(record, "bright_ti4"),
                "scan": _float(record, "scan"),
                "track": _float(record, "track"),
                "brightness_ti5": _float(record, "bright_ti5"),
                "frp": _float(record, "frp"),
                "confidence": record.get("confidence") or None,
                "day_night": record.get("daynight") or None,
                "processing_version": processing_version,
            })

        new_rows = self._exclude_known_detections(rows)
        inserted = 0
        if new_rows:
            inserted = self.db.execute(INSERT_SQL, new_rows).rowcount

        # Keep per-location history current for the rows just added.
        cells = {cell_of(r["longitude"], r["latitude"]) for r in new_rows}
        refreshed = refresh_cells(self.db.connection(), cells)
        self.db.commit()

        return {
            "source": "NASA_FIRMS",
            "sensor": self.provider.source,
            "start_date": start_date.isoformat() if start_date else None,
            "day_range": day_range,
            "records_received": len(records),
            "inserted": int(inserted),
            "skipped": len(records) - int(inserted),
            "cells_refreshed": refreshed,
        }

    def _exclude_known_detections(self, rows: list[dict]) -> list[dict]:
        """Drop detections already stored under a different fingerprint.

        The API reports acq_time unpadded ("538") while downloaded CSVs pad
        it ("0538"), so the same detection can arrive with two fingerprints.
        Satellite, time and coordinates identify it either way.
        """
        if not rows:
            return []
        times = [r["observed_at"] for r in rows]
        existing = self.db.execute(text("""
            SELECT satellite, observed_at, latitude, longitude
            FROM thermal_observations
            WHERE source = 'NASA_FIRMS'
              AND observed_at BETWEEN :start AND :end
        """), {"start": min(times), "end": max(times)}).all()
        known = {
            (s, t, round(lat, 5), round(lon, 5))
            for s, t, lat, lon in existing
        }

        result, seen = [], set()
        for r in rows:
            key = (r["satellite"], r["observed_at"],
                   round(r["latitude"], 5), round(r["longitude"], 5))
            if key in known or key in seen:
                continue
            seen.add(key)
            result.append(r)
        return result

    async def ingest_range(self, start: date, end: date) -> dict:
        """Fetch [start, end] in the API's maximum 5-day windows."""
        run_id = start_run(self.db.connection(), "firms_ingestion", {
            "start_date": start.isoformat(), "end_date": end.isoformat(),
        })
        self.db.commit()

        windows = []
        try:
            cursor = start
            while cursor <= end:
                days = min(5, (end - cursor).days + 1)
                windows.append(await self.ingest_area(
                    **INDIA_AREA, day_range=days, start_date=cursor,
                ))
                cursor += timedelta(days=days)
        except Exception as exc:
            self.db.rollback()
            finish_run(self.db.connection(), run_id, "failed", {
                "error": str(exc), "windows": windows,
            })
            self.db.commit()
            raise

        summary = {
            "windows": windows,
            "records_received": sum(w["records_received"] for w in windows),
            "inserted": sum(w["inserted"] for w in windows),
        }
        finish_run(self.db.connection(), run_id, "success", summary)
        self.db.commit()
        return summary
