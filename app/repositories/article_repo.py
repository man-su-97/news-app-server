from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article


class ArticleRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert_batch(self, articles: list[dict], source_id: int) -> int:
        """Batch upsert with ON CONFLICT DO UPDATE on url.

        Why DO UPDATE instead of DO NOTHING:
        - Publishers correct articles (fix typos, update titles, swap images).
        - DO NOTHING silently eats corrections forever.
        - created_at and source_id are excluded from the update set — they reflect
          the original ingestion and must not be overwritten.
        - raw_payload is updated so the stored blob always reflects the latest fetch.

        Returns the count of rows written (inserted + updated). Single DB round-trip
        regardless of batch size — replaces the previous per-article commit loop.
        """
        if not articles:
            return 0

        rows = [
            {
                "source_id": source_id,
                "title": a["title"],
                "description": a.get("description"),
                "content": a.get("content"),
                "url": a["url"],
                "image_url": a.get("image_url"),
                "published_at": a.get("published_at"),
                "raw_payload": a["raw_payload"],
            }
            for a in articles
        ]

        stmt = insert(Article).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["url"],
            set_=dict(
                title=stmt.excluded.title,
                description=stmt.excluded.description,
                image_url=stmt.excluded.image_url,
                raw_payload=stmt.excluded.raw_payload,
                updated_at=func.now(),
            ),
        ).returning(Article.id)

        result = await self.db.execute(stmt)
        await self.db.commit()
        return len(result.fetchall())

    async def get_all(self, limit: int = 20, offset: int = 0) -> list[Article]:
        stmt = (
            select(Article)
            .order_by(Article.published_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, article_id: int) -> Article | None:
        result = await self.db.execute(
            select(Article).where(Article.id == article_id)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(Article))
        return result.scalar_one()
