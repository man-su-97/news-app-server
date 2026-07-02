"""Tests for the retrieval-evaluation metrics and golden-set harness (pure)."""

from app.repositories.chunk_repo import RetrievedChunk
from app.services.ai.eval.metrics import (
    EvalCase,
    evaluate_retrieval,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_precision_at_k():
    # 2 of the top 3 are relevant.
    assert precision_at_k([1, 2, 3], [1, 3], 3) == 2 / 3
    assert precision_at_k([], [1], 3) == 0.0


def test_recall_at_k():
    # top-2 covers 1 of 2 relevant.
    assert recall_at_k([1, 9], [1, 5], 2) == 0.5
    assert recall_at_k([1], [], 2) == 0.0


def test_reciprocal_rank():
    assert reciprocal_rank([9, 1, 3], [1]) == 0.5  # first hit at rank 2
    assert reciprocal_rank([1, 2], [1]) == 1.0
    assert reciprocal_rank([7, 8], [1]) == 0.0


def _chunk(article_id):
    return RetrievedChunk(
        chunk_id=article_id,
        article_id=article_id,
        chunk_index=0,
        content="c",
        title="t",
        url="u",
        distance=0.1,
    )


class FakeRetrieval:
    def __init__(self, mapping):
        self._mapping = mapping  # question -> list[article_id]

    async def search(self, query, k=None):
        return [_chunk(i) for i in self._mapping.get(query, [])]


async def test_evaluate_retrieval_aggregates():
    # q1: perfect hit at rank 1; q2: relevant doc missing entirely.
    retrieval = FakeRetrieval({"q1": [1, 2], "q2": [8, 9]})
    cases = [
        EvalCase(question="q1", relevant_article_ids=[1]),
        EvalCase(question="q2", relevant_article_ids=[5]),
    ]
    report = await evaluate_retrieval(retrieval, cases, k=2)
    assert report.n == 2
    # q1 mrr=1.0, q2 mrr=0.0 -> mean 0.5
    assert report.mrr == 0.5
    # q1 recall=1.0, q2 recall=0.0 -> mean 0.5
    assert report.recall_at_k == 0.5


async def test_evaluate_retrieval_dedupes_article_ids():
    # Same article returned twice (two chunks) should count once.
    retrieval = FakeRetrieval({"q": [3, 3]})
    report = await evaluate_retrieval(
        retrieval, [EvalCase(question="q", relevant_article_ids=[3])], k=5
    )
    assert report.precision_at_k == 1.0  # single distinct id, all relevant
