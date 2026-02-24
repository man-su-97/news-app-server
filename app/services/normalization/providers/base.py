"""
app/services/normalization/providers/base.py — AI Provider Abstractions & Shared Logic
========================================================================================
Two-stage AI processing pipeline for the crime news aggregator.

STAGE 1 — FILTER (one call per raw article):
  COMBINED_PROCESS_PROMPT   → extract fields + classify crime type (multi-label)
  CombinedOutput            → validated Pydantic model for stage 1 output
  build_process_message()   → builds user message with raw payload + web context
  parse_combined_output()   → strips fences, validates, returns complete article dict

STAGE 2 — POST-PROCESS (one call per crime article that passed stage 1):
  POST_PROCESS_PROMPT       → rewrite title/description + score importance
  PostProcessOutput         → validated Pydantic model for stage 2 output
  build_post_process_message() → builds user message from filter stage result
  parse_post_process_output()  → parses and validates stage 2 AI response

AIProvider abstract base class:
  process()      — ABSTRACT: stage 1 (extract + classify)
  post_process() — CONCRETE default: returns None (providers override for stage 2)

Architecture pattern: "Strategy" pattern.
  The provider (Gemini, Claude, etc.) is chosen at runtime and injected into
  IngestionService. IngestionService calls provider.process() and post_process()
  without knowing which AI backend is used.
"""

import json
import logging
import re
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError, field_validator

from app.services.source_normalizer import parse_date  # Reuse shared date parser

logger = logging.getLogger(__name__)


# ============================================================
# STAGE 1: COMBINED PROCESS PROMPT — extract + classify
# ============================================================
# Design decisions:
#   - ONE prompt for stage 1: saves one API round-trip per article vs. two-step
#   - "Return ONLY valid JSON" prevents markdown code fences (```json...```)
#   - sub_category_ids as ARRAY: one article can span multiple crime types
#     (e.g. kidnapping-for-ransom = Violent Crime + Financial Crime)
#   - Fixed sub_category list prevents hallucinated values; unknown → "other"
#   - web_search_context: DuckDuckGo results for better importance calibration
COMBINED_PROCESS_PROMPT = """\
You are a crime news processing engine for a real-time crime news aggregation platform.
You receive raw JSON from a news source (RSS feed or REST API) and optional web search
context. Your task: extract article fields AND classify the crime content in ONE pass.

Rules:
- Return ONLY valid JSON. No markdown, no prose, no code fences.
- title: required. Extract exactly as provided by the source — do not rephrase or modify.
  If absent, derive from the first sentence of the content.
- url: absolute HTTP(S) URL, or null if absent or relative.
- description: Extract the description or body text from the raw content as-is (clean HTML tags
  if present). 1-3 sentences. null if there is no usable content.
- published_at: ISO 8601 UTC (e.g. "2024-01-15T10:30:00Z"), or null.
- image_url: absolute HTTP(S) URL, or null.
- is_crime: true if the article is primarily about criminal activity, false otherwise.
- category: pick exactly one from:
    politics, technology, business, science, health, sports,
    entertainment, world, environment, crime, other
  Use "crime" when is_crime=true.
- sub_category: when is_crime=true pick the SINGLE BEST match from:
    murder, theft, fraud, cybercrime, terrorism, corruption,
    drugs, violence, trafficking, other
  Set null for non-crime articles.
- sub_category_ids: when is_crime=true, pick ALL that apply (array) from the same list:
    ["murder", "theft", "fraud", "cybercrime", "terrorism", "corruption",
     "drugs", "violence", "trafficking", "other"]
  Example: a kidnapping-for-ransom → ["violence", "fraud"]
  Set [] for non-crime articles.
- location: city and country where the incident occurred (e.g. "Mumbai, India").
  null if not determinable.
- region: pick exactly one from:
    South Asia, Southeast Asia, East Asia, Central Asia,
    Middle East, Europe, North America, Latin America, Africa, Oceania, unknown
- summary: 2-3 sentence factual summary suitable for a news card preview.
  Be concise and objective. null if insufficient content.
- importance_score: integer 1-10.
    1-3  = local / minor interest
    4-6  = regional / moderate public interest
    7-8  = national / significant impact
    9-10 = breaking / international crisis
  Use web_search_context (if provided) to calibrate — wider coverage = higher score.

Output schema (return exactly this shape, nothing else):
{
  "title": "string",
  "url": "string or null",
  "description": "string or null",
  "image_url": "string or null",
  "published_at": "ISO 8601 string or null",
  "is_crime": true or false,
  "category": "string",
  "sub_category": "string or null",
  "sub_category_ids": ["string", ...],
  "location": "string or null",
  "region": "string",
  "summary": "string or null",
  "importance_score": integer
}"""

