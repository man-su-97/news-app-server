"""
app/services/normalization/providers/anthropic_prov.py — Anthropic (Claude) Provider
======================================================================================
Implements the AIProvider interface using Anthropic's Claude models.

Claude API has a unique feature: it accepts a `system` parameter separately
from the `messages` array. This is more natural for instruction-following than
injecting the system prompt as the first user message (which is how OpenAI works).
Using the native system parameter generally improves instruction adherence.

Models you can use (set when creating the DB config):
  "claude-haiku-4-5-20251001"  — fast and cheap (recommended for high-volume)
  "claude-sonnet-4-6"          — balanced quality/cost
  "claude-opus-4-6"            — highest quality, slowest, most expensive

Single-call design: process() makes ONE API call that extracts basic fields AND
classifies crime type/location/score simultaneously. This is more efficient than
the old two-call approach (normalize then enrich separately).
"""

import logging

import anthropic   # Anthropic's official Python SDK

from app.services.normalization.providers.base import (
    AIProvider,
    COMBINED_PROCESS_PROMPT,
    POST_PROCESS_PROMPT,
    build_post_process_message,
    build_process_message,
    parse_combined_output,
    parse_post_process_output,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    """Claude models via Anthropic's Python SDK.

    Uses Anthropic's native system= parameter for better instruction-following.
    Makes a single combined API call per article (extract + classify in one shot).
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        # AsyncAnthropic manages HTTP connection pooling internally.
        # This client is created ONCE (cached in provider_factory.py) and
        # reused across all process() calls to avoid repeated connection overhead.
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def model_id(self) -> str:
        """Identifier stored in raw_ingestion_events.normalized_by for audit trail.
        Example: "ai:anthropic:claude-haiku-4-5-20251001"
        """
        return f"ai:anthropic:{self._model}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        """Single Claude API call: extract article fields + classify crime content.

        The AI receives:
          - system: COMBINED_PROCESS_PROMPT (extraction + classification instructions)
          - user message: source_type + raw payload as pretty-printed JSON

        max_tokens=768: combined output is larger than extraction-only was (512).
        All enrichment fields are included in the same response.

        Returns the complete article dict or None on any error.
        """
        user_message = build_process_message(raw_payload, source_type)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=768,                         # Enough for complete JSON output
                system=COMBINED_PROCESS_PROMPT,         # Anthropic's native system param
                messages=[{"role": "user", "content": user_message}],
            )
            # response.content[0].text: the AI's text response
            text = response.content[0].text
        except anthropic.APIError as exc:
            # Catches auth errors, rate limits, server errors, network timeouts
            logger.error("Anthropic API error: %s", exc)
            return None  # Caller drops this article

        # parse_combined_output handles: code fence stripping, JSON parsing,
        # Pydantic validation, date parsing → returns complete article dict or None
        return parse_combined_output(text, raw_payload)

    async def post_process(self, filter_article: dict, search_context: str = "") -> dict | None:
        """STAGE 2: Rewrite and score a crime article using POST_PROCESS_PROMPT.

        Makes a second Claude API call with the filter stage output.
        Returns rewritten_title, rewritten_description, reference_urls, imp_score.
        """
        user_message = build_post_process_message(filter_article, search_context)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=600,
                system=POST_PROCESS_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text
        except anthropic.APIError as exc:
            logger.error("Anthropic post_process API error: %s", exc)
            return None
        return parse_post_process_output(text)
