"""Location history, persistent sites, data status and national analytics."""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.services.pipeline_runs import latest_runs
from app.services.places import places_for_points
from app.services.static_model import model_card

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, compute: Callable[[], Any]) -> Any:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = compute()
    _cache[key] = (time.monotonic(), value)
    return value


def _month_range(start: date, end: date) -> list[date]:
    months, cursor = [], date(start.year, start.month, 1)
    while cursor <= end:
        months.append(cursor)
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
    return months


def national_coverage(conn: Connection) -> dict[date, int]:
    """Distinct UTC days per month with any stored detection in India.

    Lets a chart tell "no data that month" apart from "nothing detected
    here that month".
    """
    def compute():
        rows = conn.execute(text("""
            SELECT date_trunc('month', d)::date AS month, COUNT(*) AS days
            FROM (
                SELECT DISTINCT (observed_at AT TIME ZONE 'UTC')::date AS d
                FROM thermal_observations WHERE source = 'NASA_FIRMS'
            ) AS days
            GROUP BY 1
        """)).all()
        return {r.month: int(r.days) for r in rows}

    return _cached("coverage", 600, compute)


def location_history(conn: Connection, latitude: float, longitude: float,
                     radius_m: float) -> dict[str, Any]:
    params = {
        "lat": latitude, "lon": longitude, "radius_m": radius_m,
        "deg": radius_m / 111_000 * 1.6,
    }
    where = """
        source = 'NASA_FIRMS'
        AND geometry && ST_Expand(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                                  CAST(:deg AS double precision))
        AND ST_DWithin(geometry::geography,
                       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                       CAST(:radius_m AS double precision))
    """
    monthly = {
        r.month: r for r in conn.execute(text(f"""
            SELECT
                date_trunc('month', observed_at AT TIME ZONE 'UTC')::date AS month,
                COUNT(*) AS detections,
                COUNT(DISTINCT (observed_at AT TIME ZONE 'UTC')::date) AS active_days,
                COUNT(*) FILTER (WHERE day_night = 'N') AS night,
                MAX(frp) AS max_frp,
                AVG(frp) AS mean_frp,
                COUNT(firms_type) AS typed,
                COUNT(*) FILTER (WHERE firms_type = 2) AS static
            FROM thermal_observations
            WHERE {where}
            GROUP BY 1
        """), params)
    }
    recent = conn.execute(text(f"""
        SELECT id, observed_at, latitude, longitude, frp, brightness_ti4,
               confidence, day_night, firms_type, processing_version
        FROM thermal_observations
        WHERE {where}
        ORDER BY observed_at DESC
        LIMIT 40
    """), params).mappings().all()

    coverage = national_coverage(conn)
    if not coverage:
        return {"months": [], "recent_detections": []}
    today = datetime.now(timezone.utc).date()
    series = []
    for month in _month_range(min(coverage), today):
        row = monthly.get(month)
        series.append({
            "month": month.isoformat(),
            "detections": int(row.detections) if row else 0,
            "active_days": int(row.active_days) if row else 0,
            "night_detections": int(row.night) if row else 0,
            "max_frp": round(float(row.max_frp), 2) if row and row.max_frp is not None else None,
            "mean_frp": round(float(row.mean_frp), 2) if row and row.mean_frp is not None else None,
            "nasa_static_share": (
                round(row.static / row.typed, 3) if row and row.typed else None
            ),
            "data_days": coverage.get(month, 0),
        })

    return {
        "query": {"latitude": latitude, "longitude": longitude, "radius_m": radius_m},
        "months": series,
        "recent_detections": [
            {**dict(r), "observed_at": r["observed_at"].isoformat()} for r in recent
        ],
        "note": "data_days is the number of days that month with any stored "
                "detection in India; 0 means no data, not no activity.",
    }


