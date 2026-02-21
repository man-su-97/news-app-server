"""
app/api/routes_ingest.py — Manual Ingestion Trigger Endpoint
=============================================================
HTTP endpoint to manually trigger the ingestion pipeline for a source.

The pipeline runs automatically every 5 minutes via the scheduler.
This endpoint lets you trigger it manually without waiting:
  - Testing a newly-added source
  - Forcing a refresh when breaking news just broke
  - Debugging ingestion issues

Endpoint:
  POST /ingest/ with {"source_id": 1}

The source.type (rss or rest) is stored in the DB — the caller only needs
the source_id, not the type. The service dispatches internally.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import get_ingestion_service, get_source_repo
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService

router = APIRouter()

# Valid source types — anything else is rejected immediately.
# This prevents confusing error messages from deep inside the ingestion pipeline.
_SUPPORTED_SOURCE_TYPES = {"rss", "rest"}


class IngestRequest(BaseModel):
    """Request body for POST /ingest/."""
    source_id: int   # Which source to ingest


@router.post("/")
async def trigger_ingest(
    payload: IngestRequest,
    # Two separate dependencies:
    source_repo: SourceRepository = Depends(get_source_repo),         # to look up the source
    svc: IngestionService = Depends(get_ingestion_service),            # to run ingestion
    # Architecture note: Both share the same DB session (injected by FastAPI).
    # source_repo and svc.source_repo will be DIFFERENT SourceRepository instances
    # but they share the same underlying AsyncSession (see deps.py get_ingestion_service).
):
    """Trigger immediate ingestion for a specific source.

    Steps:
      1. Look up the source by ID (returns 404 if not found)
      2. Validate the source type (returns 400 if unsupported)
      3. Run the full ingestion pipeline (fetch → normalize → enrich → save)
      4. Return the count of articles written

    Example request:
      POST /ingest/
      {"source_id": 1}

    Example response:
      {"source_id": 1, "source_type": "rss", "ingested": 12}
    """
    # Step 1: verify the source exists
    source = await source_repo.get_by_id(payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    # Step 2: verify the source type is supported
    # The service handles this too, but checking here gives a clearer error message.
    if source.type not in _SUPPORTED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source type: {source.type!r}. Expected one of {_SUPPORTED_SOURCE_TYPES}",
        )

    # Step 3: run the full ingestion pipeline
    # svc.ingest() handles everything: fetch, normalize, enrich, filter, upsert
    count = await svc.ingest(source)

    # Step 4: return the result
    return {
        "source_id": source.id,
        "source_type": source.type,
        "ingested": count,    # number of articles written to the DB
    }
