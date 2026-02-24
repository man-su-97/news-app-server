"""
app/api/routes_raw_ingestion.py — Raw Ingestion Read Endpoints
==============================================================
HTTP API for inspecting the raw_ingestion table.

This is the "inbox" of the pipeline — every payload fetched from a source
lands here before AI processing. Useful for:
  - Seeing what came in from a source (with raw_payload included)
  - Auditing AI processing outcomes (status: filtered / filtered_out / failed)
  - Debugging why an article was dropped

Endpoints:
  GET /raw-ingestion/        → paginated list, optionally filtered by status
  GET /raw-ingestion/{id}    → single row by ID including full raw_payload
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_raw_ingestion_repo
from app.repositories.raw_ingestion_repo import RawIngestionRepository
from app.schemas.master_data_schema import RawIngestionListResponse, RawIngestionResponse

router = APIRouter()


@router.get(
    "/",
    response_model=RawIngestionListResponse,
    summary="List raw ingestion events (paginated)",
)
async def list_raw_ingestion(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(
        None,
        description="Filter by status: pending | filtered | filtered_out | failed",
    ),
    source_id: int | None = Query(None, description="Filter by source ID"),
    repo: RawIngestionRepository = Depends(get_raw_ingestion_repo),
):
    """Return a paginated list of raw ingestion rows ordered by created_at descending.

    Use the `status` query param to focus on specific pipeline outcomes:
      - `pending`      → not yet processed by AI
      - `filtered`     → accepted as crime, filter_articles row exists
      - `filtered_out` → AI said not crime (expected, not a bug)
      - `failed`       → AI errored — check error_message field

    Use `source_id` to see only rows from a specific news source.
    """
    items = await repo.get_all(limit=limit, offset=offset, status=status, source_id=source_id)
    total = await repo.count(status=status, source_id=source_id)
    return RawIngestionListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{row_id}",
    response_model=RawIngestionResponse,
    summary="Get raw ingestion row by ID",
)
async def get_raw_ingestion(
    row_id: int,
    repo: RawIngestionRepository = Depends(get_raw_ingestion_repo),
):
    """Return a single raw ingestion row including the full raw_payload JSON.

    The raw_payload contains exactly what was received from the news source
    (RSS feedparser dict or REST API JSON response).
    Returns 404 if the row does not exist.
    """
    row = await repo.get_by_id(row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Raw ingestion row not found")
    return row
