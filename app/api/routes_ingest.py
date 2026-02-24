from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.deps import get_ingestion_service, get_source_repo
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService

router = APIRouter()

_SUPPORTED_SOURCE_TYPES = {"rss", "rest"}


class IngestRequest(BaseModel):
    source_id: int = Field(..., description="ID of the source to ingest", examples=[2])


class IngestResponse(BaseModel):
    source_id: int
    source_type: str
    ingested: int = Field(..., description="Number of articles written to the database")


@router.post(
    "/",
    response_model=IngestResponse,
    summary="Trigger ingestion for a source",
    responses={
        404: {"description": "Source not found"},
        400: {"description": "Unsupported source type"},
    },
)
async def trigger_ingest(
    payload: IngestRequest,
    source_repo: SourceRepository = Depends(get_source_repo),
    svc: IngestionService = Depends(get_ingestion_service),
):
    """Immediately runs the full pipeline for the given source.

    Fetches articles, runs AI classification and scoring, and writes results
    to the database. The pipeline runs automatically every 5 minutes via
    the scheduler — use this endpoint to trigger an immediate run.
    """
    source = await source_repo.get_by_id(payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if source.type not in _SUPPORTED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source type: {source.type!r}. Expected: {_SUPPORTED_SOURCE_TYPES}",
        )

    count = await svc.ingest(source)
    return IngestResponse(source_id=source.id, source_type=source.type, ingested=count)
