"""
app/services/normalization/providers/base.py — AI Provider Abstractions & Shared Logic
========================================================================================
This file is the heart of the AI normalization system. It defines:

1. NORMALIZATION_SYSTEM_PROMPT: The instruction given to every AI for extracting
   article fields (title, url, description, etc.) from raw source payloads.

2. ENRICHMENT_SYSTEM_PROMPT: The instruction for the second AI pass — classifying
   crime type, extracting location, generating summary, scoring importance.

3. Pydantic models (_NormOutput, EnrichmentOutput): Validate that the AI's JSON
   response has the correct shape and valid values. If the AI returns garbage,
   these models catch it and we fall back to None gracefully.

4. Helper functions (build_user_message, build_enrichment_message, parse_*):
   Shared utility functions used by ALL provider implementations, so the logic
   lives in ONE place instead of being duplicated in Anthropic/OpenAI/Gemini files.

5. AIProvider abstract base class: defines the interface ALL providers must implement.
   IngestionService only depends on AIProvider — it doesn't know about Claude, GPT,
   or Gemini specifically. Adding a new provider = add a subclass, no other changes.

Architecture pattern: "Strategy" pattern.
  The provider is chosen at runtime (from DB config or env var) and injected
  into IngestionService. IngestionService calls provider.normalize() and
  provider.enrich() without knowing which AI is being used.
"""

import json     # For JSON serialization/deserialization
import logging
import re       # For stripping markdown code fences from AI responses
from abc import ABC, abstractmethod  # ABC = Abstract Base Class

# BaseModel = Pydantic model base
# ValidationError = raised when AI output doesn't match expected schema
# field_validator = decorator for custom field validation rules
from pydantic import BaseModel, ValidationError, field_validator

from app.services.source_normalizer import parse_date  # Reuse date parsing


logger = logging.getLogger(__name__)

# ============================================================
# PROMPT 1: Normalization — extract basic fields from raw data
# ============================================================
# This is the SYSTEM MESSAGE sent to the AI for the first pass.
# The AI receives raw JSON from an RSS feed or REST API and must extract
# the canonical article fields.
#
# Design decisions:
#   - "Return ONLY valid JSON" prevents the AI from wrapping in markdown (```json...```)
#   - All fields are optional except title (an article must have a headline)
#   - The exact output schema is specified to prevent the AI from adding extra fields
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

# ============================================================
# PROMPT 2: Enrichment — classify crime type, location, priority
# ============================================================
# This is the SYSTEM MESSAGE for the second AI pass (enrichment).
# Input: already-normalized article (title + description + url + optional web search results)
# Output: crime classification, location, region, summary, priority score
#
# Key design decisions:
#   - "is_crime: true/false" allows the AI to flag non-crime articles for filtering
#   - Fixed category and region lists prevent the AI from inventing new values
#   - "web_search_context" field: if DuckDuckGo found related news, it's included here
#     This allows the AI to calibrate importance_score based on real-world coverage
ENRICHMENT_SYSTEM_PROMPT = """\
You are a crime news analyst for a real-time crime news aggregation platform.
Given a normalized news article (title, description, url) and optional web_search_context,
produce a structured classification for card display and priority ranking.

Rules:
- Return ONLY valid JSON. No markdown, no prose, no code fences.
- is_crime: true if the article is primarily about criminal activity, false otherwise.
- category: "crime" when is_crime=true, otherwise pick from:
    politics, technology, business, science, health, sports,
    entertainment, world, environment, other
- sub_category: when is_crime=true pick exactly one from:
    murder, theft, fraud, cybercrime, terrorism, corruption,
    drugs, violence, trafficking, other
  For non-crime set null.
- location: city and country where the incident occurred (e.g. "Mumbai, India").
  null if not determinable.
- region: pick exactly one from:
    South Asia, Southeast Asia, East Asia, Central Asia,
    Middle East, Europe, North America, Latin America, Africa, Oceania, unknown
- summary: 2-3 sentence factual summary suitable for a news card preview.
  Be concise and objective. Do not editorialize.
- importance_score: integer 1–10.
    1–3  = local / minor interest
    4–6  = regional / moderate public interest
    7–8  = national / significant impact
    9–10 = breaking / international crisis
  Use web_search_context (if provided) to calibrate — wider coverage = higher score.

Output schema (return exactly this shape, nothing else):
{
  "is_crime": true or false,
  "category": "string",
  "sub_category": "string or null",
  "location": "string or null",
  "region": "string",
  "summary": "string",
  "importance_score": integer
}"""

# Valid values for category — AI must pick from this list exactly.
# frozenset is immutable, which prevents accidental modification.
_VALID_CATEGORIES = frozenset({
    "politics", "technology", "business", "science", "health", "sports",
    "entertainment", "world", "environment", "crime", "other",
})

