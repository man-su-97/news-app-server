"""Generation-quality evaluation with RAGAS (optional).

RAGAS scores the *answer* half of RAG with an LLM judge: faithfulness (is the
answer grounded in the retrieved context) and answer relevancy. It complements the
deterministic retrieval metrics in `scripts/eval_retrieval.py`.

Install the optional deps and run (needs a populated DB + OPENAI_API_KEY):
    uv sync --extra eval
    uv run python -m scripts.eval_ragas app/services/ai/eval/golden_set.example.json
"""

import asyncio
import json
import sys

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.repositories.chunk_repo import ChunkRepository
from app.services.ai.embeddings import OpenAIEmbedder
from app.services.ai.llm import OpenAIChatCompleter
from app.services.ai.rag_service import RagService
from app.services.ai.retrieval import RetrievalService


async def main(path: str) -> None:
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, faithfulness
    except ImportError as exc:  # optional dependency
        raise SystemExit(
            "RAGAS not installed. Run: uv sync --extra eval"
        ) from exc

    if not settings.OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is required.")

    with open(path) as f:
        questions = [c["question"] for c in json.load(f)]

    rows = {"question": [], "answer": [], "contexts": []}
    async with AsyncSessionLocal() as db:
        embedder = OpenAIEmbedder(settings.OPENAI_API_KEY, settings.EMBEDDING_MODEL)
        retrieval = RetrievalService(
            ChunkRepository(db), embedder, top_k=settings.RETRIEVAL_TOP_K
        )
        chat = OpenAIChatCompleter(
            settings.OPENAI_API_KEY, settings.LLM_MODEL, max_tokens=settings.LLM_MAX_TOKENS
        )
        rag = RagService(
            retrieval,
            chat,
            top_k=settings.RETRIEVAL_TOP_K,
            min_score=settings.RETRIEVAL_MIN_SCORE,
            max_context_tokens=settings.MAX_CONTEXT_TOKENS,
        )
        for q in questions:
            chunks = await retrieval.search(q, k=settings.RETRIEVAL_TOP_K)
            answer = await rag.ask(q)
            rows["question"].append(q)
            rows["answer"].append(answer.answer)
            rows["contexts"].append([c.content for c in chunks])

    dataset = Dataset.from_dict(rows)
    result = evaluate(dataset, metrics=[faithfulness, answer_relevancy])
    print(result)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else (
        "app/services/ai/eval/golden_set.example.json"
    )
    asyncio.run(main(path))
