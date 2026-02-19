from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import get_ingestion_service, get_source_repo
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService

router = APIRouter()


class IngestRequest(BaseModel):
    source_id: int


@router.post("/rss")
async def ingest_rss(
    payload: IngestRequest,
    source_repo: SourceRepository = Depends(get_source_repo),
    svc: IngestionService = Depends(get_ingestion_service),
):
    source = await source_repo.get_by_id(payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.type != "rss":
        raise HTTPException(status_code=400, detail="Source type must be 'rss'")
    count = await svc.ingest_rss(source)
    return {"ingested": count}


@router.post("/api")
async def ingest_api(
    payload: IngestRequest,
    source_repo: SourceRepository = Depends(get_source_repo),
    svc: IngestionService = Depends(get_ingestion_service),
):
    source = await source_repo.get_by_id(payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.type != "rest":
        raise HTTPException(status_code=400, detail="Source type must be 'rest'")
    count = await svc.ingest_api(source)
    return {"ingested": count}
