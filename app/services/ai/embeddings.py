"""Embedding client wrapper around the OpenAI embeddings API.

Kept behind a small interface (`embed_documents` / `embed_query`) so services
that depend on it can be unit-tested with a fake, and so the provider could be
swapped without touching business logic.
"""

from __future__ import annotations

from typing import Protocol

from openai import AsyncOpenAI


class Embedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self._client.embeddings.create(model=self._model, input=texts)
        # The API preserves input order in `data`.
        return [item.embedding for item in resp.data]

    async def embed_query(self, text: str) -> list[float]:
        resp = await self._client.embeddings.create(model=self._model, input=[text])
        return resp.data[0].embedding
