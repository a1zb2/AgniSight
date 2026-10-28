"""Human-readable location labels: nearest settlement, district, state.

Built from OpenStreetMap place nodes and administrative boundaries. Labels
help people scan and discuss events; they are not used as evidence.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection

NEAREST_PLACE_KM = 15.0

# Prefer the English name when the local name is in another script.
PLACE_NAME = """
    CASE
        WHEN name ~ '^[[:ascii:]]+$' THEN name
        ELSE COALESCE(substring(other_tags from '"name:en"=>"([^"]+)"'), name)
    END
"""


def build_place_tables(conn: Connection) -> dict[str, int]:
    has_sources = conn.execute(text("""
        SELECT to_regclass('public.osm_places') IS NOT NULL
           AND to_regclass('public.osm_admin_areas') IS NOT NULL
    """)).scalar()
    if not has_sources:
        return {"place_points": 0, "admin_area_parts": 0}

    conn.execute(text("TRUNCATE place_points RESTART IDENTITY"))
    places = conn.execute(text(f"""
        INSERT INTO place_points (name, kind, geometry)
        SELECT {PLACE_NAME}, place, geometry
        FROM osm_places
        WHERE name IS NOT NULL AND geometry IS NOT NULL
    """)).rowcount

    conn.execute(text("TRUNCATE admin_area_parts RESTART IDENTITY"))
    parts = conn.execute(text(f"""
        INSERT INTO admin_area_parts (admin_level, name, geometry)
        SELECT admin_level::smallint, {PLACE_NAME},
               -- ~50 m simplification is ample for naming a district.
               ST_Subdivide(ST_MakeValid(ST_SimplifyPreserveTopology(geometry, 0.0005)), 128)
        FROM osm_admin_areas
        WHERE name IS NOT NULL AND admin_level IN ('4', '5')
    """)).rowcount

    conn.execute(text("ANALYZE place_points"))
    conn.execute(text("ANALYZE admin_area_parts"))
    return {"place_points": int(places), "admin_area_parts": int(parts)}


PLACE_QUERY = text("""
    WITH pts AS (
        SELECT pid, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
        FROM unnest(
            CAST(:ids AS integer[]),
            CAST(:lons AS double precision[]),
            CAST(:lats AS double precision[])
        ) AS t(pid, lon, lat)
    )
    SELECT
        p.pid,
        near.name, near.kind,
        ST_Distance(near.geometry::geography, p.g::geography) / 1000 AS distance_km,
        (SELECT a.name FROM admin_area_parts a
         WHERE a.admin_level = 5 AND ST_Intersects(a.geometry, p.g) LIMIT 1) AS district,
        (SELECT a.name FROM admin_area_parts a
         WHERE a.admin_level = 4 AND ST_Intersects(a.geometry, p.g) LIMIT 1) AS state
    FROM pts AS p
    LEFT JOIN LATERAL (
        SELECT name, kind, geometry FROM place_points
        WHERE geometry && ST_Expand(p.g, 0.2)
        ORDER BY geometry <-> p.g
        LIMIT 1
    ) AS near ON TRUE
""")


def _label(row: Any) -> str | None:
    region = ", ".join(v for v in (row["district"], row["state"]) if v)
    near = (
        row["name"]
        if row["name"] and row["distance_km"] is not None
        and row["distance_km"] <= NEAREST_PLACE_KM
        else None
    )
    if near and region:
        return f"{near} · {region}"
    return near or region or None


def places_for_points(
    conn: Connection,
    points: Iterable[tuple[float, float]],
) -> list[dict[str, Any] | None]:
    """Label each (longitude, latitude); None where nothing is known."""
    points = list(points)
    if not points:
        return []
    if not conn.execute(text("SELECT EXISTS (SELECT 1 FROM place_points)")).scalar():
        return [None] * len(points)

    rows = conn.execute(PLACE_QUERY, {
        "ids": list(range(len(points))),
        "lons": [p[0] for p in points],
        "lats": [p[1] for p in points],
    }).mappings().all()

    result: list[dict[str, Any] | None] = [None] * len(points)
    for row in rows:
        result[row["pid"]] = {
            "name": row["name"],
            "kind": row["kind"],
            "distance_km": (
                round(float(row["distance_km"]), 1)
                if row["distance_km"] is not None else None
            ),
            "district": row["district"],
            "state": row["state"],
            "label": _label(row),
        }
    return result
