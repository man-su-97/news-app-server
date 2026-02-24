"""
app/repositories/filter_article_repo.py — Filter Articles DB Operations
========================================================================
All database operations for the "filter_articles" table.

Pipeline position:  raw_ingestion → [here] → post_processed_articles

insert_batch() is the primary write method used by the ingestion service after
the AI filter stage. It:
  - Uses main_url as the upsert conflict key (same article may be re-ingested)
  - Accepts raw_ingestion_id mappings to maintain the FK link
  - Returns {main_url: filter_article_id} for use by the post-processing stage

Read methods (get_all, get_by_id, count) are available for internal admin use
or a future /filter-articles/ debug endpoint.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.filter_article import FilterArticle

logger = logging.getLogger(__name__)


class FilterArticleRepository:
    """Handles all database operations for the filter_articles table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert_batch(
        self,
        articles: list[dict],
        hash_to_raw_id: dict[str, int],
    ) -> dict[str, int]:
        """Upsert a batch of crime-filtered articles.

        Args:
            articles: list of dicts from the AI filter, each containing:
                - title, description, image_url, main_url (= original url)
                - published_at, content_hash (used to look up raw_ingestion_id)
            hash_to_raw_id: {content_hash: raw_ingestion_id} from store_batch()

        Returns:
            {main_url: filter_article_id} for all inserted/updated rows.
            Used by the post-processing stage to set filter_article_id FK.

        ON CONFLICT (main_url) DO UPDATE:
            Updates metadata fields on re-ingestion (title may be corrected by publisher).
            raw_ingestion_id is NOT updated — keeps the FK to the FIRST ingestion.
        """
        if not articles:
            return {}

        rows = [
            {
                "raw_ingestion_id": hash_to_raw_id.get(a.get("content_hash")),
                "title": a["title"],
                "description": a.get("description"),
                "image_url": a.get("image_url"),
                "main_url": a["url"],
                "published_at": a.get("published_at"),
                # Legacy single FK — kept for backward compat, None until cleanup migration
                "sub_category_id": None,
                # Multi-label JSONB array of master_sub_category IDs, e.g. [1, 3]
                # Populated by CategoryResolver.resolve_all() in IngestionService
                "sub_category_ids": a.get("sub_category_ids") or [],
                # State FK resolved from AI location string by LocationResolver
                "location_state_id": a.get("location_state_id"),
            }
            for a in articles
        ]

        stmt = insert(FilterArticle).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["main_url"],
            set_=dict(
                title=stmt.excluded.title,
                description=stmt.excluded.description,
                image_url=stmt.excluded.image_url,
                published_at=stmt.excluded.published_at,
                sub_category_ids=stmt.excluded.sub_category_ids,
                location_state_id=stmt.excluded.location_state_id,
                # raw_ingestion_id intentionally not updated — preserve first link
            ),
        ).returning(FilterArticle.main_url, FilterArticle.id)

        result = await self.db.execute(stmt)
        await self.db.commit()
        return {row.main_url: row.id for row in result.all()}

    async def get_all(
        self,
        limit: int = 20,
        offset: int = 0,
        sub_category_id: int | None = None,
        q: str | None = None,
    ) -> list[FilterArticle]:
        """Paginated list ordered by published_at descending.

        sub_category_id: JSONB containment filter — matches rows where
            sub_category_ids array contains this integer (e.g. [1, 3] @> [2]).
        q: case-insensitive keyword search across title and description.
        """
        stmt = select(FilterArticle).order_by(FilterArticle.published_at.desc().nulls_last())
        if sub_category_id is not None:
            # PostgreSQL @> operator: sub_category_ids @> '[sub_category_id]'
            stmt = stmt.where(FilterArticle.sub_category_ids.contains([sub_category_id]))
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                FilterArticle.title.ilike(pattern) | FilterArticle.description.ilike(pattern)
            )
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, article_id: int) -> FilterArticle | None:
        result = await self.db.execute(
            select(FilterArticle).where(FilterArticle.id == article_id)
        )
        return result.scalar_one_or_none()

    async def count(self, sub_category_id: int | None = None, q: str | None = None) -> int:
        stmt = select(func.count()).select_from(FilterArticle)
        if sub_category_id is not None:
            stmt = stmt.where(FilterArticle.sub_category_ids.contains([sub_category_id]))
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                FilterArticle.title.ilike(pattern) | FilterArticle.description.ilike(pattern)
            )
        result = await self.db.execute(stmt)
        return result.scalar_one()
