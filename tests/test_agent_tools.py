"""Unit tests for the agent tools — verified without an LLM in the loop.

The tools are plain async functions over injected services, so their contract can
be checked deterministically with fakes.
"""

from app.repositories.chunk_repo import RetrievedChunk
from app.services.ai.agent.tools import get_article_tool, semantic_search_tool


class FakeRetrieval:
    def __init__(self, chunks):
        self._chunks = chunks

    async def search(self, query, k=None):
        return self._chunks


class FakeArticle:
    def __init__(self, title, content=None, description=None):
        self.title = title
        self.content = content
        self.description = description


class FakeArticleRepo:
    def __init__(self, article):
        self._article = article

    async def get_by_id(self, article_id):
        return self._article


def _chunk(article_id, title, content):
    return RetrievedChunk(
        chunk_id=article_id,
        article_id=article_id,
        chunk_index=0,
        content=content,
        title=title,
        url=f"https://news.example/{article_id}",
        distance=0.1,
    )


async def test_semantic_search_tool_formats_results():
    chunks = [_chunk(7, "Rates rise", "The bank raised rates.")]
    out = await semantic_search_tool(FakeRetrieval(chunks), "rates")
    assert "[article 7]" in out
    assert "Rates rise" in out


async def test_semantic_search_tool_no_results():
    out = await semantic_search_tool(FakeRetrieval([]), "nothing")
    assert out == "No matching articles."


async def test_get_article_tool_found_uses_content():
    repo = FakeArticleRepo(FakeArticle("Headline", content="Full body."))
    out = await get_article_tool(repo, 3)
    assert "Headline" in out
    assert "Full body." in out


async def test_get_article_tool_falls_back_to_description():
    repo = FakeArticleRepo(FakeArticle("Headline", content=None, description="Sub."))
    out = await get_article_tool(repo, 3)
    assert "Sub." in out


async def test_get_article_tool_missing():
    out = await get_article_tool(FakeArticleRepo(None), 999)
    assert out == "No article with id 999."
