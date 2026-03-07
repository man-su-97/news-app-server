"""
app/models/location.py — Geographic Reference Tables
=====================================================
Two-level location hierarchy used for tagging articles with where a crime occurred:

  Country  → e.g. "India", "United States"
  State    → e.g. "Maharashtra", "California"
              each State belongs to exactly one Country

post_processed_articles carry a location_id FK pointing to a State row.
The Country is reached by joining State → Country.

Tables: country, state
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.post_processed_article import PostProcessedArticle


class Country(Base):
    """Top-level geographic reference: a country."""

    __tablename__ = "country"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    states: Mapped[list["State"]] = relationship(
        "State", back_populates="country", passive_deletes=True
    )


class State(Base):
    """State, province, or region within a Country.

    Used as the FK target in post_processed_articles.location_id.
    Provides a structured location instead of a free-text string.
    """

    __tablename__ = "state"

    id: Mapped[int] = mapped_column(primary_key=True)

    country_id: Mapped[int] = mapped_column(
        ForeignKey("country.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    country: Mapped["Country"] = relationship(
        "Country", back_populates="states")
    post_processed_articles: Mapped[list["PostProcessedArticle"]] = relationship(  # noqa: F821
        "PostProcessedArticle", back_populates="location"
    )
