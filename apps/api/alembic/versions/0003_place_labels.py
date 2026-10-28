"""Derived tables for human-readable event locations.

Source tables osm_places and osm_admin_areas are imported from the
Geofabrik India extract by scripts/import-osm-places.ps1; these derived
copies are rebuilt by build_thermal_registry.py.

Revision ID: 0003_place_labels
Revises: 0002_thermal_sites
"""

from alembic import op


revision = "0003_place_labels"
down_revision = "0002_thermal_sites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS place_points (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            geometry geometry(Point, 4326) NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_place_points_geometry "
        "ON place_points USING gist (geometry)"
    )
    # States (admin_level 4) and districts (5), cut into small pieces so
    # point-in-polygon tests stay fast.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_area_parts (
            id SERIAL PRIMARY KEY,
            admin_level SMALLINT NOT NULL,
            name TEXT NOT NULL,
            geometry geometry(Polygon, 4326) NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_area_parts_geometry "
        "ON admin_area_parts USING gist (geometry)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_area_parts")
    op.execute("DROP TABLE IF EXISTS place_points")
