"""
app/models/raw_event.py — Raw Ingestion Events Table
=====================================================
Every raw payload fetched from a source is saved here BEFORE normalization.
This is the "audit log" / "inbox" of the ingestion pipeline.

Why store raw data separately from articles?
  1. Idempotency: If the same article is fetched twice, the content_hash
     (SHA-256 of the payload) detects the duplicate and skips re-processing.
  2. Debugging: If normalization fails, the raw data is still here.
     You can inspect it and replay it with a better normalizer later.
  3. Audit trail: You know exactly what came in, when, and whether it
     was processed successfully or failed.
  4. Retry: Failed items can be retried without re-fetching from the source.

Status lifecycle:
  "pending"    → just fetched, not yet normalized
  "normalized" → successfully processed and written to articles table
  "failed"     → normalization failed (see error_message for why)
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawIngestionEvent(Base):
    """One row = one raw payload received from a news source."""

    __tablename__ = "raw_ingestion_events"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Which source produced this raw event.
    # ondelete="CASCADE": if the source is deleted, all its raw events are too.
    # index=True: fast lookup of "all events for source X".
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )

    # SHA-256 hash of (source_id + sorted JSON payload).
    # This is the deduplication key — if we fetch the same article twice,
    # the hash will be identical and the second insert will be ignored
    # (ON CONFLICT DO NOTHING in the repository).
    # String(64): SHA-256 produces a 64-character hex string.
    # unique=True: enforces no duplicate raw events at the database level.
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # The complete original payload from the source, stored exactly as received.
    # For RSS: the feedparser entry dict.
    # For REST: the JSON object from the API response.
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Current processing state. Possible values:
    #   "pending"    → waiting to be normalized (just fetched)
    #   "normalized" → processed successfully, article row exists
    #   "failed"     → normalization failed after max retries
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    # Which normalizer processed this event. Examples:
    #   "deterministic"                    → rule-based normalizer succeeded
    #   "ai:anthropic:claude-haiku-..."    → AI provider was used
    #   "ai:gemini_langgraph:gemini-2.0-flash" → LangGraph provider
    # None means not yet processed.
    normalized_by: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Human-readable error description when status="failed".
    # e.g. "validation_failed: url is missing or not HTTP(S)"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # How many times we've attempted to normalize this event.
    # SmallInteger saves space — we'll never retry thousands of times.
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # When this raw event was first received (auto-set by PostgreSQL on INSERT).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # When normalization was attempted (success or failure).
    # None = not yet processed.
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
