"""Archive summaries and published event snapshots.

archive_days and cell_months hold everything the API needs from the
multi-year archive, so a hosted copy can keep only recent raw detections.
event_snapshot_* hold events built by refresh_data.py, so a small hosted
API serves them without loading the model.

Revision ID: 0004_hosting_tables
Revises: 0003_place_labels
"""

from alembic import op


revision = "0004_hosting_tables"
down_revision = "0003_place_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_days (
            day DATE PRIMARY KEY,
            detections INTEGER NOT NULL,
            night INTEGER NOT NULL,
            typed INTEGER NOT NULL,
            nasa_static INTEGER NOT NULL
        )
        """
    )
    # Compact types: 1.4M rows for the 2024-2026 archive.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cell_months (
            cell_x INTEGER NOT NULL,
            cell_y INTEGER NOT NULL,
            month DATE NOT NULL,
            detections SMALLINT NOT NULL,
            night SMALLINT NOT NULL,
            frp_count SMALLINT NOT NULL,
            typed SMALLINT NOT NULL,
            nasa_static SMALLINT NOT NULL,
            frp_sum REAL,
            frp_max REAL,
            PRIMARY KEY (cell_x, cell_y, month)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS event_snapshot_layers (
            name TEXT PRIMARY KEY,
            built_at TIMESTAMPTZ NOT NULL,
            payload JSON NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS event_snapshot_events (
            event_id TEXT PRIMARY KEY,
            payload JSON NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS event_snapshot_events")
    op.execute("DROP TABLE IF EXISTS event_snapshot_layers")
    op.execute("DROP TABLE IF EXISTS cell_months")
    op.execute("DROP TABLE IF EXISTS archive_days")
