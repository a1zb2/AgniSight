
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine

from app.core.config import settings


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = ROOT / "data" / "firms" / "archive" / "827421"

FILES = [
    ARCHIVE_DIR / "fire_archive_J2V-C2_827421.csv",
    ARCHIVE_DIR / "fire_nrt_J2V-C2_827421.csv",
]

SOURCE = "NASA_FIRMS"

COLUMNS = [
    "fingerprint", "source", "satellite", "instrument", "observed_at",
    "latitude", "longitude", "brightness_ti4", "scan", "track",
    "brightness_ti5", "frp", "confidence", "day_night",
    "processing_version", "firms_type",
]

CREATE_STAGE = """
CREATE TEMP TABLE agnisight_firms_import_stage (
    fingerprint VARCHAR(64) NOT NULL,
    source VARCHAR(50) NOT NULL,
    satellite VARCHAR(50),
    instrument VARCHAR(50),
    observed_at TIMESTAMPTZ NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    brightness_ti4 DOUBLE PRECISION,
    scan DOUBLE PRECISION,
    track DOUBLE PRECISION,
    brightness_ti5 DOUBLE PRECISION,
    frp DOUBLE PRECISION,
    confidence VARCHAR(50),
    day_night VARCHAR(10),
    processing_version VARCHAR(50),
    firms_type SMALLINT
) ON COMMIT PRESERVE ROWS
"""

COPY_SQL = (
    "COPY agnisight_firms_import_stage ("
    + ", ".join(COLUMNS)
    + ") FROM STDIN WITH (FORMAT CSV, NULL '')"
)

INSERT_SQL = """
INSERT INTO thermal_observations (
    fingerprint, source, satellite, instrument, observed_at,
    latitude, longitude, brightness_ti4, scan, track,
    brightness_ti5, frp, confidence, day_night,
    processing_version, firms_type, geometry
)
SELECT
    fingerprint, source, satellite, instrument, observed_at,
    latitude, longitude, brightness_ti4, scan, track,
    brightness_ti5, frp, confidence, day_night,
    processing_version, firms_type,
    ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
FROM agnisight_firms_import_stage
ON CONFLICT (fingerprint) DO NOTHING
"""

# Fill the NASA type for rows imported before firms_type was stored.
BACKFILL_TYPE_SQL = """
UPDATE thermal_observations AS t
SET firms_type = s.firms_type
FROM agnisight_firms_import_stage AS s
WHERE t.fingerprint = s.fingerprint
  AND s.firms_type IS NOT NULL
  AND t.firms_type IS DISTINCT FROM s.firms_type
"""


def number(value, field, filename, line, required=False):
    if value is None or not value.strip():
        if required:
            raise ValueError(
                f"{filename}, line {line}: missing {field}"
            )
        return None

    result = float(value)
    if not math.isfinite(result):
        raise ValueError(
            f"{filename}, line {line}: invalid {field}={value!r}"
        )
    return result


def fingerprint(record, latitude, longitude):
    # Intentionally identical to the live FIRMS ingestion service.
    fingerprint_input = "|".join([
        SOURCE,
        record.get("satellite") or "",
        record.get("instrument") or "",
        record["acq_date"],
        record["acq_time"],
        str(latitude),
        str(longitude),
        record.get("version") or "",
    ])
    return hashlib.sha256(
        fingerprint_input.encode("utf-8")
    ).hexdigest()


