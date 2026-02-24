"""
app/models/post_processed_article.py — AI Post-Processing Stage Output Table
=============================================================================
Stores the final, publication-ready version of each crime article.

Pipeline position:  filter_articles → post_processed_articles

The post-processing stage takes a FilterArticle and applies deeper AI enrichment:
  - Rewrites title and description for clarity and news-card readability
  - Collects reference_urls (related sources, previous coverage)
  - Assigns a precise geographic location (State FK)
  - Re-confirms or refines the sub_category

This is the table the frontend reads for the news feed.

Table: post_processed_articles
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.filter_article import FilterArticle
    from app.models.category import MasterSubCategory
    from app.models.final_article import FinalArticle
    from app.models.location import State


class PostProcessedArticle(Base):
    """One row = one fully enriched, publication-ready crime news article."""

    __tablename__ = "post_processed_articles"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The filter_article this was produced from.
    # One-to-one: each FilterArticle produces at most one PostProcessedArticle.
    # SET NULL: if the filter article is deleted, this record can remain as a
    # standalone published record.
    filter_article_id: Mapped[int | None] = mapped_column(
        ForeignKey("filtered_articles.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,     # enforces one-to-one at DB level
        index=True,
    )

    # --- AI-enriched article fields ---

    # AI-rewritten headline optimised for the news card.
    title: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # AI-written 2-3 sentence summary suitable for the card preview.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Thumbnail image URL (may be the same as filter_articles.image_url,
    # or replaced by the AI with a more relevant image).
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Array of related article URLs gathered during post-processing:
    # previous coverage, official sources, related incidents, etc.
    # Stored as PostgreSQL ARRAY(Text) for efficient multi-value storage.
    # Nullable: not all articles will have reference links found.
    reference_urls: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )

    # When this post-processed row was created in our DB.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # When the original article was published (propagated from filter stage).
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Crime sub-category (may differ from filter stage if the AI refines it).
    # SET NULL: retiring a sub-category does not remove published articles.
    sub_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("master_sub_category.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # State where the crime occurred — FK to state table.
    # Nullable: not every article has a determinable precise location.
    # SET NULL: retiring a state reference does not remove published articles.
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("state.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Importance score 1-100 computed by the post-processing AI stage.
    # Combines crime severity, category priority, geographic scope, and media reach.
    # Higher scores surface in the final_articles feed ranking.
    # NULL = not yet scored (rows written before this feature, or AI call failed).
    imp_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # --- Relationships ---
    filter_article: Mapped["FilterArticle | None"] = relationship(  # noqa: F821
        "FilterArticle", back_populates="post_processed_article"
    )
    sub_category: Mapped["MasterSubCategory | None"] = relationship(  # noqa: F821
        "MasterSubCategory", back_populates="post_processed_articles"
    )
    location: Mapped["State | None"] = relationship(  # noqa: F821
        "State", back_populates="post_processed_articles"
    )
    final_article: Mapped["FinalArticle | None"] = relationship(  # noqa: F821
        "FinalArticle", back_populates="post_processed_article", uselist=False
    )
