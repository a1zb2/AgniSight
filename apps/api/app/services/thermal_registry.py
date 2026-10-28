"""Precomputed per-location thermal history (cells) and persistent sites.

thermal_cells: one row per ~400 m cell that has ever had a detection, with
counts, NASA source-type counts and the distinct UTC dates it was active.
Interactive requests read history from here instead of scanning the
multi-year observation table.

cell_months and archive_days: monthly per-cell and daily national totals
for charts. With thermal_cells they hold everything the API needs from the
archive, so a hosted copy can keep only recent raw detections. Ingestion
adds new detections to all three with merge_observations().

thermal_sites: connected groups of cells whose neighbourhood was active in
at least SITE_MIN_MONTHS distinct months. Measured on the 2024-01..2026-06
labeled archive, this rule agrees with NASA's "static land source" label far
better than counting active days (see build report in pipeline_runs).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.services.grid import cell_center, neighborhood
from app.services.spatial_context import context_for_points

SITE_MIN_MONTHS = 6
# A member cell must itself be active in 2+ months, so a single burn next
# to a persistent source does not grow the site.
MEMBER_MIN_MONTHS = 2

CELL_AGGREGATE = """
    SELECT
        agni_cell(longitude) AS cell_x,
        agni_cell(latitude) AS cell_y,
        COUNT(*) AS detection_count,
        COUNT(*) FILTER (WHERE day_night = 'N') AS night_count,
        COUNT(*) FILTER (
            WHERE LOWER(COALESCE(confidence, '')) IN ('h', 'high')
        ) AS high_confidence_count,
        COUNT(frp) AS frp_count,
        SUM(frp) AS frp_sum,
        MAX(frp) AS frp_max,
        COUNT(firms_type) AS typed_count,
        COUNT(*) FILTER (WHERE firms_type = 0) AS type0_count,
        COUNT(*) FILTER (WHERE firms_type = 1) AS type1_count,
        COUNT(*) FILTER (WHERE firms_type = 2) AS type2_count,
        COUNT(*) FILTER (WHERE firms_type = 3) AS type3_count,
        ARRAY_AGG(DISTINCT (observed_at AT TIME ZONE 'UTC')::date)
            AS active_dates,
        MIN(observed_at) AS first_seen,
        MAX(observed_at) AS last_seen
    FROM thermal_observations
    WHERE source = 'NASA_FIRMS' {where}
    GROUP BY 1, 2
"""

CELL_MONTH_AGGREGATE = """
    SELECT
        agni_cell(longitude) AS cell_x,
        agni_cell(latitude) AS cell_y,
        date_trunc('month', observed_at AT TIME ZONE 'UTC')::date AS month,
        COUNT(*) AS detections,
        COUNT(*) FILTER (WHERE day_night = 'N') AS night,
        COUNT(frp) AS frp_count,
        COUNT(firms_type) AS typed,
        COUNT(*) FILTER (WHERE firms_type = 2) AS nasa_static,
        SUM(frp) AS frp_sum,
        MAX(frp) AS frp_max
    FROM thermal_observations
    WHERE source = 'NASA_FIRMS' {where}
    GROUP BY 1, 2, 3
"""

ARCHIVE_DAY_AGGREGATE = """
    SELECT
        (observed_at AT TIME ZONE 'UTC')::date AS day,
        COUNT(*) AS detections,
        COUNT(*) FILTER (WHERE day_night = 'N') AS night,
        COUNT(firms_type) AS typed,
        COUNT(*) FILTER (WHERE firms_type = 2) AS nasa_static
    FROM thermal_observations
    WHERE source = 'NASA_FIRMS' {where}
    GROUP BY 1
