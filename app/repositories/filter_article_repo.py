import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.filter_article import FilterArticle

logger = logging.getLogger(__name__)


class FilterArticleRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def insert_batch(
        self,
        articles: list[dict],
        hash_to_raw_id: dict[str, int],
    ) -> dict[str, int]:
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
                "sub_category_ids": a.get("sub_category_ids") or [],
                "category_ids": a.get("category_ids") or [],
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
                category_ids=stmt.excluded.category_ids,
                location_state_id=stmt.excluded.location_state_id,
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
        stmt = select(FilterArticle).order_by(FilterArticle.published_at.desc().nulls_last())
        if sub_category_id is not None:
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
