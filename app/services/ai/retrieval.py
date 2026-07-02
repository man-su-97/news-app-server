"""Retrieval: embed the query, then rank chunks — pure vector or hybrid.

The read side of RAG. Thin on purpose — the vector and full-text SQL lives in
`ChunkRepository`; this service owns query embedding, the top-k policy, and routing
between `"vector"` (cosine only) and `"hybrid"` (vector + full-text fused by RRF).
Metadata `filters` are independent of ranking and apply in either mode.
"""

from typing import Literal

from app.repositories.chunk_repo import (
    ChunkRepository,
    RetrievalFilters,
    RetrievedChunk,
)
from app.services.ai.embeddings import Embedder

SearchMode = Literal["vector", "hybrid"]


class RetrievalService:
    def __init__(
        self,
        chunk_repo: ChunkRepository,
        embedder: Embedder,
        top_k: int = 5,
        candidate_n: int = 50,
        rrf_k: int = 60,
    ) -> None:
        self.chunk_repo = chunk_repo
        self.embedder = embedder
        self.top_k = top_k
        self.candidate_n = candidate_n
        self.rrf_k = rrf_k

    async def search(
        self,
        query: str,
        k: int | None = None,
        mode: SearchMode = "vector",
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievedChunk]:
        query = query.strip()
        if not query:
            return []
        query_embedding = await self.embedder.embed_query(query)
        if mode == "hybrid":
            return await self.chunk_repo.hybrid_search(
                query_embedding,
                query,
                k=k or self.top_k,
                filters=filters,
                candidate_n=self.candidate_n,
                rrf_k=self.rrf_k,
            )
        return await self.chunk_repo.search(query_embedding, k=k or self.top_k)