# Valid crime subcategories — only used when category == "crime".
_VALID_CRIME_SUBCATEGORIES = frozenset({
    "murder", "theft", "fraud", "cybercrime", "terrorism", "corruption",
    "drugs", "violence", "trafficking", "other",
})

# Valid geographic regions for frontend filtering.
_VALID_REGIONS = frozenset({
    "south asia", "southeast asia", "east asia", "central asia",
    "middle east", "europe", "north america", "latin america",
    "africa", "oceania", "unknown",
})


# ============================================================
# Pydantic validation models
# ============================================================

class _NormOutput(BaseModel):
    """Validates the JSON the AI returns for the normalization call.

    If the AI omits a field or uses the wrong type, Pydantic raises ValidationError
    and the caller returns None (article is dropped/retried). This protects the
    database from receiving malformed data.
    """
    title: str                          # Required — article must have a title
    description: str | None = None      # Optional
    url: str | None = None             # Optional (validator in canonical_validator.py checks it)
    published_at: str | None = None    # Optional — parsed to datetime in parse_llm_output()
    image_url: str | None = None       # Optional
    author: str | None = None          # Optional (not stored in Article model currently)


class EnrichmentOutput(BaseModel):
    """Validates the JSON the AI returns for the enrichment call.

    All fields have defaults (except importance_score) so that partially-valid
    AI responses can still be used. For example, if the AI returns a valid
    category and score but forgets location, we still use what we got.
    """
    is_crime: bool = True              # Default True: fail-safe (don't drop on error)
    category: str                      # Required — validated by _check_category
    sub_category: str | None = None    # Only for crime articles
    location: str | None = None        # City + country
    region: str = "unknown"            # Default "unknown" if AI doesn't return valid region
    summary: str = ""                  # AI-written card preview text
    importance_score: int              # Required — 1-10 integer

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        """Normalize to lowercase and validate against the allowed list."""
        v = v.lower().strip()
        if v not in _VALID_CATEGORIES:
            raise ValueError(f"Unknown category: {v!r}")
        return v

    @field_validator("sub_category")
    @classmethod
    def _check_sub_category(cls, v: str | None) -> str | None:
        """Validate crime subcategory if provided."""
        if v is None:
            return None
        v = v.lower().strip()
        if v not in _VALID_CRIME_SUBCATEGORIES:
            raise ValueError(f"Unknown sub_category: {v!r}")
        return v

    @field_validator("region")
    @classmethod
    def _check_region(cls, v: str) -> str:
        """Normalize region to lowercase. Fall back to 'unknown' if invalid.

        Design decision: instead of raising ValueError (which would fail the
        entire enrichment), we silently default to "unknown". Region is less
        critical than category or score — a wrong region is better than no enrichment.
        """
        v_lower = v.lower().strip()
        if v_lower not in _VALID_REGIONS:
            return "unknown"   # Graceful fallback instead of rejection
        return v_lower

    @field_validator("importance_score")
    @classmethod
    def _check_score(cls, v: int) -> int:
        """Ensure score is in the 1-10 range."""
        if not (1 <= v <= 10):
            raise ValueError(f"importance_score must be 1–10, got {v}")
        return v


# ============================================================
# Message builder helpers
# ============================================================

def build_user_message(raw_payload: dict, source_type: str) -> str:
    """Build the USER message for the normalization call.

    This is sent alongside NORMALIZATION_SYSTEM_PROMPT to the AI.
    Including source_type ("rss" or "rest") helps the AI understand the
    structure of the payload (RSS fields differ from REST API fields).
    """
    return (
        f"Source type: {source_type}\n\n"
        f"Raw payload:\n{json.dumps(raw_payload, default=str, indent=2)}"
        # default=str: converts non-JSON types (like datetime) to strings
        # indent=2: pretty-printed for better AI comprehension
    )


def build_enrichment_message(article: dict, search_context: str = "") -> str:
    """Build the USER message for the enrichment call.

    Sends a minimal JSON with just the fields the enrichment AI needs:
    title, description, url. This is intentionally smaller than the full
    raw_payload — the AI doesn't need the entire RSS entry to classify the article.

    If search_context is provided (from DuckDuckGo), it's included so the AI
    can calibrate importance_score based on how widely covered the story is.
    """
    payload: dict = {
        "title": article.get("title", ""),
        "description": article.get("description"),
        "url": article.get("url", ""),
    }
    if search_context:
        # Add web search results as context for better importance scoring
        payload["web_search_context"] = search_context
    return json.dumps(payload, ensure_ascii=False)  # ensure_ascii=False preserves Unicode


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that some AI models add around JSON.

    Problem: some models (especially Gemini) wrap responses in ```json ... ```
    even when instructed not to. json.loads() fails on this format.
    Solution: strip the fences before parsing.

    Examples handled:
      ```json\n{"key": "value"}\n```  → {"key": "value"}
      ```\n{"key": "value"}\n```       → {"key": "value"}
      {"key": "value"}                 → {"key": "value"} (unchanged)
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)   # remove opening fence
    text = re.sub(r"\n?```$", "", text)               # remove closing fence
    return text.strip()


