"""Chat-completion wrapper built on LangChain's ChatOpenAI.

Exposed behind a tiny `ChatCompleter` protocol (`complete(system, user)`) so the
RAG service depends on an interface, not on LangChain directly — which keeps it
unit-testable with a fake and lets the model be swapped in one place.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class ChatCompleter(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


class OpenAIChatCompleter:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> None:
        from langchain_openai import ChatOpenAI

        # max_tokens caps output (generation) cost per call.
        self._llm = ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def complete(self, system: str, user: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        resp = await self._llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
        # Observability: record token usage so cost/optimisation is measurable.
        usage = getattr(resp, "usage_metadata", None)
        if usage:
            logger.info(
                "LLM token usage: input=%s output=%s total=%s",
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                usage.get("total_tokens"),
            )
        content = resp.content
        return content if isinstance(content, str) else str(content)
