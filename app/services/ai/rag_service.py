"""RAG orchestration: retrieve → assemble grounded prompt → generate.

Hallucination defence lives here: the system prompt forces the model to answer
only from the retrieved context and to say so when the answer is not present,
and every context block is numbered so answers can cite sources. Only the sources
the model actually cites (via `[n]` markers) are returned as citations.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.repositories.chunk_repo import RetrievedChunk
from app.services.ai.llm import ChatCompleter
from app.services.ai.retrieval import RetrievalService
from app.services.ai.tokens import count_tokens

# Matches inline citation markers like [1] or [12] in the model's answer.
_CITATION_RE = re.compile(r"\[(\d+)\]")

_SYSTEM_PROMPT = (
    "You are a news analyst. Answer the user's question using ONLY the numbered "
    "news excerpts provided in the context. If the context does not contain the "
    "answer, reply exactly: \"I don't have relevant articles on that.\" Do not use "
    "outside knowledge and do not speculate. Cite the sources you used with their "
    "numbers in square brackets, e.g. [1], [2]."
)

_NO_CONTEXT_ANSWER = "I don't have relevant articles on that."


@dataclass
class Citation:
    ref: int
    article_id: int
    title: str
    url: str


@dataclass
class RagAnswer:
    answer: str
    citations: list[Citation]


def _block(ref: int, chunk: RetrievedChunk) -> str:
    return f"[{ref}] {chunk.title}\n{chunk.content}"


def _format_context(chunks: list[RetrievedChunk]) -> str:
    return "\n\n".join(_block(i, c) for i, c in enumerate(chunks, start=1))


def _parse_cited_refs(answer: str, n: int) -> list[int]:
    """Return the distinct, in-range citation numbers the answer actually used.

    Ignores markers outside 1..n (the model occasionally invents a number).
    """
    refs: list[int] = []
    for match in _CITATION_RE.findall(answer):
        ref = int(match)
        if 1 <= ref <= n and ref not in refs:
            refs.append(ref)
    return sorted(refs)


class RagService:
    def __init__(
        self,
        retrieval: RetrievalService,
        chat: ChatCompleter,
        top_k: int = 5,
        min_score: float = -1.0,
        max_context_tokens: int = 1_000_000,
        token_counter: Callable[[str], int] = count_tokens,
    ) -> None:
        self.retrieval = retrieval
        self.chat = chat
        self.top_k = top_k
        # Token-optimisation policy (defaults are permissive; deps inject config).
        self.min_score = min_score
        self.max_context_tokens = max_context_tokens
        self._count = token_counter

    def _select_chunks(
        self, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        """Drop weakly-relevant chunks, then pack under the token budget.

        Fewer/only-relevant chunks → fewer input tokens (and better grounding).
        The highest-scoring chunk is always kept even if it alone exceeds the
        budget, so a relevant answer is never starved of context.
        """
        selected: list[RetrievedChunk] = []
        used = 0
        for chunk in chunks:
            if chunk.score < self.min_score:
                continue
            tokens = self._count(_block(len(selected) + 1, chunk))
            if selected and used + tokens > self.max_context_tokens:
                break
            selected.append(chunk)
            used += tokens
        return selected

    async def ask(self, question: str, k: int | None = None) -> RagAnswer:
        chunks = await self.retrieval.search(question, k=k or self.top_k)
        selected = self._select_chunks(chunks)
        if not selected:
            # Nothing relevant survived → skip the LLM call entirely.
            return RagAnswer(answer=_NO_CONTEXT_ANSWER, citations=[])

        context = _format_context(selected)
        user = f"Context:\n{context}\n\nQuestion: {question}"
        answer = (await self.chat.complete(_SYSTEM_PROMPT, user)).strip()

        # Return only the sources the model actually cited, mapped to the [n]
        # markers it used. A synthesised sentence with no [n] → no citations.
        citations = [
            Citation(
                ref=ref,
                article_id=selected[ref - 1].article_id,
                title=selected[ref - 1].title,
                url=selected[ref - 1].url,
            )
            for ref in _parse_cited_refs(answer, len(selected))
        ]
        return RagAnswer(answer=answer, citations=citations)
