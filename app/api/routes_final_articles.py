"""
app/api/routes_final_articles.py — Final Articles API Endpoints
================================================================
HTTP API for reading the public curated news feed.
Reads from final_articles — the terminal output of the full pipeline.

Endpoints:
  GET /final-articles/       → paginated feed ordered by rank_score descending
  GET /final-articles/{id}   → single final article by ID
  POST /final-articles/publish → manually trigger a publishing run (admin use)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_final_article_repo, get_post_processed_repo
from app.repositories.final_article_repo import FinalArticleRepository
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository
from app.schemas.final_article_schema import FinalArticleListResponse, FinalArticleResponse
from app.services.publishing_service import PublishingService

router = APIRouter()


@router.get(
    "/",
    response_model=FinalArticleListResponse,
    summary="Get the public crime news feed (ranked)",
)
async def list_final_articles(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sub_category_id: int | None = Query(
        None,
        description="Filter by sub-category ID (joins to post_processed_articles)",
    ),
    q: str | None = Query(None, description="Keyword search across title and description"),
    repo: FinalArticleRepository = Depends(get_final_article_repo),
):
    """Return the curated public news feed ordered by rank_score descending.

    rank_score combines imp_score (AI importance, 1-100) with a time-decay
    factor, so fresh breaking news appears above older articles of similar score.

    Filters:
      `?sub_category_id=2` → only articles in that crime sub-category
      `?q=robbery`         → keyword search in title / description

    Use limit/offset for pagination:
      GET /final-articles/?limit=20&offset=0   → page 1 (top 20)
      GET /final-articles/?limit=20&offset=20  → page 2
    """
    items = await repo.get_feed(limit=limit, offset=offset, sub_category_id=sub_category_id, q=q)
    total = await repo.count(sub_category_id=sub_category_id, q=q)
    return FinalArticleListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{article_id}",
    response_model=FinalArticleResponse,
    summary="Get a single final article by ID",
)
async def get_final_article(
    article_id: int,
    repo: FinalArticleRepository = Depends(get_final_article_repo),
):
    """Return a single ranked final article by its database ID.

    Returns 404 if no article with that ID exists in the final feed.
    """
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Final article not found")
    return article


@router.post(
    "/publish",
    summary="Manually trigger a publishing run",
    response_model=dict,
    tags=["Admin"],
)
async def trigger_publishing(
    top_n: int = Query(20, ge=1, le=100, description="Number of top articles to publish"),
    post_processed_repo: PostProcessedArticleRepository = Depends(get_post_processed_repo),
    final_repo: FinalArticleRepository = Depends(get_final_article_repo),
):
    """Manually trigger the PublishingService to recompute rankings.

    Useful for:
      - Forcing a re-rank after manually editing imp_score values
      - Testing the publishing pipeline without waiting for the scheduler
      - Recovering from a failed scheduled publishing run

    Returns the count of final_articles rows inserted or updated.
    """
    svc = PublishingService(
        post_processed_repo=post_processed_repo,
        final_article_repo=final_repo,
    )
    count = await svc.publish(top_n=top_n)
    return {"published": count, "top_n": top_n}
