from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.filter_article import FilterArticle
    from app.models.category import MasterSubCategory
    from app.models.final_article import FinalArticle
    from app.models.location import State


class PostProcessedArticle(Base):
    __tablename__ = "post_processed_articles"

    id: Mapped[int] = mapped_column(primary_key=True)

    filter_article_id: Mapped[int | None] = mapped_column(
        ForeignKey("filtered_articles.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    reference_urls: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    sub_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("master_sub_category.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("state.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    imp_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    filter_article: Mapped["FilterArticle | None"] = relationship(
        "FilterArticle", back_populates="post_processed_article"
    )
    sub_category: Mapped["MasterSubCategory | None"] = relationship(
        "MasterSubCategory", back_populates="post_processed_articles"
    )
    location: Mapped["State | None"] = relationship(
        "State", back_populates="post_processed_articles"
    )
    final_article: Mapped["FinalArticle | None"] = relationship(
        "FinalArticle", back_populates="post_processed_article", uselist=False
    )
