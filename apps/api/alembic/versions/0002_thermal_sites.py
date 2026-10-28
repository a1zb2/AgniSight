"""Store NASA source type and add derived site/context tables.

All tables added here are derived from thermal_observations and the
imported OSM tables; build_thermal_registry.py repopulates them.

Revision ID: 0002_thermal_sites
Revises: 0001_expand_thermal_obs
"""

from alembic import op


revision = "0002_thermal_sites"
down_revision = "0001_expand_thermal_obs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NASA FIRMS "type" (0 vegetation, 1 volcano, 2 static land, 3 offshore).
    # Only the standard-processing archive carries it; NRT rows stay NULL.
    op.execute(
        "ALTER TABLE thermal_observations "
        "ADD COLUMN IF NOT EXISTS firms_type SMALLINT"
    )

    # ~400 m grid cell (about one VIIRS I-band pixel). Python code computes
    # the same value with math.floor(value / 0.004).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION agni_cell(value double precision)
        RETURNS integer
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS 'SELECT floor(value / 0.004::double precision)::integer'
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_thermal_observations_cell "
        "ON thermal_observations "
        "(agni_cell(longitude), agni_cell(latitude))"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS osm_context_features (
            id SERIAL PRIMARY KEY,
            osm_type TEXT NOT NULL,
            osm_id TEXT NOT NULL,
            name TEXT,
            category TEXT NOT NULL,
            feature_group TEXT NOT NULL,
            thermal_relevance TEXT NOT NULL,
            is_area BOOLEAN NOT NULL,
            geometry geometry(Geometry, 4326) NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_osm_context_features_geometry "
        "ON osm_context_features USING gist (geometry)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS thermal_cells (
            cell_x INTEGER NOT NULL,
            cell_y INTEGER NOT NULL,
            detection_count INTEGER NOT NULL,
            night_count INTEGER NOT NULL,
            high_confidence_count INTEGER NOT NULL,
            frp_count INTEGER NOT NULL,
            frp_sum DOUBLE PRECISION,
            frp_max DOUBLE PRECISION,
            typed_count INTEGER NOT NULL,
            type0_count INTEGER NOT NULL,
            type1_count INTEGER NOT NULL,
            type2_count INTEGER NOT NULL,
            type3_count INTEGER NOT NULL,
            active_dates DATE[] NOT NULL,
            first_seen TIMESTAMPTZ NOT NULL,
            last_seen TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (cell_x, cell_y)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS thermal_sites (
            site_id TEXT PRIMARY KEY,
            latitude DOUBLE PRECISION NOT NULL,
            longitude DOUBLE PRECISION NOT NULL,
            cell_count INTEGER NOT NULL,
            detection_count INTEGER NOT NULL,
            active_days INTEGER NOT NULL,
            active_months INTEGER NOT NULL,
            calendar_months INTEGER NOT NULL,
            site_class TEXT NOT NULL,
            first_seen TIMESTAMPTZ NOT NULL,
            last_seen TIMESTAMPTZ NOT NULL,
            night_share DOUBLE PRECISION NOT NULL,
            mean_frp DOUBLE PRECISION,
            max_frp DOUBLE PRECISION,
            nasa_typed_count INTEGER NOT NULL,
            nasa_static_share DOUBLE PRECISION,
            nasa_offshore_share DOUBLE PRECISION,
            context_relation TEXT NOT NULL,
            context_group TEXT,
            context_category TEXT,
            context_name TEXT,
            context_osm_id TEXT,
            context_distance_m DOUBLE PRECISION,
            geometry geometry(Point, 4326) NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_thermal_sites_geometry "
        "ON thermal_sites USING gist (geometry)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id SERIAL PRIMARY KEY,
            kind TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'running',
            details JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pipeline_runs_kind_started "
        "ON pipeline_runs (kind, started_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pipeline_runs")
    op.execute("DROP TABLE IF EXISTS thermal_sites")
    op.execute("DROP TABLE IF EXISTS thermal_cells")
    op.execute("DROP TABLE IF EXISTS osm_context_features")
    op.execute("DROP INDEX IF EXISTS ix_thermal_observations_cell")
    op.execute("DROP FUNCTION IF EXISTS agni_cell(double precision)")
    op.execute(
        "ALTER TABLE thermal_observations DROP COLUMN IF EXISTS firms_type"
    )
