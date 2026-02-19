from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_source_repo
from app.repositories.source_repo import SourceRepository
from app.schemas.source_schema import SourceCreate, SourceResponse

router = APIRouter()


@router.post("/", response_model=SourceResponse, status_code=201)
async def create_source(
    payload: SourceCreate,
    repo: SourceRepository = Depends(get_source_repo),
):
    return await repo.create(payload)


@router.get("/", response_model=list[SourceResponse])
async def list_sources(
    repo: SourceRepository = Depends(get_source_repo),
):
    return await repo.get_all()


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: int,
    repo: SourceRepository = Depends(get_source_repo),
):
    source = await repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source
