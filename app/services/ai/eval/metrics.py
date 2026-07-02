"""Retrieval-quality metrics + a golden-set harness.

These measure the *retrieval* half of RAG deterministically, with no LLM judge:
given a set of questions each labelled with the article ids that should be
retrieved, compute precision@k, recall@k, and mean reciprocal rank. This is the
cheap, repeatable signal you run on every change ("measure, don't trust vibes").
Generation-quality (faithfulness / answer relevancy) is evaluated separately with
RAGAS — see `scripts/eval_ragas.py`.
"""

from dataclasses import dataclass
from statistics import mean

from app.services.ai.retrieval import RetrievalService


@dataclass
class EvalCase:
    question: str
    relevant_article_ids: list[int]


@dataclass
class EvalReport:
    n: int
    precision_at_k: float
    recall_at_k: float
    mrr: float


def precision_at_k(retrieved: list[int], relevant: list[int], k: int) -> float:
    top = retrieved[:k]
    if not top:
        return 0.0
    relevant_set = set(relevant)
    return sum(1 for i in top if i in relevant_set) / len(top)


def recall_at_k(retrieved: list[int], relevant: list[int], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(retrieved[:k])
    return len(top & set(relevant)) / len(set(relevant))


def reciprocal_rank(retrieved: list[int], relevant: list[int]) -> float:
    relevant_set = set(relevant)
    for rank, article_id in enumerate(retrieved, start=1):
        if article_id in relevant_set:
            return 1.0 / rank
    return 0.0


def _distinct_article_ids(chunks) -> list[int]:
    """Collapse retrieved chunks to distinct article ids, preserving rank order."""
    ids: list[int] = []
    for c in chunks:
        if c.article_id not in ids:
            ids.append(c.article_id)
    return ids


async def evaluate_retrieval(
    retrieval: RetrievalService, cases: list[EvalCase], k: int
) -> EvalReport:
    precisions, recalls, rrs = [], [], []
    for case in cases:
        chunks = await retrieval.search(case.question, k=k)
        ids = _distinct_article_ids(chunks)
        precisions.append(precision_at_k(ids, case.relevant_article_ids, k))
        recalls.append(recall_at_k(ids, case.relevant_article_ids, k))
        rrs.append(reciprocal_rank(ids, case.relevant_article_ids))
    n = len(cases)
    return EvalReport(
        n=n,
        precision_at_k=mean(precisions) if n else 0.0,
        recall_at_k=mean(recalls) if n else 0.0,
        mrr=mean(rrs) if n else 0.0,
    )
