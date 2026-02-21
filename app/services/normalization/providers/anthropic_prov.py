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

Architecture note: AnthropicProvider does NOT use LangGraph for enrichment.
It makes a direct API call to Claude for both normalize() and enrich().
For web-search-enhanced enrichment, use GeminiLangGraphProvider instead.
"""

import logging

import anthropic   # Anthropic's official Python SDK

# Import everything we need from the shared base module
from app.services.normalization.providers.base import (
    AIProvider,
    ENRICHMENT_SYSTEM_PROMPT,
    NORMALIZATION_SYSTEM_PROMPT,
    _NULL_ENRICHMENT,            # The "all-None" fallback dict returned on error
    build_enrichment_message,
    build_user_message,
    parse_enrichment_output,
    parse_llm_output,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    """Claude models via Anthropic's Python SDK.

    Uses Anthropic's native API format (system= parameter) rather than
    the messages array, which improves instruction-following for structured output.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        # AsyncAnthropic manages HTTP connection pooling internally.
        # This client is created ONCE (cached in provider_factory.py) and
        # reused across all normalize() and enrich() calls.
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def model_id(self) -> str:
        """Identifier stored in raw_ingestion_events.normalized_by for audit trail."""
        return f"ai:anthropic:{self._model}"

    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        """Call Claude to extract canonical article fields from a raw payload.

        The AI receives:
          - system: NORMALIZATION_SYSTEM_PROMPT (instructions)
          - user message: source type + the raw payload as JSON

        max_tokens=512: normalization output is a small JSON object, doesn't need more.
        Anthropic APIError covers all API-level errors (auth, rate limit, server error).
        Returns None on any error so the caller tries the next method.
        """
        user_message = build_user_message(raw_payload, source_type)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,                          # JSON output is small
                system=NORMALIZATION_SYSTEM_PROMPT,      # Anthropic's native system param
                messages=[{"role": "user", "content": user_message}],
            )
            # response.content[0].text: the AI's text response
            text = response.content[0].text
        except anthropic.APIError as exc:
            # Catches auth errors, rate limits, server errors, timeouts
            logger.error("Anthropic API error: %s", exc)
            return None  # Caller will try AI fallback or drop the article

        # Parse and validate the JSON text into a canonical article dict
        return parse_llm_output(text, raw_payload)

    async def enrich(self, article: dict) -> dict:
        """Call Claude to classify the article and generate enrichment fields.

        Sends the article title/description/url (no raw payload — smaller is better).
        max_tokens=256: enrichment output is a small JSON object.

        On any API error, returns _NULL_ENRICHMENT (all fields None, is_crime=True).
        The is_crime=True default means enrichment failure NEVER drops articles.
        """
        user_message = build_enrichment_message(article)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=256,                         # Enrichment JSON is compact
                system=ENRICHMENT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text
        except anthropic.APIError as exc:
            logger.warning("Anthropic enrichment API error: %s", exc)
            return _NULL_ENRICHMENT   # Fail safe: article is saved with NULL enrichment

        # Parse and validate — returns _NULL_ENRICHMENT internally on parse error too
        return parse_enrichment_output(text)