"""


def _sum(column: str) -> str:
    return f"{column} = t.{column} + EXCLUDED.{column}"


def _nullable_sum(column: str) -> str:
    # SUM ignores NULLs, so a side with no FRP values does not erase the other.
    return (f"{column} = (SELECT SUM(v) FROM (VALUES (t.{column}), "
            f"(EXCLUDED.{column})) AS s(v))")


# Each summary table: (name, columns, aggregate, how a merge combines rows).
SUMMARIES = (
    ("thermal_cells", (
        "cell_x", "cell_y", "detection_count", "night_count",
        "high_confidence_count", "frp_count", "frp_sum", "frp_max",
        "typed_count", "type0_count", "type1_count", "type2_count",
        "type3_count", "active_dates", "first_seen", "last_seen",
    ), CELL_AGGREGATE, "(cell_x, cell_y)", (
        *map(_sum, ("detection_count", "night_count", "high_confidence_count",
                    "frp_count", "typed_count", "type0_count", "type1_count",
                    "type2_count", "type3_count")),
        _nullable_sum("frp_sum"),
        "frp_max = GREATEST(t.frp_max, EXCLUDED.frp_max)",
        "active_dates = ARRAY(SELECT DISTINCT d FROM unnest("
        "t.active_dates || EXCLUDED.active_dates) AS d ORDER BY d)",
        "first_seen = LEAST(t.first_seen, EXCLUDED.first_seen)",
        "last_seen = GREATEST(t.last_seen, EXCLUDED.last_seen)",
    )),
    ("cell_months", (
        "cell_x", "cell_y", "month", "detections", "night", "frp_count",
        "typed", "nasa_static", "frp_sum", "frp_max",
    ), CELL_MONTH_AGGREGATE, "(cell_x, cell_y, month)", (
        *map(_sum, ("detections", "night", "frp_count", "typed", "nasa_static")),
        _nullable_sum("frp_sum"),
        "frp_max = GREATEST(t.frp_max, EXCLUDED.frp_max)",
    )),
    ("archive_days", (
        "day", "detections", "night", "typed", "nasa_static",
    ), ARCHIVE_DAY_AGGREGATE, "(day)", (
        *map(_sum, ("detections", "night", "typed", "nasa_static")),
    )),
)


def archive_is_pruned(conn: Connection) -> bool:
    """True when raw detections older than the stored history were removed
    (the hosted copy keeps only recent ones), so history cannot be rebuilt."""
    return bool(conn.execute(text("""
        SELECT (SELECT MIN(first_seen) FROM thermal_cells)
             < (SELECT MIN(observed_at) FROM thermal_observations)
    """)).scalar())


def rebuild_history(conn: Connection) -> dict[str, int]:
    """Recompute cells, cell months and archive days from every detection."""
    if archive_is_pruned(conn):
        raise RuntimeError(
            "This database keeps only recent detections; rebuilding would "
            "erase older history. Rebuild on the full archive instead."
        )
    report = {}
    for table, columns, aggregate, _, _ in SUMMARIES:
        conn.execute(text(f"TRUNCATE {table}"))
        report[table] = int(conn.execute(text(
            f"INSERT INTO {table} ({', '.join(columns)}) "
            + aggregate.format(where="")
        )).rowcount)
        conn.execute(text(f"ANALYZE {table}"))
    return report


def merge_observations(conn: Connection, ids: Iterable[int]) -> int:
    """Add newly stored detections to the history tables.

    Works from the new rows alone, so it does not need the older archive.
    Each id must be merged exactly once. Returns the number of cells touched.
    """
    ids = sorted(set(ids))
    if not ids:
        return 0
    touched = 0
    for table, columns, aggregate, key, updates in SUMMARIES:
        result = conn.execute(text(
            f"INSERT INTO {table} AS t ({', '.join(columns)}) "
            + aggregate.format(where="AND id = ANY(CAST(:ids AS integer[]))")
            + f" ON CONFLICT {key} DO UPDATE SET {', '.join(updates)}"
        ), {"ids": ids})
        if table == "thermal_cells":
            touched = int(result.rowcount)
    return touched


def load_cells(
    conn: Connection,
    cells: Iterable[tuple[int, int]],
) -> dict[tuple[int, int], dict[str, Any]]:
    cells = sorted(set(cells))
    if not cells:
        return {}

    rows = conn.execute(text("""
        SELECT c.*
        FROM unnest(CAST(:xs AS integer[]), CAST(:ys AS integer[])) AS k(x, y)
        JOIN thermal_cells AS c ON c.cell_x = k.x AND c.cell_y = k.y
    """), {
        "xs": [c[0] for c in cells],
        "ys": [c[1] for c in cells],
    }).mappings().all()
    return {(r["cell_x"], r["cell_y"]): dict(r) for r in rows}


def _month(d: date) -> tuple[int, int]:
    return d.year, d.month


def summarize_cells(cells: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Combine cell rows into one location history summary."""
    cells = list(cells)
    dates: set[date] = set()
    totals = defaultdict(float)
    frp_max = None
    first = last = None

    for c in cells:
        dates.update(c["active_dates"])
        for key in (
            "detection_count", "night_count", "high_confidence_count",
            "frp_count", "typed_count", "type0_count", "type1_count",
            "type2_count", "type3_count",
        ):
            totals[key] += c[key]
        totals["frp_sum"] += c["frp_sum"] or 0.0
        if c["frp_max"] is not None:
            frp_max = c["frp_max"] if frp_max is None else max(frp_max, c["frp_max"])
        first = c["first_seen"] if first is None else min(first, c["first_seen"])
        last = c["last_seen"] if last is None else max(last, c["last_seen"])

    detections = int(totals["detection_count"])
    typed = int(totals["typed_count"])

    def share(key: str, denominator: int) -> float | None:
        return round(totals[key] / denominator, 3) if denominator else None

    return {
        "detection_count": detections,
        "active_days": len(dates),
        "active_months": len({_month(d) for d in dates}),
        "active_years": len({d.year for d in dates}),
        # Distinct months of the year (1-12): year-round vs seasonal.
        "calendar_months": len({d.month for d in dates}),
        "first_seen": first,
        "last_seen": last,
        "night_share": share("night_count", detections),
        "mean_frp": (
            round(totals["frp_sum"] / totals["frp_count"], 2)
            if totals["frp_count"] else None
        ),
        "max_frp": round(frp_max, 2) if frp_max is not None else None,
        "nasa_typed_count": typed,
        "nasa_vegetation_share": share("type0_count", typed),
        "nasa_volcano_share": share("type1_count", typed),
        "nasa_static_share": share("type2_count", typed),
        "nasa_offshore_share": share("type3_count", typed),
        "dates": dates,
    }


