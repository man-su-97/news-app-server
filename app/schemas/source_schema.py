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

from pydantic import BaseModel


class SourceCreate(BaseModel):
    """Request body for POST /sources/ — creates a new news source.

    The client provides these fields in JSON:
    {
        "name": "Times of India Crime",
        "type": "rss",
        "url": "https://timesofindia.indiatimes.com/rss.cms",
        "config": null
    }
    """
    name: str               # Human-readable label for this source
    type: str               # "rss" or "rest" — determines which fetcher is used
    url: str                # Feed URL to fetch from
    config: dict | None = None  # Optional extra config (e.g. {"headers": {"Authorization": "Bearer ..."}})


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
