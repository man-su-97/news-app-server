from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_final_article_repo, get_post_processed_repo
from app.repositories.final_article_repo import FinalArticleRepository
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository
from app.schemas.final_article_schema import FinalArticleListResponse, FinalArticleResponse
from app.services.publishing_service import PublishingService

router = APIRouter()


@router.get(
    "/",
    response_model=FinalArticleListResponse,
    summary="Get the ranked crime news feed",
)
async def list_final_articles(
    limit: int = Query(20, ge=1, le=100, description="Number of articles per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    sub_category_id: int | None = Query(None, description="Filter by crime sub-category ID"),
    q: str | None = Query(None, description="Keyword search in title and description"),
    repo: FinalArticleRepository = Depends(get_final_article_repo),
):
    """Returns the curated news feed ordered by relevance score (descending).

    Each article is ranked by AI importance score combined with time decay —
    breaking news appears above older articles of similar importance.
    """
    items = await repo.get_feed(limit=limit, offset=offset, sub_category_id=sub_category_id, q=q)
    total = await repo.count(sub_category_id=sub_category_id, q=q)
    return FinalArticleListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{article_id}",
    response_model=FinalArticleResponse,
    summary="Get a single article by ID",
    responses={404: {"description": "Article not found"}},
)
async def get_final_article(
    article_id: int,
    repo: FinalArticleRepository = Depends(get_final_article_repo),
):
    """Returns a single ranked article by its ID."""
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.post(
    "/publish",
    summary="Trigger a publishing run",
    response_model=dict,
)
async def trigger_publishing(
    top_n: int = Query(20, ge=1, le=100, description="Number of top articles to publish"),
    post_processed_repo: PostProcessedArticleRepository = Depends(get_post_processed_repo),
    final_repo: FinalArticleRepository = Depends(get_final_article_repo),
):
    """Recomputes rankings and refreshes the final feed.

    Selects the top `top_n` articles by importance score, applies time decay,
    and upserts them into the feed. Runs automatically every 5 minutes via
    the scheduler — use this endpoint to force an immediate refresh.
    """
    svc = PublishingService(
        post_processed_repo=post_processed_repo,
        final_article_repo=final_repo,
    )
    count = await svc.publish(top_n=top_n)
    return {"published": count, "top_n": top_n}
