from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.observations import get_db
from app.services.firms_ingestion import FIRMSIngestionService


router = APIRouter(
    prefix="/api/v1/ingestion/firms",
    tags=["FIRMS ingestion"],
)


@router.post("")
async def ingest_firms(
    start_date: date | None = Query(
        default=None,
        description="First UTC day to fetch. Defaults to two days ago.",
    ),
    end_date: date | None = Query(
        default=None,
        description="Last UTC day to fetch. Defaults to today.",
    ),
    db: Session = Depends(get_db),
):
    today = datetime.now(timezone.utc).date()
    end = end_date or today
    start = start_date or end - timedelta(days=2)

    if start > end:
        raise HTTPException(422, "start_date must not be after end_date")
    if (end - start).days > 31:
        raise HTTPException(422, "Fetch at most 31 days per request")

    return await FIRMSIngestionService(db).ingest_range(start, end)
