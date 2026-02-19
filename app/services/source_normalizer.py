import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)


def _parse_date(raw: str | None) -> datetime | None:
    """Try RFC 2822 (RSS), then ISO 8601 (REST APIs). Return UTC datetime or None."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
    except Exception:
        pass
    logger.warning("Could not parse date string: %r", raw)
    return None


def _to_plain_dict(obj) -> object:
    """Recursively coerce feedparser objects and other non-JSON types to plain Python types.

    feedparser returns FeedParserDict (a dict subclass with attribute access) and
    custom structs. Storing them directly into JSONB crashes because SQLAlchemy's
    JSON serialiser expects plain dicts/lists/scalars.
    """
    if isinstance(obj, dict):
        return {k: _to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain_dict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # feedparser special types — coerce via items()
    try:
        return {k: _to_plain_dict(v) for k, v in obj.items()}
    except Exception:
        return str(obj)


def normalize(item) -> dict:
    """Convert a raw RSS entry or REST API item into the canonical article dict."""
    raw: dict = _to_plain_dict(item)  # type: ignore[assignment]

    # image: prefer media:thumbnail (RSS), fall back to image_url (REST)
    image_url: str | None = None
    thumbnails = raw.get("media_thumbnail")
    if isinstance(thumbnails, list) and thumbnails:
        image_url = thumbnails[0].get("url")
    if not image_url:
        image_url = raw.get("image_url")

    return {
        "title": raw.get("title") or "Untitled",
        "description": raw.get("summary") or raw.get("description"),
        "content": None,
        "url": raw.get("link") or raw.get("url") or "",
        "image_url": image_url,
        "published_at": _parse_date(
            raw.get("published") or raw.get("publishedAt") or raw.get("published_at")
        ),
        "raw_payload": raw,
    }