# Valid values for category — lenient validator falls back to "other" instead of rejecting.
_VALID_CATEGORIES = frozenset({
    "politics", "technology", "business", "science", "health", "sports",
    "entertainment", "world", "environment", "crime", "other",
})

# Valid crime subcategories — only meaningful when category == "crime".
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
# Pydantic validation model for STAGE 1 output
# ============================================================

class CombinedOutput(BaseModel):
    """Validates the JSON the AI returns from a single combined process() call.

    Design philosophy: LENIENT validation.
      Old approach: strict validators raised ValueError → article dropped on bad AI output.
      New approach: validators use sensible fallbacks → article saved with default values.

    The only hard failure is a missing title — articles MUST have a headline.
    """
    title: str                              # Required — ValidationError if missing → dropped
    url: str | None = None                 # Optional — validated for http/https below
    description: str | None = None         # Optional
    image_url: str | None = None           # Optional
    published_at: str | None = None        # Optional — parsed to datetime in parse_combined_output
    is_crime: bool = True                  # Default True: fail-safe (don't drop on AI error)
    category: str = "other"               # Default "other" — overridden by AI
    sub_category: str | None = None        # Single best-match crime sub-type (legacy)
    sub_category_ids: list[str] = []       # Multi-label list of matching sub-types
    location: str | None = None            # City + country free text
    region: str = "unknown"               # Default "unknown" if AI skips this field
    summary: str | None = None             # Card preview text
    importance_score: int = 5             # Default 5 (moderate) — overridden by AI

    @field_validator("url", mode="before")
    @classmethod
    def _check_url(cls, v) -> str | None:
        if not v or not isinstance(v, str):
            return None
        if not v.startswith(("http://", "https://")):
            return None
        return v

    @field_validator("category", mode="before")
    @classmethod
    def _check_category(cls, v) -> str:
        if not isinstance(v, str):
            return "other"
        v = v.lower().strip()
        return v if v in _VALID_CATEGORIES else "other"

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
        """Validate the multi-label sub_category list. Drop unrecognised entries."""
        if not v or not isinstance(v, list):
            return []
        cleaned = []
        for item in v:
            if isinstance(item, str):
                s = item.lower().strip()
                if s in _VALID_CRIME_SUBCATEGORIES:
                    cleaned.append(s)
        return cleaned

    @field_validator("region", mode="before")
    @classmethod
    def _check_region(cls, v) -> str:
        if not isinstance(v, str):
            return "unknown"
        v_lower = v.lower().strip()
        return v_lower if v_lower in _VALID_REGIONS else "unknown"

    @field_validator("importance_score", mode="before")
    @classmethod
    def _check_score(cls, v) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 5
        return max(1, min(10, v))


