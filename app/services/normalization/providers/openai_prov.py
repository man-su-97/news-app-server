import logging

from openai import AsyncOpenAI

from app.services.normalization.providers.base import (
    AIProvider,
    NORMALIZATION_SYSTEM_PROMPT,
    build_user_message,
    parse_llm_output,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(AIProvider):
    """OpenAI-compatible chat completion endpoint.

    This single class handles three distinct deployment targets by varying base_url:

    1. OpenAI (GPT-4o, GPT-4o-mini, o1, …)
       base_url=None  →  uses openai SDK default (api.openai.com/v1)

    2. Google Gemini via its OpenAI-compatible endpoint
       base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
       model="gemini-1.5-flash"  |  "gemini-2.0-flash"  |  "gemini-1.5-pro"
       Note: pass your Gemini API key as api_key.

    3. Any self-hosted OpenAI-compatible server
       Ollama:    base_url="http://localhost:11434/v1"   api_key="ollama"
       vLLM:      base_url="http://localhost:8000/v1"    api_key="EMPTY"
       LM Studio: base_url="http://localhost:1234/v1"    api_key="lm-studio"
    """

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self._model = model
        # AsyncOpenAI manages connection pooling — safe to keep as a long-lived instance.
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._provider_label = "openai" if base_url is None else base_url.split("/")[2]

    @property
    def model_id(self) -> str:
        return f"ai:{self._provider_label}:{self._model}"

    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        user_message = build_user_message(raw_payload, source_type)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=512,
                # JSON mode: instructs the model to return a valid JSON object.
                # Supported by: OpenAI gpt-4o-mini+, Gemini 1.5+, most local servers.
                # Falls back gracefully — parse_llm_output handles non-JSON text.
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": NORMALIZATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            text = response.choices[0].message.content or ""
        except Exception as exc:
            # Catch broad Exception: openai SDK raises different error types depending
            # on whether it's an HTTP error, timeout, or connection failure.
            logger.error("OpenAI-compatible provider error (%s): %s", self._provider_label, exc)
            return None

        return parse_llm_output(text, raw_payload)
