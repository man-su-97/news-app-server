"""
app/models/final_article.py — Public News Feed Table
=====================================================
Stores the top-ranked, publication-ready articles selected by PublishingService.

Pipeline position:  post_processed_articles → [PublishingService] → final_articles

This is the TERMINAL stage of the pipeline:
  - Scheduler runs PublishingService after every ingestion cycle
  - PublishingService selects top N articles by imp_score + time-decay
  - Those articles are upserted here with a computed rank_score
  - The frontend /final-articles/ endpoint reads exclusively from this table

Why a separate table instead of a flag on post_processed_articles?
  - Clean separation: post_processed_articles is the enrichment store;
    final_articles is the curated public feed.
  - rank_score is recomputed on every publishing cycle — the same article
    can move up/down in ranking as new articles arrive. A separate table
    makes these updates cheap (upsert on small table) and auditable.
  - Non-crime or low-score articles never appear here, keeping the table small.

Table: final_articles
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.post_processed_article import PostProcessedArticle


class FinalArticle(Base):
    """One row = one curated, ranked article in the public news feed."""

    __tablename__ = "final_articles"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The post-processed article this was selected from.
    # One-to-one: each post_processed_article appears at most once in the feed.
    # SET NULL: removing a post_processed_article retains the final feed row.
    post_processed_article_id: Mapped[int | None] = mapped_column(
        ForeignKey("post_processed_articles.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,    # enforces one-to-one at DB level
        index=True,
    )

    # --- Denormalized display fields ---
    # Copied from post_processed_articles so the frontend can read this table
    # alone without a join (important for cold-path caching).

    # AI-rewritten headline optimised for news card display.
    title: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # 2-3 sentence AI summary for the card preview.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Thumbnail image URL (propagated from post_processed_articles).
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Related source URLs — propagated from post_processed_articles.reference_urls.
    reference_urls: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )

    # --- Ranking ---

    # Composite score used to order the feed. Higher = shown first.
    # Formula applied by PublishingService:
    #   rank_score = imp_score
    #                * time_decay_factor(published_at)
    #                * category_priority_boost(sub_category)
    # Range: typically 0–100 (higher is more prominent).
    # Recomputed on every publishing cycle — articles move up/down as fresh
    # news arrives and older articles decay.
    rank_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0", index=True
    )

    # When this final_article row was created (first publication time).
    # Used by the frontend to show "published X minutes ago".
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # --- Relationships ---
    post_processed_article: Mapped["PostProcessedArticle | None"] = relationship(
        "PostProcessedArticle", back_populates="final_article"
    )