# ============================================================
# STAGE 2: POST-PROCESS PROMPT — rewrite + score
# ============================================================
# Called ONLY for articles that passed stage 1 (is_crime=True).
# Input: filter article data (title, description, url, sub_category).
# Output: rewritten title/description + importance score 1-100 + reference URLs.
#
# Why separate from stage 1?
#   - Stage 1 runs on ALL articles (cheap filter).
#   - Stage 2 runs only on crime articles (expensive enrichment).
#   - Different concerns: stage 1 is classification; stage 2 is publishing-quality writing.
#   - Splitting reduces wasted compute on non-crime articles (typically 50-90% of raw feed).
POST_PROCESS_PROMPT = """\
You are a senior crime news editor for a real-time news platform.
You receive a pre-classified crime news article (title, description, URL, crime type)
and web search results showing similar coverage of this story across the internet.
Your task: produce a publication-ready version with rephrased writing, reference links,
and an importance score.

Rules:
- Return ONLY valid JSON. No markdown, no prose, no code fences.
- rewritten_title: rephrase the headline in your own words — do NOT copy the source verbatim
  (plagiarism concern). Max 15 words, active voice, factual. Include location if known.
- rewritten_description: rephrase in your own words (~100 words, 4-6 sentences).
  Cover: what happened, who is involved (if known), where it occurred, key context.
  Do NOT copy source text verbatim. Do NOT include personal opinions or speculation.
- reference_urls: extract up to 5 URLs of SIMILAR or RELATED news articles found in
  web_search_context. These are reference links shown to readers wanting more coverage.
  Rules for reference_urls:
    * Only include URLs actually present in web_search_context — never invent URLs.
    * Prefer news sources (BBC, Reuters, NDTV, Times of India, Hindu, etc.).
    * Do NOT include the original article's own URL.
    * Return [] if web_search_context is absent or contains no relevant URLs.
- imp_score: integer 1-100 importance score.
    1-20:   Hyperlocal / minor incident (e.g. petty theft in a small town)
    21-40:  Local / notable (e.g. single murder in a major city)
    41-60:  Regional / significant (e.g. crime gang bust, notable fraud)
    61-80:  National / high impact (e.g. major terrorism foiled, senior official arrested)
    81-100: International / breaking crisis (e.g. multi-city attack, political assassination)
  Factors: crime severity, number of victims, geographic scope, public official involvement,
           breadth of web_search_context coverage, recency.

Output schema (return exactly this shape, nothing else):
{
  "rewritten_title": "string",
  "rewritten_description": "string",
  "reference_urls": ["url1", "url2", ...],
  "imp_score": integer
}"""


# ============================================================
# Pydantic validation model for STAGE 2 output
# ============================================================

class PostProcessOutput(BaseModel):
    """Validates the JSON the AI returns from a post_process() call."""

    rewritten_title: str                   # Required — if missing, caller falls back to original
    rewritten_description: str = ""        # Defaults to empty string if missing
    reference_urls: list[str] = []         # Default empty list
    imp_score: int = 50                    # Default moderate score

    @field_validator("reference_urls", mode="before")
    @classmethod
    def _check_urls(cls, v) -> list[str]:
        """Keep only valid absolute HTTP/HTTPS URLs."""
        if not isinstance(v, list):
            return []
        return [
            url for url in v
            if isinstance(url, str) and url.startswith(("http://", "https://"))
        ]

    @field_validator("imp_score", mode="before")
    @classmethod
    def _check_imp_score(cls, v) -> int:
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 50
        return max(1, min(100, v))


# ============================================================
# Stage 1 message builder
# ============================================================

def build_process_message(raw_payload: dict, source_type: str, search_context: str = "") -> str:
    """Build the user message for the stage 1 combined process() AI call.

    Sends the full raw payload along with source_type so the AI understands
    whether it's processing an RSS entry (feedparser keys) or a REST JSON object.

    search_context: DuckDuckGo results passed by GeminiLangGraphProvider.
    """
    payload: dict = {
        "source_type": source_type,
        "raw_payload": raw_payload,
    }
    if search_context:
        payload["web_search_context"] = search_context
    return json.dumps(payload, default=str, indent=2)


# ============================================================
# Stage 2 message builder
# ============================================================

def build_post_process_message(filter_article: dict, search_context: str = "") -> str:
    """Build the user message for the stage 2 post_process() AI call.

    filter_article: dict with fields from stage 1 output:
      title, description, url, sub_category, location, summary
    search_context: optional DuckDuckGo web search results.
    """
    payload: dict = {
        "article": {
            "title": filter_article.get("title", ""),
            "description": filter_article.get("description") or filter_article.get("summary", ""),
            "url": filter_article.get("url", ""),
            "crime_type": filter_article.get("sub_category"),
            "crime_types": filter_article.get("sub_category_ids", []),
            "location": filter_article.get("location"),
            "region": filter_article.get("region"),
        }
    }
    if search_context:
        payload["web_search_context"] = search_context
    return json.dumps(payload, default=str, indent=2)


# ============================================================
# Code fence stripper (shared utility)
# ============================================================

def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that some AI models add around JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


# ============================================================
# Stage 1 output parser
# ============================================================