# ============================================================
# Output parsers
# ============================================================

def parse_llm_output(text: str, raw_payload: dict) -> dict | None:
    """Parse and validate the AI's normalization response text.

    1. Strip code fences (some models add them even when told not to)
    2. Parse as JSON
    3. Validate with _NormOutput Pydantic model
    4. Convert published_at string to Python datetime
    5. Return canonical article dict

    Returns None on ANY failure — callers treat None as "this article failed,
    try the next normalization method or drop it".
    """
    try:
        # Step 1+2: strip fences and parse JSON
        data = json.loads(_strip_code_fences(text))
        # Step 3: validate schema
        output = _NormOutput.model_validate(data)
    except json.JSONDecodeError as exc:
        logger.warning("AI provider returned non-JSON: %s", exc)
        return None
    except ValidationError as exc:
        logger.warning("AI output failed schema validation: %s", exc)
        return None

    # Step 4: parse the date string to a Python datetime object
    published_at = parse_date(output.published_at) if output.published_at else None

    # Step 5: return the canonical article dict shape
    return {
        "title": output.title,
        "description": output.description,
        "content": None,          # Not extracted in this pipeline (future use)
        "url": output.url or "",  # or "" ensures url is never None
        "image_url": output.image_url,
        "published_at": published_at,
        "raw_payload": raw_payload,  # preserve original for audit/reprocessing
    }


# Canonical "null enrichment" returned when enrichment fails.
# is_crime=True (default): articles are NOT dropped if enrichment fails.
# All other fields None: article is saved but with no enrichment data.
# This dict is exported so providers can import and return it on error.
_NULL_ENRICHMENT: dict = {
    "is_crime": True,       # IMPORTANT: default True prevents accidental article dropping
    "category": None,
    "sub_category": None,
    "location": None,
    "region": None,
    "summary": None,
    "importance_score": None,
}


def parse_enrichment_output(text: str) -> dict:
    """Parse and validate the AI's enrichment response text.

    Unlike parse_llm_output, this NEVER returns None — it always returns a dict.
    On any failure, it returns _NULL_ENRICHMENT so the article is still saved
    (just without enrichment data).

    Architecture decision: enrichment is "best effort". A bad AI response should
    never cause an article to be lost. The worst case is saving an article with
    NULL enrichment fields, which is much better than silently dropping real news.
    """
    try:
        data = json.loads(_strip_code_fences(text))
        output = EnrichmentOutput.model_validate(data)
    except json.JSONDecodeError as exc:
        logger.warning("Enrichment: non-JSON response: %s", exc)
        return _NULL_ENRICHMENT
    except ValidationError as exc:
        logger.warning("Enrichment: schema validation failed: %s", exc)
        return _NULL_ENRICHMENT

    return {
        "is_crime": output.is_crime,
        "category": output.category,
        "sub_category": output.sub_category,
        "location": output.location,
        "region": output.region,
        "summary": output.summary or None,  # empty string → None
        "importance_score": output.importance_score,
    }


# ============================================================
# Abstract base class — the interface all providers must implement
# ============================================================

class AIProvider(ABC):
    """Abstract base class that all AI provider implementations must subclass.

    Why an abstract base class?
      IngestionService depends on AIProvider, not on AnthropicProvider or
      GeminiLangGraphProvider directly. This means:
        - Adding a new AI provider = add a new subclass + register in factory
        - No changes needed in IngestionService, routes, or any other file
        - Tests can use a mock AIProvider without making real API calls

    Subclasses:
      - AnthropicProvider      (providers/anthropic_prov.py)
      - OpenAICompatibleProvider (providers/openai_prov.py)
      - GeminiLangGraphProvider  (providers/gemini_langgraph_prov.py)
    """

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Human-readable identifier stored in raw_ingestion_events.normalized_by.

        Used for tracking which AI processed each article. Example values:
          "ai:anthropic:claude-haiku-4-5-20251001"
          "ai:gemini_langgraph:gemini-2.0-flash"
        """

    @abstractmethod
    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        """Extract canonical article fields from a raw source payload.

        Returns a dict compatible with ArticleRepository.upsert_batch on success,
        or None if the AI call fails or produces invalid output.
        The caller (IngestionService) runs CanonicalValidator on the result.
        """

    @abstractmethod
    async def enrich(self, article: dict) -> dict:
        """Add category, sub_category, location, region, summary, importance_score.

        Takes a NORMALIZED article dict (from normalize()) and returns an enrichment
        dict with the AI-generated classification fields.

        MUST always return a dict (never raise, never return None).
        On any error, return _NULL_ENRICHMENT so the article is still saved.
        The is_crime field in the return dict controls whether the article is kept
        (is_crime=True) or dropped (is_crime=False).
        """
