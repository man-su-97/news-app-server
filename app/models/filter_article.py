from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.raw_event import RawIngestion
    from app.models.location import State
    from app.models.post_processed_article import PostProcessedArticle


class FilterArticle(Base):
    __tablename__ = "filtered_articles"

    id: Mapped[int] = mapped_column(primary_key=True)

    raw_ingestion_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_ingestion.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    main_url: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    sub_category_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb", default=list
    )
    category_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb", default=list
    )
    location_state_id: Mapped[int | None] = mapped_column(
        ForeignKey("state.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    raw_ingestion: Mapped["RawIngestion | None"] = relationship(
        "RawIngestion", back_populates="filter_article"
    )
    location_state: Mapped["State | None"] = relationship(
        "State", foreign_keys=[location_state_id]
    )
    post_processed_article: Mapped["PostProcessedArticle | None"] = relationship(
        "PostProcessedArticle", back_populates="filter_article", uselist=False
    )
