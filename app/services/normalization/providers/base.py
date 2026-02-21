import json
import logging
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError

from app.services.source_normalizer import parse_date

logger = logging.getLogger(__name__)

# Shared extraction prompt — identical behaviour across all providers.
# Every provider sends this as the system instruction.
NORMALIZATION_SYSTEM_PROMPT = """\
You are a structured data extraction engine for a news aggregation system.
You receive a raw JSON payload from a news source (RSS feed or REST API) and must
extract canonical fields into a JSON object.

Rules:
- Return ONLY valid JSON. No markdown, no prose, no code fences.
- If a field is absent or genuinely ambiguous, use null for optional fields.
- Normalize published_at to ISO 8601 UTC (e.g. "2024-01-15T10:30:00Z"), or null.
- title is required. If truly absent, derive it from the first sentence of description.
- url must be an absolute HTTP(S) URL. If absent or relative, return null for url.
- description: 1-3 sentence summary, or null if no content is available.

Output schema (return exactly this shape, nothing else):
{
  "title": "string",
  "description": "string or null",
  "url": "string or null",
  "published_at": "ISO 8601 string or null",
  "image_url": "string or null",
  "author": "string or null"
}"""


class _NormOutput(BaseModel):
    """Validates the JSON the LLM is expected to return."""
    title: str
    description: str | None = None
    url: str | None = None
    published_at: str | None = None
    image_url: str | None = None
    author: str | None = None


def build_user_message(raw_payload: dict, source_type: str) -> str:
    return (
        f"Source type: {source_type}\n\n"
        f"Raw payload:\n{json.dumps(raw_payload, default=str, indent=2)}"
    )


def parse_llm_output(text: str, raw_payload: dict) -> dict | None:
    """Parse + validate raw LLM text into a canonical article dict.

    Shared by all providers so parsing logic stays in one place.
    Returns None on any parse/validation failure so callers can log and move on.
    """
    try:
        data = json.loads(text.strip())
        output = _NormOutput.model_validate(data)
    except json.JSONDecodeError as exc:
        logger.warning("AI provider returned non-JSON: %s", exc)
        return None
    except ValidationError as exc:
        logger.warning("AI output failed schema validation: %s", exc)
        return None

    published_at = parse_date(output.published_at) if output.published_at else None

    return {
        "title": output.title,
        "description": output.description,
        "content": None,
        "url": output.url or "",
        "image_url": output.image_url,
        "published_at": published_at,
        "raw_payload": raw_payload,
    }


class AIProvider(ABC):
    """All AI providers implement this interface.

    IngestionService depends only on this base class — adding a new provider
    means adding a subclass here and registering it in provider_factory.py.
    No changes to IngestionService, the validator, or any route.
    """

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Human-readable label stored in raw_ingestion_events.normalized_by."""

    @abstractmethod
    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        """Extract canonical article fields from a raw payload.

        Returns a normalized article dict compatible with ArticleRepository.upsert_batch,
        or None if the provider call fails or produces unparseable output.
        The caller (IngestionService) runs CanonicalValidator on the returned dict.
        """
