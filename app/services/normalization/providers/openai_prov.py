import logging

from openai import AsyncOpenAI

from app.services.normalization.providers.base import (
    AIProvider,
    SINGLE_PROCESS_PROMPT,
    build_process_message,
    parse_single_output,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        if base_url is None:
            self._provider_label = "openai"
        else:
            parts = base_url.split("/")
            self._provider_label = parts[2] if len(parts) > 2 else base_url

    @property
    def model_id(self) -> str:
        return f"ai:{self._provider_label}:{self._model}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        user_message = build_process_message(raw_payload, source_type)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=4096,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SINGLE_PROCESS_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            text = response.choices[0].message.content or ""
        except Exception as exc:
            logger.error("OpenAI-compatible provider error (%s): %s", self._provider_label, exc)
            return None
        return parse_single_output(text, raw_payload)
