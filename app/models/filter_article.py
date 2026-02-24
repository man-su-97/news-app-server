"""
app/models/filter_article.py — AI Filter Stage Output Table
============================================================
Stores articles that have passed the AI crime-relevance filter.

Pipeline position:  raw_ingestion → filter_articles → post_processed_articles

When the AI filter processes a raw_ingestion row:
  - Non-crime content  → raw_ingestion.status = "filtered_out", no row created here
  - Crime-relevant     → a FilterArticle row is created with normalised fields
                         and raw_ingestion.status = "filtered"

The filter stage extracts only the essential display fields from the raw payload:
  title, description, image_url, main_url, published_at, sub_category_id

The subsequent post-processing stage (PostProcessedArticle) reads from this table
and produces the publication-ready version.

Table: filter_articles
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.raw_event import RawIngestion
    from app.models.category import MasterSubCategory
    from app.models.location import State
    from app.models.post_processed_article import PostProcessedArticle


class FilterArticle(Base):
    """One row = one crime-relevant article that survived the AI filter stage."""

    __tablename__ = "filter_articles"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The raw payload row this was produced from.
    # One-to-one: each raw_ingestion produces at most one FilterArticle.
    # SET NULL rather than CASCADE: if the raw event is cleaned up, the filter
    # article can remain as a valid processed record.
    raw_ingestion_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_ingestion.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,     # enforces the one-to-one constraint at DB level
        index=True,
    )

    # --- AI-extracted article fields ---

    # Cleaned/normalised headline from the AI filter.
    title: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Short description extracted or cleaned from the raw payload.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Thumbnail image URL.
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Canonical URL of the original article on the source website.
    main_url: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)

    # When this filter_article row was created in our DB.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # When the original article was published on the source website.
    # Nullable: some sources don't provide a publish date.
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Crime sub-category assigned by the AI filter (legacy single-FK).
    # Kept for backward compatibility; new code writes sub_category_ids instead.
    # Will be dropped in a future cleanup migration.
    sub_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("master_sub_category.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Multi-label crime classification: JSONB array of master_sub_category.id ints.
    # Example: [1, 3] = Murder + Terrorism.
    # Default empty list so JSON containment queries (@>) work without NULL-checks.
    sub_category_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb", default=list
    )

    # State where the crime occurred — FK to state table.
    # Populated by the AI filter stage alongside sub_category_ids.
    # SET NULL: retiring a state does not remove filter articles.
    location_state_id: Mapped[int | None] = mapped_column(
        ForeignKey("state.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Relationships ---
    raw_ingestion: Mapped["RawIngestion | None"] = relationship(  # noqa: F821
        "RawIngestion", back_populates="filter_article"
    )
    sub_category: Mapped["MasterSubCategory | None"] = relationship(  # noqa: F821
        "MasterSubCategory", back_populates="filter_articles"
    )
    location_state: Mapped["State | None"] = relationship(  # noqa: F821
        "State", foreign_keys=[location_state_id]
    )
    post_processed_article: Mapped["PostProcessedArticle | None"] = relationship(  # noqa: F821
        "PostProcessedArticle", back_populates="filter_article", uselist=False
    )
