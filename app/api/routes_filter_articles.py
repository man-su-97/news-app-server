"""
app/api/routes_filter_articles.py — Filter Articles Read Endpoints
==================================================================
HTTP API for inspecting filter_articles — Stage 1 AI output.

filter_articles contains every article that passed the AI crime-relevance
filter. Useful for:
  - Checking what the AI classified as crime and what sub-categories were assigned
  - Verifying sub_category_ids (multi-label JSONB array) are resolved correctly
  - Comparing stage-1 fields against the post-processed version in /articles/

Endpoints:
  GET /filter-articles/        → paginated list ordered by published_at desc
  GET /filter-articles/{id}    → single filter article by ID
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_filter_article_repo
from app.repositories.filter_article_repo import FilterArticleRepository
from app.schemas.article_schema import FilterArticleListResponse, FilterArticleResponse

router = APIRouter()


@router.get(
    "/",
    response_model=FilterArticleListResponse,
    summary="List Stage 1 filter articles (paginated)",
)
async def list_filter_articles(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sub_category_id: int | None = Query(
        None, description="Filter by sub-category ID (matches JSONB sub_category_ids array)"
    ),
    q: str | None = Query(None, description="Keyword search across title and description"),
    repo: FilterArticleRepository = Depends(get_filter_article_repo),
):
    """Return a paginated list of Stage 1 AI filter articles.

    These are articles that the AI classified as crime-relevant.
    Each row shows the raw extracted fields (before Stage 2 rewriting):
      - title, description, image_url, main_url
      - sub_category_ids: multi-label JSONB array of master_sub_category IDs
      - location_state_id: FK to state table

    Filters:
      `?sub_category_id=2` → rows where sub_category_ids contains 2
      `?q=murder`          → keyword search in title / description

    Ordered by published_at descending (newest first).
    """
    items = await repo.get_all(limit=limit, offset=offset, sub_category_id=sub_category_id, q=q)
    total = await repo.count(sub_category_id=sub_category_id, q=q)
    return FilterArticleListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{article_id}",
    response_model=FilterArticleResponse,
    summary="Get Stage 1 filter article by ID",
)
async def get_filter_article(
    article_id: int,
    repo: FilterArticleRepository = Depends(get_filter_article_repo),
):
    """Return a single Stage 1 filter article by its database ID.

    Returns 404 if no filter article with that ID exists.
    """
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Filter article not found")
    return article