def parse_combined_output(text: str, raw_payload: dict) -> dict | None:
    """Parse and validate the AI's stage 1 process() response.

    Returns a complete article dict (basic fields + enrichment) on success.
    Returns None on any failure — caller treats None as "article dropped".
    """
    try:
        data = json.loads(_strip_code_fences(text))
        output = CombinedOutput.model_validate(data)
    except json.JSONDecodeError as exc:
        logger.warning("AI process: non-JSON response: %s | text=%r", exc, text[:200])
        return None
    except ValidationError as exc:
        logger.warning("AI process: missing required fields: %s", exc)
        return None

    published_at = parse_date(output.published_at) if output.published_at else None

    return {
        # Basic article fields
        "title": output.title,
        "description": output.description,
        "content": None,
        "url": output.url or "",
        "image_url": output.image_url,
        "published_at": published_at,
        "raw_payload": raw_payload,
        # Enrichment fields
        "is_crime": output.is_crime,
        "category": output.category,
        "sub_category": output.sub_category,
        "sub_category_ids": output.sub_category_ids,   # NEW: multi-label list
        "location": output.location,
        "region": output.region,
        "summary": output.summary,
        "importance_score": output.importance_score,
    }


# ============================================================
# Stage 2 output parser
# ============================================================

def parse_post_process_output(text: str) -> dict | None:
    """Parse and validate the AI's stage 2 post_process() response.

    Returns a dict with rewritten_title, rewritten_description, reference_urls, imp_score.
    Returns None on any failure — caller uses stage 1 data as fallback.
    """
    try:
        data = json.loads(_strip_code_fences(text))
        output = PostProcessOutput.model_validate(data)
    except json.JSONDecodeError as exc:
        logger.warning("AI post_process: non-JSON response: %s | text=%r", exc, text[:200])
        return None
    except ValidationError as exc:
        logger.warning("AI post_process: validation failed: %s", exc)
        return None

    return {
        "rewritten_title": output.rewritten_title,
        "rewritten_description": output.rewritten_description,
        "reference_urls": output.reference_urls or [],
        "imp_score": output.imp_score,
    }


# ============================================================
# Abstract base class — the interface all providers must implement
# ============================================================

class AIProvider(ABC):
    """Abstract base class that all AI provider implementations must subclass.

    Two-stage interface:
      process()      — ABSTRACT: stage 1 — extract fields + classify (all articles)
      post_process() — CONCRETE: stage 2 — rewrite + score (crime articles only)
                       Default implementation returns None (no enrichment).
                       Override in subclasses to enable stage 2 processing.

    Adding a new AI provider:
      1. Subclass AIProvider
      2. Implement process() (required)
      3. Implement post_process() (optional but recommended for full pipeline)
      4. Register in provider_factory.py
    """

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Human-readable identifier stored in raw_ingestion.normalized_by.

        Used for audit trail — which AI processed which article. Examples:
          "ai:anthropic:claude-haiku-4-5-20251001"
          "ai:gemini_langgraph:gemini-2.0-flash"
          "ai:openai:gpt-4o-mini"
        """

    @abstractmethod
    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        """STAGE 1: Extract article fields AND classify crime type in a single AI call.

        Args:
          raw_payload:  raw dict from RSS feed or REST API
          source_type:  "rss" or "rest"

        Returns:
          dict: complete article dict including is_crime, sub_category_ids, location
          None: if the AI call failed or returned invalid output

        Contract:
          - MUST NOT raise exceptions. Catch all errors internally and return None.
          - is_crime=False → IngestionService filters the article out (not a crime article)
        """

    async def post_process(self, filter_article: dict, search_context: str = "") -> dict | None:
        """STAGE 2: Rewrite and score a crime article that passed stage 1.

        Default implementation returns None, meaning "no stage 2 enrichment".
        Subclasses override this to enable rewriting + reference URL collection + scoring.

        Args:
          filter_article: stage 1 result dict (title, description, url, sub_category, etc.)
          search_context: optional web search results for reference URL discovery

        Returns:
          dict: {rewritten_title, rewritten_description, reference_urls, imp_score}
          None: not supported / AI failed — caller will use stage 1 data as fallback
        """
        return None
