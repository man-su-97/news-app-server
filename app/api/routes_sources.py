"""
app/api/routes_sources.py — News Source CRUD Endpoints
=======================================================
HTTP API for managing news sources (RSS feeds and REST API endpoints).
A "source" is a URL the system fetches articles from automatically every 5 minutes.

Endpoints:
  POST /sources/        → register a new news source
  GET  /sources/        → list all active sources
  GET  /sources/{id}    → get one source by ID

Typical usage flow:
  1. POST /sources/ with name, type="rss", url="https://example.com/feed.rss"
  2. POST /ingest/ with {"source_id": 1} to test it immediately
  3. Scheduler automatically fetches it every 5 minutes going forward
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_source_repo
from app.repositories.source_repo import SourceRepository
from app.schemas.source_schema import SourceCreate, SourceResponse, SourceUpdate

router = APIRouter()


@router.post("/", response_model=SourceResponse, status_code=201, summary="Register a new news source")
async def create_source(
    payload: SourceCreate,              # Request body (validated by Pydantic automatically)
    repo: SourceRepository = Depends(get_source_repo),
):
    """Register a new news source.

    Example request body:
    {
        "name": "TOI Crime",
        "type": "rss",
        "url": "https://timesofindia.indiatimes.com/rssfeeds/7503091.cms",
        "config": null
    }

    For REST APIs with authentication:
    {
        "name": "NewsAPI Crime",
        "type": "rest",
        "url": "https://newsapi.org/v2/top-headlines?category=crime&apiKey=...",
        "config": {"headers": {"Authorization": "Bearer YOUR_API_KEY"}}
    }

    status_code=201: HTTP 201 Created is the correct status for successful resource creation.
    (200 OK would also work but 201 is semantically more accurate.)
    """
    # repo.create() inserts the new source and returns it with id and created_at populated
    return await repo.create(payload)


@router.get("/", response_model=list[SourceResponse], summary="List news sources")
async def list_sources(
    include_inactive: bool = Query(False, description="Set true to include paused/inactive sources"),
    repo: SourceRepository = Depends(get_source_repo),
):
    """List news sources. Active sources only by default.

    Pass `?include_inactive=true` to also see sources that have been paused
    (is_active=false). Useful for re-activating a source without re-adding it.
    """
    active_only = not include_inactive
    return await repo.get_all(active_only=active_only)


@router.get("/{source_id}", response_model=SourceResponse, summary="Get source by ID")
async def get_source(
    source_id: int,
    repo: SourceRepository = Depends(get_source_repo),
):
    """Get a single source by its ID. Returns 404 if it doesn't exist."""
    source = await repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.patch("/{source_id}", response_model=SourceResponse, summary="Update a source")
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    repo: SourceRepository = Depends(get_source_repo),
):
    """Partially update a source. Only the fields you send are changed.

    Common uses:
      - Pause a source:    `{"is_active": false}`
      - Resume a source:   `{"is_active": true}`
      - Change the URL:    `{"url": "https://new-feed.example.com/rss"}`

    The scheduler respects is_active immediately on the next 5-minute cycle.
    Returns 404 if the source doesn't exist.
    """
    source = await repo.update(source_id, payload)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.delete("/{source_id}", status_code=204, summary="Delete a source")
async def delete_source(
    source_id: int,
    repo: SourceRepository = Depends(get_source_repo),
):
    """Permanently delete a source and stop fetching from it.

    To temporarily pause instead of deleting, use PATCH with `{"is_active": false}`.
    Returns 404 if the source doesn't exist.
    status_code=204: success with no response body.
    """
    deleted = await repo.delete(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
