from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article
from app.models.article_chunk import ArticleChunk
from app.models.source import Source


@dataclass
class RetrievedChunk:
    """A chunk returned from search, joined to its parent article.

    For pure vector search, ranking is by cosine `distance`. For hybrid search,
    `rrf_score` carries the fused Reciprocal Rank Fusion score and `distance` is
    not meaningful.
    """

    chunk_id: int
    article_id: int
    chunk_index: int
    content: str
    title: str
    url: str
    distance: float
    rrf_score: float | None = None

    @property
    def score(self) -> float:
        if self.rrf_score is not None:
            return self.rrf_score
        # Cosine distance in [0, 2] → similarity in [-1, 1]; higher is closer.
        return 1.0 - self.distance


@dataclass
class RetrievalFilters:
    """Plain, framework-free metadata filters shared by both search arms.

    Built from the API's Pydantic filter model at the edge and passed down, so the
    repository and service layers stay free of Pydantic. `to_conditions` renders the
    set fields into SQLAlchemy WHERE clauses applied identically to each arm.
    """

    source_id: int | None = None
    source_name: str | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None

    def to_conditions(self) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []
        if self.source_id is not None:
            conditions.append(Article.source_id == self.source_id)
        if self.source_name is not None:
            # Scalar subquery avoids a join, keeping both arms' WHERE identical.
            conditions.append(
                Article.source_id.in_(
                    select(Source.id).where(Source.name == self.source_name)
                )
            )
        if self.published_from is not None:
            conditions.append(Article.published_at >= self.published_from)
        if self.published_to is not None:
            conditions.append(Article.published_at <= self.published_to)
        return conditions


def _compute_rrf(
    list_a: list[int], list_b: list[int], k: int = 60
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion of two ranked id-lists (rank 1 = best).

    score(id) = sum over each list containing id of 1 / (k + rank_in_list).
    Returns (id, score) pairs sorted best-first; ties break by id ascending.
    Fusing ranks (not raw scores) avoids reconciling cosine distance against
    ts_rank on different scales — `k` only damps the contribution of rank.
    """
    scores: dict[int, float] = {}
    for ranked in (list_a, list_b):
        for rank, id_ in enumerate(ranked, start=1):
            scores[id_] = scores.get(id_, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


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

    async def hybrid_search(
        self,
        query_embedding: list[float],
        query_text: str,
        k: int = 5,
        filters: RetrievalFilters | None = None,
        candidate_n: int = 50,
        rrf_k: int = 60,
    ) -> list[RetrievedChunk]:
        """Fuse a vector arm and a full-text arm via Reciprocal Rank Fusion.

        Each arm retrieves up to `candidate_n` chunk ids (with `filters` applied
        identically), then `_compute_rrf` fuses the two rankings and the top `k`
        chunks are hydrated. Ranks — not raw scores — are fused, so cosine distance
        and ts_rank never have to be reconciled on the same scale.
        """
        conditions = filters.to_conditions() if filters else []

        # Vector arm: nearest neighbours by cosine distance.
        distance = ArticleChunk.embedding.cosine_distance(query_embedding)
        vector_stmt = (
            select(ArticleChunk.id)
            .join(Article, Article.id == ArticleChunk.article_id)
            .where(*conditions)
            .order_by(distance)
            .limit(candidate_n)
        )
        vector_ids = list((await self.db.execute(vector_stmt)).scalars().all())

        # Lexical arm: full-text match ranked by ts_rank.
        tsquery = func.websearch_to_tsquery("english", query_text)
        lexical_stmt = (
            select(ArticleChunk.id)
            .join(Article, Article.id == ArticleChunk.article_id)
            .where(ArticleChunk.content_tsv.op("@@")(tsquery), *conditions)
            .order_by(func.ts_rank(ArticleChunk.content_tsv, tsquery).desc())
            .limit(candidate_n)
        )
        lexical_ids = list((await self.db.execute(lexical_stmt)).scalars().all())

        fused = _compute_rrf(vector_ids, lexical_ids, k=rrf_k)
        top = fused[:k]
        if not top:
            return []
        rrf_by_id = dict(top)
        top_ids = [id_ for id_, _ in top]

        rows_stmt = (
            select(
                ArticleChunk.id,
                ArticleChunk.article_id,
                ArticleChunk.chunk_index,
                ArticleChunk.content,
                Article.title,
                Article.url,
            )
            .join(Article, Article.id == ArticleChunk.article_id)
            .where(ArticleChunk.id.in_(top_ids))
        )
        rows = {row.id: row for row in (await self.db.execute(rows_stmt)).all()}
        # Preserve fused order (the IN query does not guarantee ordering).
        return [
            RetrievedChunk(
                chunk_id=row.id,
                article_id=row.article_id,
                chunk_index=row.chunk_index,
                content=row.content,
                title=row.title,
                url=row.url,
                distance=0.0,
                rrf_score=rrf_by_id[id_],
            )
            for id_ in top_ids
            if (row := rows.get(id_)) is not None
        ]
