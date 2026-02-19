from datetime import datetime

from pydantic import BaseModel


class ArticleResponse(BaseModel):
    id: int
    source_id: int
    title: str
    description: str | None
    content: str | None
    url: str
    image_url: str | None
    published_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ArticleListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ArticleResponse]
