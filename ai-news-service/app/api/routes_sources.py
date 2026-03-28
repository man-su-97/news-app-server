from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_source_repo
from app.repositories.source_repo import SourceRepository
from app.schemas.source_schema import SourceCreate, SourceResponse, SourceUpdate

router = APIRouter()


@router.post(
    "/",
    response_model=SourceResponse,
    status_code=201,
    summary="Add a news source",
)
async def create_source(
    payload: SourceCreate,
    repo: SourceRepository = Depends(get_source_repo),
):
    """Registers a new RSS feed or REST API as a news source.

    The source is activated immediately and will be fetched on the next
    scheduler cycle (every 5 minutes). Use `POST /ingest/` to fetch it now.
    """
    return await repo.create(payload)


@router.get(
    "/",
    response_model=list[SourceResponse],
    summary="List news sources",
)
async def list_sources(
    include_inactive: bool = Query(False, description="Include paused sources"),
    repo: SourceRepository = Depends(get_source_repo),
):
    """Returns all registered news sources. Active sources only by default."""
    return await repo.get_all(active_only=not include_inactive)


@router.get(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Get a source by ID",
    responses={404: {"description": "Source not found"}},
)
async def get_source(
    source_id: int,
    repo: SourceRepository = Depends(get_source_repo),
):
    """Returns a single news source by its ID."""
    source = await repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.patch(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Update a source",
    responses={404: {"description": "Source not found"}},
)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    repo: SourceRepository = Depends(get_source_repo),
):
    """Partially updates a source. Only provided fields are changed.

    To pause fetching: `{"is_active": false}`. To resume: `{"is_active": true}`.
    """
    source = await repo.update(source_id, payload)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.delete(
    "/{source_id}",
    status_code=204,
    summary="Delete a source",
    responses={404: {"description": "Source not found"}},
)
async def delete_source(
    source_id: int,
    repo: SourceRepository = Depends(get_source_repo),
):
    """Permanently removes a source. To pause temporarily, use PATCH with `is_active: false`."""
    deleted = await repo.delete(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
