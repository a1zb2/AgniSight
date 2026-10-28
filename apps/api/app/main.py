import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from app.api.context import router as context_router
from app.api.events import router as events_router
from app.api.firms import router as firms_router
from app.api.insights import router as insights_router
from app.api.observations import router as observations_router
from app.db.database import SessionLocal, engine
from app.services.events import build_events

logger = logging.getLogger(__name__)


def _warm_event_cache() -> None:
    # Loads the model and builds the default 14-day window so the first
    # dashboard visit does not wait for it.
    db = SessionLocal()
    try:
        build_events(db, 14)
    except Exception:
        logger.exception("Event cache warm-up failed")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warm_event_cache, daemon=True).start()
    yield


app = FastAPI(
    title="AgniSight API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# GeoJSON layers are large and compress roughly 10x.
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.include_router(context_router)
app.include_router(observations_router)
app.include_router(firms_router)
app.include_router(events_router)
app.include_router(insights_router)


@app.get("/api/v1/health")
def health_check():
    return {
        "status": "ok",
        "service": "agnisight-api",
    }


@app.get("/api/v1/health/db")
def database_health_check():
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))
        value = result.scalar()

    return {
        "status": "ok",
        "database": "connected",
        "test_query": value,
    }
