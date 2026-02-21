"""
app/models/article.py — Article Database Model
===============================================
Defines the "articles" table — the central table of the entire application.
Every crime news article that survives normalization and AI enrichment
ends up as a row in this table.

A news card in the frontend is built entirely from one Article row:
  - title, summary          → card headline and preview text
  - url                     → "Read full article" link
  - image_url               → card thumbnail
  - published_at            → "2 hours ago" timestamp
  - location, region        → location tag and region filter
  - sub_category            → crime type badge (murder, fraud, etc.)
  - importance_score        → used to sort the feed (higher = shown first)

Architecture decisions:
  - url is UNIQUE: prevents duplicate articles if the same URL appears in
    multiple fetches. ON CONFLICT DO UPDATE (in the repo) keeps it fresh.
  - Enrichment fields (category, sub_category, etc.) are nullable: articles
    ingested before the AI was configured still have a valid row, just with
    NULL enrichment fields. This avoids data loss during upgrades.
  - raw_payload (JSONB) stores the original data from the source. Useful for
    debugging, reprocessing, and future feature extraction without re-fetching.
"""

from datetime import datetime

# Import all needed SQLAlchemy column type classes
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB    # PostgreSQL binary JSON
from sqlalchemy.orm import Mapped, mapped_column   # SQLAlchemy 2.0 typed columns

from app.models.base import Base


class Article(Base):
    """One row = one crime news article stored in the database."""

    __tablename__ = "articles"

    # --- Identity ---
    id: Mapped[int] = mapped_column(primary_key=True)

    # Which source this article came from.
    # ForeignKey links to sources.id — if a source is deleted, all its articles
    # are also deleted (ondelete="CASCADE").
    # index=True speeds up queries like "give me all articles from source X".
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )

    # --- Core article content (set during normalization) ---

    # The article headline. index=True enables fast text searches on title.
    title: Mapped[str] = mapped_column(String, index=True)

    # Original description/summary from the source feed (may be raw HTML).
    # Text type = unlimited length (unlike String which has a default limit).
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full article body text. Not populated in the current pipeline
    # (fetchers only get metadata, not full content). Reserved for future use.
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The full URL to the article on its original website.
    # unique=True is the deduplication key — if the same article URL comes in
    # twice, the repo upserts (updates) the existing row instead of creating a duplicate.
    url: Mapped[str] = mapped_column(String, unique=True, index=True)

    # URL of the article's thumbnail image. Used for the news card image.
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # When the article was originally published (timezone-aware UTC datetime).
    # index=True enables efficient "latest news first" sorting.
    # nullable=True because some sources don't provide publish dates.
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )

    # The complete raw JSON payload from the source, stored as-is.
    # Why store this? It allows reprocessing the article with a better AI
    # later without re-fetching from the source. Also useful for debugging.
    raw_payload: Mapped[dict] = mapped_column(JSONB)

    # --- AI Enrichment fields (set by the LangGraph enrichment agent) ---
    # All nullable: articles ingested before AI was configured have NULL here.

    # Top-level category. Always "crime" for articles that pass the filter.
    # index=True enables efficient filtering: "show only crime articles".
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # Crime subcategory picked from the fixed list:
    # murder, theft, fraud, cybercrime, terrorism, corruption,
    # drugs, violence, trafficking, other
    sub_category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Priority score from 1 (local/minor) to 10 (breaking/global crisis).
    # Frontend sorts the news feed by this value — higher = shown first.
    importance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # AI-generated 2-3 sentence summary written for a news card preview.
    # More readable than the raw description from the RSS feed.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # City + country where the crime occurred, e.g. "Mumbai, India"
    # Extracted by the AI from the article title/description.
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Broad geographic region for frontend filtering, e.g. "South Asia"
    # Picked from a fixed list: South Asia, Europe, North America, etc.
    # index=True enables efficient region-based filtering in the frontend.
    region: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # --- Timestamps (set by the database, not Python) ---

    # When the article was first inserted into our DB.
    # server_default=func.now() means PostgreSQL sets this automatically on INSERT.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # When the article was last updated (e.g., title corrected by publisher).
    # onupdate=func.now() auto-updates this whenever the row changes.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
