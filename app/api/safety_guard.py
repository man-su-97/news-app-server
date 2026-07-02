"""Input safety guard for the AI endpoints (HTTP layer).

Bridges the pure safety logic (`app/services/ai/safety`) to HTTP: rejects
prompt-injection attempts with 400 and redacts PII from the user's text before it
is passed to a service (and thus to the model). Controlled by `SAFETY_ENABLED`.
"""

from fastapi import HTTPException

from app.core.config import settings
from app.services.ai.safety.injection import contains_injection
from app.services.ai.safety.pii import redact_pii


def enforce_input_safety(text: str) -> str:
    """Return a safe, PII-redacted version of `text`, or raise 400 on injection."""
    if not settings.SAFETY_ENABLED:
        return text
    if contains_injection(text):
        raise HTTPException(
            status_code=400,
            detail="Request blocked: the input looks like a prompt-injection attempt.",
        )
    return redact_pii(text)
