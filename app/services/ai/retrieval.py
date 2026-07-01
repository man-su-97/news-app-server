"""Retrieval: embed the query, then pgvector cosine top-k.

The read side of RAG. Thin on purpose — the vector search itself lives in
`ChunkRepository.search`; this service owns query embedding and the top-k policy.
"""

from app.repositories.chunk_repo import ChunkRepository, RetrievedChunk
from app.services.ai.embeddings import Embedder


class RetrievalService:
    def __init__(
        self, chunk_repo: ChunkRepository, embedder: Embedder, top_k: int = 5
    ) -> None:
        self.chunk_repo = chunk_repo
        self.embedder = embedder
        self.top_k = top_k

    async def search(
        self, query: str, k: int | None = None
    ) -> list[RetrievedChunk]:
        query = query.strip()
        if not query:
            return []
        query_embedding = await self.embedder.embed_query(query)
        return await self.chunk_repo.search(query_embedding, k=k or self.top_k)
