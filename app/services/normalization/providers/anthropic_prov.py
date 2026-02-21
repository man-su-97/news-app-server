import logging

import anthropic

from app.services.normalization.providers.base import (
    AIProvider,
    NORMALIZATION_SYSTEM_PROMPT,
    build_user_message,
    parse_llm_output,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    """Claude models via the Anthropic SDK.

    Uses the dedicated system parameter (Anthropic's native API format) rather
    than injecting it as a user message, which improves instruction-following.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        # AsyncAnthropic is designed to be long-lived; it manages connection pooling.
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def model_id(self) -> str:
        return f"ai:anthropic:{self._model}"

    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        user_message = build_user_message(raw_payload, source_type)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=NORMALIZATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text
        except anthropic.APIError as exc:
            logger.error("Anthropic API error: %s", exc)
            return None

        return parse_llm_output(text, raw_payload)
