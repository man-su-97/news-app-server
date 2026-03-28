from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_post_processed_repo
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository
from app.schemas.article_schema import ArticleListResponse, PostProcessedArticleResponse

router = APIRouter()


@router.get(
    "/",
    response_model=ArticleListResponse,
    summary="List post-processed articles",
)
async def list_post_processed(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sub_category_id: int | None = Query(None, description="Filter by sub-category ID"),
    q: str | None = Query(None, description="Keyword search on title / description"),
    from_date: datetime | None = Query(None, description="Published on or after (ISO 8601)"),
    to_date: datetime | None = Query(None, description="Published on or before (ISO 8601)"),
    repo: PostProcessedArticleRepository = Depends(get_post_processed_repo),
):
    """Returns AI-enriched articles from stage 2 (rewritten title, description, imp_score).

    Articles with `imp_score=null` skipped stage 2 (low importance) and won't
    appear in the ranked feed at `GET /final-articles/`.
    """
    items = await repo.get_all(
        limit=limit,
        offset=offset,
        sub_category_id=sub_category_id,
        q=q,
        from_date=from_date,
        to_date=to_date,
    )
    total = await repo.count(
        sub_category_id=sub_category_id,
        q=q,
        from_date=from_date,
        to_date=to_date,
    )
    return ArticleListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{article_id}",
    response_model=PostProcessedArticleResponse,
    summary="Get a post-processed article by ID",
    responses={404: {"description": "Article not found"}},
)
async def get_post_processed(
    article_id: int,
    repo: PostProcessedArticleRepository = Depends(get_post_processed_repo),
):
    """Returns a single post-processed article by its ID."""
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
