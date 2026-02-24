"""
app/models/category.py — Crime Category Taxonomy Tables
========================================================
Two-level crime category hierarchy used for classifying articles:

  MasterCategory      → top-level crime type (e.g. "Violent Crime")
  MasterSubCategory   → specific sub-type (e.g. "Murder", "Assault")
                        each belongs to exactly one MasterCategory

Both tables are reference/lookup data:
  - Seeded once via Alembic data migration or admin API
  - Filtered and post-processed articles carry a sub_category_id FK
  - priority_point is used by the frontend to order categories in the UI

Tables: master_category, master_sub_category
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.post_processed_article import PostProcessedArticle


class MasterCategory(Base):
    """Top-level crime category, e.g. 'Violent Crime', 'Financial Crime'."""

    __tablename__ = "master_category"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Display label shown in the UI, e.g. "Violent Crime"
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Optional longer description of what this category covers.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # UI sort weight — lower number = shown first in category lists.
    priority_point: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # When False, this category is hidden from the frontend feed.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Set by PostgreSQL on INSERT.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # --- Relationships ---
    sub_categories: Mapped[list["MasterSubCategory"]] = relationship(
        "MasterSubCategory", back_populates="category", passive_deletes=True
    )


class MasterSubCategory(Base):
    """Crime sub-category tied to a MasterCategory.

    Examples:
      MasterCategory: "Violent Crime"  →  MasterSubCategory: "Murder", "Assault"
      MasterCategory: "Financial Crime" →  MasterSubCategory: "Fraud", "Corruption"
    """

    __tablename__ = "master_sub_category"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Parent category — RESTRICT prevents deleting a category that still has sub-cats.
    category_id: Mapped[int] = mapped_column(
        ForeignKey("master_category.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Display label, e.g. "Murder", "Cybercrime"
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Optional longer description.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # UI sort weight within the parent category.
    priority_point: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # When False, articles with this sub-category are hidden from the feed.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Set by PostgreSQL on INSERT.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # --- Relationships ---
    category: Mapped["MasterCategory"] = relationship(
        "MasterCategory", back_populates="sub_categories"
    )
    post_processed_articles: Mapped[list["PostProcessedArticle"]] = relationship(  # noqa: F821
        "PostProcessedArticle", back_populates="sub_category"
    )
