"""LangGraph news agent.

An LLM in a tool-use loop, built as a LangGraph ReAct agent: the model decides
whether to call a tool (`semantic_search`, `get_article`), sees the result, and
reasons about the next step until it can answer. A recursion limit caps the loop
so it can never run forever / burn unbounded tokens.

The graph is constructed per request from the injected retrieval service, article
repository, and chat model, so tools operate on the current DB session.
"""

from dataclasses import dataclass
from datetime import datetime

from app.repositories.article_repo import ArticleRepository
from app.services.ai.agent.tools import get_article_tool, semantic_search_tool
from app.services.ai.retrieval import RetrievalService

_SYSTEM_PROMPT = (
    "You are a news research assistant. Use the tools to find relevant articles "
    "before answering. Use `semantic_search` to find articles by topic and "
    "`get_article` to read a specific article by its id. Answer only from what the "
    "tools return; if you cannot find relevant articles, say so. Be concise."
)


def _parse_published_after(value: str | None) -> datetime | None:
    """Parse an ISO date/datetime the model supplies; ignore malformed input.

    Lenient on purpose — a bad date from the LLM should drop the recency filter,
    never crash the tool call.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class AgentResult:
    answer: str
    tools_used: list[str]


class AgentService:
    def __init__(
        self,
        chat_model,
        retrieval: RetrievalService,
        article_repo: ArticleRepository,
        max_iterations: int = 6,
    ) -> None:
        self._max_iterations = max_iterations
        self._agent = self._build(chat_model, retrieval, article_repo)

    @staticmethod
    def _build(chat_model, retrieval, article_repo):
        from langchain_core.tools import StructuredTool
        from langgraph.prebuilt import create_react_agent

        async def semantic_search(
            query: str, published_after: str | None = None
        ) -> str:
            """Search the news corpus for articles relevant to a query.

            Optionally pass published_after as an ISO date (e.g. "2026-06-25")
            to restrict results to articles published on or after that date.
            """
            return await semantic_search_tool(
                retrieval, query, published_after=_parse_published_after(published_after)
            )

        async def get_article(article_id: int) -> str:
            """Read a single news article by its numeric id."""
            return await get_article_tool(article_repo, article_id)

        tools = [
            StructuredTool.from_function(
                coroutine=semantic_search,
                name="semantic_search",
                description="Find news articles relevant to a topic or question.",
            ),
            StructuredTool.from_function(
                coroutine=get_article,
                name="get_article",
                description="Read one news article by its numeric id.",
            ),
        ]
        return create_react_agent(chat_model, tools, prompt=_SYSTEM_PROMPT)

    async def run(self, question: str) -> AgentResult:
        result = await self._agent.ainvoke(
            {"messages": [("user", question)]},
            # recursion_limit bounds the agent<->tool loop.
            config={"recursion_limit": self._max_iterations * 2},
        )
        messages = result["messages"]
        answer = messages[-1].content
        answer = answer if isinstance(answer, str) else str(answer)
        tools_used = [
            getattr(m, "name", "")
            for m in messages
            if getattr(m, "type", None) == "tool"
        ]
        return AgentResult(answer=answer.strip(), tools_used=tools_used)
