import logging

import anthropic

from app.services.normalization.providers.base import (
    AIProvider,
    SINGLE_PROCESS_PROMPT,
    build_process_message,
    parse_single_output,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def model_id(self) -> str:
        return f"ai:anthropic:{self._model}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        user_message = build_process_message(raw_payload, source_type)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=SINGLE_PROCESS_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text
        except anthropic.APIError as exc:
            logger.error("Anthropic API error: %s", exc)
            return None
        return parse_single_output(text, raw_payload)
