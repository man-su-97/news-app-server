"""
app/schemas/article_schema.py — Article API Response Schemas
=============================================================
Pydantic schemas define the shape of JSON data that goes IN and OUT of the API.

Key difference between models and schemas:
  - models/article.py  → SQLAlchemy model — describes the DATABASE table structure
  - schemas/article_schema.py → Pydantic schema — describes the HTTP REQUEST/RESPONSE body

Why separate schemas from models?
  - You might want to expose only SOME columns to the API (never expose raw_payload,
    internal flags, etc.) without changing the DB structure.
  - You can have different schemas for different operations (e.g. CreateRequest
    vs UpdateRequest vs Response — each with different required fields).
  - Pydantic handles JSON serialization (datetime → ISO string, etc.) automatically.

from_attributes = True:
  This tells Pydantic that it can build the schema from a SQLAlchemy ORM object
  (not just a plain dict). Without this, doing ArticleResponse.from_orm(article_obj)
  would fail because ORM objects don't behave exactly like dicts.
"""

from datetime import datetime

from pydantic import BaseModel   # Base class for all Pydantic models


class ArticleResponse(BaseModel):
    """Schema for a single article returned by the API.

    This is what the frontend receives — every field here appears in the JSON response.
    Fields are chosen to give the frontend everything needed to render a news card.
    """

    # --- Identity ---
    id: int                     # Database primary key — useful for fetching a specific article
    source_id: int              # Which source this came from (join to sources table if needed)

    # --- Card content ---
    title: str                  # Article headline (always present)
    description: str | None     # Raw description from the source feed (may be messy HTML)
    content: str | None         # Full article body (currently always None — future use)
    url: str                    # "Read full article" link to the original website
    image_url: str | None       # Thumbnail for the news card

    # When the article was published on the source website.
    # datetime | None because some sources don't provide publish dates.
    published_at: datetime | None

    # --- AI Enrichment fields ---
    # These are populated by the LangGraph enrichment agent.
    # They may be None for older articles ingested before AI was configured.

    category: str | None        # Always "crime" for articles that passed the filter
    sub_category: str | None    # Crime type: murder, theft, fraud, cybercrime, etc.
    importance_score: int | None  # 1-10 priority (10 = breaking news, 1 = minor local)

    # AI-written 2-3 sentence summary for the news card preview.
    # More readable than the raw description from the RSS feed.
    summary: str | None

    # Where the crime happened, e.g. "Mumbai, India"
    location: str | None

    # Broad region for filtering: "South Asia", "Europe", "North America", etc.
    region: str | None

    # --- Timestamps ---
    created_at: datetime        # When this article was first saved in OUR database

    # from_attributes=True: allows Pydantic to read from SQLAlchemy ORM objects.
    # Without this, you'd have to manually convert Article objects to dicts first.
    model_config = {"from_attributes": True}


class ArticleListResponse(BaseModel):
    """Schema for the paginated list of articles returned by GET /articles/.

    Wraps a list of ArticleResponse with pagination metadata so the frontend
    knows how many total results exist and can implement "load more" or page numbers.
    """
    total: int                      # Total articles in the DB (for pagination UI)
    limit: int                      # How many were requested (e.g. 20)
    offset: int                     # How many were skipped (e.g. 40 = page 3)
    items: list[ArticleResponse]    # The actual articles for this page
