"""
app/api/routes_articles.py — Article Read Endpoints
====================================================
HTTP API for reading stored crime news articles.
These endpoints are used by the frontend to fetch articles for display.

Endpoints:
  GET /articles/           → paginated list of articles (for the news feed)
  GET /articles/{id}       → single article by ID (for a detail view)

Architecture notes:
  - These are read-only endpoints — no POST/PUT/DELETE for articles.
    Articles are created exclusively by the ingestion pipeline (POST /ingest/).
  - Pagination (limit/offset) prevents loading thousands of articles at once.
  - The repo sorts by importance_score DESC so high-priority crime news
    appears first in the frontend feed.
"""

from fastapi import APIRouter, Depends, HTTPException, Query  # FastAPI components

from app.core.deps import get_article_repo                    # Dependency: creates ArticleRepository
from app.repositories.article_repo import ArticleRepository   # Type hint
from app.schemas.article_schema import ArticleListResponse, ArticleResponse  # Response schemas

# APIRouter is a "mini-app" — routes are registered on this,
# then included in main.py with a prefix (/articles).
router = APIRouter()


@router.get("/", response_model=ArticleListResponse)
async def list_articles(
    # Query parameters with validation:
    # limit: how many articles to return (1-100, default 20)
    # offset: how many to skip (for pagination, default 0)
    # Query(20, ge=1, le=100) means: default=20, minimum=1, maximum=100
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    # Depends(get_article_repo): FastAPI calls get_article_repo() and injects the result.
    # This gives us an ArticleRepository with a DB session for this request.
    repo: ArticleRepository = Depends(get_article_repo),
):
    """Return a paginated list of crime news articles, newest/most important first.

    Example requests:
      GET /articles/          → first 20 articles
      GET /articles/?limit=50 → first 50 articles
      GET /articles/?offset=20 → articles 21-40 (page 2)

    Response includes total count so the frontend can show "Page 1 of 10" etc.
    """
    # Fetch the articles for this page
    items = await repo.get_all(limit=limit, offset=offset)
    # Get the total count (separate query — needed for pagination UI)
    total = await repo.count()
    # Return wrapped in ArticleListResponse (includes pagination metadata)
    return ArticleListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: int,   # Path parameter: /articles/42 → article_id=42
    repo: ArticleRepository = Depends(get_article_repo),
):
    """Return a single article by its database ID.

    Returns 404 if the article doesn't exist.
    Used for detail views or when sharing a link to a specific article.
    """
    article = await repo.get_by_id(article_id)
    if article is None:
        # HTTPException(404) tells FastAPI to return {"detail": "Article not found"}
        # with HTTP status code 404. The client knows the article doesn't exist.
        raise HTTPException(status_code=404, detail="Article not found")
    return article  # FastAPI serializes this Article ORM object using ArticleResponse schema
