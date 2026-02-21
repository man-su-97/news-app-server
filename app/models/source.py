"""
app/models/source.py — Source Database Model
=============================================
Defines the "sources" table — a "source" is a news feed that the system
periodically fetches articles from.

Examples of sources:
  - An RSS feed from a crime news website: type="rss", url="https://example.com/rss"
  - A REST API endpoint: type="rest", url="https://newsapi.org/v2/..."

Architecture decision: sources are stored in the DB (not hardcoded) so you can
add/remove/disable them without redeploying the application.
The scheduler checks this table every 5 minutes and fetches all active sources.
"""

from datetime import datetime

# SQLAlchemy column type imports
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB   # PostgreSQL JSON column type
from sqlalchemy.orm import Mapped, mapped_column   # Modern SQLAlchemy 2.0 style

from app.models.base import Base   # All models must inherit from Base


class Source(Base):
    """Represents a single news source (RSS feed or REST API endpoint).

    One Source → many Articles (fetched over time from that source).
    """
    __tablename__ = "sources"   # This maps the class to the "sources" DB table

    # Auto-incrementing primary key — unique ID for each source
    id: Mapped[int] = mapped_column(primary_key=True)

    # Human-readable name, e.g. "Times of India Crime"
    name: Mapped[str] = mapped_column(String, nullable=False)

    # What kind of source this is — determines which fetcher to use:
    #   "rss"  → RSSFetcher (reads XML RSS feed via feedparser library)
    #   "rest" → RestFetcher (HTTP GET that returns JSON)
    type: Mapped[str] = mapped_column(String, nullable=False)

    # The URL to fetch from.
    # unique=True prevents accidentally adding the same source twice.
    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    # Optional JSON configuration for this source.
    # Currently used for REST sources to store custom HTTP headers:
    #   config = {"headers": {"Authorization": "Bearer TOKEN123"}}
    # JSONB is PostgreSQL's binary JSON type — faster to query than plain JSON.
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # When False, the scheduler skips this source.
    # Allows temporarily disabling a source without deleting it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Automatically set to the current timestamp when the row is inserted.
    # server_default=func.now() means the DB sets this, not Python —
    # more reliable across timezones and clock skew.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
