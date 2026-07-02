"""Chat-completion wrapper built on LangChain's ChatOpenAI.

Exposed behind a tiny `ChatCompleter` protocol (`complete(system, user)`) so the
RAG service depends on an interface, not on LangChain directly — which keeps it
unit-testable with a fake and lets the model be swapped in one place.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

logger = logging.getLogger(__name__)


class ChatCompleter(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def build_chat_model(
    api_key: str,
    model: str = "gpt-4o-mini",
    temperature: float = 0.0,
    max_tokens: int | None = None,
):
    """Construct a LangChain ChatOpenAI model.

    Shared by the RAG completer and the LangGraph agent so the model config
    lives in one place.
    """
    from langchain_openai import ChatOpenAI

    # max_tokens caps output (generation) cost per call.
    return ChatOpenAI(
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


class OpenAIChatCompleter:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> None:
        self._model = model
        self._llm = build_chat_model(api_key, model, temperature, max_tokens)

    async def complete(self, system: str, user: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        start = time.perf_counter()
        resp = await self._llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
        latency_ms = (time.perf_counter() - start) * 1000
        # Observability: record model, latency, and token usage per call so cost
        # and performance are measurable (and optimisations are provable).
        usage = getattr(resp, "usage_metadata", None) or {}
        logger.info(
            "LLM call model=%s latency_ms=%.0f input=%s output=%s total=%s",
            self._model,
            latency_ms,
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            usage.get("total_tokens"),
        )
        content = resp.content
        return content if isinstance(content, str) else str(content)
