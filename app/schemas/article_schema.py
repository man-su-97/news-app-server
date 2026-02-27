from datetime import datetime

from pydantic import BaseModel


class FilterArticleResponse(BaseModel):
    id: int
    raw_ingestion_id: int | None
    title: str
    description: str | None
    image_url: str | None
    main_url: str
    published_at: datetime | None
    created_at: datetime
    sub_category_ids: list
    category_ids: list
    location_state_id: int | None

    model_config = {"from_attributes": True}


class FilterArticleListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FilterArticleResponse]


class PostProcessedArticleResponse(BaseModel):
    id: int
    filter_article_id: int | None

    title: str
    description: str | None
    image_url: str | None
    reference_urls: list[str] | None

    published_at: datetime | None
    created_at: datetime

    sub_category_id: int | None
    location_id: int | None
    imp_score: int | None

    model_config = {"from_attributes": True}


class ArticleListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PostProcessedArticleResponse]


ArticleResponse = PostProcessedArticleResponse
