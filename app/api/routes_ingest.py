from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import get_ingestion_service, get_source_repo
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService

router = APIRouter()

_SUPPORTED_SOURCE_TYPES = {"rss", "rest"}


class IngestRequest(BaseModel):
    source_id: int


@router.post("/")
async def trigger_ingest(
    payload: IngestRequest,
    source_repo: SourceRepository = Depends(get_source_repo),
    svc: IngestionService = Depends(get_ingestion_service),
):
    """Trigger ingestion for any source type.

    The route no longer leaks the source.type into the URL — the service
    dispatches internally based on the stored source.type. Callers only need
    to know the source_id, not how it is fetched.
    """
    source = await source_repo.get_by_id(payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.type not in _SUPPORTED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source type: {source.type!r}. Expected one of {_SUPPORTED_SOURCE_TYPES}",
        )

    count = await svc.ingest(source)
    return {"source_id": source.id, "source_type": source.type, "ingested": count}
