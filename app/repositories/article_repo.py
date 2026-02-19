from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article


class ArticleRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert(self, data: dict, source_id: int) -> None:
        stmt = (
            insert(Article)
            .values(
                source_id=source_id,
                title=data["title"],
                description=data.get("description"),
                content=data.get("content"),
                url=data["url"],
                image_url=data.get("image_url"),
                published_at=data.get("published_at"),
                raw_payload=data["raw_payload"],
            )
            .on_conflict_do_nothing(index_elements=["url"])
        )
        await self.db.execute(stmt)
        await self.db.commit()

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