def sites_geojson(conn: Connection, site_class: str | None) -> dict[str, Any]:
    rows = conn.execute(text("""
        SELECT * FROM thermal_sites
        WHERE CAST(:cls AS text) IS NULL OR site_class = :cls
        ORDER BY detection_count DESC
    """), {"cls": site_class}).mappings().all()

    def iso(v):
        return v.isoformat() if v else None

    places = places_for_points(conn, [(r["longitude"], r["latitude"]) for r in rows])
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": r["site_id"],
                "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
                "properties": {
                    **{
                        k: (iso(v) if isinstance(v, datetime) else v)
                        for k, v in r.items() if k != "geometry"
                    },
                    "place_label": place["label"] if place else None,
                },
            }
            for r, place in zip(rows, places)
        ],
    }


def data_status(conn: Connection) -> dict[str, Any]:
    def compute():
        totals = conn.execute(text("""
            SELECT COUNT(*) AS total,
                   MIN(observed_at) AS first,
                   MAX(observed_at) AS latest,
                   COUNT(*) FILTER (WHERE firms_type IS NOT NULL) AS labelled,
                   COUNT(*) FILTER (WHERE observed_at >= now() - interval '24 hours') AS last_24h,
                   COUNT(*) FILTER (WHERE observed_at >= now() - interval '7 days') AS last_7d
            FROM thermal_observations WHERE source = 'NASA_FIRMS'
        """)).mappings().one()
        missing = [r.d.isoformat() for r in conn.execute(text("""
            SELECT d::date FROM generate_series(
                (now() AT TIME ZONE 'UTC')::date - 30,
                (now() AT TIME ZONE 'UTC')::date - 1, interval '1 day') AS d
            WHERE NOT EXISTS (
                SELECT 1 FROM thermal_observations
                WHERE observed_at >= d AND observed_at < d + interval '1 day'
            )
        """))]
        sites = dict(conn.execute(text(
            "SELECT site_class, COUNT(*) FROM thermal_sites GROUP BY 1"
        )).all())
        latest = totals["latest"]
        return {
            "source": "NASA FIRMS VIIRS NOAA-21 (archive SP + NRT)",
            "observations": int(totals["total"]),
            "nasa_labelled_observations": int(totals["labelled"]),
            "first_observation": totals["first"].isoformat() if totals["first"] else None,
            "latest_observation": latest.isoformat() if latest else None,
            "hours_since_latest": (
                round((datetime.now(timezone.utc) - latest).total_seconds() / 3600, 1)
                if latest else None
            ),
            "observations_last_24h": int(totals["last_24h"]),
            "observations_last_7d": int(totals["last_7d"]),
            "days_without_data_last_30d": missing,
            "sites": sites,
            "pipeline": latest_runs(conn),
            "model": model_card(),
        }

    return _cached("status", 60, compute)


def analytics_overview(conn: Connection) -> dict[str, Any]:
    def compute():
        monthly = conn.execute(text("""
            SELECT date_trunc('month', observed_at AT TIME ZONE 'UTC')::date AS month,
                   COUNT(*) AS detections,
                   COUNT(*) FILTER (WHERE day_night = 'N') AS night,
                   COUNT(*) FILTER (WHERE firms_type = 2) AS nasa_static,
                   COUNT(firms_type) AS labelled
            FROM thermal_observations WHERE source = 'NASA_FIRMS'
            GROUP BY 1 ORDER BY 1
        """)).mappings().all()
        coverage = national_coverage(conn)
        by_context = conn.execute(text("""
            SELECT site_class, COALESCE(context_group, 'unmapped') AS context_group,
                   COUNT(*) AS sites, SUM(detection_count) AS detections
            FROM thermal_sites
            GROUP BY 1, 2 ORDER BY 3 DESC
        """)).mappings().all()
        return {
            "monthly_detections": [
                {
                    "month": r["month"].isoformat(),
                    "detections": int(r["detections"]),
                    "night_detections": int(r["night"]),
                    "nasa_static": int(r["nasa_static"]),
                    "nasa_labelled": int(r["labelled"]),
                    "data_days": coverage.get(r["month"], 0),
                }
                for r in monthly
            ],
            "sites_by_class_and_context": [dict(r) for r in by_context],
        }

    return _cached("analytics", 600, compute)
