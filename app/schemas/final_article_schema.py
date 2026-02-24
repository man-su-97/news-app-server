"""
app/schemas/final_article_schema.py — Final Articles API Response Schemas
=========================================================================
Pydantic schemas for the /final-articles/ API endpoints.

FinalArticleResponse is the public news feed schema — what the frontend renders.
It includes rank_score so clients can display articles in the correct order.
"""

from datetime import datetime

from pydantic import BaseModel


class FinalArticleResponse(BaseModel):
    """Response schema for a single ranked article in the public news feed.

    Populated from the final_articles table — the output of PublishingService.
    Fields are denormalized (copied from post_processed_articles at publish time)
    so the frontend can render a card without any additional joins.
    """

    id: int
    post_processed_article_id: int | None   # FK to post_processed_articles

    title: str
    description: str | None
    image_url: str | None
    reference_urls: list[str] | None        # related source URLs

    rank_score: float                       # composite ranking score (higher = first)
    created_at: datetime

    model_config = {"from_attributes": True}


class FinalArticleListResponse(BaseModel):
    """Paginated response for GET /final-articles/.

    Includes pagination metadata so the frontend can implement infinite scroll
    or "Load more" without knowing the total count up front.
    """

    total: int                              # total rows in final_articles
    limit: int
    offset: int
    items: list[FinalArticleResponse]
