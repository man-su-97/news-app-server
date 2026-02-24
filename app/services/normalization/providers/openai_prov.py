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
  The OpenAI Chat Completions API has become the de-facto standard — most LLM
  providers implement it. One class = one place to maintain, consistent behavior.

  For Gemini with LangGraph web-search enrichment, use GeminiLangGraphProvider.
  This class's process() is a simple single API call (no web search context).

JSON mode (response_format={"type": "json_object"}):
  Instructs the model to ALWAYS return valid JSON.
  Supported by: OpenAI gpt-4o-mini+, Gemini 1.5+, most local servers.
  Falls back gracefully — parse_combined_output handles non-JSON text anyway.
"""

import logging

from openai import AsyncOpenAI  # Official OpenAI async Python SDK

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


class OpenAICompatibleProvider(AIProvider):
    """OpenAI-compatible chat completion endpoint (OpenAI, Gemini, Ollama, etc.)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self._model = model
        # AsyncOpenAI manages connection pooling — safe to keep as a long-lived instance.
        # base_url=None → default OpenAI endpoint (api.openai.com/v1)
        # base_url=something → custom endpoint (Gemini, Ollama, etc.)
        # max_retries=0: disable the SDK's built-in auto-retry on 429.
        # With free-tier rate limits (5 RPM for gemini-2.5-flash), the SDK's
        # default retries (2× with sub-second delays) burn quota faster —
        # retrying after 0.5s is still within the same minute window.
        # Our pipeline already handles None returns gracefully, so a 429
        # should just drop the article rather than retry immediately.
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        # Extract a readable label from the base_url for logging.
        # "openai" if no URL, otherwise the domain from the URL.
        if base_url is None:
            self._provider_label = "openai"
        else:
            parts = base_url.split("/")
            self._provider_label = parts[2] if len(parts) > 2 else base_url

    @property
    def model_id(self) -> str:
        """Identifier stored in raw_ingestion_events for audit trail.
        Example: "ai:openai:gpt-4o-mini" or "ai:generativelanguage.googleapis.com:gemini-1.5-flash"
        """
        return f"ai:{self._provider_label}:{self._model}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        """Single API call: extract article fields + classify crime content.

        Uses response_format={"type": "json_object"} (JSON mode) to enforce
        valid JSON output. System message is passed as the first message in the
        messages array (OpenAI-style, unlike Anthropic's separate system= param).

        max_tokens=1500: enough headroom for articles with long titles and summaries.

        Returns complete article dict or None on any error.
        """
        user_message = build_process_message(raw_payload, source_type)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=1500,
                # JSON mode: model MUST return a JSON object.
                # Without this, models sometimes add prose around the JSON.
                response_format={"type": "json_object"},
                messages=[
                    # System message: the extraction + classification instructions
                    {"role": "system", "content": COMBINED_PROCESS_PROMPT},
                    # User message: source_type + raw payload
                    {"role": "user", "content": user_message},
                ],
            )
            # Extract the text content from the first response choice
            text = response.choices[0].message.content or ""
        except Exception as exc:
            # Broad Exception: the OpenAI SDK raises different types (network error,
            # auth error, API error) depending on what went wrong. Log and return None.
            logger.error("OpenAI-compatible provider error (%s): %s", self._provider_label, exc)
            return None

        return parse_combined_output(text, raw_payload)

    async def post_process(self, filter_article: dict, search_context: str = "") -> dict | None:
        """STAGE 2: Rewrite and score a crime article using POST_PROCESS_PROMPT.

        Makes a second OpenAI-compatible API call with the filter stage output.
        Returns rewritten_title, rewritten_description, reference_urls, imp_score.
        """
        user_message = build_post_process_message(filter_article, search_context)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=800,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": POST_PROCESS_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            text = response.choices[0].message.content or ""
        except Exception as exc:
            logger.error(
                "OpenAI-compatible post_process error (%s): %s", self._provider_label, exc
            )
            return None
        return parse_post_process_output(text)
