from datetime import datetime

from pydantic import BaseModel


class FinalArticleResponse(BaseModel):
    id: int
    post_processed_article_id: int | None

    title: str
    description: str | None
    image_url: str | None
    reference_urls: list[str] | None

    rank_score: float
    created_at: datetime

    model_config = {"from_attributes": True}


class FinalArticleListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FinalArticleResponse]