PERSISTENT_MIN_CALENDAR_MONTHS = 8
PERSISTENT_MIN_NIGHT_SHARE = 0.5
SEASONAL_MAX_CALENDAR_MONTHS = 5


def classify_site(summary: dict[str, Any]) -> str:
    """Year-round, night-visible heat vs. seasonally repeated burning.

    Six or more active months alone also catches fields burned every
    season. On the labeled archive, ">= 8 calendar months and mostly night
    detections" kept 98.6% of NASA-static sites; most remaining sites it
    adds are night-dominant and inside or beside mapped industry, i.e.
    plausible static sources that NASA's static mask does not flag.
    """
    if (summary["nasa_static_share"] or 0) >= 0.5:
        return "persistent"
    if (
        summary["calendar_months"] >= PERSISTENT_MIN_CALENDAR_MONTHS
        and (summary["night_share"] or 0) >= PERSISTENT_MIN_NIGHT_SHARE
    ):
        return "persistent"
    if summary["calendar_months"] <= SEASONAL_MAX_CALENDAR_MONTHS:
        return "seasonal"
    return "recurrent"


def build_sites(conn: Connection) -> dict[str, Any]:
    """Rebuild thermal_sites from thermal_cells. Returns a build report."""
    rows = conn.execute(text("""
        SELECT * FROM thermal_cells
        WHERE cardinality(active_dates) >= 2
    """)).mappings().all()
    cells = {(r["cell_x"], r["cell_y"]): dict(r) for r in rows}
    months = {
        key: {_month(d) for d in c["active_dates"]}
        for key, c in cells.items()
    }

    members = set()
    for key, own_months in months.items():
        if len(own_months) < MEMBER_MIN_MONTHS:
            continue
        combined: set[tuple[int, int]] = set()
        for n in neighborhood(key):
            combined |= months.get(n, set())
        if len(combined) >= SITE_MIN_MONTHS:
            members.add(key)

    # Connected components over 8-neighbour adjacency.
    parent = {key: key for key in members}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for key in members:
        for n in neighborhood(key):
            if n in parent and n != key:
                parent[find(n)] = find(key)

    components: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for key in members:
        components[find(key)].append(key)

    sites = []
    for component in components.values():
        footprint = set()
        for key in component:
            footprint.update(n for n in neighborhood(key) if n in cells)
        summary = summarize_cells(cells[k] for k in footprint)

        weight = sum(cells[k]["detection_count"] for k in component)
        lon = sum(cell_center(k)[0] * cells[k]["detection_count"] for k in component) / weight
        lat = sum(cell_center(k)[1] * cells[k]["detection_count"] for k in component) / weight
        anchor = min(component)
        sites.append({
            # Stable while the site's south-west-most member cell persists.
            "site_id": f"S{anchor[1]}-{anchor[0]}",
            "longitude": lon,
            "latitude": lat,
            "cell_count": len(component),
            "site_class": classify_site(summary),
            **{k: v for k, v in summary.items() if k != "dates"},
        })

    contexts = context_for_points(
        conn, [(s["longitude"], s["latitude"]) for s in sites]
    )

    conn.execute(text("TRUNCATE thermal_sites"))
    insert = text("""
        INSERT INTO thermal_sites (
            site_id, latitude, longitude, cell_count, detection_count,
            active_days, active_months, calendar_months, site_class,
            first_seen, last_seen, night_share,
            mean_frp, max_frp, nasa_typed_count, nasa_static_share,
            nasa_offshore_share, context_relation, context_group,
            context_category, context_name, context_osm_id,
            context_distance_m, geometry
        ) VALUES (
            :site_id, :latitude, :longitude, :cell_count, :detection_count,
            :active_days, :active_months, :calendar_months, :site_class,
            :first_seen, :last_seen,
            :night_share, :mean_frp, :max_frp, :nasa_typed_count,
            :nasa_static_share, :nasa_offshore_share, :context_relation,
            :context_group, :context_category, :context_name,
            :context_osm_id, :context_distance_m,
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)
        )
    """)
    payload = []
    for site, context in zip(sites, contexts):
        primary = context["primary"]
        payload.append({
            **{k: site[k] for k in (
                "site_id", "latitude", "longitude", "cell_count",
                "detection_count", "active_days", "active_months",
                "calendar_months", "site_class",
                "first_seen", "last_seen", "mean_frp", "max_frp",
                "nasa_typed_count", "nasa_static_share",
                "nasa_offshore_share",
            )},
            "night_share": site["night_share"] or 0.0,
            "context_relation": context["relation"],
            "context_group": primary["group"] if primary else None,
            "context_category": primary["category"] if primary else None,
            "context_name": primary["name"] if primary else None,
            "context_osm_id": primary["osm_id"] if primary else None,
            "context_distance_m": primary["distance_m"] if primary else None,
        })
    if payload:
        conn.execute(insert, payload)

    return _site_report(conn, cells, members, len(sites))


