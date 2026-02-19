from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_article_repo
from app.repositories.article_repo import ArticleRepository
from app.schemas.article_schema import ArticleListResponse, ArticleResponse

router = APIRouter()


@router.get("/", response_model=ArticleListResponse)
async def list_articles(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: ArticleRepository = Depends(get_article_repo),
):
    items = await repo.get_all(limit=limit, offset=offset)
    total = await repo.count()
    return ArticleListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: int,
    repo: ArticleRepository = Depends(get_article_repo),
):
    article = await repo.get_by_id(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
