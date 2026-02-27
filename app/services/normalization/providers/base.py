import json
import logging
import re
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError, field_validator

from app.services.source_normalizer import parse_date

logger = logging.getLogger(__name__)


SINGLE_PROCESS_PROMPT = """\
You are a crime news processing engine for a real-time crime news aggregation platform.
You receive raw JSON from a news source (RSS feed or REST API).

STEP 1 — Crime check:
Determine if the article is PRIMARILY about criminal activity.
If NOT a crime article: return ONLY {"is_crime": false} — nothing else.

STEP 2 — Full processing (ONLY if crime):
Extract, classify, AND produce publication-ready content in one response.

Rules:
- Return ONLY valid JSON. No markdown, no prose, no code fences.
- title: extract the original headline exactly as provided by the source (clean HTML if present).
  Derive from the first sentence of content if the title field is absent.
- rewritten_title: rephrase the headline in your own words — do NOT copy source verbatim.
  Max 15 words, active voice, factual. Include location if known.
- url: absolute HTTP(S) URL of the article, or null if absent or relative.
- description: extract source text as-is (clean HTML tags). 1-3 sentences. null if absent.
- rewritten_description: rephrase in your own words (~80-100 words, 3-5 sentences).
  Cover: what happened, who is involved (if known), where it occurred, key context.
  Do NOT copy source text verbatim. Do NOT speculate.
- image_url: absolute HTTP(S) URL, or null.
- published_at: ISO 8601 UTC (e.g. "2024-01-15T10:30:00Z"), or null.
- sub_category: pick the SINGLE BEST match from:
    murder, theft, fraud, cybercrime, terrorism, corruption,
    drugs, violence, trafficking, other
- sub_category_ids: ALL that apply (array) from the same list.
  Example: kidnapping-for-ransom → ["violence", "trafficking"]
- location: city and country where the incident occurred (e.g. "Mumbai, India").
  null if not determinable.
- imp_score: integer 1-100 importance score.
    1-20:   Hyperlocal / minor incident (e.g. petty theft in a small town)
    21-40:  Local / notable (e.g. single murder in a major city)
    41-60:  Regional / significant (e.g. crime gang bust, notable fraud)
    61-80:  National / high impact (e.g. major terrorism foiled, senior official arrested)
    81-100: International / breaking crisis (e.g. multi-city attack, political assassination)
  Factors: crime severity, number of victims, geographic scope, public official involvement.

Non-crime output (return ONLY this):
{"is_crime": false}

Crime output schema (return exactly this shape):
{
  "is_crime": true,
  "title": "original title from source",
  "rewritten_title": "your rephrased headline",
  "url": "string or null",
  "description": "original description or null",
  "rewritten_description": "your rephrased description",
  "image_url": "string or null",
  "published_at": "ISO 8601 or null",
  "sub_category": "string",
  "sub_category_ids": ["string", ...],
  "location": "string or null",
  "imp_score": integer
}"""


_VALID_CRIME_SUBCATEGORIES = frozenset({
    "murder", "theft", "fraud", "cybercrime", "terrorism", "corruption",
    "drugs", "violence", "trafficking", "other",
})

class SingleOutput(BaseModel):
    is_crime: bool = False
    title: str = ""
    rewritten_title: str = ""
    url: str | None = None
    description: str | None = None
    rewritten_description: str = ""
    image_url: str | None = None
    published_at: str | None = None
    sub_category: str | None = None
    sub_category_ids: list[str] = []
    location: str | None = None
    imp_score: int = 50

    @field_validator("url", "image_url", mode="before")
    @classmethod
    def _check_url(cls, v) -> str | None:
        if not v or not isinstance(v, str):
            return None
        return v if v.startswith(("http://", "https://")) else None

    @field_validator("sub_category", mode="before")
    @classmethod
    def _check_sub_category(cls, v) -> str | None:
        if not v or not isinstance(v, str):
            return None
        v = v.lower().strip()
        return v if v in _VALID_CRIME_SUBCATEGORIES else None

    @field_validator("sub_category_ids", mode="before")
    @classmethod
    def _check_sub_category_ids(cls, v) -> list[str]:
        if not v or not isinstance(v, list):
            return []
        return [
            item.lower().strip()
            for item in v
            if isinstance(item, str) and item.lower().strip() in _VALID_CRIME_SUBCATEGORIES
        ]

    @field_validator("imp_score", mode="before")
    @classmethod
    def _check_imp_score(cls, v) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 50
        return max(1, min(100, v))


def build_process_message(raw_payload: dict, source_type: str, search_context: str = "") -> str:
    payload: dict = {
        "source_type": source_type,
        "raw_payload": raw_payload,
    }
    if search_context:
        payload["web_search_context"] = search_context
    return json.dumps(payload, default=str, separators=(",", ":"))


def _extract_json(text: str) -> str:
    """Strip code fences, thinking blocks, and isolate the JSON object."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return text


_strip_code_fences = _extract_json


def parse_single_output(text: str, raw_payload: dict) -> dict | None:
    try:
        data = json.loads(_extract_json(text))
        output = SingleOutput.model_validate(data)
    except json.JSONDecodeError as exc:
        logger.warning("AI single: non-JSON response: %s | text=%r", exc, text[:200])
        return None
    except ValidationError as exc:
        logger.warning("AI single: validation failed: %s", exc)
        return None

    if not output.is_crime:
        return {"is_crime": False}

    if not output.title:
        logger.warning("AI single: crime article has no title — dropping")
        return None

    published_at = parse_date(output.published_at) if output.published_at else None

    url = output.url
    if not url:
        fallback = raw_payload.get("link") or raw_payload.get("url") or ""
        if isinstance(fallback, str) and fallback.startswith(("http://", "https://")):
            url = fallback

    return {
        "is_crime": True,
        "title": output.title,
        "rewritten_title": output.rewritten_title,
        "description": output.description,
        "rewritten_description": output.rewritten_description,
        "content": None,
        "url": url or "",
        "image_url": output.image_url,
        "published_at": published_at,
        "raw_payload": raw_payload,
        "sub_category": output.sub_category,
        "sub_category_ids": output.sub_category_ids,
        "location": output.location,
        "imp_score": output.imp_score,
    }


class AIProvider(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifier stored in raw_ingestion.normalized_by for audit trail."""

    @abstractmethod
    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        """Single AI call: extract + classify + rewrite + score. Returns article dict or None."""
