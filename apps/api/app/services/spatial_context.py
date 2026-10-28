"""Mapped-infrastructure context from the local OpenStreetMap extract.

osm_context_features is a normalized copy of the relevant OSM points,
lines and polygons: one row per OSM object, one category, a feature group
and a thermal relevance. Relevance says how plausible a feature is as a
heat source; it is context for an assessment, never proof of causation.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Distances are measured from the event or site centroid.
PIXEL_M = 375.0  # VIIRS I-band pixel at nadir
NEARBY_M = 1500.0
RELEVANCE_RANK = {"high": 0, "medium": 1, "low": 2}

GROUP_LABELS = {
    "thermal_power": "Thermal power plant",
    "brick_kiln": "Brick kiln",
    "heavy_industry": "Heavy industry",
    "industrial_area": "Industrial area",
    "extraction": "Quarry / mine",
    "waste": "Landfill / waste",
    "storage": "Storage / depot",
    "other_power": "Power plant (non-combustion)",
    "utility": "Utility infrastructure",
}


# Large plants are often mapped only as landuse=industrial with a name.
# A name match is weaker evidence than a tag and is labelled as such.
NAME_PATTERN = (
    "'(steel|refiner|cement|smelter|thermal power|super thermal|ntpc|"
    "coke|sponge iron|ferro[ -]?alloy|alumin|fertili[sz]er|petrochem|"
    "distiller)'"
)


def _tag(alias: str, key: str) -> str:
    return (
        f"substring(COALESCE({alias}.other_tags, '') "
        f"from '\"{key}\"=>\"([^\"]+)\"')"
    )


def _classified_select(table: str, osm_type_sql: str, osm_id_sql: str,
                       landuse: str, building: str, is_area: bool) -> str:
    a = "s"
    power = _tag(a, "power")
    source = _tag(a, "plant:source")
    industrial = _tag(a, "industrial")
    product = _tag(a, "product")
    landuse = landuse or _tag(a, "landuse")
    building = building or _tag(a, "building")

    # Order matters: the most specific, most heat-relevant rule wins.
    return f"""
        SELECT
            {osm_type_sql} AS osm_type,
            {osm_id_sql} AS osm_id,
            NULLIF({a}.name, '') AS name,
            c.category, c.feature_group, c.thermal_relevance,
            {str(is_area).upper()} AS is_area,
            {a}.geometry
        FROM {table} AS {a}
        CROSS JOIN LATERAL (
            SELECT {power} AS power, {source} AS source,
                   {industrial} AS industrial, {product} AS product,
                   {landuse} AS landuse, {building} AS building
        ) AS t
        CROSS JOIN LATERAL (
            SELECT * FROM (VALUES (
                CASE
                    WHEN t.power = 'plant'
                     AND t.source ~ '(coal|gas|oil|diesel|biomass|waste)'
                        THEN 'Thermal power plant (' || t.source || ')'
                    WHEN t.power = 'plant'
                        THEN 'Power plant ('
                             || COALESCE(t.source, 'source not mapped') || ')'
                    WHEN {a}.man_made = 'kiln'
                      OR t.industrial IN ('brickyard', 'brickworks')
                      OR t.product IN ('brick', 'bricks')
                        THEN 'Brick kiln'
                    WHEN t.industrial ~ '(refinery|oil|steel|cement|chemical|smelter|foundry|metal|petrochemical|fertili[sz]er|gas|glass|sugar|distillery)'
                        THEN 'Heavy industry (' || t.industrial || ')'
                    WHEN {a}.name ~* {NAME_PATTERN}
                        THEN 'Heavy industry (inferred from name)'
                    WHEN {a}.man_made = 'chimney' THEN 'Industrial chimney'
                    WHEN {a}.man_made IN ('cooling', 'cooling_tower')
                        THEN 'Cooling tower'
                    WHEN {a}.man_made = 'works' THEN 'Industrial works'
                    WHEN {a}.man_made = 'coal_pile' THEN 'Coal stockpile'
                    WHEN t.industrial = 'mine' OR t.landuse = 'quarry'
                        THEN 'Quarry / mine'
                    WHEN t.landuse = 'landfill' THEN 'Landfill'
                    WHEN {a}.man_made = 'storage_tank' THEN 'Storage tank'
                    WHEN t.industrial IN ('depot', 'warehouse', 'storage', 'port', 'bus_depot')
                        THEN 'Depot / warehouse'
                    WHEN t.power = 'substation' THEN 'Electrical substation'
                    WHEN {a}.man_made IN ('wastewater_plant', 'water_works', 'pumping_station')
                        THEN 'Water / wastewater works'
                    WHEN t.landuse = 'industrial' THEN 'Industrial area'
                    WHEN t.building = 'industrial' THEN 'Industrial building'
                    WHEN t.industrial IS NOT NULL
                        THEN 'Industrial facility (' || t.industrial || ')'
                END,
                CASE
                    WHEN t.power = 'plant'
                     AND t.source ~ '(coal|gas|oil|diesel|biomass|waste)'
                        THEN 'thermal_power'
                    WHEN t.power = 'plant' THEN 'other_power'
                    WHEN {a}.man_made = 'kiln'
                      OR t.industrial IN ('brickyard', 'brickworks')
                      OR t.product IN ('brick', 'bricks')
                        THEN 'brick_kiln'
                    WHEN t.industrial ~ '(refinery|oil|steel|cement|chemical|smelter|foundry|metal|petrochemical|fertili[sz]er|gas|glass|sugar|distillery)'
                      OR {a}.name ~* {NAME_PATTERN}
                      OR {a}.man_made IN ('chimney', 'cooling', 'cooling_tower', 'works', 'coal_pile')
                        THEN 'heavy_industry'
                    WHEN t.industrial = 'mine' OR t.landuse = 'quarry'
                        THEN 'extraction'
                    WHEN t.landuse = 'landfill' THEN 'waste'
                    WHEN {a}.man_made = 'storage_tank'
                      OR t.industrial IN ('depot', 'warehouse', 'storage', 'port', 'bus_depot')
                        THEN 'storage'
                    WHEN t.power = 'substation'
                      OR {a}.man_made IN ('wastewater_plant', 'water_works', 'pumping_station')
                        THEN 'utility'
                    WHEN t.landuse = 'industrial' OR t.building = 'industrial'
                      OR t.industrial IS NOT NULL
                        THEN 'industrial_area'
                END
            )) AS v(category, feature_group)
            CROSS JOIN LATERAL (
                SELECT CASE
                    WHEN v.feature_group IN ('thermal_power', 'brick_kiln', 'heavy_industry')
                        THEN 'high'
                    WHEN v.feature_group IN ('industrial_area', 'extraction', 'waste', 'storage')
                        THEN 'medium'
                    WHEN v.feature_group = 'other_power' AND t.source IS NULL
                        THEN 'medium'
                    ELSE 'low'
                END AS thermal_relevance
            ) AS r
        ) AS c
        WHERE c.category IS NOT NULL AND {a}.geometry IS NOT NULL
    """


def build_context_features(conn: Connection) -> int:
    """Rebuild osm_context_features from the imported OSM tables."""
    selects = [
        _classified_select("public.osm_multipolygons",
                           "CASE WHEN s.osm_id IS NOT NULL THEN 'relation' ELSE 'way' END",
                           "COALESCE(s.osm_id, s.osm_way_id)",
                           "s.landuse", "s.building", True),
        _classified_select("public.osm_lines", "'way'", "s.osm_id",
                           "", "", False),
        _classified_select("public.osm_points", "'node'", "s.osm_id",
                           "", "", False),
    ]
    conn.execute(text("TRUNCATE osm_context_features RESTART IDENTITY"))
    # A closed way can appear both as a line and as a polygon; keep the
    # polygon, which supports point-in-area tests.
    result = conn.execute(text(f"""
        INSERT INTO osm_context_features (
            osm_type, osm_id, name, category, feature_group,
            thermal_relevance, is_area, geometry
        )
        SELECT DISTINCT ON (osm_type, osm_id)
            osm_type, osm_id, name, category, feature_group,
            thermal_relevance, is_area, geometry
        FROM ({' UNION ALL '.join(selects)}) AS classified
        WHERE osm_id IS NOT NULL
        ORDER BY osm_type, osm_id, is_area DESC
    """))
    conn.execute(text("ANALYZE osm_context_features"))
    return int(result.rowcount)


CONTEXT_QUERY = text("""
    WITH pts AS (
        SELECT pid, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
        FROM unnest(
            CAST(:ids AS integer[]),
            CAST(:lons AS double precision[]),
            CAST(:lats AS double precision[])
        ) AS t(pid, lon, lat)
    )
    SELECT
        p.pid, f.osm_type, f.osm_id, f.name, f.category,
        f.feature_group, f.thermal_relevance, f.is_area,
        ST_Distance(f.geometry::geography, p.g::geography) AS distance_m,
        ST_Y(ST_ClosestPoint(f.geometry, p.g)) AS latitude,
        ST_X(ST_ClosestPoint(f.geometry, p.g)) AS longitude
    FROM pts AS p
    JOIN osm_context_features AS f
      ON f.geometry && ST_Expand(p.g, CAST(:bbox_deg AS double precision))
     AND ST_DWithin(f.geometry::geography, p.g::geography,
                    CAST(:radius_m AS double precision))
