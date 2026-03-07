from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_raw_ingestion_repo
from app.repositories.raw_ingestion_repo import RawIngestionRepository
from app.schemas.article_schema import RawIngestionListResponse, RawIngestionResponse

router = APIRouter()

_VALID_STATUSES = {"pending", "filtered", "processed", "filtered_out", "failed"}


@router.get(
    "/",
    response_model=RawIngestionListResponse,
    summary="List raw ingestion events",
)
async def list_raw_ingestions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, description="Filter by status: pending | filtered | processed | filtered_out | failed"),
    source_id: int | None = Query(None, description="Filter by source ID"),
    repo: RawIngestionRepository = Depends(get_raw_ingestion_repo),
):
    """Returns raw ingestion rows ordered by created_at descending.

    Useful for monitoring the pipeline inbox — see what was fetched,
    what was filtered out by AI, and what failed.
    """
    if status and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status {status!r}. Valid values: {sorted(_VALID_STATUSES)}",
        )
    items = await repo.get_all(limit=limit, offset=offset, status=status, source_id=source_id)
    total = await repo.count(status=status, source_id=source_id)
    return RawIngestionListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{row_id}",
    response_model=RawIngestionResponse,
    summary="Get a single raw ingestion row by ID",
    responses={404: {"description": "Row not found"}},
)
async def get_raw_ingestion(
    row_id: int,
    repo: RawIngestionRepository = Depends(get_raw_ingestion_repo),
):
    """Returns a single raw ingestion row including its full raw_payload JSON."""
    row = await repo.get_by_id(row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Raw ingestion row not found")
    return row
