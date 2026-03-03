from typing import Any
import httpx
import os

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/generate",
)

MODEL_NAME = os.getenv(
    "OLLAMA_MODEL",
    "dengcao/Qwen3-30B-A3B-Instruct-2507",
)


class LLMService:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate(self, prompt: str) -> str:
        response = await self.client.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
            },
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data["response"]

    async def close(self) -> None:
        await self.client.aclose()