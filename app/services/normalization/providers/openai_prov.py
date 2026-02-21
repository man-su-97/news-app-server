"""
app/services/normalization/providers/openai_prov.py — OpenAI-Compatible Provider
==================================================================================
Implements the AIProvider interface for ANY endpoint that speaks the OpenAI
Chat Completions API format. This single class handles three deployment targets:

1. OpenAI (GPT-4o, GPT-4o-mini, o1, …)
   base_url=None → SDK uses https://api.openai.com/v1

2. Google Gemini via its OpenAI-compatible endpoint
   base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
   model="gemini-2.0-flash"

3. Self-hosted models (Ollama, vLLM, LM Studio, etc.)
   Ollama:    base_url="http://localhost:11434/v1"   api_key="ollama"
   vLLM:      base_url="http://localhost:8000/v1"    api_key="EMPTY"
   LM Studio: base_url="http://localhost:1234/v1"    api_key="lm-studio"

Why one class for all three?
  Architecture decision: The OpenAI Chat Completions API has become the
  de-facto standard — most LLM providers implement it. One class = one place
  to maintain, one set of tests, consistent behavior.

  For Gemini with LangGraph search enrichment, use GeminiLangGraphProvider instead.
  This class's enrich() is a simple single API call (no web search).

JSON mode (response_format={"type": "json_object"}):
  Instructs the model to ALWAYS return valid JSON.
  Supported by: OpenAI gpt-4o-mini+, Gemini 1.5+, most local servers.
  Falls back gracefully — parse_llm_output handles non-JSON text anyway.
"""

import logging

from openai import AsyncOpenAI  # Official OpenAI async Python SDK

from app.services.normalization.providers.base import (
    AIProvider,
    ENRICHMENT_SYSTEM_PROMPT,
    NORMALIZATION_SYSTEM_PROMPT,
    _NULL_ENRICHMENT,
    build_enrichment_message,
    build_user_message,
    parse_enrichment_output,
    parse_llm_output,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(AIProvider):
    """OpenAI-compatible chat completion endpoint (OpenAI, Gemini, Ollama, etc.)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self._model = model
        # AsyncOpenAI manages connection pooling — safe to keep as a long-lived instance.
        # base_url=None → default OpenAI endpoint (api.openai.com/v1)
        # base_url=something → custom endpoint (Gemini, Ollama, etc.)
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        # Extract a readable label from the base_url for logging.
        # "openai" if no URL, otherwise domain from URL (e.g. "generativelanguage.googleapis.com")
        self._provider_label = "openai" if base_url is None else base_url.split("/")[2]

    @property
    def model_id(self) -> str:
        """Identifier stored in raw_ingestion_events for audit trail.
        Example: "ai:openai:gpt-4o-mini" or "ai:generativelanguage.googleapis.com:gemini-1.5-flash"
        """
        return f"ai:{self._provider_label}:{self._model}"

    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        """Call the OpenAI-compatible endpoint to extract canonical article fields.

        Uses response_format={"type": "json_object"} to enable JSON mode.
        System message is injected as the first message (OpenAI-style, not
        as a separate parameter like Anthropic's API).

        max_tokens=512: normalization output is a small JSON object.
        """
        user_message = build_user_message(raw_payload, source_type)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=512,
                # JSON mode: model MUST return a JSON object.
                # Without this, models sometimes add explanatory prose around the JSON.
                response_format={"type": "json_object"},
                messages=[
                    # System message: the instructions
                    {"role": "system", "content": NORMALIZATION_SYSTEM_PROMPT},
                    # User message: the raw payload to process
                    {"role": "user", "content": user_message},
                ],
            )
            # Extract the text content from the first choice
            text = response.choices[0].message.content or ""
        except Exception as exc:
            # Broad Exception catch: the OpenAI SDK raises different exception types
            # depending on whether it's a network error, auth error, or API error.
            # Catching all of them here and logging keeps the failure contained.
            logger.error("OpenAI-compatible provider error (%s): %s", self._provider_label, exc)
            return None

        return parse_llm_output(text, raw_payload)

    async def enrich(self, article: dict) -> dict:
        """Call the endpoint to classify the article and generate enrichment fields.

        max_tokens=256: enrichment output is compact JSON.
        Returns _NULL_ENRICHMENT on any error (article still saved, just without enrichment).
        """
        user_message = build_enrichment_message(article)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=256,
                response_format={"type": "json_object"},  # enforce JSON output
                messages=[
                    {"role": "system", "content": ENRICHMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            text = response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning(
                "OpenAI-compatible enrichment error (%s): %s", self._provider_label, exc
            )
            return _NULL_ENRICHMENT  # Fail safe

        return parse_enrichment_output(text)
