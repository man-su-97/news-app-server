"""
app/services/normalization/ai_processor.py — Environment Variable AI Provider Fallback
========================================================================================
When no AI provider is configured in the database (via POST /ai-providers),
this module checks whether API keys are set in environment variables and
automatically creates an AI provider from those keys.

This is a BACKWARDS-COMPATIBILITY layer. New deployments should configure
providers through the API (POST /ai-providers + PATCH activate). But for:
  - Quick local development: just set GEMINI_API_KEY=... in .env and it works
  - Existing deployments that used ANTHROPIC_API_KEY before the DB config existed

Resolution order (first key that is set wins):
  1. GEMINI_API_KEY  → GeminiLangGraphProvider with gemini-2.0-flash
     (recommended — includes LangGraph + DuckDuckGo search enrichment)
  2. ANTHROPIC_API_KEY → AnthropicProvider with Claude Haiku
     (legacy — basic enrichment, no web search)
  3. Neither set → returns None → deterministic-only normalization

Called by: IngestionService._load_ai_provider() as the last fallback.
"""

import logging

from app.core.config import settings
from app.services.normalization.provider_factory import (
    create_from_env,
    create_gemini_from_env,
    create_gemini_multimodal_from_env,
)
from app.services.normalization.providers.base import AIProvider

logger = logging.getLogger(__name__)

# Default model IDs used when creating providers from env vars.
# Users can override these by configuring a provider via POST /ai-providers.
_GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"
_ANTHROPIC_FALLBACK_MODEL = "claude-haiku-4-5-20251001"


def get_env_fallback_provider() -> AIProvider | None:
    """Return an AI provider built from environment variables, or None.

    Resolution order (first available wins):

      1. GEMINI_API_KEY → GeminiMultimodalLangGraphProvider  ← RECOMMENDED
            Two-graph LangGraph pipeline with:
            • Multimodal Gemini (image + text classification)
            • Structured output (no JSON parsing)
            • Multi-label sub_category_ids
            • Concurrent DuckDuckGo search in both stages
            • Proper imp_score 1-100 from post_process stage

      2. GEMINI_API_KEY (fallback) → GeminiLangGraphProvider
            Used only if the multimodal provider fails to initialise.
            Single-graph, single combined AI call per article.

      3. ANTHROPIC_API_KEY → AnthropicProvider
            Claude-based enrichment without web search.

      4. Neither key set → None
            Ingestion skips AI processing entirely.

    Instances are cached in provider_factory._provider_cache for the process
    lifetime, so repeated calls (every scheduler run) reuse the same client.
    """
    if settings.GEMINI_API_KEY:
        # Try multimodal first (recommended path)
        try:
            return create_gemini_multimodal_from_env(
                api_key=settings.GEMINI_API_KEY,
                model=_GEMINI_DEFAULT_MODEL,
            )
        except Exception as exc:
            logger.error(
                "Failed to build GeminiMultimodal provider, falling back to LangGraph: %s", exc
            )
        # Fallback: original LangGraph provider (no multimodal, no structured output)
        try:
            return create_gemini_from_env(
                api_key=settings.GEMINI_API_KEY,
                model=_GEMINI_DEFAULT_MODEL,
            )
        except Exception as exc:
            logger.error("Failed to build GeminiLangGraph fallback provider: %s", exc)

    if settings.ANTHROPIC_API_KEY:
        try:
            return create_from_env(
                api_key=settings.ANTHROPIC_API_KEY,
                model=_ANTHROPIC_FALLBACK_MODEL,
            )
        except Exception as exc:
            logger.error("Failed to build Anthropic env-var provider: %s", exc)

    return None
