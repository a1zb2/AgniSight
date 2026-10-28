"""Copy the slim hosted database (Neon) from the local one.

The hosted copy holds the history summaries, sites, map context and place
labels in full, but raw detections only for the last --keep-days. The
local archive is only read.

Put the Neon connection string in apps/api/.env.hosted (git-ignored):

    HOSTED_DATABASE_URL=postgresql://user:password@host/neondb?sslmode=require

then run from apps/api:

    python publish_hosted_db.py             # first copy, then publish events
    python publish_hosted_db.py --replace   # drop and recopy hosted tables

Data streams between the local Docker container's pg_dump and psql and the
hosted server; nothing is written to disk.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

CONTAINER = "agnisight-db"
SOURCE = ["-U", "agnisight", "-d", "agnisight"]

# Copied in full.
TABLES = [
    "thermal_cells", "cell_months", "archive_days", "thermal_sites",
    "osm_context_features", "place_points", "admin_area_parts",
    "pipeline_runs", "alembic_version",
]
# Schema only: published by refresh_data.py on the hosted copy.
EMPTY_TABLES = ["event_snapshot_layers", "event_snapshot_events"]
OBSERVATIONS = "thermal_observations"

SETUP_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE OR REPLACE FUNCTION public.agni_cell(value double precision)
RETURNS integer
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS 'SELECT floor(value / 0.004::double precision)::integer';
"""


def hosted_url() -> str:
    url = os.environ.get("HOSTED_DATABASE_URL")
    env_file = Path(__file__).with_name(".env.hosted")
    if not url and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "HOSTED_DATABASE_URL":
                url = value.strip().strip('"')
    if not url:
        sys.exit("Set HOSTED_DATABASE_URL in apps/api/.env.hosted")
    if "localhost" in url or "127.0.0.1" in url:
        sys.exit("HOSTED_DATABASE_URL points at this machine; refusing.")
    # psql takes plain libpq URLs.
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def in_container(script: str, url: str, stdin: str | None = None) -> str:
    """Run a shell pipeline inside the database container.

    The hosted URL travels as an environment variable, never on a command
    line that gets echoed.
    """
    result = subprocess.run(
        ["docker", "exec", "-i", "-e", f"TARGET_URL={url}", CONTAINER,
         "bash", "-c", "set -euo pipefail\n" + script],
        input=stdin, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        sys.exit(f"Failed:\n{result.stderr.strip()[-2000:]}")
    return result.stdout


def target(sql: str, url: str) -> str:
    return in_container(
        'psql "$TARGET_URL" -X -q -t -A -v ON_ERROR_STOP=1', url, stdin=sql
    ).strip()


def table_flags(tables: list[str]) -> str:
    return " ".join(f"-t public.{t}" for t in tables)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-days", type=int, default=60,
                        help="Raw detections to copy (default 60 days).")
    parser.add_argument("--replace", action="store_true",
                        help="Drop the hosted copy's tables first.")
    args = parser.parse_args()
    url = hosted_url()
    every_table = TABLES + EMPTY_TABLES + [OBSERVATIONS]

    print("Checking hosted database...")
    existing = target(
        "SELECT string_agg(tablename, ', ') FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename = ANY(ARRAY["
        + ", ".join(f"'{t}'" for t in every_table) + "])",
        url,
    )
    if existing and not args.replace:
        sys.exit(f"Hosted database already has: {existing}. "
                 "Run with --replace to recopy them.")
    if existing:
        print(f"Dropping hosted tables: {existing}")
        target("".join(f"DROP TABLE IF EXISTS public.{t} CASCADE;\n"
                       for t in every_table), url)

    print("Creating PostGIS and schema...")
    target(SETUP_SQL, url)
    pg_dump = "pg_dump -U agnisight -d agnisight --no-owner --no-privileges"
    psql_target = 'psql "$TARGET_URL" -X -q -v ON_ERROR_STOP=1 >/dev/null'
    in_container(
        f"{pg_dump} --schema-only {table_flags(every_table)} | {psql_target}", url
    )

    print("Copying history, sites, context and place tables...")
    in_container(
        f"{pg_dump} --data-only {table_flags(TABLES)} | {psql_target}", url
    )

    print(f"Copying raw detections from the last {args.keep_days} days...")
    select = (f"SELECT * FROM {OBSERVATIONS} WHERE observed_at >= "
              f"now() - interval '{int(args.keep_days)} days'")
    in_container(
        f'psql -U agnisight -d agnisight -X -q -c "\\copy ({select}) TO STDOUT" '
        f'| psql "$TARGET_URL" -X -q -v ON_ERROR_STOP=1 '
        f'-c "\\copy {OBSERVATIONS} FROM STDIN"',
        url,
    )
    target(
        f"SELECT setval(pg_get_serial_sequence('{OBSERVATIONS}', 'id'), "
        f"(SELECT MAX(id) FROM {OBSERVATIONS}));\n"
        "VACUUM ANALYZE;",
        url,
    )

    report = target("""
        SELECT format('%s detections, %s cells, %s sites; database %s',
            (SELECT COUNT(*) FROM thermal_observations),
            (SELECT COUNT(*) FROM thermal_cells),
            (SELECT COUNT(*) FROM thermal_sites),
            pg_size_pretty(pg_database_size(current_database())))
    """, url)
    print(f"Copied: {report}")

    print("Publishing events to the hosted copy...")
    published = subprocess.run(
        [sys.executable, "refresh_data.py", "--skip-ingest"],
        cwd=Path(__file__).parent, env={**os.environ, "DATABASE_URL": url},
    )
    return published.returncode


if __name__ == "__main__":
    raise SystemExit(main())
