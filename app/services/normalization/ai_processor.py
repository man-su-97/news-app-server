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

from app.core.config import settings   # reads GEMINI_API_KEY and ANTHROPIC_API_KEY from .env
from app.services.normalization.provider_factory import create_from_env, create_gemini_from_env
from app.services.normalization.providers.base import AIProvider

logger = logging.getLogger(__name__)

# Default model IDs used when creating providers from env vars.
# Users can override these by using the DB config API instead.
_GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"          # Fast Gemini model
_ANTHROPIC_FALLBACK_MODEL = "claude-haiku-4-5-20251001"  # Fast and cheap Claude model


def get_env_fallback_provider() -> AIProvider | None:
    """Return an AI provider built from environment variables, or None.

    Priority:
      1. GEMINI_API_KEY → GeminiLangGraphProvider (crime app's recommended default)
         This includes LangGraph + DuckDuckGo web search for better enrichment.
      2. ANTHROPIC_API_KEY → AnthropicProvider (legacy backwards-compat)
         Basic enrichment without web search.
      3. Neither → None → ingestion runs with deterministic-only normalization.

    Provider instances are cached in provider_factory.py's module-level cache,
    so calling this function multiple times (e.g. every scheduled ingest run)
    does NOT create new SDK client objects each time — they're reused.
    """
    # Check GEMINI_API_KEY first — this is the recommended provider for this app
    if settings.GEMINI_API_KEY:
        try:
            # create_gemini_from_env() returns (or creates) a cached GeminiLangGraphProvider
            return create_gemini_from_env(
                api_key=settings.GEMINI_API_KEY,
                model=_GEMINI_DEFAULT_MODEL,
            )
        except Exception as exc:
            # Building the provider failed (e.g. invalid API key format)
            # Log it and try the next fallback
            logger.error("Failed to build Gemini env-var provider: %s", exc)

    # Check ANTHROPIC_API_KEY as a secondary fallback
    if settings.ANTHROPIC_API_KEY:
        try:
            # create_from_env() returns (or creates) a cached AnthropicProvider
            return create_from_env(
                api_key=settings.ANTHROPIC_API_KEY,
                model=_ANTHROPIC_FALLBACK_MODEL,
            )
        except Exception as exc:
            logger.error("Failed to build Anthropic env-var provider: %s", exc)

    # Neither key is set — ingestion will use deterministic-only normalization.
    # This is fine: articles from well-structured RSS feeds will still be saved.
    # Only poorly-structured sources (missing title or URL) will be dropped.
    return None
