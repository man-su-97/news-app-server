"""Indexing pipeline: article → chunks → embeddings → DB.

This is the write side of the RAG pipeline. It is idempotent: only articles
without existing chunks are processed, so `/ai/index` can be re-run safely as new
articles are ingested.
"""

import logging
from dataclasses import dataclass

from app.repositories.chunk_repo import ChunkRepository
from app.services.ai.chunking import build_article_text, chunk_text
from app.services.ai.embeddings import Embedder

logger = logging.getLogger(__name__)


@dataclass
class IndexResult:
    indexed_articles: int
    indexed_chunks: int


class IndexingService:
    def __init__(
        self,
        chunk_repo: ChunkRepository,
        embedder: Embedder,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
    ) -> None:
        self.chunk_repo = chunk_repo
        self.embedder = embedder
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    async def index_pending(self, limit: int = 100) -> IndexResult:
        articles = await self.chunk_repo.get_unindexed_articles(limit=limit)
        total_articles = 0
        total_chunks = 0
        for article in articles:
            try:
                text = build_article_text(
                    article.title, article.description, article.content
                )
                pieces = chunk_text(text, self.chunk_size, self.chunk_overlap)
                if not pieces:
                    continue
                embeddings = await self.embedder.embed_documents(pieces)
                rows = [
                    (i, content, embeddings[i])
                    for i, content in enumerate(pieces)
                ]
                await self.chunk_repo.replace_for_article(article.id, rows)
                total_articles += 1
                total_chunks += len(rows)
            except Exception as exc:  # one bad article must not stop the batch
                logger.error("Failed to index article_id=%s: %s", article.id, exc)
        logger.info(
            "Indexing complete: %d articles, %d chunks",
            total_articles,
            total_chunks,
        )
        return IndexResult(
            indexed_articles=total_articles, indexed_chunks=total_chunks
        )
