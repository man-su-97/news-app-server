"""
app/models/source.py — News Source Database Model
==================================================
Defines the "news_sources" table — a "source" is a news feed that the system
periodically fetches articles from.

Pipeline position:  news_sources → raw_ingestion → filter_articles → post_processed_articles

Architecture decision: sources are stored in the DB (not hardcoded) so you can
add/remove/disable them without redeploying the application.
The scheduler checks this table and fetches all active sources on each cycle.

Renamed from "sources" → "news_sources" in the pipeline redesign migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.raw_event import RawIngestion


class Source(Base):
    """Represents a single news source (RSS feed or REST API endpoint).

    One Source → many RawIngestion rows (fetched payloads over time from that source).
    """

    __tablename__ = "news_sources"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String, nullable=False)

    type: Mapped[str] = mapped_column(String, nullable=False)

    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # --- Relationships ---
    raw_ingestions: Mapped[list["RawIngestion"]] = relationship(  # noqa: F821
        "RawIngestion", back_populates="source", passive_deletes=True
    )
