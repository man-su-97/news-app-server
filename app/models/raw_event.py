"""
app/models/raw_event.py — Raw Ingestion Table
==============================================
Every raw payload fetched from a source is saved here BEFORE any AI processing.
This is the "inbox" / audit log of the ingestion pipeline.

Pipeline position:  news_sources → raw_ingestion → filter_articles → post_processed_articles

Why store raw data separately from processed articles?
  1. Idempotency: content_hash (SHA-256 of source_id + payload) detects duplicates
     across fetches — the same article fetched twice is silently ignored.
  2. Replayability: if AI normalization fails or improves, raw payloads can be
     reprocessed without re-fetching from the source.
  3. Audit trail: every inbound payload is recorded with its processing status.

Status lifecycle:
  "pending"      → fetched, not yet processed by AI filter
  "filtered"     → survived AI filtering; filter_articles row exists
  "processed"    → fully processed; post_processed_articles row exists
  "filtered_out" → AI determined this is not a crime article
  "failed"       → processing failed (see error_message)

Renamed from "raw_ingestion_events" → "raw_ingestion" in pipeline redesign migration.
RawIngestionEvent class renamed → RawIngestion to match new table name.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.source import Source
    from app.models.filter_article import FilterArticle


class RawIngestion(Base):
    """One row = one raw payload received from a news source."""

    __tablename__ = "raw_ingestion"

    id: Mapped[int] = mapped_column(primary_key=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("news_sources.id", ondelete="CASCADE"), index=True
    )

    content_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False)

    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )

    normalized_by: Mapped[str | None] = mapped_column(
        String(200), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    retry_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source: Mapped["Source"] = relationship(
        "Source", back_populates="raw_ingestions"
    )
    filter_article: Mapped["FilterArticle | None"] = relationship(
        "FilterArticle", back_populates="raw_ingestion", uselist=False
    )
