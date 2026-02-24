"""
app/repositories/post_processed_article_repo.py — Post-Processed Articles DB Operations
========================================================================================
All database operations for the "post_processed_articles" table.

Pipeline position:  filter_articles → [here]

This is the FINAL stage table — what the frontend reads for the news feed.
insert_batch() is called by the ingestion service after AI post-processing.
get_all/get_by_id/count are used by the GET /articles/ API endpoints.

insert_batch() upsert key is filter_article_id (unique constraint):
  - Same filter article re-processed → updates the post-processed row in-place.
  - This keeps the feed current if a publisher corrects an article.
"""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post_processed_article import PostProcessedArticle

logger = logging.getLogger(__name__)


class PostProcessedArticleRepository:
    """Handles all database operations for the post_processed_articles table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert_batch(
        self,
        articles: list[dict],
        url_to_filter_id: dict[str, int],
    ) -> int:
        """Upsert a batch of fully-enriched articles.

        Args:
            articles: list of AI-processed dicts, each containing:
                - title, description, image_url, published_at
                - reference_urls (list[str] | None)
                - url (used to look up filter_article_id)
                - sub_category_id, location_id (may be None until master data exists)
            url_to_filter_id: {main_url: filter_article_id} from filter stage.

        Returns:
            Count of rows inserted or updated.

        ON CONFLICT (filter_article_id) DO UPDATE:
            Re-running post-processing on the same article updates title,
            description, reference_urls — useful when AI improves.
        """
        if not articles:
            return 0

        rows = [
            {
                "filter_article_id": url_to_filter_id.get(a["url"]),
                # Stage 2 post_process() rewrites these; fall back to stage 1 values
                "title": a.get("rewritten_title") or a["title"],
                "description": (
                    a.get("rewritten_description")
                    or a.get("summary")
                    or a.get("description")
                ),
                "image_url": a.get("image_url"),
                # Stage 2 fills reference_urls; stage 1 leaves it empty
                "reference_urls": a.get("reference_urls") or a.get("stage2_reference_urls"),
                "published_at": a.get("published_at"),
                "sub_category_id": a.get("sub_category_id"),
                "location_id": a.get("location_id"),
                # Stage 2 imp_score: 1-100. None if stage 2 not run / failed.
                "imp_score": a.get("imp_score"),
            }
            for a in articles
            if url_to_filter_id.get(a["url"]) is not None
        ]

        if not rows:
            logger.warning("insert_batch: no rows had a valid filter_article_id — skipping")
            return 0

        stmt = insert(PostProcessedArticle).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["filter_article_id"],
            set_=dict(
                title=stmt.excluded.title,
                description=stmt.excluded.description,
                image_url=stmt.excluded.image_url,
                reference_urls=stmt.excluded.reference_urls,
                published_at=stmt.excluded.published_at,
                sub_category_id=stmt.excluded.sub_category_id,
                location_id=stmt.excluded.location_id,
                imp_score=stmt.excluded.imp_score,
            ),
        ).returning(PostProcessedArticle.id)

        result = await self.db.execute(stmt)
        await self.db.commit()
        return len(result.fetchall())

    async def get_all(
        self,
        limit: int = 20,
        offset: int = 0,
        sub_category_id: int | None = None,
        q: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[PostProcessedArticle]:
        """Paginated list ordered by published_at descending.

        sub_category_id: exact FK match on sub_category_id column.
        q: case-insensitive keyword search across title and description.
        from_date / to_date: filter by published_at range (inclusive).
        """
        stmt = select(PostProcessedArticle).order_by(
            PostProcessedArticle.published_at.desc().nulls_last()
        )
        if sub_category_id is not None:
            stmt = stmt.where(PostProcessedArticle.sub_category_id == sub_category_id)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                PostProcessedArticle.title.ilike(pattern)
                | PostProcessedArticle.description.ilike(pattern)
            )
        if from_date is not None:
            stmt = stmt.where(PostProcessedArticle.published_at >= from_date)
        if to_date is not None:
            stmt = stmt.where(PostProcessedArticle.published_at <= to_date)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, article_id: int) -> PostProcessedArticle | None:
        result = await self.db.execute(
            select(PostProcessedArticle).where(
                PostProcessedArticle.id == article_id
            )
        )
        return result.scalar_one_or_none()

    async def count(
        self,
        sub_category_id: int | None = None,
        q: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(PostProcessedArticle)
        if sub_category_id is not None:
            stmt = stmt.where(PostProcessedArticle.sub_category_id == sub_category_id)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                PostProcessedArticle.title.ilike(pattern)
                | PostProcessedArticle.description.ilike(pattern)
            )
        if from_date is not None:
            stmt = stmt.where(PostProcessedArticle.published_at >= from_date)
        if to_date is not None:
            stmt = stmt.where(PostProcessedArticle.published_at <= to_date)
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_top_by_imp_score(self, limit: int = 20) -> list[PostProcessedArticle]:
        """Return top N articles ordered by imp_score descending.

        Used by PublishingService to select candidates for final_articles.
        Articles with NULL imp_score are excluded (they have not been post-processed).
        """
        stmt = (
            select(PostProcessedArticle)
            .where(PostProcessedArticle.imp_score.is_not(None))
            .order_by(PostProcessedArticle.imp_score.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