""")


def relation_for(distance_m: float, is_area: bool) -> str:
    if is_area and distance_m <= 1.0:
        return "inside"
    if distance_m <= PIXEL_M:
        return "adjacent"
    if distance_m <= NEARBY_M:
        return "nearby"
    return "vicinity"


def _feature(row: Any) -> dict[str, Any]:
    distance = float(row["distance_m"])
    return {
        "osm_id": f"{row['osm_type']}/{row['osm_id']}",
        "name": row["name"],
        "category": row["category"],
        "group": row["feature_group"],
        "group_label": GROUP_LABELS.get(row["feature_group"], row["feature_group"]),
        "thermal_relevance": row["thermal_relevance"],
        "distance_m": round(distance, 1),
        "relation": relation_for(distance, bool(row["is_area"])),
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
    }


def summarize(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the primary feature and summarize what is mapped around a point.

    The primary feature is the most heat-relevant one at pixel scale
    (inside or within 375 m); failing that, the most relevant within
    1.5 km. A relevant feature beats a closer, irrelevant one.
    """
    band = {"inside": 0, "adjacent": 0, "nearby": 1, "vicinity": 2}
    ranked = sorted(
        features,
        key=lambda f: (
            band[f["relation"]],
            RELEVANCE_RANK[f["thermal_relevance"]],
            f["distance_m"],
        ),
    )
    within = [f for f in ranked if f["relation"] != "vicinity"]
    primary = within[0] if within else None
    containing = next(
        (f for f in ranked if f["relation"] == "inside"), None
    )

    group_counts: dict[str, int] = {}
    for f in within:
        group_counts[f["group"]] = group_counts.get(f["group"], 0) + 1

    return {
        "relation": primary["relation"] if primary else "none",
        "primary": primary,
        "containing_area": containing,
        "group_counts_1500m": group_counts,
        "feature_count_1500m": len(within),
        "features": ranked[:12],
    }


def context_for_points(
    conn: Connection,
    points: Iterable[tuple[float, float]],
    radius_m: float = NEARBY_M,
) -> list[dict[str, Any]]:
    """Return a context summary for each (longitude, latitude) point."""
    points = list(points)
    if not points:
        return []

    rows = conn.execute(CONTEXT_QUERY, {
        "ids": list(range(len(points))),
        "lons": [p[0] for p in points],
        "lats": [p[1] for p in points],
        "radius_m": radius_m,
        # Generous degree box so ST_DWithin can use the GiST index.
        "bbox_deg": radius_m / 111_000 * 1.6,
    }).mappings().all()

    by_point: list[list[dict[str, Any]]] = [[] for _ in points]
    for row in rows:
        by_point[row["pid"]].append(_feature(row))

    return [summarize(features) for features in by_point]
