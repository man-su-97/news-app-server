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

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_source_repo
from app.repositories.source_repo import SourceRepository
from app.schemas.source_schema import SourceCreate, SourceResponse

router = APIRouter()


@router.post("/", response_model=SourceResponse, status_code=201)
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


@router.get("/", response_model=list[SourceResponse])
async def list_sources(
    repo: SourceRepository = Depends(get_source_repo),
):
    """List all active news sources.

    Only returns active sources (is_active=True).
    Deactivated sources are hidden from this list.
    """
    # get_all(active_only=True) is the default — only active sources are returned
    return await repo.get_all()


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: int,    # Extracted from the URL path: /sources/3 → source_id=3
    repo: SourceRepository = Depends(get_source_repo),
):
    """Get a single source by its ID.

    Useful for checking the configuration of a specific source
    or verifying it exists before triggering manual ingestion.
    Returns 404 if the source doesn't exist.
    """
    source = await repo.get_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source
