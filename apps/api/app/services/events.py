"""Recent thermal events enriched with history, context and assessment.

Pipeline per request (cached until new observations arrive):
recent detections -> clusters -> location history from thermal_cells ->
nearest persistent site -> mapped OSM context -> static-source model ->
assessment.assess_event().
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.thermal_observation import ThermalObservation
from app.services.assessment import assess_event
from app.services.grid import cell_of, neighborhood
from app.services.spatial_context import context_for_points
from app.services.static_model import (
    history_features,
    model_card,
    observation_features,
    predict_static_probability,
)
from app.services.thermal_clustering import cluster_observations
from app.services.thermal_registry import load_cells, summarize_cells

SITE_LINK_M = 1000.0
CACHE_TTL_SECONDS = 600
_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}

NEAREST_SITE_QUERY = text("""
    WITH pts AS (
        SELECT pid, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
        FROM unnest(
            CAST(:ids AS integer[]),
            CAST(:lons AS double precision[]),
            CAST(:lats AS double precision[])
        ) AS t(pid, lon, lat)
    )
    SELECT p.pid, s.*,
           ST_Distance(s.geometry::geography, p.g::geography) AS distance_m
    FROM pts AS p
    CROSS JOIN LATERAL (
        SELECT * FROM thermal_sites ORDER BY geometry <-> p.g LIMIT 1
    ) AS s
