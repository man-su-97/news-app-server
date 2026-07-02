"""Run retrieval-quality evaluation against a golden set.

Usage (needs a populated DB + OPENAI_API_KEY):
    uv run python -m scripts.eval_retrieval app/services/ai/eval/golden_set.example.json

Prints precision@k, recall@k, and MRR averaged over the golden questions.
"""

import asyncio
import json
import sys

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.repositories.chunk_repo import ChunkRepository
from app.services.ai.embeddings import OpenAIEmbedder
from app.services.ai.eval.metrics import EvalCase, evaluate_retrieval
from app.services.ai.retrieval import RetrievalService


async def main(path: str) -> None:
    with open(path) as f:
        cases = [EvalCase(**c) for c in json.load(f)]

    if not settings.OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is required to embed queries.")

    async with AsyncSessionLocal() as db:
        embedder = OpenAIEmbedder(settings.OPENAI_API_KEY, settings.EMBEDDING_MODEL)
        retrieval = RetrievalService(
            ChunkRepository(db), embedder, top_k=settings.RETRIEVAL_TOP_K
        )
        report = await evaluate_retrieval(
            retrieval, cases, k=settings.RETRIEVAL_TOP_K
        )

    print(f"cases={report.n}")
    print(f"precision@{settings.RETRIEVAL_TOP_K}={report.precision_at_k:.3f}")
    print(f"recall@{settings.RETRIEVAL_TOP_K}={report.recall_at_k:.3f}")
    print(f"mrr={report.mrr:.3f}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else (
        "app/services/ai/eval/golden_set.example.json"
    )
    asyncio.run(main(path))
