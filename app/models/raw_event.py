from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RawIngestionEvent(Base):
    __tablename__ = "raw_ingestion_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    # SHA-256(source_id + sorted JSON payload) — dedup key across all time
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # "pending" | "normalized" | "ai_normalized" | "failed"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    normalized_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
