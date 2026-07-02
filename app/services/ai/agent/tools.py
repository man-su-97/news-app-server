"""Agent tools as plain async functions.

Kept as ordinary functions (not tied to any framework) so they can be unit-tested
in isolation — pass a fake service, assert the formatted output — before they are
ever wrapped as LangChain tools and handed to the model. This is the "test tools
independently" principle: the tool contract is verified without an LLM in the loop.
"""

from app.repositories.article_repo import ArticleRepository
from app.services.ai.retrieval import RetrievalService

_SNIPPET = 200
_ARTICLE_BODY = 1500


async def semantic_search_tool(
    retrieval: RetrievalService, query: str, k: int = 5
) -> str:
    """Return the most relevant article excerpts for a query, as text."""
    chunks = await retrieval.search(query, k=k)
    if not chunks:
        return "No matching articles."
    lines = [
        f"[article {c.article_id}] {c.title}: {c.content[:_SNIPPET]}"
        for c in chunks
    ]
    return "\n".join(lines)


async def get_article_tool(
    article_repo: ArticleRepository, article_id: int
) -> str:
    """Return a single article's title and body by id."""
    article = await article_repo.get_by_id(article_id)
    if article is None:
        return f"No article with id {article_id}."
    body = article.content or article.description or ""
    return f"{article.title}\n\n{body[:_ARTICLE_BODY]}"
