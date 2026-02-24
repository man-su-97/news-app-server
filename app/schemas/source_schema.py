"""
app/schemas/source_schema.py — Source API Schemas
==================================================
Pydantic schemas for the /sources API endpoints.

Two schemas:
  - SourceCreate:   what the client sends when CREATING a new source (POST body)
  - SourceResponse: what the API returns when reading sources (GET response)

Architecture note: SourceCreate doesn't have `is_active` because new sources
should always start active — the API sets this automatically.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    """Request body for POST /sources/ — creates a new news source."""
    name: str = Field(..., description="Human-readable label for this source", examples=["India News Crime RSS"])
    type: str = Field(..., description="Feed type: 'rss' for RSS/Atom feeds, 'rest' for JSON APIs", examples=["rss"])
    url: str = Field(..., description="Feed URL to fetch articles from", examples=["https://timesofindia.indiatimes.com/rssfeeds/7503091.cms"])
    config: dict | None = Field(
        default=None,
        description="Optional extra config. For REST sources with auth: {\"headers\": {\"Authorization\": \"Bearer TOKEN\"}}",
        examples=[None],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "RSS feed",
                    "value": {
                        "name": "Times of India Crime",
                        "type": "rss",
                        "url": "https://timesofindia.indiatimes.com/rssfeeds/7503091.cms",
                        "config": None,
                    },
                },
                {
                    "summary": "REST API with auth header",
                    "value": {
                        "name": "NewsAPI Crime",
                        "type": "rest",
                        "url": "https://newsapi.org/v2/top-headlines?category=crime",
                        "config": {"headers": {"Authorization": "Bearer YOUR_API_KEY"}},
                    },
                },
            ]
        }
    }


class SourceUpdate(BaseModel):
    """Request body for PATCH /sources/{id} — all fields optional (partial update)."""
    name: str | None = Field(default=None, description="New display name for this source")
    url: str | None = Field(default=None, description="New feed URL")
    is_active: bool | None = Field(default=None, description="Set false to pause fetching without deleting")
    config: dict | None = Field(default=None, description="Updated config (headers, etc.)")


class SourceResponse(BaseModel):
    """Response body for GET /sources/ and GET /sources/{id}.

    Returned as JSON — the frontend can use this to list all configured sources.
    """
    id: int                 # Database primary key
    name: str               # Source label
    type: str               # "rss" or "rest"
    url: str                # Feed URL
    config: dict | None     # Any stored config (headers, etc.)
    is_active: bool         # Whether this source is currently being fetched
    created_at: datetime    # When it was added

    # Allow building this schema from a SQLAlchemy Source ORM object
    model_config = {"from_attributes": True}
