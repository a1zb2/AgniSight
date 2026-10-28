# Import OSM settlements and state/district boundaries for event labels.
# Requires data/osm/raw/india-latest.osm.pbf (Geofabrik) and Docker.
# Afterwards run:  cd apps/api; python build_thermal_registry.py
$ErrorActionPreference = "Stop"
$osm = Join-Path $PSScriptRoot "..\data\osm" | Resolve-Path
New-Item -ItemType Directory -Force (Join-Path $osm "places") | Out-Null
$pg = "PG:host=host.docker.internal port=5432 dbname=agnisight user=agnisight password=agnisight"

docker run --rm -v "${osm}:/data" agnisight-osmium tags-filter /data/raw/india-latest.osm.pbf `
    n/place=city,town,village,suburb r/boundary=administrative `
    -o /data/places/places-admin.osm.pbf --overwrite

docker run --rm -v "${osm}\places:/data" ghcr.io/osgeo/gdal:ubuntu-small-latest ogr2ogr `
    -f PostgreSQL $pg /data/places-admin.osm.pbf `
    -sql "SELECT name, place, other_tags FROM points WHERE place IN ('city','town','village','suburb')" `
    -nln osm_places -nlt POINT -lco GEOMETRY_NAME=geometry -overwrite

docker run --rm -v "${osm}\places:/data" ghcr.io/osgeo/gdal:ubuntu-small-latest ogr2ogr `
    --config OSM_MAX_TMPFILE_SIZE 1024 -f PostgreSQL $pg /data/places-admin.osm.pbf `
    -sql "SELECT name, admin_level, other_tags FROM multipolygons WHERE boundary='administrative' AND admin_level IN ('4','5')" `
    -nln osm_admin_areas -nlt MULTIPOLYGON -lco GEOMETRY_NAME=geometry -overwrite
