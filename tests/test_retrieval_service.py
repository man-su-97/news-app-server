"""Service-layer routing tests for RetrievalService — fakes only, no DB.

Verifies that `mode` selects the right repository method and that filters and
the RRF/candidate config are threaded through to the hybrid arm.
"""

import pytest

from app.repositories.chunk_repo import RetrievalFilters
from app.services.ai.retrieval import RetrievalService


class FakeEmbedder:
    async def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class FakeChunkRepo:
    def __init__(self):
        self.search_calls = []
        self.hybrid_calls = []

    async def search(self, query_embedding, k=5):
        self.search_calls.append({"embedding": query_embedding, "k": k})
        return ["vector-result"]

    async def hybrid_search(
        self, query_embedding, query_text, k=5, filters=None, candidate_n=50, rrf_k=60
    ):
        self.hybrid_calls.append(
            {
                "embedding": query_embedding,
                "query_text": query_text,
                "k": k,
                "filters": filters,
                "candidate_n": candidate_n,
                "rrf_k": rrf_k,
            }
        )
        return ["hybrid-result"]


def make_service(**kwargs):
    return RetrievalService(FakeChunkRepo(), FakeEmbedder(), **kwargs)


@pytest.mark.asyncio
async def test_default_mode_is_vector():
    svc = make_service()
    result = await svc.search("central bank")
    assert result == ["vector-result"]
    assert len(svc.chunk_repo.search_calls) == 1
    assert svc.chunk_repo.hybrid_calls == []


@pytest.mark.asyncio
async def test_hybrid_mode_calls_hybrid_with_text_and_filters():
    svc = make_service()
    filters = RetrievalFilters(source_name="Reuters")
    result = await svc.search("central bank", mode="hybrid", filters=filters)
    assert result == ["hybrid-result"]
    assert svc.chunk_repo.search_calls == []
    assert len(svc.chunk_repo.hybrid_calls) == 1
    call = svc.chunk_repo.hybrid_calls[0]
    assert call["query_text"] == "central bank"
    assert call["filters"] is filters


@pytest.mark.asyncio
async def test_empty_query_returns_empty_without_touching_repo():
    svc = make_service()
    assert await svc.search("   ", mode="hybrid") == []
    assert svc.chunk_repo.search_calls == []
    assert svc.chunk_repo.hybrid_calls == []


@pytest.mark.asyncio
async def test_service_threads_candidate_n_and_rrf_k_into_hybrid():
    svc = make_service(candidate_n=25, rrf_k=42)
    await svc.search("q", mode="hybrid")
    call = svc.chunk_repo.hybrid_calls[0]
    assert call["candidate_n"] == 25
    assert call["rrf_k"] == 42
