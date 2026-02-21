import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Titles that a broken normalizer produces when the field is missing
_PLACEHOLDER_TITLES = frozenset({"untitled", "", "no title", "n/a", "none"})


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


def validate(article: dict) -> ValidationResult:
    """Gate check before any normalized article reaches the DB.

    Both the deterministic normalizer and the AI fallback must pass this.
    A ValidationResult.valid=False means the article is discarded (or routed to AI).
    The errors list is structured for logging and raw_event.error_message storage.
    """
    errors: list[str] = []

    title = (article.get("title") or "").strip()
    if title.lower() in _PLACEHOLDER_TITLES:
        errors.append(f"title is absent or placeholder: {article.get('title')!r}")

    url = article.get("url") or ""
    if not url.startswith(("http://", "https://")):
        errors.append(f"url is missing or not HTTP(S): {url!r}")

    if errors:
        logger.warning(
            "Normalization validation failed — url=%r title=%r errors=%s",
            url,
            title,
            errors,
        )
        return ValidationResult(valid=False, errors=errors)

    return ValidationResult(valid=True)
