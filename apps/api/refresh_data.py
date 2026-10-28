"""Fetch new FIRMS detections, update history and sites, publish events.

Runs on a schedule against the hosted database (.github/workflows/
refresh-data.yml) and works the same against the local one:

    python refresh_data.py                  # last 3 days, then publish events
    python refresh_data.py --skip-ingest    # publish events only
    python refresh_data.py --keep-days 60   # hosted copy: drop old raw rows

History tables keep every detection's contribution, so pruning raw rows
loses only per-detection detail. It refuses to run on a full archive.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db.database import SessionLocal
from app.services.event_snapshots import SNAPSHOT_DAYS, publish_snapshot
from app.services.firms_ingestion import FIRMSIngestionService
from app.services.thermal_registry import archive_is_pruned


def prune(db, keep_days: int) -> int:
    if not archive_is_pruned(db.connection()):
        raise RuntimeError(
            "Refusing to prune: this database holds the full archive. "
            "Pruning is only for the hosted copy made by publish_hosted_db.py."
        )
    deleted = db.execute(text("""
        DELETE FROM thermal_observations
        WHERE observed_at < now() - make_interval(days => :days)
    """), {"days": keep_days}).rowcount
    db.commit()
    return int(deleted)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3, choices=range(1, 32),
                        metavar="1-31", help="UTC days to fetch, ending today.")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--keep-days", type=int,
                        help=f"Delete raw detections older than this (>= {2 * SNAPSHOT_DAYS}).")
    args = parser.parse_args()
    if args.keep_days is not None and args.keep_days < 2 * SNAPSHOT_DAYS:
        parser.error(f"--keep-days must be at least {2 * SNAPSHOT_DAYS}")

    report: dict = {}
    db = SessionLocal()
    try:
        if not args.skip_ingest:
            end = datetime.now(timezone.utc).date()
            start = end - timedelta(days=args.days - 1)
            summary = asyncio.run(FIRMSIngestionService(db).ingest_range(start, end))
            report["ingestion"] = {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "records_received": summary["records_received"],
                "inserted": summary["inserted"],
                "sites_rebuilt": "sites" in summary,
            }
        report["snapshot"] = publish_snapshot(db)
        if args.keep_days is not None:
            report["pruned"] = prune(db, args.keep_days)
    finally:
        db.close()

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
