"""
app/api/routes_articles.py — Article Read Endpoints
====================================================
HTTP API for reading publication-ready crime news articles.
Reads from post_processed_articles — the final output stage of the pipeline.

Endpoints:
  GET /articles/       → paginated list (news feed)
  GET /articles/{id}   → single article by ID
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_article_repo
from app.repositories.article_repo import ArticleRepository
from app.schemas.article_schema import ArticleListResponse, PostProcessedArticleResponse

router = APIRouter()


@router.get(
    "/",
    response_model=ArticleListResponse,
    summary="List post-processed articles (paginated)",
)
async def list_articles(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sub_category_id: int | None = Query(None, description="Filter by sub-category ID"),
    q: str | None = Query(None, description="Keyword search across title and description"),
    from_date: datetime | None = Query(None, description="published_at >= this datetime (ISO 8601)"),
    to_date: datetime | None = Query(None, description="published_at <= this datetime (ISO 8601)"),
    repo: ArticleRepository = Depends(get_article_repo),
):
    """Return a paginated list of publication-ready crime news articles.

    Reads from post_processed_articles ordered by published_at descending.

    Filters:
      `?sub_category_id=3`            → only murder articles (if 3 = murder)
      `?q=delhi`                      → keyword search in title / description
      `?from_date=2026-01-01T00:00Z`  → articles published after this date
      `?to_date=2026-01-31T23:59Z`    → articles published before this date

    Use limit/offset for pagination:
      GET /articles/?limit=20&offset=0   → page 1
      GET /articles/?limit=20&offset=20  → page 2
    """
    items = await repo.get_all(
        limit=limit, offset=offset,
        sub_category_id=sub_category_id, q=q,
        from_date=from_date, to_date=to_date,
    )
    total = await repo.count(sub_category_id=sub_category_id, q=q, from_date=from_date, to_date=to_date)
    return ArticleListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{article_id}",
    response_model=PostProcessedArticleResponse,
    summary="Get post-processed article by ID",
)
async def get_article(
    article_id: int,
    repo: ArticleRepository = Depends(get_article_repo),
):
    """Return a single post-processed article by its database ID.

    Returns 404 if no article with that ID exists.
    """
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
