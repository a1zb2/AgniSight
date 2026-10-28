# Hosting AgniSight on free tiers

| Part | Host | Free-tier limits that matter |
|---|---|---|
| Database | Neon (PostGIS) | 1 GB storage; compute sleeps after 5 min idle |
| API | Render web service | 512 MB RAM, ~0.1 CPU; sleeps after 15 min idle, ~1 min to wake |
| Frontend | Vercel | Static and server rendering for Next.js |
| Data refresh | GitHub Actions | Runs `refresh_data.py` every 6 hours |

## How it differs from local

- **The hosted database is a slim copy (~430 MB).** It holds the history
  summaries (`thermal_cells`, `cell_months`, `archive_days`), sites, OSM
  context and place labels in full. Raw detections are kept for 60 days
  only. The full archive stays on your machine and is never modified.
- **Events are built ahead of time.** The refresh job fetches new FIRMS
  detections, adds them to the history tables, rebuilds sites and
  publishes the 14-day events (`event_snapshot_*`). The API runs with
  `EVENTS_SOURCE=snapshot` and serves those rows as stored. It never loads
  the model and uses about 120 MB of RAM.
- **Ingestion is not exposed.** The API has no FIRMS key, so
  `POST /api/v1/ingestion/firms` does not exist on the hosted API.
- **Some things need the full archive.** Rebuilding history or retraining
  the model needs the local database. `build_thermal_registry.py` refuses
  to run on the slim copy, and `refresh_data.py --keep-days` refuses to
  run on a full one.

## First deployment

1. **GitHub.** Create an empty repository and push this one:
   `git remote add origin <url>` then `git push -u origin main`.
   `.env` and `.env.hosted` are git-ignored; keep them that way.

2. **Neon.** Create a project in **AWS Asia Pacific (Singapore)**. Under
   *Connect*, turn **Connection pooling off** and copy the connection
   string. Save it as one line in `apps/api/.env.hosted`:

   ```
   HOSTED_DATABASE_URL=postgresql://...neon.tech/neondb?sslmode=require&channel_binding=require
   ```

3. **Copy the database.** With the local Docker database running:

   ```
   cd apps/api
   python publish_hosted_db.py
   ```

   It copies the tables (under a minute plus upload time), then publishes
   events. To start over, add `--replace`.

4. **Render.** *New → Blueprint*, pick the repository; `render.yaml`
   defines the service. When asked, set `DATABASE_URL` to the same Neon
   string. Leave `CORS_ORIGINS` as `http://localhost:3000` for now. Note the
   service URL, e.g. `https://agnisight-api.onrender.com`, and check that
   `/api/v1/health/db` returns `connected`.

5. **Vercel.** *Add New → Project*, import the repository, set **Root
   Directory** to `apps/web` and add the environment variable
   `NEXT_PUBLIC_API_BASE_URL` = the Render URL (no trailing slash). Deploy.

6. **Allow the site to call the API.** In Render, set `CORS_ORIGINS` to
   the Vercel production URL, e.g. `https://agnisight.vercel.app`, and
   save (the service restarts). Use a comma to list several origins.
   Vercel preview URLs are not allowed unless added.

7. **Scheduled refresh.** In GitHub, *Settings → Secrets and variables →
   Actions*, add `DATABASE_URL` (the Neon string) and `FIRMS_MAP_KEY`.
   Then open *Actions → Refresh data → Run workflow* once and check that it
   succeeds.

## Running it

- **Freshness.** The header dot turns amber after 24 hours without new
  data and red after 72; check the Actions tab if it does.
- **Scheduled runs stop on idle public repositories.** GitHub disables
  scheduled workflows in public repositories after 60 days without
  activity. Re-enable it from the Actions tab, or push a commit.
- **Schema changes.** Run `alembic upgrade head` with `DATABASE_URL` set to
  the Neon string, or recopy with `publish_hosted_db.py --replace`.
- **Sites, OSM context or model changed locally.** Rebuild locally, then
  recopy with `--replace`; the hosted copy cannot rebuild them itself.
- **Storage.** Check *Neon → Monitoring → Storage*. Lower
  `--keep-days` in `.github/workflows/refresh-data.yml` if it gets close to
  the limit.
