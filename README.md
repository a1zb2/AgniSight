# AgniSight

Explainable monitoring of satellite-detected heat across India.

AgniSight groups NASA FIRMS VIIRS (NOAA-21) active-fire detections into
events. Each event is checked against the location's multi-year detection
history, mapped industrial and land-use context from OpenStreetMap, and a
static-source model. Events are then ranked for review. Every assessment
shows the evidence for and against it, how strong that evidence is, and
what remains unknown. It never gives a single confidence score.

Built for Smart India Hackathon 2026 (Space Technology).

## What it does

- **Event queue and map.** Recent detections are clustered into events
  (3 km, 6 h) and drawn as a heat layer over Sentinel-2 imagery. Events
  are sorted by an additive, itemised review priority.
- **Location history.** Every ~400 m grid cell that has ever had a
  detection keeps its counts, NASA source-type labels and active dates.
  These show whether a place burns continuously, seasonally or for the
  first time.
- **Persistent sites.** Connected cells active in at least 6 distinct
  months form sites. They are classed as persistent, seasonal or
  recurrent.
- **Context.** OSM industrial, mining, waste, energy and land-use features
  near each event decide whether it sits *inside*, *adjacent to* or
  *near* a mapped facility. Nearest settlement, district and state label
  each event.
- **Static-source model.** A gradient-boosted classifier estimates whether
  NASA would label a detection a static land source. It is used as
  evidence only where NASA's own label for the location is missing.
- **Analytics.** National monthly detections by day and night, persistent
  sites by context, and sites NASA does not flag as static.

## How the evidence was checked

Measured on the 2024–2026 NOAA-21 archive (about 1.7 million detections
over India):

| Approach | Precision | Recall |
|---|---|---|
| Earlier rule (active on 3+ days) for "industrial" | 0.08 | — |
| Transparent site rule (≥ 8 calendar months, ≥ 50% night) | 0.87 | 0.998 |
| Static-source model, spatial hold-out (0.5° blocks) | 0.92 | 0.97 |

The model does not use coordinates and is tested on held-out regions, so
the figures above reflect places it has not seen. Volcano and offshore
classes are not modelled. Training details:
`apps/api/models/static_source_metrics.json`.

## Stack

| Part | Technology |
|---|---|
| API | FastAPI, SQLAlchemy, PostgreSQL + PostGIS, scikit-learn |
| Frontend | Next.js 16, React 19, MapLibre GL, Recharts |
| Data | NASA FIRMS VIIRS NOAA-21 (archive + NRT), OpenStreetMap (Geofabrik India), EOX Sentinel-2 cloudless, NASA GIBS |

## Running locally

Requirements: Docker, Python 3.13, Node.js 20+, a free
[FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/).

```bash
docker compose up -d                      # PostGIS
cd apps/api
cp .env.example .env                      # add FIRMS_MAP_KEY
pip install -r requirements.txt
python -m app.db.init_db                  # base table (migration 0001 alters it)
alembic stamp 0001_expand_thermal_obs
alembic upgrade head
python refresh_data.py --days 7           # fetch recent detections, publish events
uvicorn app.main:app --reload             # http://127.0.0.1:8000/docs

cd ../web
npm install
npm run dev                               # http://localhost:3000
```

Location history, sites, context and place labels come from the
multi-year FIRMS archive and the OSM India extract. Load the archive with
`import_firms_archive.py --commit` and OSM places with
`scripts/import-osm-places.ps1`, then build the derived tables with
`python build_thermal_registry.py`. With only a few days of data, every
location looks new.

## Hosting

The site runs on free tiers: Neon for the database, Render for the API,
Vercel for the frontend, and GitHub Actions to refresh data every 6
hours. See [docs/DEPLOY.md](docs/DEPLOY.md).

## Limitations

- One sensor: NOAA-21 VIIRS, at most two overpasses a day at 375 m
  resolution. Small, short or cloud-covered fires are missed.
- OSM coverage of industrial sites in India is incomplete. "Unmapped" means
  not mapped, not "not industrial".
- Assessments describe how a detection fits the evidence. They are not a
  verified cause, and nothing here replaces checking on the ground.

## Data sources

NASA FIRMS (LANCE/EOSDIS), OpenStreetMap contributors (ODbL), Sentinel-2
cloudless by EOX (contains modified Copernicus Sentinel data), and NASA
GIBS.
