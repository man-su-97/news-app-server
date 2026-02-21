"""
app/services/source_normalizer.py — Deterministic (Rule-Based) Normalizer
==========================================================================
Converts raw data from any source (RSS feedparser dict or REST API dict)
into a single "canonical" article dict that the rest of the pipeline understands.

This is the FIRST pass of normalization — fast, no API calls, no AI.
It uses simple rules like "title = raw.get('title') or raw.get('headline')".

If this deterministic pass produces a valid article (title + valid URL),
the article goes straight to the DB without calling any AI.
Only articles that fail validation (missing title or URL) go to the AI fallback.

This design means:
  - For well-structured sources: zero AI cost, instant processing
  - For messy/malformed sources: AI is used as a fallback
  - If no AI is configured: only deterministic articles are saved

Two helper functions are also exported:
  - parse_date(): parses date strings from different formats (RSS and REST)
  - to_plain_dict(): converts feedparser's special objects to plain Python dicts
"""

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime   # Parses RFC 2822 dates (RSS format)

logger = logging.getLogger(__name__)


def parse_date(raw: str | None) -> datetime | None:
    """Try to parse a date string into a timezone-aware UTC datetime.

    News sources use different date formats:
      - RSS feeds use RFC 2822: "Mon, 15 Jan 2024 10:30:00 +0530"
      - REST APIs use ISO 8601: "2024-01-15T10:30:00Z" or "2024-01-15T05:00:00+00:00"

    Strategy: try RFC 2822 first (most RSS feeds), then ISO 8601 (most REST APIs).
    If both fail, log a warning and return None (article is still saved, just
    without a publish date).

    .astimezone(timezone.utc): converts to UTC so all dates in the DB are
    in the same timezone, making comparisons and sorting correct.
    """
    if not raw:
        return None  # Nothing to parse

    # Attempt 1: RFC 2822 format — standard for RSS/Atom feeds
    # Example: "Mon, 15 Jan 2024 10:30:00 +0530"
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        pass  # Not RFC 2822 — try the next format

    # Attempt 2: ISO 8601 format — standard for REST APIs
    # Example: "2024-01-15T10:30:00Z" or "2024-01-15T10:30:00+05:30"
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
    except Exception:
        pass  # Not ISO 8601 either

    # Both formats failed — log it so we know which sources have weird dates
    logger.warning("Could not parse date string: %r", raw)
    return None


def to_plain_dict(obj) -> object:
    """Recursively convert feedparser objects to plain Python dicts/lists/scalars.

    Problem: feedparser returns FeedParserDict (a dict subclass) and custom
    struct objects with attribute access (like entry.links[0].href).
    SQLAlchemy's JSONB column can only store plain Python types (dict, list, str,
    int, float, bool, None). Passing a FeedParserDict directly causes a crash.

    Solution: recursively convert everything:
      - dicts (including FeedParserDict) → plain dict
      - lists → plain list
      - str/int/float/bool/None → unchanged
      - Any other object with .items() → converted as if it were a dict
      - Anything else → str() (fallback)

    Idempotent: calling this on an already-plain dict is a no-op.
    This is important because IngestionService calls to_plain_dict() on the
    feedparser entries, and source_normalizer.normalize() also calls it
    internally — calling it twice is safe.
    """
    if isinstance(obj, dict):
        # Convert each key-value pair recursively
        return {k: to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        # Convert each list element recursively
        return [to_plain_dict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        # These are already JSON-serializable — return as-is
        return obj
    # feedparser's special struct types have an .items() method like dicts
    try:
        return {k: to_plain_dict(v) for k, v in obj.items()}
    except Exception:
        # Last resort: convert to string (e.g. for datetime objects)
        return str(obj)


def normalize(item) -> dict:
    """Convert a raw source item into the canonical article dict shape.

    Input: either a feedparser FeedParserDict (RSS) or a plain dict (REST).
    Output: a dict with exactly these keys:
      title, description, content, url, image_url, published_at, raw_payload

    This canonical shape is what ArticleRepository.upsert_batch() expects.
    The AI providers also return this same shape when they do normalization.

    Field mapping strategy:
      - title: raw["title"] (all sources should have this)
      - description: try "summary" first (RSS standard), then "description" (REST)
      - url: try "link" first (RSS standard), then "url" (REST)
      - image_url: try RSS media:thumbnail first, then REST image_url
      - published_at: try multiple date field names (RSS and REST variations)
    """
    # First, convert the input to a plain dict (safe to call even if already plain)
    raw: dict = to_plain_dict(item)  # type: ignore[assignment]

    # Image URL extraction:
    # RSS feeds often use the media:thumbnail extension → comes as media_thumbnail list
    # Example: [{"url": "https://example.com/img.jpg", "width": "..."}]
    image_url: str | None = None
    thumbnails = raw.get("media_thumbnail")
    if isinstance(thumbnails, list) and thumbnails:
        image_url = thumbnails[0].get("url")   # use the first thumbnail

    # Fall back to a plain "image_url" field (common in REST APIs)
    if not image_url:
        image_url = raw.get("image_url")

    return {
        # title: "or 'Untitled'" ensures we always have a non-empty string.
        # CanonicalValidator will reject articles where title is "Untitled",
        # routing them to the AI fallback to extract a proper title.
        "title": raw.get("title") or "Untitled",

        # description: RSS uses "summary", REST APIs use "description"
        "description": raw.get("summary") or raw.get("description"),

        # content: full article body — not fetched in this pipeline (future use)
        "content": None,

        # url: RSS uses "link", REST uses "url"
        # or "" ensures url is never None (validator checks it's a valid HTTP URL)
        "url": raw.get("link") or raw.get("url") or "",

        "image_url": image_url,

        # published_at: try multiple field names used by different sources:
        #   RSS:         "published"
        #   NewsAPI:     "publishedAt"
        #   Generic:     "published_at"
        "published_at": parse_date(
            raw.get("published") or raw.get("publishedAt") or raw.get("published_at")
        ),

        # Store the complete original payload — never modified after this point.
        # If we need to re-process this article with a better AI later, we have
        # the full original data without re-fetching from the source.
        "raw_payload": raw,
    }
