"""RAG service tests using fakes for retrieval and the chat model.

No database or OpenAI key required — the point is to verify the grounding /
citation behaviour deterministically.
"""

from app.repositories.chunk_repo import RetrievedChunk
from app.services.ai.rag_service import RagService, _NO_CONTEXT_ANSWER


class FakeRetrieval:
    def __init__(self, chunks):
        self._chunks = chunks
        self.last_query = None
        self.last_mode = None
        self.last_filters = None

    async def search(self, query, k=None, mode="vector", filters=None):
        self.last_query = query
        self.last_mode = mode
        self.last_filters = filters
        return self._chunks


class FakeChat:
    def __init__(self, reply="The answer is X [1]."):
        self.reply = reply
        self.last_system = None
        self.last_user = None

    async def complete(self, system, user):
        self.last_system = system
        self.last_user = user
        return self.reply


def _chunk(article_id, title, content, distance=0.1):
    # score = 1 - distance, so distance=0.1 → score 0.9 (strong match).
    return RetrievedChunk(
        chunk_id=article_id * 10,
        article_id=article_id,
        chunk_index=0,
        content=content,
        title=title,
        url=f"https://news.example/{article_id}",
        distance=distance,
    )


async def test_no_context_returns_dont_know_and_skips_llm():
    chat = FakeChat()
    svc = RagService(FakeRetrieval([]), chat)
    result = await svc.ask("what happened?")
    assert result.answer == _NO_CONTEXT_ANSWER
    assert result.citations == []
    # LLM must not be called when there is nothing to ground on.
    assert chat.last_user is None


async def test_only_cited_sources_are_returned():
    chunks = [
        _chunk(1, "Fed raises rates", "The Fed raised interest rates."),
        _chunk(2, "Markets react", "Markets fell after the decision."),
        _chunk(3, "Analysts comment", "Analysts were divided."),
    ]
    # Model cites [1] and [3] only — [2] must NOT appear in citations.
    chat = FakeChat(reply="Rates went up [1] and markets fell [3].")
    svc = RagService(FakeRetrieval(chunks), chat)
    result = await svc.ask("what did the fed do?")

    assert [c.ref for c in result.citations] == [1, 3]
    assert result.citations[0].article_id == 1
    assert result.citations[1].url == "https://news.example/3"


async def test_answer_with_no_citation_markers_returns_empty_citations():
    chunks = [_chunk(1, "Headline", "Body.")]
    chat = FakeChat(reply="Something happened, but I won't cite it.")
    svc = RagService(FakeRetrieval(chunks), chat)
    result = await svc.ask("what happened?")
    assert result.citations == []


async def test_out_of_range_citation_markers_are_ignored():
    chunks = [_chunk(1, "Headline", "Body.")]
    # Model hallucinates a [5] that does not exist among 1 retrieved chunk.
    chat = FakeChat(reply="Per reports [5], things changed.")
    svc = RagService(FakeRetrieval(chunks), chat)
    result = await svc.ask("what happened?")
    assert result.citations == []


async def test_prompt_contains_numbered_context_and_question():
    chunks = [_chunk(1, "Headline", "Body text here.")]
    chat = FakeChat()
    svc = RagService(FakeRetrieval(chunks), chat)
    await svc.ask("tell me more")

    assert "[1] Headline" in chat.last_user
    assert "Body text here." in chat.last_user
    assert "tell me more" in chat.last_user
    # System prompt enforces grounding.
    assert "ONLY" in chat.last_system


# --- Token optimisation ---


async def test_low_score_chunks_are_dropped_from_context():
    chunks = [
        _chunk(1, "Relevant", "Strong match.", distance=0.1),   # score 0.9
        _chunk(2, "Irrelevant", "Weak match.", distance=0.95),  # score 0.05
    ]
    chat = FakeChat(reply="Answer [1].")
    svc = RagService(FakeRetrieval(chunks), chat, min_score=0.2)
    await svc.ask("q")

    # Only the strong chunk reaches the prompt → fewer input tokens.
    assert "Relevant" in chat.last_user
    assert "Irrelevant" not in chat.last_user


async def test_all_chunks_below_threshold_skips_llm():
    chunks = [_chunk(1, "Weak", "barely related", distance=0.95)]
    chat = FakeChat()
    svc = RagService(FakeRetrieval(chunks), chat, min_score=0.5)
    result = await svc.ask("q")

    assert result.answer == _NO_CONTEXT_ANSWER
    assert result.citations == []
    assert chat.last_user is None  # no tokens spent


async def test_context_token_budget_limits_chunks():
    chunks = [
        _chunk(1, "One", "alpha beta gamma"),
        _chunk(2, "Two", "delta epsilon zeta"),
        _chunk(3, "Three", "eta theta iota"),
    ]
    chat = FakeChat(reply="Answer [1].")
    # Word-count "tokens" + a tiny budget → only the first chunk fits.
    svc = RagService(
        FakeRetrieval(chunks),
        chat,
        max_context_tokens=5,
        token_counter=lambda s: len(s.split()),
    )
    await svc.ask("q")

    assert "One" in chat.last_user
    assert "Three" not in chat.last_user
