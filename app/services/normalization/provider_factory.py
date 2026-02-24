"""
app/services/normalization/provider_factory.py — AI Provider Factory
======================================================================
Creates and caches AIProvider instances from configuration objects.

The factory pattern:
  Instead of "new-ing up" a provider inside IngestionService, we go through
  this factory. Benefits:
    1. Caching: expensive SDK clients (with connection pools) are created ONCE
       and reused across all ingest runs, not recreated per-request.
    2. Single registration point: adding a new provider only requires adding
       a new `if provider == "..."` branch here. No other file needs to change.
    3. Testability: tests can replace the factory with a fake.

Cache design:
  _provider_cache is a module-level dict — it lives for the entire lifetime of
  the Python process. Cache key = (config.id, model, api_key).
  Including config.id means: if the user deactivates provider A and activates
  provider B, the next ingest run gets a fresh provider B (different config.id).
  Old entries stay in the cache but are never looked up again — effectively GC'd
  when the server restarts.
"""

import logging

from app.models.ai_provider import AIProviderConfig, PROVIDER_BASE_URLS
from app.services.normalization.providers.base import AIProvider

# Import all concrete provider implementations
from app.services.normalization.providers.anthropic_prov import AnthropicProvider
from app.services.normalization.providers.gemini_langgraph_prov import GeminiLangGraphProvider
from app.services.normalization.providers.gemini_multimodal_prov import GeminiMultimodalLangGraphProvider
from app.services.normalization.providers.openai_prov import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

# Module-level cache: { (config_id, model, api_key) → AIProvider instance }
# Persists for the lifetime of the process (until server restart).
# Architecture decision: caching here (not inside IngestionService) because:
#   - IngestionService is created fresh per HTTP request
#   - We don't want to create new SDK connection pools on every request
#   - Provider instances are stateless (safe to share across requests)
_provider_cache: dict[tuple, AIProvider] = {}


def create_from_config(config: AIProviderConfig) -> AIProvider:
    """Return (or create and cache) an AIProvider for a DB config row.

    Cache key = (config.id, config.model, config.api_key).
    The api_key is included so that if the user deletes and recreates a config
    with the same model but a new key, a fresh client is created (old key = stale).
    """
    cache_key = (config.id, config.model, config.api_key)
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]   # Return cached instance — no new objects created

    # Build a fresh provider instance (creates SDK client with connection pool)
    provider = _build(config)
    _provider_cache[cache_key] = provider   # Cache for future calls
    return provider


def create_from_env(api_key: str, model: str) -> AIProvider:
    """Build an AnthropicProvider from env-var credentials (legacy backwards-compat).

    Cache key uses "env:anthropic" prefix to distinguish from DB-configured providers.
    Called by ai_processor.get_env_fallback_provider() when ANTHROPIC_API_KEY is set.
    """
    cache_key = ("env:anthropic", model, api_key)
    if cache_key not in _provider_cache:
        _provider_cache[cache_key] = AnthropicProvider(api_key=api_key, model=model)
    return _provider_cache[cache_key]


def create_gemini_from_env(api_key: str, model: str) -> AIProvider:
    """Build a GeminiLangGraphProvider from env-var credentials.

    Cache key uses "env:gemini_langgraph" prefix.
    Kept for backward compatibility — new code should prefer create_gemini_multimodal_from_env.
    """
    cache_key = ("env:gemini_langgraph", model, api_key)
    if cache_key not in _provider_cache:
        _provider_cache[cache_key] = GeminiLangGraphProvider(api_key=api_key, model=model)
    return _provider_cache[cache_key]


def create_gemini_multimodal_from_env(api_key: str, model: str) -> AIProvider:
    """Build a GeminiMultimodalLangGraphProvider from env-var credentials.

    This is the RECOMMENDED env-var path for this crime news app.
    Provides: multimodal image processing, structured output, multi-label
    classification, concurrent news search, and proper post-processing.
    """
    cache_key = ("env:gemini_multimodal", model, api_key)
    if cache_key not in _provider_cache:
        _provider_cache[cache_key] = GeminiMultimodalLangGraphProvider(
            api_key=api_key, model=model
        )
    return _provider_cache[cache_key]


def _build(config: AIProviderConfig) -> AIProvider:
    """Instantiate the correct AIProvider subclass for the given config.

    Architecture decision: using if/elif chains (not a registry dict or
    dynamic import) because:
      - The number of providers is small and changes rarely
      - Explicit is better than implicit (Python Zen)
      - Mypy/Pylance can type-check each branch separately

    How to add a new provider:
      1. Create a new subclass of AIProvider in providers/your_provider.py
      2. Add an import above
      3. Add an elif branch here
      4. Add the provider name to SUPPORTED_PROVIDERS in models/ai_provider.py
    """
    provider = config.provider
    model = config.model
    api_key = config.api_key
    # Use the stored base_url if the user provided one,
    # or fall back to the provider default (e.g. Gemini's Google API endpoint)
    base_url = config.base_url or PROVIDER_BASE_URLS.get(provider)

    if provider == "anthropic":
        # Anthropic SDK — uses api_key to call api.anthropic.com
        return AnthropicProvider(api_key=api_key, model=model)

    if provider == "gemini_langgraph":
        # Original LangGraph provider: search_node → process_node (single combined call).
        return GeminiLangGraphProvider(api_key=api_key, model=model)

    if provider == "gemini_multimodal":
        # Enhanced multimodal LangGraph provider — RECOMMENDED.
        # Two separate graphs: filter (extract→search→classify) and post-process (search→rewrite+rank).
        # Supports image-in-message for crime scene classification.
        return GeminiMultimodalLangGraphProvider(api_key=api_key, model=model)

    if provider in ("openai", "gemini", "custom"):
        # OpenAI-compatible endpoint — works for OpenAI, Gemini (via OpenAI format),
        # and any self-hosted server (Ollama, vLLM, LM Studio).
        # base_url=None uses the OpenAI SDK's default (api.openai.com).
        return OpenAICompatibleProvider(api_key=api_key, model=model, base_url=base_url)

    raise ValueError(
        f"Unknown provider {provider!r}. "
        "Add a new subclass of AIProvider and register it here."
    )
