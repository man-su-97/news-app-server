from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.article_chunk import ArticleChunk


@dataclass
class RetrievedChunk:
    """A chunk returned from vector search, joined to its parent article."""

    chunk_id: int
    article_id: int
    chunk_index: int
    content: str
    title: str
    url: str
    distance: float

    @property
    def score(self) -> float:
        # Cosine distance in [0, 2] → similarity in [-1, 1]; higher is closer.
        return 1.0 - self.distance


class ChunkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def replace_for_article(
        self, article_id: int, chunks: list[tuple[int, str, list[float]]]
    ) -> int:
        """Idempotently (re)write all chunks for one article.

        `chunks` is a list of (chunk_index, content, embedding).
        """
        await self.db.execute(
            delete(ArticleChunk).where(ArticleChunk.article_id == article_id)
        )
        self.db.add_all(
            [
                ArticleChunk(
                    article_id=article_id,
                    chunk_index=idx,
                    content=content,
                    embedding=embedding,
                )
                for idx, content, embedding in chunks
            ]
        )
        await self.db.commit()
        return len(chunks)

    async def get_unindexed_articles(self, limit: int = 100) -> list[Article]:
        """Articles that have no chunks yet."""
        indexed = select(ArticleChunk.article_id).distinct()
        stmt = (
            select(Article)
            .where(Article.id.notin_(indexed))
            .order_by(Article.id)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def search(
        self, query_embedding: list[float], k: int = 5
    ) -> list[RetrievedChunk]:
        """Top-k chunks by cosine distance to the query embedding."""
        distance = ArticleChunk.embedding.cosine_distance(query_embedding).label(
            "distance"
        )
        stmt = (
            select(
                ArticleChunk.id,
                ArticleChunk.article_id,
                ArticleChunk.chunk_index,
                ArticleChunk.content,
                Article.title,
                Article.url,
                distance,
            )
            .join(Article, Article.id == ArticleChunk.article_id)
            .order_by(distance)
            .limit(k)
        )
        result = await self.db.execute(stmt)
        return [
            RetrievedChunk(
                chunk_id=row.id,
                article_id=row.article_id,
                chunk_index=row.chunk_index,
                content=row.content,
                title=row.title,
                url=row.url,
                distance=float(row.distance),
            )
            for row in result.all()
        ]