def convert_file(path, writer):
    required_columns = {
        "latitude", "longitude", "brightness", "scan", "track",
        "acq_date", "acq_time", "satellite", "instrument",
        "confidence", "version", "bright_t31", "frp", "daynight",
    }

    count = 0
    earliest = None
    latest = None

    with path.open(
        "r", newline="", encoding="utf-8-sig"
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(f"{path.name}: missing CSV header")

        missing = required_columns - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"{path.name}: missing columns {sorted(missing)}"
            )

        for line, record in enumerate(reader, start=2):
            latitude = number(
                record.get("latitude"), "latitude",
                path.name, line, required=True
            )
            longitude = number(
                record.get("longitude"), "longitude",
                path.name, line, required=True
            )

            if not -90 <= latitude <= 90:
                raise ValueError(
                    f"{path.name}, line {line}: invalid latitude"
                )
            if not -180 <= longitude <= 180:
                raise ValueError(
                    f"{path.name}, line {line}: invalid longitude"
                )

            acq_date = record["acq_date"].strip()
            acq_time = record["acq_time"].strip()

            observed_at = datetime.strptime(
                f"{acq_date} {acq_time.zfill(4)}",
                "%Y-%m-%d %H%M",
            ).replace(tzinfo=timezone.utc)

            version = record.get("version") or None
            satellite = record.get("satellite") or None
            instrument = record.get("instrument") or None

            fp = fingerprint(
                record, latitude, longitude
            )

            brightness = number(
                record.get("brightness"), "brightness",
                path.name, line
            )
            scan = number(
                record.get("scan"), "scan", path.name, line
            )
            track = number(
                record.get("track"), "track", path.name, line
            )
            bright_t31 = number(
                record.get("bright_t31"), "bright_t31",
                path.name, line
            )
            frp = number(
                record.get("frp"), "frp", path.name, line
            )
            # Only standard-processing archive files carry "type".
            firms_type = (record.get("type") or "").strip()
            if firms_type and firms_type not in {"0", "1", "2", "3"}:
                raise ValueError(
                    f"{path.name}, line {line}: invalid type={firms_type!r}"
                )

            writer.writerow([
                fp,
                SOURCE,
                satellite,
                instrument,
                observed_at.isoformat(),
                latitude,
                longitude,
                brightness,
                scan,
                track,
                bright_t31,
                frp,
                record.get("confidence") or None,
                record.get("daynight") or None,
                version,
                firms_type or None,
            ])

            count += 1
            earliest = (
                observed_at
                if earliest is None
                else min(earliest, observed_at)
            )
            latest = (
                observed_at
                if latest is None
                else max(latest, observed_at)
            )

            if count % 250_000 == 0:
                print(
                    f"  {path.name}: {count:,} rows processed",
                    flush=True,
                )

    print(f"  {path.name}: {count:,} rows processed")
    return count, earliest, latest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Insert the observations. Without this flag, run a dry run.",
    )
    parser.add_argument(
        "--backfill-type",
        action="store_true",
        help="With --commit, also set firms_type on already-imported rows.",
    )
    args = parser.parse_args()

    missing = [str(path) for path in FILES if not path.is_file()]
    if missing:
        print("Missing input files:", *missing, sep="\n", file=sys.stderr)
        return 2

    print(
        "Mode:",
        "IMPORT — DATABASE WILL CHANGE"
        if args.commit
        else "DRY RUN — NO PERSISTENT DATA CHANGES",
    )
    print(f"Archive: {ARCHIVE_DIR}")

    engine = create_engine(
        str(settings.database_url),
        pool_pre_ping=True,
    )
    connection = None
    cursor = None

    try:
        with tempfile.TemporaryDirectory(
            prefix="agnisight-firms-"
        ) as temp_dir:
            staging_file = Path(temp_dir) / "staging.csv"
            total_rows = 0
            date_min = None
            date_max = None

            # Transform the NASA files into one streaming-friendly CSV.
            with staging_file.open(
                "w", newline="", encoding="utf-8"
            ) as output:
                writer = csv.writer(output, lineterminator="\n")

                for path in FILES:
                    count, earliest, latest = convert_file(
                        path, writer
                    )
                    total_rows += count

                    if earliest is not None:
                        date_min = (
                            earliest if date_min is None
                            else min(date_min, earliest)
                        )
                        date_max = (
                            latest if date_max is None
                            else max(date_max, latest)
                        )

            print(f"\nSource rows: {total_rows:,}")
            print(f"Observation range: {date_min} to {date_max}")
            print(
                f"Temporary staging size: "
                f"{staging_file.stat().st_size:,} bytes"
            )
            print("Loading temporary PostgreSQL staging table...")

            connection = engine.raw_connection()
            cursor = connection.cursor()
            cursor.execute(CREATE_STAGE)

            if hasattr(cursor, "copy_expert"):
                # psycopg2 driver
                with staging_file.open(
                    "r", newline="", encoding="utf-8"
                ) as input_file:
                    cursor.copy_expert(COPY_SQL, input_file)

            elif hasattr(cursor, "copy"):
                # psycopg 3 driver: stream the file in 1 MB chunks
                with staging_file.open("rb") as input_file:
                    with cursor.copy(COPY_SQL) as copy:
                        while True:
                            chunk = input_file.read(1024 * 1024)
                            if not chunk:
                                break
                            copy.write(chunk)

            else:
             raise RuntimeError(
                    "Unsupported PostgreSQL COPY interface: "
                    f"{type(cursor).__module__}.{type(cursor).__name__}"
                )

            cursor.execute(
                "CREATE INDEX agnisight_firms_stage_fp_idx "
                "ON agnisight_firms_import_stage (fingerprint)"
            )
            cursor.execute(
                "ANALYZE agnisight_firms_import_stage"
            )

            cursor.execute("""
                SELECT COUNT(*),
                       COUNT(DISTINCT fingerprint),
                       MIN(observed_at),
                       MAX(observed_at)
                FROM agnisight_firms_import_stage
            """)
            staged, distinct, first, last = cursor.fetchone()

            cursor.execute("""
                SELECT COUNT(DISTINCT s.fingerprint)
                FROM agnisight_firms_import_stage s
                JOIN thermal_observations t
                  ON t.fingerprint = s.fingerprint
            """)
            existing = int(cursor.fetchone()[0])

            print("\nPreflight summary")
            print(f"  Staged rows:              {int(staged):,}")
            print(f"  Unique fingerprints:      {int(distinct):,}")
            print(
                "  Duplicate fingerprints "
                f"inside files:            {int(staged) - int(distinct):,}"
            )
            print(f"  Already in database:      {existing:,}")
            print(f"  Estimated new records:     {int(distinct) - existing:,}")
            print(f"  Staged date range:         {first} to {last}")

            if args.commit:
                print("\nImporting records. Please keep this terminal open...")
                cursor.execute(INSERT_SQL)
                inserted = int(cursor.rowcount)

                if args.backfill_type:
                    cursor.execute(BACKFILL_TYPE_SQL)
                    print(f"  firms_type backfilled: {int(cursor.rowcount):,}")
                connection.commit()

                print("\nIMPORT COMMITTED")
                print(f"  Inserted: {inserted:,}")
                print(f"  Not inserted: {int(staged) - inserted:,}")

                cursor.execute("""
                    SELECT COUNT(*),
                           COUNT(DISTINCT
                               (observed_at AT TIME ZONE 'UTC')::date),
                           MIN(observed_at),
                           MAX(observed_at)
                    FROM thermal_observations
                    WHERE source = %s
                """, (SOURCE,))
                total, days, minimum, maximum = cursor.fetchone()

                print(f"  Total FIRMS observations: {int(total):,}")
                print(f"  Distinct UTC dates:       {int(days):,}")
                print(f"  Database date range:      {minimum} to {maximum}")
            else:
                connection.rollback()
                print("\nDRY RUN COMPLETE")
                print("No persistent database changes were made.")
                print("Review the summary before running with --commit.")

        return 0

    except Exception as exc:
        if connection is not None:
            connection.rollback()
        print(f"\nIMPORT FAILED: {exc}", file=sys.stderr)
        print("No uncommitted changes were retained.", file=sys.stderr)
        return 1

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
