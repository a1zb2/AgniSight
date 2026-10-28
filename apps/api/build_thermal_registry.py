"""Rebuild derived tables: OSM context, place labels, history, sites.

Run after importing OSM data or a large FIRMS archive:

    python build_thermal_registry.py            # everything
    python build_thermal_registry.py --sites    # sites only (cells unchanged)

Ingestion adds new detections to the history tables and rebuilds sites
itself. Needs the full archive; refuses on a pruned (hosted) copy.
"""

from __future__ import annotations

import argparse
import json
import time

from app.db.database import engine
from app.services.pipeline_runs import finish_run, start_run
from app.services.places import build_place_tables
from app.services.spatial_context import build_context_features
from app.services.thermal_registry import build_sites, rebuild_history


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sites", action="store_true",
                        help="Only rebuild thermal_sites.")
    args = parser.parse_args()

    report: dict = {}
    with engine.begin() as conn:
        run_id = start_run(conn, "registry_build")

    try:
        with engine.begin() as conn:
            if not args.sites:
                t = time.perf_counter()
                report["context_features"] = build_context_features(conn)
                print(f"OSM context features: {report['context_features']:,} "
                      f"({time.perf_counter() - t:.1f}s)")

                t = time.perf_counter()
                report["places"] = build_place_tables(conn)
                print(f"Place labels: {report['places']} "
                      f"({time.perf_counter() - t:.1f}s)")

                t = time.perf_counter()
                report["history"] = rebuild_history(conn)
                print(f"History tables: {report['history']} "
                      f"({time.perf_counter() - t:.1f}s)")

            t = time.perf_counter()
            report["sites"] = build_sites(conn)
            print(f"Thermal sites ({time.perf_counter() - t:.1f}s):")
            print(json.dumps(report["sites"], indent=2))
    except Exception as exc:
        with engine.begin() as conn:
            finish_run(conn, run_id, "failed", {"error": str(exc)})
        raise

    with engine.begin() as conn:
        finish_run(conn, run_id, "success", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
