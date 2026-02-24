"""
app/repositories/final_article_repo.py — Final Articles DB Operations
=======================================================================
All database operations for the "final_articles" table.

Pipeline position:  post_processed_articles → [PublishingService] → [here]

This is the TERMINAL stage repository — what the /final-articles/ API reads.

upsert_batch() is the primary write method used by PublishingService.
  - Upsert key: post_processed_article_id (unique constraint)
  - Existing rows are updated in-place with new rank_score and content
    (rank_score changes on every publishing cycle as new articles arrive
    and old articles time-decay)

get_feed() is the main read method used by the API endpoint.
  - Returns top N articles ordered by rank_score descending (the public feed)
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.final_article import FinalArticle
from app.models.post_processed_article import PostProcessedArticle

logger = logging.getLogger(__name__)


class FinalArticleRepository:
    """Handles all database operations for the final_articles table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert_batch(self, articles: list[dict]) -> int:
        """Upsert a batch of ranked articles into the final feed.

        Args:
            articles: list of dicts from PublishingService, each containing:
                - post_processed_article_id: FK to post_processed_articles
                - title, description, image_url, reference_urls: display fields
                - rank_score: computed ranking float

        Returns:
            Count of rows inserted or updated.

        ON CONFLICT (post_processed_article_id) DO UPDATE:
            Recalculates rank_score on every publishing cycle.
            Content fields are also refreshed in case they were edited.
        """
        if not articles:
            return 0

        stmt = insert(FinalArticle).values(articles)
        stmt = stmt.on_conflict_do_update(
            index_elements=["post_processed_article_id"],
            set_=dict(
                title=stmt.excluded.title,
                description=stmt.excluded.description,
                image_url=stmt.excluded.image_url,
                reference_urls=stmt.excluded.reference_urls,
                rank_score=stmt.excluded.rank_score,
            ),
        ).returning(FinalArticle.id)

        result = await self.db.execute(stmt)
        await self.db.commit()
        return len(result.fetchall())

    async def get_feed(
        self,
        limit: int = 20,
        offset: int = 0,
        sub_category_id: int | None = None,
        q: str | None = None,
    ) -> list[FinalArticle]:
        """Return the public news feed — top articles ordered by rank_score.

        sub_category_id: filter by crime sub-category. Requires a JOIN to
            post_processed_articles because final_articles is denormalized
            (no sub_category_id column).
        q: case-insensitive keyword search across title and description.
        """
        stmt = select(FinalArticle).order_by(FinalArticle.rank_score.desc())
        if sub_category_id is not None:
            stmt = stmt.join(
                PostProcessedArticle,
                FinalArticle.post_processed_article_id == PostProcessedArticle.id,
            ).where(PostProcessedArticle.sub_category_id == sub_category_id)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                FinalArticle.title.ilike(pattern) | FinalArticle.description.ilike(pattern)
            )
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, article_id: int) -> FinalArticle | None:
        result = await self.db.execute(
            select(FinalArticle).where(FinalArticle.id == article_id)
        )
        return result.scalar_one_or_none()

    async def count(
        self,
        sub_category_id: int | None = None,
        q: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(FinalArticle)
        if sub_category_id is not None:
            stmt = stmt.join(
                PostProcessedArticle,
                FinalArticle.post_processed_article_id == PostProcessedArticle.id,
            ).where(PostProcessedArticle.sub_category_id == sub_category_id)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                FinalArticle.title.ilike(pattern) | FinalArticle.description.ilike(pattern)
            )
        result = await self.db.execute(stmt)
        return result.scalar_one()
