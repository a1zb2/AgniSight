"""Expand thermal observation schema.

Revision ID: 0001_expand_thermal_observation_schema
Revises:
"""

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0001_expand_thermal_obs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename our existing brightness field to match FIRMS terminology.
    op.alter_column(
        "thermal_observations",
        "brightness",
        new_column_name="brightness_ti4",
    )

    # Add the new FIRMS fields.
    op.add_column(
        "thermal_observations",
        sa.Column(
            "fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
    )

    op.add_column(
        "thermal_observations",
        sa.Column("scan", sa.Float(), nullable=True),
    )

    op.add_column(
        "thermal_observations",
        sa.Column("track", sa.Float(), nullable=True),
    )

    op.add_column(
        "thermal_observations",
        sa.Column("brightness_ti5", sa.Float(), nullable=True),
    )

    op.add_column(
        "thermal_observations",
        sa.Column("frp", sa.Float(), nullable=True),
    )

    op.add_column(
        "thermal_observations",
        sa.Column(
            "day_night",
            sa.String(length=1),
            nullable=True,
        ),
    )

    op.add_column(
        "thermal_observations",
        sa.Column(
            "processing_version",
            sa.String(length=50),
            nullable=True,
        ),
    )

    # Give existing rows a deterministic fingerprint.
    connection = op.get_bind()

    rows = connection.execute(
        sa.text(
            """
            SELECT
                id,
                source,
                satellite,
                instrument,
                observed_at,
                latitude,
                longitude
            FROM thermal_observations
            """
        )
    ).mappings().all()

    for row in rows:
        fingerprint_input = "|".join(
            [
                row["source"] or "",
                row["satellite"] or "",
                row["instrument"] or "",
                row["observed_at"].isoformat(),
                str(row["latitude"]),
                str(row["longitude"]),
                str(row["id"]),
            ]
        )

        fingerprint = hashlib.sha256(
            fingerprint_input.encode("utf-8")
        ).hexdigest()

        connection.execute(
            sa.text(
                """
                UPDATE thermal_observations
                SET fingerprint = :fingerprint
                WHERE id = :id
                """
            ),
            {
                "fingerprint": fingerprint,
                "id": row["id"],
            },
        )

    op.alter_column(
        "thermal_observations",
        "fingerprint",
        nullable=False,
    )

    op.create_unique_constraint(
        "uq_thermal_observations_fingerprint",
        "thermal_observations",
        ["fingerprint"],
    )

    op.create_index(
        "ix_thermal_observations_observed_at",
        "thermal_observations",
        ["observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_thermal_observations_observed_at",
        table_name="thermal_observations",
    )

    op.drop_constraint(
        "uq_thermal_observations_fingerprint",
        "thermal_observations",
        type_="unique",
    )

    op.drop_column(
        "thermal_observations",
        "processing_version",
    )

    op.drop_column(
        "thermal_observations",
        "day_night",
    )

    op.drop_column(
        "thermal_observations",
        "frp",
    )

    op.drop_column(
        "thermal_observations",
        "brightness_ti5",
    )

    op.drop_column(
        "thermal_observations",
        "track",
    )

    op.drop_column(
        "thermal_observations",
        "scan",
    )

    op.drop_column(
        "thermal_observations",
        "fingerprint",
    )

    op.alter_column(
        "thermal_observations",
        "brightness_ti4",
        new_column_name="brightness",
    )