def _site_report(conn, cells, members, site_count) -> dict[str, Any]:
    """Agreement between the site rule and NASA's static-source label."""
    total_static = conn.execute(text(
        "SELECT COALESCE(SUM(type2_count), 0) FROM thermal_cells"
    )).scalar()
    member_typed = sum(cells[k]["typed_count"] for k in members)
    member_static = sum(cells[k]["type2_count"] for k in members)
    classes = dict(conn.execute(text("""
        SELECT site_class, COUNT(*) FROM thermal_sites GROUP BY 1
    """)).all())
    persistent_unflagged = conn.execute(text("""
        SELECT COUNT(*) FROM thermal_sites
        WHERE site_class = 'persistent'
          AND COALESCE(nasa_static_share, 0) < 0.5
          AND nasa_typed_count >= 5
    """)).scalar()
    return {
        "site_count": site_count,
        "site_classes": classes,
        "persistent_sites_not_flagged_static_by_nasa": persistent_unflagged,
        "member_cells": len(members),
        "rule": f"neighbourhood active in >= {SITE_MIN_MONTHS} distinct months; "
                f"member cell active in >= {MEMBER_MIN_MONTHS} months",
        "nasa_static_share_of_site_detections": (
            round(member_static / member_typed, 3) if member_typed else None
        ),
        "share_of_all_nasa_static_detections_in_sites": (
            round(member_static / total_static, 3) if total_static else None
        ),
    }
