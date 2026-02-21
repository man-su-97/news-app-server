"""Backwards-compatible env-var-based AI provider loader.

When no AI provider is configured in the database, IngestionService calls
get_env_fallback_provider() to check whether ANTHROPIC_API_KEY is set in the
environment. This preserves the behaviour that existed before the multi-provider
DB config was introduced — existing deployments that export ANTHROPIC_API_KEY
continue to work without any DB changes.

New deployments should configure providers via POST /ai-providers and
PATCH /ai-providers/{id}/activate instead.
"""

import logging

from app.core.config import settings
from app.services.normalization.provider_factory import create_from_env
from app.services.normalization.providers.base import AIProvider

logger = logging.getLogger(__name__)

_ENV_FALLBACK_MODEL = "claude-haiku-4-5-20251001"


def get_env_fallback_provider() -> AIProvider | None:
    """Return an Anthropic provider built from ANTHROPIC_API_KEY, or None.

    The returned instance is cached inside provider_factory so repeated calls
    do not create new SDK client objects.
    """
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        return create_from_env(
            api_key=settings.ANTHROPIC_API_KEY,
            model=_ENV_FALLBACK_MODEL,
        )
    except Exception as exc:
        logger.error("Failed to build env-var AI provider: %s", exc)
        return None
