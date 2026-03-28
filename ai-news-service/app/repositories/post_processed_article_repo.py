import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post_processed_article import PostProcessedArticle

logger = logging.getLogger(__name__)


class PostProcessedArticleRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert_batch(
        self,
        articles: list[dict],
        url_to_filter_id: dict[str, int],
    ) -> int:
        if not articles:
            return 0

        rows = [
            {
                "filter_article_id": url_to_filter_id.get(a["url"]),
                "title": a.get("rewritten_title") or a["title"],
                "description": (
                    a.get("rewritten_description")
                    or a.get("summary")
                    or a.get("description")
                ),
                "image_url": a.get("image_url"),
                "reference_urls": a.get("reference_urls"),
                "published_at": a.get("published_at"),
                "sub_category_id": a.get("sub_category_id"),
                "location_id": a.get("location_id"),
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
            select(PostProcessedArticle).where(PostProcessedArticle.id == article_id)
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

    async def update_reference_urls(self, article_id: int, urls: list[str]) -> None:
        """Persist reference_urls on a post_processed_article row."""
        from sqlalchemy import update

        stmt = (
            update(PostProcessedArticle)
            .where(PostProcessedArticle.id == article_id)
            .values(reference_urls=urls)
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def get_without_reference_urls(
        self, limit: int = 50
    ) -> list[PostProcessedArticle]:
        """Return articles where reference_urls IS NULL (never searched).

        Articles stored with an empty list [] have already been searched and
        returned no results — they are excluded here so we never re-query them.
        Priority is given to higher imp_score so the most important articles
        are enriched first when the run cap is reached.
        """
        stmt = (
            select(PostProcessedArticle)
            .where(PostProcessedArticle.reference_urls.is_(None))
            .order_by(PostProcessedArticle.imp_score.desc().nulls_last())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_reference_urls_searched(self, article_id: int) -> None:
        """Store an empty list as a sentinel meaning 'searched, no results found'.

        This prevents the article from appearing in future get_without_reference_urls
        queries, ensuring each article is searched at most once.
        """
        from sqlalchemy import update

        stmt = (
            update(PostProcessedArticle)
            .where(PostProcessedArticle.id == article_id)
            .values(reference_urls=[])
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def get_top_by_imp_score(self, limit: int = 20) -> list[PostProcessedArticle]:
        stmt = (
            select(PostProcessedArticle)
            .where(PostProcessedArticle.imp_score.is_not(None))
            .order_by(PostProcessedArticle.imp_score.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
