import logging

from app.models.ai_provider import AIProviderConfig, PROVIDER_BASE_URLS
from app.services.normalization.providers.base import AIProvider
from app.services.normalization.providers.anthropic_prov import AnthropicProvider
from app.services.normalization.providers.openai_prov import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

# Module-level cache: keyed by (config.id, model, api_key) to avoid constructing
# new SDK clients on every ingest run. Each SDK client manages its own connection
# pool, so creating one per request is wasteful.
# The cache is invalidated implicitly when config.id changes (user activates a
# different provider record) — the old entry is simply never looked up again.
_provider_cache: dict[tuple, AIProvider] = {}


def create_from_config(config: AIProviderConfig) -> AIProvider:
    """Instantiate (or retrieve cached) an AIProvider from a DB config row.

    Cache key includes config.id so that if the user swaps the active provider,
    the new config always gets a fresh instance. api_key is included so that
    editing a config's key (delete + recreate) produces a new client.
    """
    cache_key = (config.id, config.model, config.api_key)
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]

    provider = _build(config)
    _provider_cache[cache_key] = provider
    return provider


def create_from_env(api_key: str, model: str) -> AIProvider:
    """Build an Anthropic provider from environment variables (backwards-compat path)."""
    cache_key = ("env", model, api_key)
    if cache_key not in _provider_cache:
        _provider_cache[cache_key] = AnthropicProvider(api_key=api_key, model=model)
    return _provider_cache[cache_key]


def _build(config: AIProviderConfig) -> AIProvider:
    provider = config.provider
    model = config.model
    api_key = config.api_key
    # Use the stored base_url, or fall back to the provider default
    base_url = config.base_url or PROVIDER_BASE_URLS.get(provider)

    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)

    if provider in ("openai", "gemini", "custom"):
        return OpenAICompatibleProvider(api_key=api_key, model=model, base_url=base_url)

    raise ValueError(
        f"Unknown provider {provider!r}. "
        "Add a new subclass of AIProvider and register it here."
    )