""")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _site_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "site_id": row["site_id"],
        "site_class": row["site_class"],
        "distance_m": round(float(row["distance_m"]), 1),
        "detection_count": row["detection_count"],
        "active_days": row["active_days"],
        "active_months": row["active_months"],
        "calendar_months": row["calendar_months"],
        "night_share": row["night_share"],
        "mean_frp": _round(row["mean_frp"]),
        "first_seen": _iso(row["first_seen"]),
        "last_seen": _iso(row["last_seen"]),
        "nasa_static_share": row["nasa_static_share"],
        "context_category": row["context_category"],
        "context_name": row["context_name"],
    }


def _history_dict(summary: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in summary.items() if k != "dates"}
    out["first_seen"] = _iso(out["first_seen"])
    out["last_seen"] = _iso(out["last_seen"])
    out["prior"] = {**prior, "last_date": _iso(prior["last_date"])}
    out["scope"] = "3x3 cells of ~400 m around each detection (~1.2 km)"
    return out


def _prior(summary: dict, start: datetime, group: list) -> dict[str, Any]:
    """History before this event (the event's own detections removed)."""
    start_day = start.date()
    dates = sorted(d for d in summary["dates"] if d < start_day)
    frp_values = [o.frp for o in group if o.frp is not None]
    frp_count = max(0, summary["_frp_count"] - len(frp_values))
    frp_sum = max(0.0, summary["_frp_sum"] - sum(frp_values))
    return {
        "active_days": len(dates),
        "active_months": len({(d.year, d.month) for d in dates}),
        "calendar_months": len({d.month for d in dates}),
        "detection_count": max(0, summary["detection_count"] - len(group)),
        "last_date": (
            datetime(dates[-1].year, dates[-1].month, dates[-1].day, tzinfo=timezone.utc)
            if dates else None
        ),
        "frp_count": frp_count,
        "mean_frp": round(frp_sum / frp_count, 2) if frp_count else None,
    }


def build_events(db: Session, days: int = 14) -> dict[str, Any]:
    latest_id, latest_time = db.execute(text("""
        SELECT MAX(id), MAX(observed_at) FROM thermal_observations
        WHERE source = 'NASA_FIRMS'
    """)).one()
    registry_build = db.execute(text("""
        SELECT MAX(id) FROM pipeline_runs
        WHERE kind = 'registry_build' AND status = 'success'
    """)).scalar()

    cache_key = (days, latest_id, registry_build)
    cached = _cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    started = time.perf_counter()
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=days)

    observations = list(db.scalars(
        select(ThermalObservation)
        .where(
            ThermalObservation.source == "NASA_FIRMS",
            ThermalObservation.observed_at >= window_start,
        )
        .order_by(ThermalObservation.observed_at.desc())
    ).all())
    groups = cluster_observations(observations)

    conn = db.connection()

    # Location history: one batched lookup of every cell any event touches.
    obs_cells = {o.id: cell_of(o.longitude, o.latitude) for o in observations}
    wanted = {n for c in obs_cells.values() for n in neighborhood(c)}
    cells = load_cells(conn, wanted)

    def summary_for(cell_keys) -> dict[str, Any]:
        rows = [cells[k] for k in cell_keys if k in cells]
        summary = summarize_cells(rows)
        summary["_frp_count"] = sum(r["frp_count"] for r in rows)
        summary["_frp_sum"] = sum(r["frp_sum"] or 0.0 for r in rows)
        return summary

    # Model inputs per detection, from that detection's own neighbourhood.
    cell_summaries: dict[tuple[int, int], dict] = {}
    feature_rows = []
    for o in observations:
        cell = obs_cells[o.id]
        if cell not in cell_summaries:
            cell_summaries[cell] = summary_for(neighborhood(cell))
        feature_rows.append({
            **observation_features(o),
            **history_features(cell_summaries[cell]),
        })
    probabilities = predict_static_probability(feature_rows)
    prob_by_id = (
        {o.id: p for o, p in zip(observations, probabilities)}
        if probabilities else {}
    )

    centroids = [
        (
            sum(o.longitude for o in g) / len(g),
            sum(o.latitude for o in g) / len(g),
        )
        for g in groups
    ]
    contexts = context_for_points(conn, centroids)

    sites: dict[int, dict] = {}
    if centroids:
        for row in conn.execute(NEAREST_SITE_QUERY, {
            "ids": list(range(len(centroids))),
            "lons": [c[0] for c in centroids],
            "lats": [c[1] for c in centroids],
        }).mappings():
            if row["distance_m"] <= SITE_LINK_M:
                sites[row["pid"]] = _site_dict(row)

    features = []
    category_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()

    for index, (group, (lon, lat), context) in enumerate(
        zip(groups, centroids, contexts)
    ):
        times = [o.observed_at.astimezone(timezone.utc) for o in group]
        start, end = min(times), max(times)
        frp_values = [o.frp for o in group if o.frp is not None]
        brightness = [o.brightness_ti4 for o in group if o.brightness_ti4 is not None]
        confidence = Counter((o.confidence or "").lower() for o in group if o.confidence)
        day_night_values = sorted({o.day_night for o in group if o.day_night})
        day_night = (
            day_night_values[0] if len(day_night_values) == 1
            else "mixed" if day_night_values else "unknown"
        )
        peak_frp = max(frp_values) if frp_values else None

        member_cells = {n for o in group for n in neighborhood(obs_cells[o.id])}
        summary = summary_for(member_cells)
        prior = _prior(summary, start, group)

        probs = [prob_by_id[o.id] for o in group if o.id in prob_by_id]
        model = (
            {"static_probability": round(sum(probs) / len(probs), 3), **(model_card() or {})}
            if probs else None
        )

        event = {
            "event_id": f"AG-{min(o.id for o in group):06d}",
            "observation_count": len(group),
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "start_date_label": start.strftime("%d %b %Y"),
            "span_hours": round((end - start).total_seconds() / 3600, 2),
            "satellites": ", ".join(sorted({o.satellite for o in group if o.satellite})) or "N/A",
            "max_frp_mw": _round(peak_frp),
            "reported_frp_sum_mw": _round(sum(frp_values)) if frp_values else None,
            "max_brightness_ti4": _round(max(brightness)) if brightness else None,
            "confidence_counts": dict(confidence),
            "high_confidence_count": confidence.get("h", 0) + confidence.get("high", 0),
            "day_night": day_night,
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
        }
        assessment = assess_event(
            event=event,
            history=summary,
            prior=prior,
            site=sites.get(index),
            context=context,
            model=model,
        )
        category_counts[assessment["category"]] += 1
        priority_counts[assessment["priority"]["level"]] += 1

        features.append({
            "type": "Feature",
            "id": event["event_id"],
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                **event,
                # Flat copies for map styling and filtering.
                "category": assessment["category"],
                "category_title": assessment["title"],
                "priority_level": assessment["priority"]["level"],
                "priority_score": assessment["priority"]["score"],
                "strength_level": assessment["strength"]["level"],
                "location_pattern": assessment["location_pattern"],
                "site_id": sites[index]["site_id"] if index in sites else None,
                "assessment": assessment,
                "history": _history_dict(summary, prior),
                "site": sites.get(index),
                "context": {
                    **{k: v for k, v in context.items() if k != "features"},
                    "features": context["features"][:8],
                },
                "model": model,
            },
        })

    features.sort(key=lambda f: -f["properties"]["priority_score"])
    result = {
        "type": "FeatureCollection",
        "metadata": {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "days": days,
            "latest_observation": _iso(latest_time),
            "observations": len(observations),
            "events": len(features),
            "category_counts": dict(category_counts),
            "priority_counts": dict(priority_counts),
            "build_seconds": round(time.perf_counter() - started, 2),
        },
        "features": features,
    }
    _cache.clear()
    _cache[cache_key] = (time.monotonic(), result)
    return result


# Properties small enough to ship for every event on the map.
MAP_PROPERTIES = (
    "event_id", "observation_count", "start_time", "end_time", "max_frp_mw",
    "day_night", "category", "category_title", "priority_level",
    "priority_score", "strength_level", "location_pattern", "site_id",
)


def events_map_layer(db: Session, days: int = 14) -> dict[str, Any]:
    full = build_events(db, days)
    return {
        "type": "FeatureCollection",
        "metadata": full["metadata"],
        "features": [
            {
                "type": "Feature",
                "id": f["id"],
                "geometry": f["geometry"],
                "properties": {k: f["properties"][k] for k in MAP_PROPERTIES},
            }
            for f in full["features"]
        ],
    }


def event_detail(db: Session, event_id: str, days: int = 14) -> dict[str, Any] | None:
    full = build_events(db, days)
    return next((f for f in full["features"] if f["id"] == event_id), None)
