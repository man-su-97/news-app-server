"""
app/schemas/article_schema.py — Article API Response Schemas
=============================================================
Pydantic schemas for the /articles/ API endpoints.

These map to the two-stage pipeline tables:
  FilterArticleResponse        → filter_articles table (stage 1 AI output)
  PostProcessedArticleResponse → post_processed_articles table (stage 2 AI output)

The GET /articles/ endpoint uses PostProcessedArticleResponse — the final,
publication-ready version of each article that the frontend renders.

FilterArticleResponse is available for internal/debug endpoints.

ArticleResponse is a backwards-compatible alias for PostProcessedArticleResponse
so any existing API clients do not break.
"""

from datetime import datetime

from pydantic import BaseModel


class FilterArticleResponse(BaseModel):
    """Response schema for a stage-1 AI filter article (filter_articles table).

    Represents an article that has passed the crime-relevance filter but
    has not yet been through the post-processing enrichment stage.
    """

    id: int
    raw_ingestion_id: int | None    # FK to raw_ingestion row that produced this

    title: str
    description: str | None
    image_url: str | None
    main_url: str               # canonical URL on the source website

    published_at: datetime | None
    created_at: datetime

    sub_category_id: int | None     # Legacy single FK (kept for backward compat)
    sub_category_ids: list | None   # Multi-label JSONB array of sub_category IDs
    location_state_id: int | None   # FK to state table (resolved from AI location)

    model_config = {"from_attributes": True}


class PostProcessedArticleResponse(BaseModel):
    """Response schema for a stage-2 post-processed article.

    This is the fully enriched article. The frontend may display this
    or the final_articles (ranked) feed depending on the use case.
    """

    id: int
    filter_article_id: int | None   # FK to filter_articles row

    title: str
    description: str | None         # AI-rewritten summary from stage 2
    image_url: str | None
    reference_urls: list[str] | None  # related source URLs from stage 2

    published_at: datetime | None
    created_at: datetime

    sub_category_id: int | None     # FK to master_sub_category
    location_id: int | None         # FK to state

    imp_score: int | None           # 1-100 importance score from stage 2 AI

    model_config = {"from_attributes": True}


# Backwards-compatible alias — existing code that imports ArticleResponse
# continues to work; it now maps to PostProcessedArticleResponse.
ArticleResponse = PostProcessedArticleResponse


class FilterArticleListResponse(BaseModel):
    """Paginated list response for GET /filter-articles/."""

    total: int
    limit: int
    offset: int
    items: list[FilterArticleResponse]


class ArticleListResponse(BaseModel):
    """Paginated list response for GET /articles/.

    Wraps a list of PostProcessedArticleResponse with pagination metadata.
    """

    total: int                              # total rows in post_processed_articles
    limit: int
    offset: int
    items: list[PostProcessedArticleResponse]
