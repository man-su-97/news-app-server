from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_filter_article_repo
from app.repositories.filter_article_repo import FilterArticleRepository
from app.schemas.article_schema import FilterArticleListResponse, FilterArticleResponse

router = APIRouter()


@router.get(
    "/",
    response_model=FilterArticleListResponse,
    summary="List crime-filtered articles",
)
async def list_filter_articles(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sub_category_id: int | None = Query(None, description="Filter by sub-category ID"),
    q: str | None = Query(None, description="Keyword search on title / description"),
    repo: FilterArticleRepository = Depends(get_filter_article_repo),
):
    """Returns articles that passed the AI crime filter (stage 1).

    These are raw-extracted articles classified as crime-relevant.
    Each one will have a corresponding row in `post-processed/` once stage 2 runs.
    """
    items = await repo.get_all(limit=limit, offset=offset, sub_category_id=sub_category_id, q=q)
    total = await repo.count(sub_category_id=sub_category_id, q=q)
    return FilterArticleListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/{article_id}",
    response_model=FilterArticleResponse,
    summary="Get a filtered article by ID",
    responses={404: {"description": "Article not found"}},
)
async def get_filter_article(
    article_id: int,
    repo: FilterArticleRepository = Depends(get_filter_article_repo),
):
    """Returns a single crime-filtered article by its ID."""
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
